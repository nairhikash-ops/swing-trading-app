import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Any

from app.config import Settings
from app.dhan_client import DhanClient
from app.store import TokenStore
from app.timezone import now_utc


NORMALIZED_COLUMNS = [
    "EXCH_ID",
    "SEGMENT",
    "SECURITY_ID",
    "ISIN",
    "INSTRUMENT",
    "UNDERLYING_SECURITY_ID",
    "UNDERLYING_SYMBOL",
    "SYMBOL_NAME",
    "DISPLAY_NAME",
    "INSTRUMENT_TYPE",
    "SERIES",
    "LOT_SIZE",
    "SM_EXPIRY_DATE",
    "STRIKE_PRICE",
    "OPTION_TYPE",
    "TICK_SIZE",
    "EXPIRY_FLAG",
    "BRACKET_FLAG",
    "COVER_FLAG",
    "ASM_GSM_FLAG",
    "ASM_GSM_CATEGORY",
    "BUY_SELL_INDICATOR",
    "MTF_LEVERAGE",
]


@dataclass(frozen=True)
class ImportStats:
    run_id: int
    source_url: str
    exchange_filter: str
    source_columns: list[str]
    total_rows_seen: int
    imported_rows: int
    inserted_rows: int
    updated_rows: int
    unchanged_rows: int
    deactivated_rows: int
    started_at: datetime
    completed_at: datetime


class InstrumentMasterStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS instrument_import_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT NOT NULL,
                    exchange_filter TEXT NOT NULL,
                    source_columns_json TEXT NOT NULL,
                    total_rows_seen INTEGER NOT NULL DEFAULT 0,
                    imported_rows INTEGER NOT NULL DEFAULT 0,
                    inserted_rows INTEGER NOT NULL DEFAULT 0,
                    updated_rows INTEGER NOT NULL DEFAULT 0,
                    unchanged_rows INTEGER NOT NULL DEFAULT 0,
                    deactivated_rows INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS instruments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    natural_key TEXT NOT NULL UNIQUE,
                    row_hash TEXT NOT NULL,
                    exchange_id TEXT NOT NULL,
                    segment TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    isin TEXT NOT NULL DEFAULT '',
                    instrument TEXT NOT NULL DEFAULT '',
                    underlying_security_id TEXT NOT NULL DEFAULT '',
                    underlying_symbol TEXT NOT NULL DEFAULT '',
                    symbol_name TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    instrument_type TEXT NOT NULL DEFAULT '',
                    series TEXT NOT NULL DEFAULT '',
                    lot_size REAL,
                    expiry_date TEXT NOT NULL DEFAULT '',
                    strike_price REAL,
                    option_type TEXT NOT NULL DEFAULT '',
                    tick_size REAL,
                    expiry_flag TEXT NOT NULL DEFAULT '',
                    bracket_flag TEXT NOT NULL DEFAULT '',
                    cover_flag TEXT NOT NULL DEFAULT '',
                    asm_gsm_flag TEXT NOT NULL DEFAULT '',
                    asm_gsm_category TEXT NOT NULL DEFAULT '',
                    buy_sell_indicator TEXT NOT NULL DEFAULT '',
                    mtf_leverage TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_import_run_id INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_instruments_exchange_active ON instruments(exchange_id, active)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_instruments_symbol ON instruments(symbol_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_instruments_display ON instruments(display_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_instruments_security ON instruments(security_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_instruments_isin ON instruments(isin)")

    def start_import(self, source_url: str, exchange_filter: str, source_columns: list[str]) -> int:
        started_at = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO instrument_import_runs (source_url, exchange_filter, source_columns_json, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (source_url, exchange_filter, json.dumps(source_columns), started_at),
            )
            return int(cursor.lastrowid)

    def finish_import(self, run_id: int, stats: dict[str, int], error: str = "") -> None:
        completed_at = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE instrument_import_runs
                SET total_rows_seen = ?, imported_rows = ?, inserted_rows = ?, updated_rows = ?,
                    unchanged_rows = ?, deactivated_rows = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    stats.get("total_rows_seen", 0),
                    stats.get("imported_rows", 0),
                    stats.get("inserted_rows", 0),
                    stats.get("updated_rows", 0),
                    stats.get("unchanged_rows", 0),
                    stats.get("deactivated_rows", 0),
                    error,
                    completed_at,
                    run_id,
                ),
            )

    def upsert_rows(self, run_id: int, rows: list[dict[str, str]], exchange_filter: str) -> dict[str, int]:
        stats = {
            "imported_rows": 0,
            "inserted_rows": 0,
            "updated_rows": 0,
            "unchanged_rows": 0,
            "deactivated_rows": 0,
        }
        seen_keys: set[str] = set()
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            for raw_row in rows:
                row = normalize_row(raw_row)
                natural_key = build_natural_key(row)
                row_hash = build_row_hash(row)
                seen_keys.add(natural_key)
                stats["imported_rows"] += 1
                current = conn.execute(
                    "SELECT row_hash FROM instruments WHERE natural_key = ?",
                    (natural_key,),
                ).fetchone()
                values = row_values(row, natural_key, row_hash, run_id, timestamp)
                if current is None:
                    conn.execute(insert_sql(), values)
                    stats["inserted_rows"] += 1
                elif current["row_hash"] != row_hash:
                    conn.execute(update_sql(), values[1:27] + values[28:] + (natural_key,))
                    stats["updated_rows"] += 1
                else:
                    conn.execute(
                        """
                        UPDATE instruments
                        SET active = 1, last_seen_at = ?, updated_at = ?, last_import_run_id = ?
                        WHERE natural_key = ?
                        """,
                        (timestamp, timestamp, run_id, natural_key),
                    )
                    stats["unchanged_rows"] += 1

            if seen_keys:
                placeholders = ",".join("?" for _ in seen_keys)
                cursor = conn.execute(
                    f"""
                    UPDATE instruments
                    SET active = 0, updated_at = ?
                    WHERE exchange_id = ? AND natural_key NOT IN ({placeholders})
                    """,
                    (timestamp, exchange_filter, *seen_keys),
                )
                stats["deactivated_rows"] = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        return stats

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active_count,
                    SUM(CASE WHEN exchange_id = 'NSE' THEN 1 ELSE 0 END) AS nse_count,
                    SUM(CASE WHEN exchange_id = 'NSE' AND active = 1 THEN 1 ELSE 0 END) AS active_nse_count
                FROM instruments
                """
            ).fetchone()
            run = conn.execute(
                """
                SELECT * FROM instrument_import_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return {
            "total_count": int(counts["total_count"] or 0),
            "active_count": int(counts["active_count"] or 0),
            "nse_count": int(counts["nse_count"] or 0),
            "active_nse_count": int(counts["active_nse_count"] or 0),
            "last_import": dict(run) if run else None,
        }

    def search(self, query: str, exchange_id: str, limit: int) -> list[dict[str, Any]]:
        term = f"%{query.strip().upper()}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM instruments
                WHERE active = 1 AND exchange_id = ?
                  AND (
                    UPPER(symbol_name) LIKE ?
                    OR UPPER(display_name) LIKE ?
                    OR UPPER(security_id) LIKE ?
                    OR UPPER(isin) LIKE ?
                    OR UPPER(underlying_symbol) LIKE ?
                  )
                ORDER BY
                  CASE
                    WHEN UPPER(underlying_symbol) = ? THEN 0
                    WHEN UPPER(symbol_name) = ? THEN 1
                    WHEN UPPER(display_name) = ? THEN 2
                    ELSE 3
                  END,
                  CASE WHEN segment = 'E' AND instrument = 'EQUITY' THEN 0 ELSE 1 END,
                  CASE WHEN series = 'EQ' THEN 0 ELSE 1 END,
                  symbol_name,
                  display_name
                LIMIT ?
                """,
                (
                    exchange_id.upper(),
                    term,
                    term,
                    term,
                    term,
                    term,
                    query.strip().upper(),
                    query.strip().upper(),
                    query.strip().upper(),
                    limit,
                ),
            ).fetchall()
        return [instrument_row_to_dict(row) for row in rows]


class InstrumentMasterService:
    def __init__(self, settings: Settings, store: InstrumentMasterStore, dhan_client: DhanClient | None = None) -> None:
        self.settings = settings
        self.store = store
        self.dhan_client = dhan_client or DhanClient(settings.dhan_api_base_url)

    async def refresh(self) -> ImportStats:
        source_url = self.settings.dhan_instruments_detailed_url
        exchange_filter = self.settings.dhan_instrument_exchange.upper()
        csv_text = await self.dhan_client.fetch_instrument_master_csv(source_url)
        source_columns, total_rows, rows = parse_instrument_csv(csv_text, exchange_filter)
        run_id = self.store.start_import(source_url, exchange_filter, source_columns)
        stats = {"total_rows_seen": total_rows}
        try:
            stats.update(self.store.upsert_rows(run_id, rows, exchange_filter))
            self.store.finish_import(run_id, stats)
        except Exception as exc:
            self.store.finish_import(run_id, stats, str(exc))
            raise
        status = self.store.status()["last_import"]
        return ImportStats(
            run_id=run_id,
            source_url=source_url,
            exchange_filter=exchange_filter,
            source_columns=source_columns,
            total_rows_seen=total_rows,
            imported_rows=stats["imported_rows"],
            inserted_rows=stats["inserted_rows"],
            updated_rows=stats["updated_rows"],
            unchanged_rows=stats["unchanged_rows"],
            deactivated_rows=stats["deactivated_rows"],
            started_at=datetime.fromisoformat(status["started_at"]),
            completed_at=datetime.fromisoformat(status["completed_at"]),
        )

    def status(self) -> dict[str, Any]:
        return self.store.status()

    def search(self, query: str, exchange_id: str = "NSE", limit: int = 25) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        return self.store.search(query, exchange_id, min(max(limit, 1), 100))


def parse_instrument_csv(csv_text: str, exchange_filter: str) -> tuple[list[str], int, list[dict[str, str]]]:
    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("Dhan instrument master CSV has no header row.")
    source_columns = [column.strip() for column in reader.fieldnames]
    rows: list[dict[str, str]] = []
    total_rows = 0
    for raw in reader:
        total_rows += 1
        normalized = {
            clean_column(key): clean_value(value)
            for key, value in raw.items()
            if key is not None and clean_column(key)
        }
        if normalized.get("EXCH_ID", "").upper() == exchange_filter.upper():
            rows.append(normalized)
    return source_columns, total_rows, rows


def clean_column(value: str) -> str:
    return value.strip().upper()


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_row(raw: dict[str, str]) -> dict[str, str]:
    return {column: raw.get(column, "") for column in set(raw) | set(NORMALIZED_COLUMNS)}


def build_natural_key(row: dict[str, str]) -> str:
    parts = [
        row.get("EXCH_ID", ""),
        row.get("SEGMENT", ""),
        row.get("SECURITY_ID", ""),
        row.get("INSTRUMENT", ""),
        row.get("ISIN", ""),
        row.get("SM_EXPIRY_DATE", ""),
        row.get("STRIKE_PRICE", ""),
        row.get("OPTION_TYPE", ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def build_row_hash(row: dict[str, str]) -> str:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def number_or_none(value: str) -> float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def row_values(row: dict[str, str], natural_key: str, row_hash: str, run_id: int, timestamp: str) -> tuple:
    raw_json = json.dumps(row, sort_keys=True)
    return (
        natural_key,
        row_hash,
        row.get("EXCH_ID", ""),
        row.get("SEGMENT", ""),
        row.get("SECURITY_ID", ""),
        row.get("ISIN", ""),
        row.get("INSTRUMENT", ""),
        row.get("UNDERLYING_SECURITY_ID", ""),
        row.get("UNDERLYING_SYMBOL", ""),
        row.get("SYMBOL_NAME", ""),
        row.get("DISPLAY_NAME", ""),
        row.get("INSTRUMENT_TYPE", ""),
        row.get("SERIES", ""),
        number_or_none(row.get("LOT_SIZE", "")),
        row.get("SM_EXPIRY_DATE", ""),
        number_or_none(row.get("STRIKE_PRICE", "")),
        row.get("OPTION_TYPE", ""),
        number_or_none(row.get("TICK_SIZE", "")),
        row.get("EXPIRY_FLAG", ""),
        row.get("BRACKET_FLAG", ""),
        row.get("COVER_FLAG", ""),
        row.get("ASM_GSM_FLAG", ""),
        row.get("ASM_GSM_CATEGORY", ""),
        row.get("BUY_SELL_INDICATOR", ""),
        row.get("MTF_LEVERAGE", ""),
        raw_json,
        1,
        timestamp,
        timestamp,
        timestamp,
        run_id,
    )


def insert_sql() -> str:
    return """
    INSERT INTO instruments (
        natural_key, row_hash, exchange_id, segment, security_id, isin, instrument,
        underlying_security_id, underlying_symbol, symbol_name, display_name,
        instrument_type, series, lot_size, expiry_date, strike_price, option_type,
        tick_size, expiry_flag, bracket_flag, cover_flag, asm_gsm_flag,
        asm_gsm_category, buy_sell_indicator, mtf_leverage, raw_json, active,
        first_seen_at, last_seen_at, updated_at, last_import_run_id
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """


def update_sql() -> str:
    return """
    UPDATE instruments
    SET row_hash = ?, exchange_id = ?, segment = ?, security_id = ?, isin = ?, instrument = ?,
        underlying_security_id = ?, underlying_symbol = ?, symbol_name = ?, display_name = ?,
        instrument_type = ?, series = ?, lot_size = ?, expiry_date = ?, strike_price = ?,
        option_type = ?, tick_size = ?, expiry_flag = ?, bracket_flag = ?, cover_flag = ?,
        asm_gsm_flag = ?, asm_gsm_category = ?, buy_sell_indicator = ?, mtf_leverage = ?,
        raw_json = ?, active = ?, last_seen_at = ?, updated_at = ?, last_import_run_id = ?
    WHERE natural_key = ?
    """


def instrument_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "exchange_id": row["exchange_id"],
        "segment": row["segment"],
        "security_id": row["security_id"],
        "isin": row["isin"],
        "instrument": row["instrument"],
        "symbol_name": row["symbol_name"],
        "display_name": row["display_name"],
        "instrument_type": row["instrument_type"],
        "series": row["series"],
        "lot_size": row["lot_size"],
        "expiry_date": row["expiry_date"],
        "strike_price": row["strike_price"],
        "option_type": row["option_type"],
        "tick_size": row["tick_size"],
        "buy_sell_indicator": row["buy_sell_indicator"],
        "asm_gsm_flag": row["asm_gsm_flag"],
        "mtf_leverage": row["mtf_leverage"],
        "raw": json.loads(row["raw_json"]),
    }
