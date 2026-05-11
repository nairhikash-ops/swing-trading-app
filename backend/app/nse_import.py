import csv
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from app.config import Settings
from app.store import TokenStore
from app.timezone import now_utc


FULL_REPORT = "full_bhavcopy"
UDIFF_REPORT = "udiff_bhavcopy"

FULL_FILENAME_RE = re.compile(r"^sec_bhavdata_full_(\d{8})\.csv$", re.IGNORECASE)
UDIFF_FILENAME_RE = re.compile(r"^BhavCopy_NSE_CM_0_0_0_(\d{8})_F_0000\.csv\.zip$", re.IGNORECASE)

FULL_REQUIRED_COLUMNS = [
    "SYMBOL",
    "SERIES",
    "DATE1",
    "PREV_CLOSE",
    "OPEN_PRICE",
    "HIGH_PRICE",
    "LOW_PRICE",
    "LAST_PRICE",
    "CLOSE_PRICE",
    "AVG_PRICE",
    "TTL_TRD_QNTY",
    "TURNOVER_LACS",
    "NO_OF_TRADES",
    "DELIV_QTY",
    "DELIV_PER",
]

UDIFF_REQUIRED_COLUMNS = [
    "TradDt",
    "Sgmt",
    "FinInstrmTp",
    "FinInstrmId",
    "ISIN",
    "TckrSymb",
    "SctySrs",
    "FinInstrmNm",
]


class NseImportError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedReport:
    report_type: str
    trade_date: date
    source_columns: list[str]
    total_rows_seen: int
    rows: list[dict[str, str]]


class NseImportStore:
    def __init__(self, settings: Settings, token_store: TokenStore) -> None:
        self.settings = settings
        self.token_store = token_store
        self.storage_dir = settings.nse_import_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.settings.nse_import_inbox_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nse_import_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uploaded_file_count INTEGER NOT NULL DEFAULT 0,
                    accepted_file_count INTEGER NOT NULL DEFAULT 0,
                    duplicate_file_count INTEGER NOT NULL DEFAULT 0,
                    rejected_file_count INTEGER NOT NULL DEFAULT 0,
                    published_dates_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nse_import_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id INTEGER,
                    original_filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL DEFAULT '',
                    checksum TEXT NOT NULL UNIQUE,
                    report_type TEXT NOT NULL DEFAULT '',
                    trade_date TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL DEFAULT 0,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    source_columns_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',
                    uploaded_at TEXT NOT NULL,
                    parsed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nse_import_dates (
                    trade_date TEXT PRIMARY KEY,
                    full_file_id INTEGER,
                    udiff_file_id INTEGER,
                    status TEXT NOT NULL,
                    full_row_count INTEGER NOT NULL DEFAULT 0,
                    udiff_row_count INTEGER NOT NULL DEFAULT 0,
                    published_row_count INTEGER NOT NULL DEFAULT 0,
                    unresolved_row_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    published_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nse_instruments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    isin TEXT NOT NULL UNIQUE,
                    company_name TEXT NOT NULL DEFAULT '',
                    first_seen_trade_date TEXT NOT NULL,
                    last_seen_trade_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nse_symbol_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    isin TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    series TEXT NOT NULL,
                    company_name TEXT NOT NULL DEFAULT '',
                    first_trade_date TEXT NOT NULL,
                    last_trade_date TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    UNIQUE(isin, symbol, series)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nse_eod_prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    isin TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    series TEXT NOT NULL,
                    company_name TEXT NOT NULL DEFAULT '',
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    prev_close REAL NOT NULL,
                    last_price REAL NOT NULL,
                    avg_price REAL NOT NULL,
                    volume REAL NOT NULL,
                    turnover_lacs REAL NOT NULL,
                    no_of_trades INTEGER NOT NULL,
                    delivery_qty REAL,
                    delivery_percent REAL,
                    price_basis TEXT NOT NULL DEFAULT 'raw_unadjusted',
                    dirty_flag TEXT NOT NULL DEFAULT 'clean',
                    dirty_reason TEXT NOT NULL DEFAULT '',
                    source_full_file_id INTEGER NOT NULL,
                    source_udiff_file_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(isin, trade_date, series)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nse_eod_flags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    isin TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    series TEXT NOT NULL,
                    flag TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(isin, trade_date, series, flag)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nse_import_files_date ON nse_import_files(trade_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nse_import_files_status ON nse_import_files(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nse_eod_prices_symbol ON nse_eod_prices(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nse_eod_prices_isin_date ON nse_eod_prices(isin, trade_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nse_eod_prices_date ON nse_eod_prices(trade_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nse_eod_prices_dirty ON nse_eod_prices(dirty_flag)")

    def import_files(self, files: list[tuple[str, bytes]]) -> dict[str, Any]:
        started_at = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO nse_import_batches (uploaded_file_count, started_at)
                VALUES (?, ?)
                """,
                (len(files), started_at),
            )
            batch_id = int(cursor.lastrowid)

        results: list[dict[str, Any]] = []
        touched_dates: set[str] = set()
        accepted_count = 0
        duplicate_count = 0
        rejected_count = 0
        for filename, content in files:
            result = self._store_file(batch_id, filename, content)
            results.append(result)
            if result["status"] == "valid":
                accepted_count += 1
            elif result["status"] == "duplicate":
                duplicate_count += 1
            else:
                rejected_count += 1
            if result.get("trade_date"):
                touched_dates.add(str(result["trade_date"]))

        published_dates_count = 0
        for trade_date in sorted(touched_dates):
            if self.publish_date_if_ready(trade_date):
                published_dates_count += 1

        completed_at = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE nse_import_batches
                SET accepted_file_count = ?, duplicate_file_count = ?, rejected_file_count = ?,
                    published_dates_count = ?, completed_at = ?
                WHERE id = ?
                """,
                (accepted_count, duplicate_count, rejected_count, published_dates_count, completed_at, batch_id),
            )

        return {
            "batch_id": batch_id,
            "accepted_count": accepted_count,
            "duplicate_count": duplicate_count,
            "rejected_count": rejected_count,
            "published_dates_count": published_dates_count,
            "files": results,
        }

    def import_inbox(self) -> dict[str, Any]:
        inbox_dir = self.settings.nse_import_inbox_dir
        inbox_dir.mkdir(parents=True, exist_ok=True)
        candidates = [
            path
            for path in sorted(inbox_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".csv", ".zip"}
        ]
        files = [(path.name, path.read_bytes()) for path in candidates]
        if not files:
            return {
                "batch_id": 0,
                "accepted_count": 0,
                "duplicate_count": 0,
                "rejected_count": 0,
                "published_dates_count": 0,
                "files": [],
            }
        return self.import_files(files)

    def _store_file(self, batch_id: int, filename: str, content: bytes) -> dict[str, Any]:
        safe_name = _safe_filename(filename)
        checksum = hashlib.sha256(content).hexdigest()
        uploaded_at = now_utc().isoformat()

        existing = self._file_by_checksum(checksum)
        if existing:
            return {
                "filename": safe_name,
                "status": "duplicate",
                "report_type": existing["report_type"] or None,
                "trade_date": existing["trade_date"] or None,
                "row_count": int(existing["row_count"] or 0),
                "error": "",
                "file_id": None,
                "existing_file_id": int(existing["id"]),
            }

        report_type = ""
        trade_date: date | None = None
        stored_path = ""
        source_columns: list[str] = []
        row_count = 0
        status = "valid"
        error = ""

        try:
            if len(content) > self.settings.nse_import_max_file_bytes:
                raise NseImportError("File exceeds NSE import size limit.")
            report_type, trade_date = report_type_from_filename(safe_name)
            stored_path = self._write_source_file(safe_name, content, trade_date, checksum)
            parsed = parse_report_file(safe_name, content, self.settings.nse_equity_series_set)
            source_columns = parsed.source_columns
            row_count = len(parsed.rows)
        except NseImportError as exc:
            status = "rejected" if not report_type else "schema_error"
            error = str(exc)
            if report_type and trade_date and not stored_path:
                stored_path = self._write_source_file(safe_name, content, trade_date, checksum)
        except Exception as exc:
            status = "schema_error" if report_type else "rejected"
            error = f"Unexpected import error: {exc}"
            if report_type and trade_date and not stored_path:
                stored_path = self._write_source_file(safe_name, content, trade_date, checksum)

        parsed_at = now_utc().isoformat() if status == "valid" else None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO nse_import_files (
                    batch_id, original_filename, stored_path, checksum, report_type, trade_date,
                    status, file_size_bytes, row_count, source_columns_json, error, uploaded_at, parsed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    safe_name,
                    stored_path,
                    checksum,
                    report_type,
                    trade_date.isoformat() if trade_date else "",
                    status,
                    len(content),
                    row_count,
                    json.dumps(source_columns),
                    error,
                    uploaded_at,
                    parsed_at,
                ),
            )
            file_id = int(cursor.lastrowid)
            if trade_date:
                self._upsert_import_date(conn, trade_date.isoformat())

        return {
            "filename": safe_name,
            "status": status,
            "report_type": report_type or None,
            "trade_date": trade_date.isoformat() if trade_date else None,
            "row_count": row_count,
            "error": error,
            "file_id": file_id,
            "existing_file_id": None,
        }

    def _write_source_file(self, filename: str, content: bytes, trade_date: date, checksum: str) -> str:
        target_dir = self.storage_dir / trade_date.isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{checksum[:12]}_{filename}"
        if not target_path.exists():
            target_path.write_bytes(content)
        return str(target_path)

    def _file_by_checksum(self, checksum: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nse_import_files WHERE checksum = ?", (checksum,)).fetchone()
        return dict(row) if row else None

    def _upsert_import_date(self, conn, trade_date: str) -> None:
        timestamp = now_utc().isoformat()
        latest_full = conn.execute(
            """
            SELECT id, row_count FROM nse_import_files
            WHERE trade_date = ? AND report_type = ? AND status = 'valid'
            ORDER BY id DESC
            LIMIT 1
            """,
            (trade_date, FULL_REPORT),
        ).fetchone()
        latest_udiff = conn.execute(
            """
            SELECT id, row_count FROM nse_import_files
            WHERE trade_date = ? AND report_type = ? AND status = 'valid'
            ORDER BY id DESC
            LIMIT 1
            """,
            (trade_date, UDIFF_REPORT),
        ).fetchone()
        date_errors = conn.execute(
            """
            SELECT error FROM nse_import_files
            WHERE trade_date = ? AND status IN ('rejected', 'schema_error') AND error <> ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (trade_date,),
        ).fetchone()
        status = "waiting_for_pair"
        error = ""
        if date_errors and not (latest_full and latest_udiff):
            status = "schema_error"
            error = date_errors["error"]
        if latest_full and latest_udiff:
            status = "ready"
            error = ""

        conn.execute(
            """
            INSERT INTO nse_import_dates (
                trade_date, full_file_id, udiff_file_id, status, full_row_count, udiff_row_count, error, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                full_file_id = excluded.full_file_id,
                udiff_file_id = excluded.udiff_file_id,
                status = CASE
                    WHEN nse_import_dates.status = 'published' AND excluded.status != 'ready' THEN nse_import_dates.status
                    ELSE excluded.status
                END,
                full_row_count = excluded.full_row_count,
                udiff_row_count = excluded.udiff_row_count,
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            (
                trade_date,
                int(latest_full["id"]) if latest_full else None,
                int(latest_udiff["id"]) if latest_udiff else None,
                status,
                int(latest_full["row_count"]) if latest_full else 0,
                int(latest_udiff["row_count"]) if latest_udiff else 0,
                error,
                timestamp,
            ),
        )

    def publish_date_if_ready(self, trade_date: str) -> bool:
        with self._connect() as conn:
            self._upsert_import_date(conn, trade_date)
            date_row = conn.execute("SELECT * FROM nse_import_dates WHERE trade_date = ?", (trade_date,)).fetchone()
            if not date_row or not date_row["full_file_id"] or not date_row["udiff_file_id"]:
                return False
            full_file = conn.execute("SELECT * FROM nse_import_files WHERE id = ?", (date_row["full_file_id"],)).fetchone()
            udiff_file = conn.execute("SELECT * FROM nse_import_files WHERE id = ?", (date_row["udiff_file_id"],)).fetchone()

        try:
            full_report = self._parse_stored_file(dict(full_file))
            udiff_report = self._parse_stored_file(dict(udiff_file))
            if full_report.trade_date.isoformat() != trade_date or udiff_report.trade_date.isoformat() != trade_date:
                raise NseImportError("Paired reports do not match the import date.")
            published_rows, unresolved_rows = self._publish_reports(dict(full_file), dict(udiff_file), full_report, udiff_report)
        except Exception as exc:
            timestamp = now_utc().isoformat()
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE nse_import_dates
                    SET status = ?, error = ?, updated_at = ?
                    WHERE trade_date = ?
                    """,
                    ("schema_error", str(exc), timestamp, trade_date),
                )
            return False

        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE nse_import_dates
                SET status = 'published', published_row_count = ?, unresolved_row_count = ?,
                    error = '', updated_at = ?, published_at = ?
                WHERE trade_date = ?
                """,
                (published_rows, unresolved_rows, timestamp, timestamp, trade_date),
            )
        return True

    def _parse_stored_file(self, file_row: dict[str, Any]) -> ParsedReport:
        path = Path(file_row["stored_path"])
        if not path.exists():
            raise NseImportError(f"Stored source file is missing: {path.name}")
        return parse_report_file(file_row["original_filename"], path.read_bytes(), self.settings.nse_equity_series_set)

    def _publish_reports(
        self,
        full_file: dict[str, Any],
        udiff_file: dict[str, Any],
        full_report: ParsedReport,
        udiff_report: ParsedReport,
    ) -> tuple[int, int]:
        udiff_by_key: dict[tuple[str, str], dict[str, str]] = {}
        for row in udiff_report.rows:
            key = (_clean(row["TckrSymb"]).upper(), _clean(row["SctySrs"]).upper())
            if key and row.get("ISIN"):
                udiff_by_key[key] = row

        trade_date = full_report.trade_date.isoformat()
        timestamp = now_utc().isoformat()
        published_rows = 0
        unresolved_rows = 0
        with self._connect() as conn:
            conn.execute("DELETE FROM nse_eod_flags WHERE trade_date = ?", (trade_date,))
            conn.execute("DELETE FROM nse_eod_prices WHERE trade_date = ?", (trade_date,))

            for full_row in full_report.rows:
                symbol = _clean(full_row["SYMBOL"]).upper()
                series = _clean(full_row["SERIES"]).upper()
                udiff_row = udiff_by_key.get((symbol, series))
                if not udiff_row:
                    unresolved_rows += 1
                    continue

                isin = _clean(udiff_row["ISIN"]).upper()
                company_name = _clean(udiff_row.get("FinInstrmNm", ""))
                values = _full_numeric_values(full_row)
                dirty_flag, dirty_reason = self._classify_dirty_state(conn, isin, trade_date, values)

                conn.execute(
                    """
                    INSERT INTO nse_instruments (
                        isin, company_name, first_seen_trade_date, last_seen_trade_date, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(isin) DO UPDATE SET
                        company_name = COALESCE(NULLIF(excluded.company_name, ''), nse_instruments.company_name),
                        first_seen_trade_date = MIN(nse_instruments.first_seen_trade_date, excluded.first_seen_trade_date),
                        last_seen_trade_date = MAX(nse_instruments.last_seen_trade_date, excluded.last_seen_trade_date),
                        updated_at = excluded.updated_at
                    """,
                    (isin, company_name, trade_date, trade_date, timestamp, timestamp),
                )
                conn.execute(
                    """
                    INSERT INTO nse_symbol_aliases (
                        isin, symbol, series, company_name, first_trade_date, last_trade_date, row_count, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(isin, symbol, series) DO UPDATE SET
                        company_name = COALESCE(NULLIF(excluded.company_name, ''), nse_symbol_aliases.company_name),
                        first_trade_date = MIN(nse_symbol_aliases.first_trade_date, excluded.first_trade_date),
                        last_trade_date = MAX(nse_symbol_aliases.last_trade_date, excluded.last_trade_date),
                        row_count = nse_symbol_aliases.row_count + 1,
                        updated_at = excluded.updated_at
                    """,
                    (isin, symbol, series, company_name, trade_date, trade_date, timestamp),
                )
                conn.execute(
                    """
                    INSERT INTO nse_eod_prices (
                        isin, trade_date, symbol, series, company_name, open, high, low, close,
                        prev_close, last_price, avg_price, volume, turnover_lacs, no_of_trades,
                        delivery_qty, delivery_percent, price_basis, dirty_flag, dirty_reason,
                        source_full_file_id, source_udiff_file_id, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'raw_unadjusted', ?, ?, ?, ?, ?)
                    ON CONFLICT(isin, trade_date, series) DO UPDATE SET
                        symbol = excluded.symbol,
                        company_name = excluded.company_name,
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        prev_close = excluded.prev_close,
                        last_price = excluded.last_price,
                        avg_price = excluded.avg_price,
                        volume = excluded.volume,
                        turnover_lacs = excluded.turnover_lacs,
                        no_of_trades = excluded.no_of_trades,
                        delivery_qty = excluded.delivery_qty,
                        delivery_percent = excluded.delivery_percent,
                        price_basis = excluded.price_basis,
                        dirty_flag = excluded.dirty_flag,
                        dirty_reason = excluded.dirty_reason,
                        source_full_file_id = excluded.source_full_file_id,
                        source_udiff_file_id = excluded.source_udiff_file_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        isin,
                        trade_date,
                        symbol,
                        series,
                        company_name,
                        values["open"],
                        values["high"],
                        values["low"],
                        values["close"],
                        values["prev_close"],
                        values["last_price"],
                        values["avg_price"],
                        values["volume"],
                        values["turnover_lacs"],
                        values["no_of_trades"],
                        values["delivery_qty"],
                        values["delivery_percent"],
                        dirty_flag,
                        dirty_reason,
                        int(full_file["id"]),
                        int(udiff_file["id"]),
                        timestamp,
                    ),
                )
                if dirty_flag != "clean":
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO nse_eod_flags (isin, trade_date, series, flag, reason, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (isin, trade_date, series, dirty_flag, dirty_reason, timestamp),
                    )
                published_rows += 1

        return published_rows, unresolved_rows

    def _classify_dirty_state(
        self,
        conn,
        isin: str,
        trade_date: str,
        values: dict[str, float],
    ) -> tuple[str, str]:
        if values["high"] < values["low"]:
            return "needs_review", "High price is below low price."
        if values["open"] > values["high"] or values["open"] < values["low"]:
            return "needs_review", "Open price is outside the high-low range."
        if values["close"] > values["high"] or values["close"] < values["low"]:
            return "needs_review", "Close price is outside the high-low range."

        previous = conn.execute(
            """
            SELECT close, trade_date FROM nse_eod_prices
            WHERE isin = ? AND trade_date < ?
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (isin, trade_date),
        ).fetchone()
        if not previous or float(previous["close"]) <= 0:
            return "clean", ""

        previous_close = float(previous["close"])
        ratio = values["close"] / previous_close
        change_percent = abs(values["close"] - previous_close) / previous_close * 100
        if ratio <= 0.35 or ratio >= 3.0:
            return "possible_split_bonus", f"Close changed {change_percent:.2f}% from previous stored session."
        if change_percent >= 20:
            return "ordinary_gap", f"Close changed {change_percent:.2f}% from previous stored session."
        return "clean", ""

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            date_counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'published' THEN 1 ELSE 0 END) AS published_count,
                    SUM(CASE WHEN status = 'waiting_for_pair' THEN 1 ELSE 0 END) AS waiting_count,
                    SUM(CASE WHEN status = 'schema_error' THEN 1 ELSE 0 END) AS schema_error_count,
                    MAX(CASE WHEN status = 'published' THEN trade_date ELSE NULL END) AS latest_published_date
                FROM nse_import_dates
                """
            ).fetchone()
            file_counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected_count,
                    SUM(CASE WHEN status = 'schema_error' THEN 1 ELSE 0 END) AS schema_file_count
                FROM nse_import_files
                """
            ).fetchone()
            instrument_count = conn.execute("SELECT COUNT(*) AS value FROM nse_instruments").fetchone()["value"]
            eod_count = conn.execute("SELECT COUNT(*) AS value FROM nse_eod_prices").fetchone()["value"]
            recent_files = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, original_filename, report_type, trade_date, status, row_count, error, uploaded_at
                    FROM nse_import_files
                    ORDER BY id DESC
                    LIMIT 20
                    """
                ).fetchall()
            ]
            recent_dates = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT trade_date, status, full_row_count, udiff_row_count, published_row_count,
                           unresolved_row_count, error, updated_at, published_at
                    FROM nse_import_dates
                    ORDER BY trade_date DESC
                    LIMIT 20
                    """
                ).fetchall()
            ]

        published_count = int(date_counts["published_count"] or 0)
        return {
            "generated_at": now_utc(),
            "target_sessions": self.settings.nse_eod_target_sessions,
            "inbox_path": str(self.settings.nse_import_inbox_dir),
            "published_session_count": published_count,
            "coverage_percent": round((published_count / self.settings.nse_eod_target_sessions) * 100, 2),
            "latest_published_date": date_counts["latest_published_date"],
            "waiting_for_pair_count": int(date_counts["waiting_count"] or 0),
            "schema_error_count": int(date_counts["schema_error_count"] or 0),
            "rejected_file_count": int(file_counts["rejected_count"] or 0),
            "schema_file_count": int(file_counts["schema_file_count"] or 0),
            "instrument_count": int(instrument_count or 0),
            "eod_row_count": int(eod_count or 0),
            "recent_files": recent_files,
            "recent_dates": recent_dates,
        }

    def coverage(self) -> dict[str, Any]:
        status = self.status()
        with self._connect() as conn:
            dirty_counts = {
                row["dirty_flag"]: int(row["count"])
                for row in conn.execute(
                    """
                    SELECT dirty_flag, COUNT(*) AS count
                    FROM nse_eod_prices
                    GROUP BY dirty_flag
                    ORDER BY dirty_flag
                    """
                ).fetchall()
            }
        return {
            "generated_at": status["generated_at"],
            "target_sessions": status["target_sessions"],
            "published_session_count": status["published_session_count"],
            "coverage_percent": status["coverage_percent"],
            "latest_published_date": status["latest_published_date"],
            "instrument_count": status["instrument_count"],
            "eod_row_count": status["eod_row_count"],
            "dirty_flag_counts": dirty_counts,
        }

    def rows_for_symbol(self, symbol: str, limit: int = 80) -> list[dict[str, Any]]:
        query = symbol.strip().upper()
        if not query:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM nse_eod_prices
                WHERE UPPER(symbol) = ? OR UPPER(isin) = ?
                ORDER BY trade_date DESC, series
                LIMIT ?
                """,
                (query, query, limit),
            ).fetchall()
        return [dict(row) for row in rows]


class NseImportService:
    def __init__(self, settings: Settings, store: NseImportStore) -> None:
        self.settings = settings
        self.store = store

    def import_files(self, files: list[tuple[str, bytes]]) -> dict[str, Any]:
        if not files:
            raise ValueError("At least one NSE report file is required.")
        return self.store.import_files(files)

    def import_inbox(self) -> dict[str, Any]:
        return self.store.import_inbox()

    def status(self) -> dict[str, Any]:
        return self.store.status()

    def coverage(self) -> dict[str, Any]:
        return self.store.coverage()

    def rows_for_symbol(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        return self.store.rows_for_symbol(symbol, limit)


def report_type_from_filename(filename: str) -> tuple[str, date]:
    name = Path(filename).name
    full_match = FULL_FILENAME_RE.match(name)
    if full_match:
        return FULL_REPORT, datetime.strptime(full_match.group(1), "%d%m%Y").date()
    udiff_match = UDIFF_FILENAME_RE.match(name)
    if udiff_match:
        return UDIFF_REPORT, datetime.strptime(udiff_match.group(1), "%Y%m%d").date()
    raise NseImportError("Filename does not match a supported NSE report pattern.")


def parse_report_file(filename: str, content: bytes, equity_series: set[str]) -> ParsedReport:
    report_type, trade_date = report_type_from_filename(filename)
    if report_type == FULL_REPORT:
        return parse_full_bhavcopy(_decode_csv_bytes(content), trade_date, equity_series)
    if report_type == UDIFF_REPORT:
        return parse_udiff_bhavcopy(_read_udiff_zip(filename, content), trade_date, equity_series)
    raise NseImportError("Unsupported report type.")


def parse_full_bhavcopy(csv_text: str, trade_date: date, equity_series: set[str]) -> ParsedReport:
    columns, raw_rows = _read_csv_dicts(csv_text, FULL_REQUIRED_COLUMNS)
    rows: list[dict[str, str]] = []
    for row in raw_rows:
        series = _clean(row.get("SERIES", "")).upper()
        if series not in equity_series:
            continue
        row_date = _parse_full_date(row.get("DATE1", ""))
        if row_date != trade_date:
            raise NseImportError("Full Bhavcopy row date does not match filename date.")
        symbol = _clean(row.get("SYMBOL", ""))
        if not symbol:
            continue
        rows.append(row)
    return ParsedReport(FULL_REPORT, trade_date, columns, len(raw_rows), rows)


def parse_udiff_bhavcopy(csv_text: str, trade_date: date, equity_series: set[str]) -> ParsedReport:
    columns, raw_rows = _read_csv_dicts(csv_text, UDIFF_REQUIRED_COLUMNS)
    rows: list[dict[str, str]] = []
    for row in raw_rows:
        if _clean(row.get("TradDt", "")) != trade_date.isoformat():
            raise NseImportError("UDiFF row date does not match filename date.")
        if _clean(row.get("Sgmt", "")).upper() != "CM":
            continue
        if _clean(row.get("FinInstrmTp", "")).upper() != "STK":
            continue
        if _clean(row.get("SctySrs", "")).upper() not in equity_series:
            continue
        if not _clean(row.get("ISIN", "")):
            continue
        rows.append(row)
    return ParsedReport(UDIFF_REPORT, trade_date, columns, len(raw_rows), rows)


def _read_csv_dicts(csv_text: str, required_columns: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames:
        raise NseImportError("CSV has no header row.")
    columns = [_clean_header(column) for column in reader.fieldnames]
    missing = [column for column in required_columns if column not in columns]
    if missing:
        raise NseImportError(f"Missing required column(s): {', '.join(missing)}")
    rows: list[dict[str, str]] = []
    for row in reader:
        normalized = {_clean_header(key): _clean(value) for key, value in row.items() if key is not None}
        if any(value for value in normalized.values()):
            rows.append(normalized)
    return columns, rows


def _read_udiff_zip(filename: str, content: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                raise NseImportError("UDiFF ZIP does not contain a CSV file.")
            expected_inner = filename[:-4]
            if Path(csv_names[0]).name.lower() != expected_inner.lower():
                raise NseImportError("UDiFF ZIP inner CSV name does not match the uploaded ZIP name.")
            return _decode_csv_bytes(archive.read(csv_names[0]))
    except zipfile.BadZipFile as exc:
        raise NseImportError("UDiFF report is not a readable ZIP file.") from exc


def _full_numeric_values(row: dict[str, str]) -> dict[str, Any]:
    values = {
        "prev_close": _to_float(row["PREV_CLOSE"], "PREV_CLOSE"),
        "open": _to_float(row["OPEN_PRICE"], "OPEN_PRICE"),
        "high": _to_float(row["HIGH_PRICE"], "HIGH_PRICE"),
        "low": _to_float(row["LOW_PRICE"], "LOW_PRICE"),
        "last_price": _to_float(row["LAST_PRICE"], "LAST_PRICE"),
        "close": _to_float(row["CLOSE_PRICE"], "CLOSE_PRICE"),
        "avg_price": _to_float(row["AVG_PRICE"], "AVG_PRICE"),
        "volume": _to_float(row["TTL_TRD_QNTY"], "TTL_TRD_QNTY"),
        "turnover_lacs": _to_float(row["TURNOVER_LACS"], "TURNOVER_LACS"),
        "no_of_trades": int(_to_float(row["NO_OF_TRADES"], "NO_OF_TRADES")),
        "delivery_qty": _to_optional_float(row["DELIV_QTY"], "DELIV_QTY"),
        "delivery_percent": _to_optional_float(row["DELIV_PER"], "DELIV_PER"),
    }
    return values


def _decode_csv_bytes(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")


def _parse_full_date(value: str) -> date:
    cleaned = _clean(value)
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(cleaned.title(), fmt).date()
        except ValueError:
            continue
    raise NseImportError(f"Unsupported Full Bhavcopy DATE1 value: {value}")


def _to_float(value: str, column: str) -> float:
    cleaned = _clean(value).replace(",", "")
    if cleaned == "":
        raise NseImportError(f"Missing numeric value for {column}.")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise NseImportError(f"Invalid numeric value for {column}: {value}") from exc


def _to_optional_float(value: str, column: str) -> float | None:
    cleaned = _clean(value)
    if cleaned in {"", "-"}:
        return None
    return _to_float(cleaned, column)


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clean_header(value: Any) -> str:
    return _clean(value).lstrip("\ufeff")


def _safe_filename(filename: str) -> str:
    name = Path(filename).name
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)
