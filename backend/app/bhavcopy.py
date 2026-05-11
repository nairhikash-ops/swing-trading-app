import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any

from app.config import Settings
from app.store import AppStore


FILENAME_RE = re.compile(r"^sec_bhavdata_full_(\d{8})\.csv$", re.IGNORECASE)
REQUIRED_COLUMNS = [
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


class BhavcopyImportError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedBhavcopy:
    trade_date: date
    source_columns: list[str]
    total_rows_seen: int
    rows: list[dict[str, str]]


class BhavcopyStore:
    def __init__(self, settings: Settings, store: AppStore) -> None:
        self.settings = settings
        self.store = store
        self.settings.source_file_dir.mkdir(parents=True, exist_ok=True)
        self.settings.import_inbox_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self.store.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS import_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uploaded_file_count INTEGER NOT NULL DEFAULT 0,
                    accepted_file_count INTEGER NOT NULL DEFAULT 0,
                    duplicate_file_count INTEGER NOT NULL DEFAULT 0,
                    rejected_file_count INTEGER NOT NULL DEFAULT 0,
                    published_dates_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS import_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id INTEGER,
                    original_filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL DEFAULT '',
                    checksum TEXT NOT NULL UNIQUE,
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
                CREATE TABLE IF NOT EXISTS import_dates (
                    trade_date TEXT PRIMARY KEY,
                    file_id INTEGER,
                    status TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    published_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bhavcopy_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    series TEXT NOT NULL,
                    prev_close REAL NOT NULL,
                    open_price REAL NOT NULL,
                    high_price REAL NOT NULL,
                    low_price REAL NOT NULL,
                    last_price REAL NOT NULL,
                    close_price REAL NOT NULL,
                    avg_price REAL NOT NULL,
                    traded_quantity REAL NOT NULL,
                    turnover_lacs REAL NOT NULL,
                    no_of_trades INTEGER NOT NULL,
                    delivery_qty REAL,
                    delivery_percent REAL,
                    raw_json TEXT NOT NULL,
                    source_file_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(trade_date, symbol, series)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_import_files_status ON import_files(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_import_files_date ON import_files(trade_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bhavcopy_rows_symbol ON bhavcopy_rows(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bhavcopy_rows_date ON bhavcopy_rows(trade_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bhavcopy_rows_series ON bhavcopy_rows(series)")
        self.store.protect_file()

    def import_files(self, files: list[tuple[str, bytes]]) -> dict[str, Any]:
        started_at = utc_now().isoformat()
        with self.store.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO import_batches (uploaded_file_count, started_at) VALUES (?, ?)",
                (len(files), started_at),
            )
            batch_id = int(cursor.lastrowid)

        results: list[dict[str, Any]] = []
        accepted = 0
        duplicates = 0
        rejected = 0
        published = 0
        for filename, content in files:
            result = self._import_one(batch_id, filename, content)
            results.append(result)
            if result["status"] == "valid":
                accepted += 1
                published += 1
            elif result["status"] == "duplicate":
                duplicates += 1
            else:
                rejected += 1

        with self.store.connect() as conn:
            conn.execute(
                """
                UPDATE import_batches
                SET accepted_file_count = ?, duplicate_file_count = ?, rejected_file_count = ?,
                    published_dates_count = ?, completed_at = ?
                WHERE id = ?
                """,
                (accepted, duplicates, rejected, published, utc_now().isoformat(), batch_id),
            )

        return {
            "batch_id": batch_id,
            "accepted_count": accepted,
            "duplicate_count": duplicates,
            "rejected_count": rejected,
            "published_dates_count": published,
            "files": results,
        }

    def import_inbox(self) -> dict[str, Any]:
        self.settings.import_inbox_dir.mkdir(parents=True, exist_ok=True)
        files = [
            (path.name, path.read_bytes())
            for path in sorted(self.settings.import_inbox_dir.rglob("*.csv"))
            if path.is_file()
        ]
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

    def _import_one(self, batch_id: int, filename: str, content: bytes) -> dict[str, Any]:
        safe_name = safe_filename(filename)
        checksum = hashlib.sha256(content).hexdigest()
        uploaded_at = utc_now().isoformat()

        existing = self._file_by_checksum(checksum)
        if existing and existing["status"] == "valid":
            return {
                "filename": safe_name,
                "status": "duplicate",
                "trade_date": existing["trade_date"] or None,
                "row_count": int(existing["row_count"] or 0),
                "error": "",
                "file_id": None,
                "existing_file_id": int(existing["id"]),
            }

        trade_date: date | None = None
        stored_path = ""
        source_columns: list[str] = []
        row_count = 0
        status = "valid"
        error = ""
        expected_date: date | None = None

        try:
            if len(content) > self.settings.bhavcopy_max_file_bytes:
                raise BhavcopyImportError("File exceeds bhavcopy import size limit.")
            expected_date = trade_date_from_filename(safe_name)
            parsed = parse_bhavcopy_csv(content)
            trade_date = parsed.trade_date
            source_columns = parsed.source_columns
            row_count = len(parsed.rows)
            stored_path = self._write_source_file(safe_name, content, trade_date, checksum)
        except BhavcopyImportError as exc:
            status = "schema_error" if FILENAME_RE.match(safe_name) else "rejected"
            error = str(exc)
            if FILENAME_RE.match(safe_name):
                trade_date = expected_date or trade_date_from_filename(safe_name)
                stored_path = self._write_source_file(safe_name, content, trade_date, checksum)
        except Exception as exc:
            status = "schema_error" if FILENAME_RE.match(safe_name) else "rejected"
            error = f"Unexpected import error: {exc}"
            if FILENAME_RE.match(safe_name):
                trade_date = expected_date or trade_date_from_filename(safe_name)
                stored_path = self._write_source_file(safe_name, content, trade_date, checksum)

        with self.store.connect() as conn:
            if existing:
                file_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE import_files
                    SET batch_id = ?, original_filename = ?, stored_path = ?, trade_date = ?, status = ?,
                        file_size_bytes = ?, row_count = ?, source_columns_json = ?, error = ?,
                        uploaded_at = ?, parsed_at = ?
                    WHERE id = ?
                    """,
                    (
                        batch_id,
                        safe_name,
                        stored_path,
                        trade_date.isoformat() if trade_date else "",
                        status,
                        len(content),
                        row_count,
                        json.dumps(source_columns),
                        error,
                        uploaded_at,
                        utc_now().isoformat() if status == "valid" else None,
                        file_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO import_files (
                        batch_id, original_filename, stored_path, checksum, trade_date, status,
                        file_size_bytes, row_count, source_columns_json, error, uploaded_at, parsed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        safe_name,
                        stored_path,
                        checksum,
                        trade_date.isoformat() if trade_date else "",
                        status,
                        len(content),
                        row_count,
                        json.dumps(source_columns),
                        error,
                        uploaded_at,
                        utc_now().isoformat() if status == "valid" else None,
                    ),
                )
                file_id = int(cursor.lastrowid)

        if status == "valid" and trade_date:
            parsed = parse_bhavcopy_csv(content)
            self._publish(file_id, parsed)
        elif trade_date:
            self._mark_date(trade_date.isoformat(), file_id, status, row_count, error)

        return {
            "filename": safe_name,
            "status": status,
            "trade_date": trade_date.isoformat() if trade_date else None,
            "row_count": row_count,
            "error": error,
            "file_id": file_id,
            "existing_file_id": None,
        }

    def _write_source_file(self, filename: str, content: bytes, trade_date: date, checksum: str) -> str:
        target_dir = self.settings.source_file_dir / trade_date.isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{checksum[:12]}_{filename}"
        if not target_path.exists():
            target_path.write_bytes(content)
        return str(target_path)

    def _file_by_checksum(self, checksum: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM import_files WHERE checksum = ?", (checksum,)).fetchone()
        return dict(row) if row else None

    def _publish(self, file_id: int, parsed: ParsedBhavcopy) -> None:
        trade_date = parsed.trade_date.isoformat()
        timestamp = utc_now().isoformat()
        with self.store.connect() as conn:
            conn.execute("DELETE FROM bhavcopy_rows WHERE trade_date = ?", (trade_date,))
            for row in parsed.rows:
                values = numeric_values(row)
                conn.execute(
                    """
                    INSERT INTO bhavcopy_rows (
                        trade_date, symbol, series, prev_close, open_price, high_price, low_price,
                        last_price, close_price, avg_price, traded_quantity, turnover_lacs,
                        no_of_trades, delivery_qty, delivery_percent, raw_json, source_file_id, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_date, symbol, series) DO UPDATE SET
                        prev_close = excluded.prev_close,
                        open_price = excluded.open_price,
                        high_price = excluded.high_price,
                        low_price = excluded.low_price,
                        last_price = excluded.last_price,
                        close_price = excluded.close_price,
                        avg_price = excluded.avg_price,
                        traded_quantity = excluded.traded_quantity,
                        turnover_lacs = excluded.turnover_lacs,
                        no_of_trades = excluded.no_of_trades,
                        delivery_qty = excluded.delivery_qty,
                        delivery_percent = excluded.delivery_percent,
                        raw_json = excluded.raw_json,
                        source_file_id = excluded.source_file_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        trade_date,
                        clean(row["SYMBOL"]).upper(),
                        clean(row["SERIES"]).upper(),
                        values["prev_close"],
                        values["open_price"],
                        values["high_price"],
                        values["low_price"],
                        values["last_price"],
                        values["close_price"],
                        values["avg_price"],
                        values["traded_quantity"],
                        values["turnover_lacs"],
                        values["no_of_trades"],
                        values["delivery_qty"],
                        values["delivery_percent"],
                        json.dumps(row),
                        file_id,
                        timestamp,
                    ),
                )
            conn.execute(
                """
                INSERT INTO import_dates (trade_date, file_id, status, row_count, error, updated_at, published_at)
                VALUES (?, ?, 'published', ?, '', ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    file_id = excluded.file_id,
                    status = excluded.status,
                    row_count = excluded.row_count,
                    error = excluded.error,
                    updated_at = excluded.updated_at,
                    published_at = excluded.published_at
                """,
                (trade_date, file_id, len(parsed.rows), timestamp, timestamp),
            )

    def _mark_date(self, trade_date: str, file_id: int, status: str, row_count: int, error: str) -> None:
        timestamp = utc_now().isoformat()
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO import_dates (trade_date, file_id, status, row_count, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    file_id = excluded.file_id,
                    status = excluded.status,
                    row_count = excluded.row_count,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (trade_date, file_id, status, row_count, error, timestamp),
            )

    def status(self) -> dict[str, Any]:
        with self.store.connect() as conn:
            published_dates = [
                row["trade_date"]
                for row in conn.execute(
                    """
                    SELECT trade_date
                    FROM import_dates
                    WHERE status = 'published'
                    ORDER BY trade_date DESC
                    """
                ).fetchall()
            ]
            counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'published' THEN 1 ELSE 0 END) AS published_count,
                    SUM(CASE WHEN status IN ('rejected', 'schema_error') THEN 1 ELSE 0 END) AS error_count,
                    MAX(CASE WHEN status = 'published' THEN trade_date ELSE NULL END) AS latest_published_date
                FROM import_dates
                """
            ).fetchone()
            file_counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected_count,
                    SUM(CASE WHEN status = 'schema_error' THEN 1 ELSE 0 END) AS schema_error_count
                FROM import_files
                """
            ).fetchone()
            row_count = conn.execute("SELECT COUNT(*) AS value FROM bhavcopy_rows").fetchone()["value"]
            symbol_count = conn.execute(
                "SELECT COUNT(*) AS value FROM (SELECT DISTINCT symbol, series FROM bhavcopy_rows)"
            ).fetchone()["value"]
            recent_files = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, original_filename, trade_date, status, row_count, error, uploaded_at
                    FROM import_files
                    ORDER BY id DESC
                    LIMIT 20
                    """
                ).fetchall()
            ]
            recent_dates = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT trade_date, status, row_count, error, updated_at, published_at
                    FROM import_dates
                    ORDER BY trade_date DESC
                    LIMIT 20
                    """
                ).fetchall()
            ]

        published_count = int(counts["published_count"] or 0)
        next_missing_date = suggested_next_missing_date(published_dates)
        return {
            "generated_at": utc_now(),
            "target_sessions": self.settings.bhavcopy_target_sessions,
            "inbox_path": str(self.settings.import_inbox_dir),
            "published_session_count": published_count,
            "coverage_percent": round((published_count / self.settings.bhavcopy_target_sessions) * 100, 2),
            "latest_published_date": counts["latest_published_date"],
            "next_missing_date": next_missing_date.isoformat() if next_missing_date else None,
            "next_missing_filename": filename_for_trade_date(next_missing_date) if next_missing_date else None,
            "rejected_file_count": int(file_counts["rejected_count"] or 0),
            "schema_error_count": int(file_counts["schema_error_count"] or 0),
            "row_count": int(row_count or 0),
            "symbol_count": int(symbol_count or 0),
            "recent_files": recent_files,
            "recent_dates": recent_dates,
        }

    def coverage(self) -> dict[str, Any]:
        status = self.status()
        with self.store.connect() as conn:
            series_counts = {
                row["series"]: int(row["count"])
                for row in conn.execute(
                    """
                    SELECT series, COUNT(*) AS count
                    FROM bhavcopy_rows
                    GROUP BY series
                    ORDER BY series
                    """
                ).fetchall()
            }
        return {
            "generated_at": status["generated_at"],
            "target_sessions": status["target_sessions"],
            "published_session_count": status["published_session_count"],
            "coverage_percent": status["coverage_percent"],
            "latest_published_date": status["latest_published_date"],
            "row_count": status["row_count"],
            "symbol_count": status["symbol_count"],
            "series_counts": series_counts,
        }

    def rows_for_symbol(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        query = symbol.strip().upper()
        if not query:
            return []
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM bhavcopy_rows
                WHERE UPPER(symbol) = ?
                ORDER BY trade_date DESC, series
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["raw_json"] = json.loads(item["raw_json"] or "{}")
            items.append(item)
        return items


class BhavcopyService:
    def __init__(self, settings: Settings, store: BhavcopyStore) -> None:
        self.settings = settings
        self.store = store

    def import_files(self, files: list[tuple[str, bytes]]) -> dict[str, Any]:
        if not files:
            raise ValueError("At least one bhavcopy file is required.")
        return self.store.import_files(files)

    def import_inbox(self) -> dict[str, Any]:
        return self.store.import_inbox()

    def status(self) -> dict[str, Any]:
        return self.store.status()

    def coverage(self) -> dict[str, Any]:
        return self.store.coverage()

    def rows_for_symbol(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        return self.store.rows_for_symbol(symbol, limit)


def trade_date_from_filename(filename: str) -> date:
    match = FILENAME_RE.match(Path(filename).name)
    if not match:
        raise BhavcopyImportError("Filename must match sec_bhavdata_full_DDMMYYYY.csv.")
    return datetime.strptime(match.group(1), "%d%m%Y").date()


def filename_for_trade_date(value: date) -> str:
    return f"sec_bhavdata_full_{value.strftime('%d%m%Y')}.csv"


def suggested_next_missing_date(published_dates: list[str]) -> date | None:
    if not published_dates:
        return None
    available = {datetime.strptime(value, "%Y-%m-%d").date() for value in published_dates}
    latest = max(available)
    candidate = previous_weekday(latest)
    while candidate in available:
        candidate = previous_weekday(candidate)
    return candidate


def previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def parse_bhavcopy_csv(content: bytes) -> ParsedBhavcopy:
    text = decode_csv(content)
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise BhavcopyImportError("CSV has no header row.")

    columns = [clean_header(column) for column in reader.fieldnames]
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise BhavcopyImportError(f"Missing required column(s): {', '.join(missing)}")

    rows: list[dict[str, str]] = []
    row_dates: set[date] = set()
    for raw_row in reader:
        row = {clean_header(key): clean(value) for key, value in raw_row.items() if key is not None}
        if not any(row.values()):
            continue
        row_dates.add(parse_report_date(row["DATE1"]))
        if not row["SYMBOL"] or not row["SERIES"]:
            continue
        numeric_values(row)
        rows.append(row)

    if not rows:
        raise BhavcopyImportError("Bhavcopy file has no data rows.")
    if len(row_dates) != 1:
        raise BhavcopyImportError("Bhavcopy CSV must contain exactly one DATE1 value.")
    trade_date = next(iter(row_dates))
    return ParsedBhavcopy(trade_date=trade_date, source_columns=columns, total_rows_seen=len(rows), rows=rows)


def numeric_values(row: dict[str, str]) -> dict[str, Any]:
    high = to_float(row["HIGH_PRICE"], "HIGH_PRICE")
    low = to_float(row["LOW_PRICE"], "LOW_PRICE")
    open_price = to_float(row["OPEN_PRICE"], "OPEN_PRICE")
    close_price = to_float(row["CLOSE_PRICE"], "CLOSE_PRICE")
    if high < low:
        raise BhavcopyImportError("HIGH_PRICE cannot be below LOW_PRICE.")
    if not low <= open_price <= high:
        raise BhavcopyImportError("OPEN_PRICE must be inside LOW_PRICE/HIGH_PRICE.")
    if not low <= close_price <= high:
        raise BhavcopyImportError("CLOSE_PRICE must be inside LOW_PRICE/HIGH_PRICE.")
    return {
        "prev_close": to_float(row["PREV_CLOSE"], "PREV_CLOSE"),
        "open_price": open_price,
        "high_price": high,
        "low_price": low,
        "last_price": to_float(row["LAST_PRICE"], "LAST_PRICE"),
        "close_price": close_price,
        "avg_price": to_float(row["AVG_PRICE"], "AVG_PRICE"),
        "traded_quantity": to_float(row["TTL_TRD_QNTY"], "TTL_TRD_QNTY"),
        "turnover_lacs": to_float(row["TURNOVER_LACS"], "TURNOVER_LACS"),
        "no_of_trades": int(to_float(row["NO_OF_TRADES"], "NO_OF_TRADES")),
        "delivery_qty": to_optional_float(row["DELIV_QTY"], "DELIV_QTY"),
        "delivery_percent": to_optional_float(row["DELIV_PER"], "DELIV_PER"),
    }


def decode_csv(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")


def parse_report_date(value: str) -> date:
    cleaned = clean(value)
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(cleaned.title(), fmt).date()
        except ValueError:
            continue
    raise BhavcopyImportError(f"Unsupported DATE1 value: {value}")


def to_float(value: str, column: str) -> float:
    cleaned = clean(value).replace(",", "")
    if cleaned == "":
        raise BhavcopyImportError(f"Missing numeric value for {column}.")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise BhavcopyImportError(f"Invalid numeric value for {column}: {value}") from exc


def to_optional_float(value: str, column: str) -> float | None:
    cleaned = clean(value)
    if cleaned in {"", "-"}:
        return None
    return to_float(cleaned, column)


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def clean_header(value: Any) -> str:
    return clean(value).lstrip("\ufeff")


def safe_filename(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", Path(filename).name)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
