import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Any

import httpx

from app.config import Settings
from app.store import TokenStore
from app.timezone import now_utc


NIFTY_500_INDEX_NAME = "NIFTY_500"


@dataclass(frozen=True)
class UniverseImportStats:
    run_id: int
    index_name: str
    source_url: str
    source_columns: list[str]
    total_rows_seen: int
    imported_rows: int
    inserted_rows: int
    updated_rows: int
    unchanged_rows: int
    deactivated_rows: int
    started_at: datetime
    completed_at: datetime


class IndexUniverseStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS index_universe_import_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    index_name TEXT NOT NULL,
                    source_url TEXT NOT NULL,
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
                CREATE TABLE IF NOT EXISTS index_constituents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    index_name TEXT NOT NULL,
                    natural_key TEXT NOT NULL UNIQUE,
                    row_hash TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    series TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_import_run_id INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_index_constituents_index_active ON index_constituents(index_name, active)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_index_constituents_symbol ON index_constituents(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_index_constituents_isin ON index_constituents(isin)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_index_constituents_industry ON index_constituents(industry)")

    def start_import(self, index_name: str, source_url: str, source_columns: list[str]) -> int:
        started_at = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO index_universe_import_runs (index_name, source_url, source_columns_json, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (index_name, source_url, json.dumps(source_columns), started_at),
            )
            return int(cursor.lastrowid)

    def finish_import(self, run_id: int, stats: dict[str, int], error: str = "") -> None:
        completed_at = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE index_universe_import_runs
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

    def upsert_constituents(self, run_id: int, index_name: str, rows: list[dict[str, str]]) -> dict[str, int]:
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
                row = normalize_constituent(raw_row)
                natural_key = build_natural_key(index_name, row)
                row_hash = build_row_hash(raw_row)
                seen_keys.add(natural_key)
                stats["imported_rows"] += 1

                current = conn.execute(
                    "SELECT row_hash FROM index_constituents WHERE natural_key = ?",
                    (natural_key,),
                ).fetchone()
                values = row_values(index_name, natural_key, row_hash, row, raw_row, run_id, timestamp)
                if current is None:
                    conn.execute(insert_sql(), values)
                    stats["inserted_rows"] += 1
                elif current["row_hash"] != row_hash:
                    conn.execute(
                        update_sql(),
                        (
                            row_hash,
                            row["company_name"],
                            row["industry"],
                            row["symbol"],
                            row["series"],
                            row["isin"],
                            json.dumps(raw_row, sort_keys=True),
                            1,
                            timestamp,
                            timestamp,
                            run_id,
                            natural_key,
                        ),
                    )
                    stats["updated_rows"] += 1
                else:
                    conn.execute(
                        """
                        UPDATE index_constituents
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
                    UPDATE index_constituents
                    SET active = 0, updated_at = ?
                    WHERE index_name = ? AND natural_key NOT IN ({placeholders}) AND active = 1
                    """,
                    (timestamp, index_name, *seen_keys),
                )
                stats["deactivated_rows"] = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        return stats

    def status(self, index_name: str) -> dict[str, Any]:
        with self._connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active_count,
                    COUNT(DISTINCT CASE WHEN active = 1 THEN industry END) AS industry_count
                FROM index_constituents
                WHERE index_name = ?
                """,
                (index_name,),
            ).fetchone()
            run = conn.execute(
                """
                SELECT * FROM index_universe_import_runs
                WHERE index_name = ? AND completed_at IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (index_name,),
            ).fetchone()
        return {
            "index_name": index_name,
            "total_count": int(counts["total_count"] or 0),
            "active_count": int(counts["active_count"] or 0),
            "industry_count": int(counts["industry_count"] or 0),
            "last_import": dict(run) if run else None,
        }

    def list_constituents(self, index_name: str, query: str = "", limit: int = 600) -> list[dict[str, Any]]:
        where = "index_name = ? AND active = 1"
        params: list[Any] = [index_name]
        if query.strip():
            term = f"%{query.strip().upper()}%"
            where += " AND (UPPER(company_name) LIKE ? OR UPPER(symbol) LIKE ? OR UPPER(industry) LIKE ? OR UPPER(isin) LIKE ?)"
            params.extend([term, term, term, term])

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM index_constituents
                WHERE {where}
                ORDER BY company_name
                LIMIT ?
                """,
                (*params, min(max(limit, 1), 1000)),
            ).fetchall()
        return [constituent_row_to_dict(row) for row in rows]


class IndexUniverseService:
    def __init__(self, settings: Settings, store: IndexUniverseStore) -> None:
        self.settings = settings
        self.store = store

    async def refresh_nifty_500(self) -> UniverseImportStats:
        index_name = NIFTY_500_INDEX_NAME
        source_url = self.settings.nifty_500_constituents_url
        csv_text = await fetch_csv(source_url)
        source_columns, total_rows, rows = parse_nifty_500_csv(csv_text)
        run_id = self.store.start_import(index_name, source_url, source_columns)
        stats = {"total_rows_seen": total_rows}
        try:
            stats.update(self.store.upsert_constituents(run_id, index_name, rows))
            self.store.finish_import(run_id, stats)
        except Exception as exc:
            self.store.finish_import(run_id, stats, str(exc))
            raise
        status = self.store.status(index_name)["last_import"]
        return UniverseImportStats(
            run_id=run_id,
            index_name=index_name,
            source_url=source_url,
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

    def nifty_500_status(self) -> dict[str, Any]:
        return self.store.status(NIFTY_500_INDEX_NAME)

    def nifty_500_constituents(self, query: str = "", limit: int = 600) -> list[dict[str, Any]]:
        return self.store.list_constituents(NIFTY_500_INDEX_NAME, query, limit)


async def fetch_csv(url: str) -> str:
    headers = {
        "Accept": "text/csv,*/*",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.nseindia.com/static/products-services/indices-nifty500-index",
    }
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
    response.raise_for_status()
    return response.text


def parse_nifty_500_csv(csv_text: str) -> tuple[list[str], int, list[dict[str, str]]]:
    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("Nifty 500 CSV has no header row.")
    source_columns = [column.strip() for column in reader.fieldnames]
    rows: list[dict[str, str]] = []
    total_rows = 0
    for raw in reader:
        total_rows += 1
        row = {clean_column(key): clean_value(value) for key, value in raw.items() if key is not None}
        if row.get("COMPANY NAME") and row.get("SYMBOL") and row.get("INDUSTRY"):
            rows.append(row)
    return source_columns, total_rows, rows


def normalize_constituent(raw: dict[str, str]) -> dict[str, str]:
    return {
        "company_name": raw.get("COMPANY NAME", ""),
        "industry": raw.get("INDUSTRY", ""),
        "symbol": raw.get("SYMBOL", ""),
        "series": raw.get("SERIES", ""),
        "isin": raw.get("ISIN CODE", ""),
    }


def clean_column(value: str) -> str:
    return value.strip().upper()


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_natural_key(index_name: str, row: dict[str, str]) -> str:
    identity = row["isin"] or row["symbol"]
    return f"{index_name}:{identity}"


def build_row_hash(row: dict[str, str]) -> str:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def row_values(
    index_name: str,
    natural_key: str,
    row_hash: str,
    row: dict[str, str],
    raw_row: dict[str, str],
    run_id: int,
    timestamp: str,
) -> tuple:
    raw_json = json.dumps(raw_row, sort_keys=True)
    return (
        index_name,
        natural_key,
        row_hash,
        row["company_name"],
        row["industry"],
        row["symbol"],
        row["series"],
        row["isin"],
        raw_json,
        1,
        timestamp,
        timestamp,
        timestamp,
        run_id,
    )


def insert_sql() -> str:
    return """
    INSERT INTO index_constituents (
        index_name, natural_key, row_hash, company_name, industry, symbol, series,
        isin, raw_json, active, first_seen_at, last_seen_at, updated_at, last_import_run_id
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """


def update_sql() -> str:
    return """
    UPDATE index_constituents
    SET row_hash = ?, company_name = ?, industry = ?, symbol = ?, series = ?, isin = ?,
        raw_json = ?, active = ?, last_seen_at = ?, updated_at = ?, last_import_run_id = ?
    WHERE natural_key = ?
    """


def constituent_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "index_name": row["index_name"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "symbol": row["symbol"],
        "series": row["series"],
        "isin": row["isin"],
        "raw": json.loads(row["raw_json"]),
    }
