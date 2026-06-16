import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.config import Settings
from app.crypto import TokenCrypto
from app.dhan_client import DhanClient
from app.index_universe import NIFTY_500_INDEX_NAME
from app.store import TokenStore
from app.timezone import IST, now_utc
from app.token_service import derive_data_api_status


@dataclass(frozen=True)
class HistoricalWindow:
    from_date: date
    to_date_exclusive: date


class FatalHistoricalError(Exception):
    pass


START_COVERAGE_GRACE_DAYS = 10
END_FRESHNESS_GRACE_DAYS = 3
REUSABLE_TERMINAL_FETCH_STATUSES = {"completed", "completed_with_errors"}
ARCHIVE_PROVIDER = "dhan"
ARCHIVE_INTERVAL = "daily"


def upward_movers_universe_name(threshold_percent: float) -> str:
    threshold = f"{threshold_percent:g}".replace(".", "_")
    return f"{NIFTY_500_INDEX_NAME}_UPWARD_MOVERS_GE_{threshold}"


class HistoricalDataStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_fetch_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    universe_name TEXT NOT NULL,
                    lookback_calendar_days INTEGER NOT NULL,
                    from_date TEXT NOT NULL,
                    to_date_exclusive TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_symbols INTEGER NOT NULL DEFAULT 0,
                    mapped_symbols INTEGER NOT NULL DEFAULT 0,
                    skipped_symbols INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_fetch_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    index_constituent_id INTEGER NOT NULL,
                    instrument_id INTEGER,
                    company_name TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    candles_received INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(run_id, index_constituent_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_candles (
                    instrument_id INTEGER NOT NULL,
                    security_id TEXT NOT NULL,
                    exchange_segment TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    trading_date TEXT NOT NULL,
                    source_timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    open_interest REAL,
                    source TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, trading_date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_instrument_archive (
                    instrument_id INTEGER NOT NULL,
                    security_id TEXT NOT NULL,
                    symbol TEXT NOT NULL DEFAULT '',
                    source_provider TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    first_stored_candle_date TEXT,
                    latest_stored_candle_date TEXT,
                    source_floor_reached INTEGER NOT NULL DEFAULT 0,
                    source_floor_date TEXT,
                    source_floor_reason TEXT NOT NULL DEFAULT 'unknown',
                    complete_available_history INTEGER NOT NULL DEFAULT 0,
                    last_successful_fetch_at TEXT,
                    last_no_new_data_at TEXT,
                    next_retry_after TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, source_provider, interval)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_historical_fetch_runs_status ON historical_fetch_runs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_historical_fetch_items_run_status ON historical_fetch_items(run_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_candles_security_date ON daily_candles(security_id, trading_date)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_historical_archive_latest ON historical_instrument_archive(latest_stored_candle_date)"
            )
            ensure_columns(
                conn,
                "historical_fetch_items",
                {
                    "request_from_date": "TEXT",
                    "request_to_date": "TEXT",
                    "archive_status": "TEXT NOT NULL DEFAULT ''",
                    "source_floor_reason": "TEXT NOT NULL DEFAULT ''",
                },
            )

    def active_run(self, universe_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM historical_fetch_runs
                WHERE universe_name = ? AND status IN ('queued', 'running')
                ORDER BY id DESC
                LIMIT 1
                """,
                (universe_name,),
            ).fetchone()
        return dict(row) if row else None

    def latest_run(self, universe_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM historical_fetch_runs
                WHERE universe_name = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (universe_name,),
            ).fetchone()
        return dict(row) if row else None

    def archive_metadata(self, instrument_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM historical_instrument_archive
                WHERE instrument_id = ? AND source_provider = ? AND interval = ?
                """,
                (instrument_id, ARCHIVE_PROVIDER, ARCHIVE_INTERVAL),
            ).fetchone()
        return archive_row_to_dict(row) if row else None

    def stored_candle_range(self, instrument_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MIN(trading_date) AS first_stored_candle_date,
                       MAX(trading_date) AS latest_stored_candle_date,
                       COUNT(*) AS stored_candle_count
                FROM daily_candles
                WHERE instrument_id = ?
                """,
                (instrument_id,),
            ).fetchone()
        return dict(row)

    def coverage_status(self, universe_name: str, lookback_days: int, window: HistoricalWindow) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        start_grace_date = (window.from_date + timedelta(days=START_COVERAGE_GRACE_DAYS)).isoformat()
        end_grace_date = (window.to_date_exclusive - timedelta(days=END_FRESHNESS_GRACE_DAYS)).isoformat()
        with self._connect() as conn:
            total = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_symbols,
                    SUM(CASE WHEN i.id IS NOT NULL THEN 1 ELSE 0 END) AS mapped_symbols,
                    SUM(CASE WHEN i.id IS NULL THEN 1 ELSE 0 END) AS skipped_symbols
                FROM index_constituents ic
                LEFT JOIN instruments i ON i.active = 1
                  AND i.exchange_id = 'NSE'
                  AND i.segment = 'E'
                  AND i.instrument = 'EQUITY'
                  AND i.isin = ic.isin
                WHERE ic.index_name = ? AND ic.active = 1
                """,
                (universe_name,),
            ).fetchone()
            mapped_symbols = int(total["mapped_symbols"] or 0)
            complete_symbols = conn.execute(
                """
                SELECT COUNT(*) AS complete_symbols
                FROM (
                    SELECT i.id AS instrument_id,
                           MIN(dc.trading_date) AS first_candle,
                           MAX(dc.trading_date) AS latest_candle
                    FROM index_constituents ic
                    JOIN instruments i ON i.active = 1
                      AND i.exchange_id = 'NSE'
                      AND i.segment = 'E'
                      AND i.instrument = 'EQUITY'
                      AND i.isin = ic.isin
                    JOIN daily_candles dc ON dc.instrument_id = i.id
                      AND dc.trading_date >= ?
                      AND dc.trading_date < ?
                    WHERE ic.index_name = ? AND ic.active = 1
                    GROUP BY i.id
                    HAVING first_candle <= ? AND latest_candle >= ?
                ) covered
                """,
                (
                    window.from_date.isoformat(),
                    window.to_date_exclusive.isoformat(),
                    universe_name,
                    start_grace_date,
                    end_grace_date,
                ),
            ).fetchone()
            stored_candles = conn.execute(
                """
                SELECT COUNT(*) AS stored_candle_count
                FROM daily_candles dc
                WHERE dc.trading_date >= ? AND dc.trading_date < ?
                  AND dc.instrument_id IN (
                    SELECT i.id
                    FROM index_constituents ic
                    JOIN instruments i ON i.active = 1
                      AND i.exchange_id = 'NSE'
                      AND i.segment = 'E'
                      AND i.instrument = 'EQUITY'
                      AND i.isin = ic.isin
                    WHERE ic.index_name = ? AND ic.active = 1
                  )
                """,
                (window.from_date.isoformat(), window.to_date_exclusive.isoformat(), universe_name),
            ).fetchone()

        complete = mapped_symbols > 0 and int(complete_symbols["complete_symbols"] or 0) == mapped_symbols
        return {
            "id": 0,
            "universe_name": universe_name,
            "lookback_calendar_days": lookback_days,
            "from_date": window.from_date.isoformat(),
            "to_date_exclusive": window.to_date_exclusive.isoformat(),
            "status": "up_to_date" if complete else "missing_data",
            "total_symbols": int(total["total_symbols"] or 0),
            "mapped_symbols": mapped_symbols,
            "skipped_symbols": int(total["skipped_symbols"] or 0),
            "queued_count": 0,
            "fetching_count": 0,
            "done_count": mapped_symbols if complete else int(complete_symbols["complete_symbols"] or 0),
            "failed_count": 0,
            "skipped_count": int(total["skipped_symbols"] or 0),
            "candles_received": 0,
            "stored_candle_count": int(stored_candles["stored_candle_count"] or 0),
            "error": "" if complete else "Some mapped instruments do not have candles in the current window.",
            "started_at": timestamp,
            "updated_at": timestamp,
            "completed_at": timestamp,
        }

    def coverage_status_for_constituent_ids(
        self,
        universe_name: str,
        lookback_days: int,
        window: HistoricalWindow,
        constituent_ids: list[int],
        source_universe_name: str = NIFTY_500_INDEX_NAME,
    ) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        ids = normalized_ids(constituent_ids)
        if not ids:
            return empty_historical_status(
                universe_name=universe_name,
                lookback_days=lookback_days,
                window=window,
                status="no_matches",
                error="No stocks matched the upward movement threshold.",
                timestamp=timestamp,
            )

        placeholders = ",".join("?" for _ in ids)
        start_grace_date = (window.from_date + timedelta(days=START_COVERAGE_GRACE_DAYS)).isoformat()
        end_grace_date = (window.to_date_exclusive - timedelta(days=END_FRESHNESS_GRACE_DAYS)).isoformat()
        with self._connect() as conn:
            total = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total_symbols,
                    SUM(CASE WHEN i.id IS NOT NULL THEN 1 ELSE 0 END) AS mapped_symbols,
                    SUM(CASE WHEN i.id IS NULL THEN 1 ELSE 0 END) AS skipped_symbols
                FROM index_constituents ic
                LEFT JOIN instruments i ON i.active = 1
                  AND i.exchange_id = 'NSE'
                  AND i.segment = 'E'
                  AND i.instrument = 'EQUITY'
                  AND i.isin = ic.isin
                WHERE ic.index_name = ? AND ic.active = 1 AND ic.id IN ({placeholders})
                """,
                (source_universe_name, *ids),
            ).fetchone()
            mapped_symbols = int(total["mapped_symbols"] or 0)
            complete_symbols = conn.execute(
                f"""
                SELECT COUNT(*) AS complete_symbols
                FROM (
                    SELECT i.id AS instrument_id,
                           MIN(dc.trading_date) AS first_candle,
                           MAX(dc.trading_date) AS latest_candle
                    FROM index_constituents ic
                    JOIN instruments i ON i.active = 1
                      AND i.exchange_id = 'NSE'
                      AND i.segment = 'E'
                      AND i.instrument = 'EQUITY'
                      AND i.isin = ic.isin
                    JOIN daily_candles dc ON dc.instrument_id = i.id
                      AND dc.trading_date >= ?
                      AND dc.trading_date < ?
                    WHERE ic.index_name = ? AND ic.active = 1 AND ic.id IN ({placeholders})
                    GROUP BY i.id
                    HAVING first_candle <= ? AND latest_candle >= ?
                ) covered
                """,
                (
                    window.from_date.isoformat(),
                    window.to_date_exclusive.isoformat(),
                    source_universe_name,
                    *ids,
                    start_grace_date,
                    end_grace_date,
                ),
            ).fetchone()
            stored_candles = conn.execute(
                f"""
                SELECT COUNT(*) AS stored_candle_count
                FROM daily_candles dc
                WHERE dc.trading_date >= ? AND dc.trading_date < ?
                  AND dc.instrument_id IN (
                    SELECT i.id
                    FROM index_constituents ic
                    JOIN instruments i ON i.active = 1
                      AND i.exchange_id = 'NSE'
                      AND i.segment = 'E'
                      AND i.instrument = 'EQUITY'
                      AND i.isin = ic.isin
                    WHERE ic.index_name = ? AND ic.active = 1 AND ic.id IN ({placeholders})
                  )
                """,
                (window.from_date.isoformat(), window.to_date_exclusive.isoformat(), source_universe_name, *ids),
            ).fetchone()

        complete = mapped_symbols > 0 and int(complete_symbols["complete_symbols"] or 0) == mapped_symbols
        return {
            "id": 0,
            "universe_name": universe_name,
            "lookback_calendar_days": lookback_days,
            "from_date": window.from_date.isoformat(),
            "to_date_exclusive": window.to_date_exclusive.isoformat(),
            "status": "up_to_date" if complete else "missing_data",
            "total_symbols": int(total["total_symbols"] or 0),
            "mapped_symbols": mapped_symbols,
            "skipped_symbols": int(total["skipped_symbols"] or 0),
            "queued_count": 0,
            "fetching_count": 0,
            "done_count": mapped_symbols if complete else int(complete_symbols["complete_symbols"] or 0),
            "failed_count": 0,
            "skipped_count": int(total["skipped_symbols"] or 0),
            "candles_received": 0,
            "stored_candle_count": int(stored_candles["stored_candle_count"] or 0),
            "error": "" if complete else "Some selected instruments do not have full cached coverage for this window.",
            "started_at": timestamp,
            "updated_at": timestamp,
            "completed_at": timestamp,
        }

    def create_run(self, universe_name: str, lookback_days: int, window: HistoricalWindow) -> int:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO historical_fetch_runs (
                    universe_name, lookback_calendar_days, from_date, to_date_exclusive,
                    status, started_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    universe_name,
                    lookback_days,
                    window.from_date.isoformat(),
                    window.to_date_exclusive.isoformat(),
                    timestamp,
                    timestamp,
                ),
            )
            run_id = int(cursor.lastrowid)
            constituents = conn.execute(
                """
                SELECT id, company_name, industry, symbol, isin
                FROM index_constituents
                WHERE index_name = ? AND active = 1
                ORDER BY company_name
                """,
                (universe_name,),
            ).fetchall()

            mapped_symbols = 0
            skipped_symbols = 0
            for constituent in constituents:
                instrument = conn.execute(
                    """
                    SELECT id, security_id
                    FROM instruments
                    WHERE active = 1
                      AND exchange_id = 'NSE'
                      AND segment = 'E'
                      AND instrument = 'EQUITY'
                      AND isin = ?
                    ORDER BY CASE WHEN series = 'EQ' THEN 0 ELSE 1 END, id
                    LIMIT 1
                    """,
                    (constituent["isin"],),
                ).fetchone()
                if instrument:
                    mapped_symbols += 1
                    instrument_id = instrument["id"]
                    security_id = instrument["security_id"]
                    plan = fetch_plan_for_instrument(conn, int(instrument_id), str(security_id), constituent["symbol"], window)
                    status = plan["status"]
                    error = plan["error"]
                else:
                    skipped_symbols += 1
                    status = "skipped_unmapped"
                    instrument_id = None
                    security_id = ""
                    error = "No active Dhan NSE equity instrument matched this Nifty 500 ISIN."
                    plan = {"request_from_date": None, "request_to_date": None, "archive_status": "", "source_floor_reason": ""}
                conn.execute(
                    """
                    INSERT INTO historical_fetch_items (
                        run_id, index_constituent_id, instrument_id, company_name, industry,
                        symbol, isin, security_id, status, error, request_from_date, request_to_date,
                        archive_status, source_floor_reason, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        constituent["id"],
                        instrument_id,
                        constituent["company_name"],
                        constituent["industry"],
                        constituent["symbol"],
                        constituent["isin"],
                        security_id,
                        status,
                        error,
                        plan["request_from_date"],
                        plan["request_to_date"],
                        plan["archive_status"],
                        plan["source_floor_reason"],
                        timestamp,
                    ),
                )

            conn.execute(
                """
                UPDATE historical_fetch_runs
                SET total_symbols = ?, mapped_symbols = ?, skipped_symbols = ?, updated_at = ?
                WHERE id = ?
                """,
                (len(constituents), mapped_symbols, skipped_symbols, timestamp, run_id),
            )
            return run_id

    def create_run_for_constituent_ids(
        self,
        universe_name: str,
        lookback_days: int,
        window: HistoricalWindow,
        constituent_ids: list[int],
        source_universe_name: str = NIFTY_500_INDEX_NAME,
    ) -> int:
        timestamp = now_utc().isoformat()
        ids = normalized_ids(constituent_ids)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO historical_fetch_runs (
                    universe_name, lookback_calendar_days, from_date, to_date_exclusive,
                    status, started_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    universe_name,
                    lookback_days,
                    window.from_date.isoformat(),
                    window.to_date_exclusive.isoformat(),
                    timestamp,
                    timestamp,
                ),
            )
            run_id = int(cursor.lastrowid)
            if ids:
                placeholders = ",".join("?" for _ in ids)
                constituents = conn.execute(
                    f"""
                    SELECT id, company_name, industry, symbol, isin
                    FROM index_constituents
                    WHERE index_name = ? AND active = 1 AND id IN ({placeholders})
                    ORDER BY company_name
                    """,
                    (source_universe_name, *ids),
                ).fetchall()
            else:
                constituents = []

            mapped_symbols = 0
            skipped_symbols = 0
            for constituent in constituents:
                instrument = conn.execute(
                    """
                    SELECT id, security_id
                    FROM instruments
                    WHERE active = 1
                      AND exchange_id = 'NSE'
                      AND segment = 'E'
                      AND instrument = 'EQUITY'
                      AND isin = ?
                    ORDER BY CASE WHEN series = 'EQ' THEN 0 ELSE 1 END, id
                    LIMIT 1
                    """,
                    (constituent["isin"],),
                ).fetchone()
                if instrument:
                    mapped_symbols += 1
                    instrument_id = instrument["id"]
                    security_id = instrument["security_id"]
                    plan = fetch_plan_for_instrument(conn, int(instrument_id), str(security_id), constituent["symbol"], window)
                    status = plan["status"]
                    error = plan["error"]
                else:
                    skipped_symbols += 1
                    status = "skipped_unmapped"
                    instrument_id = None
                    security_id = ""
                    error = "No active Dhan NSE equity instrument matched this Nifty 500 ISIN."
                    plan = {"request_from_date": None, "request_to_date": None, "archive_status": "", "source_floor_reason": ""}
                conn.execute(
                    """
                    INSERT INTO historical_fetch_items (
                        run_id, index_constituent_id, instrument_id, company_name, industry,
                        symbol, isin, security_id, status, error, request_from_date, request_to_date,
                        archive_status, source_floor_reason, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        constituent["id"],
                        instrument_id,
                        constituent["company_name"],
                        constituent["industry"],
                        constituent["symbol"],
                        constituent["isin"],
                        security_id,
                        status,
                        error,
                        plan["request_from_date"],
                        plan["request_to_date"],
                        plan["archive_status"],
                        plan["source_floor_reason"],
                        timestamp,
                    ),
                )

            conn.execute(
                """
                UPDATE historical_fetch_runs
                SET total_symbols = ?, mapped_symbols = ?, skipped_symbols = ?, updated_at = ?
                WHERE id = ?
                """,
                (len(constituents), mapped_symbols, skipped_symbols, timestamp, run_id),
            )
            return run_id

    def prepare_run(self, run_id: int) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE historical_fetch_items
                SET status = 'queued', updated_at = ?
                WHERE run_id = ? AND status = 'fetching'
                """,
                (timestamp, run_id),
            )
            conn.execute(
                """
                UPDATE historical_fetch_runs
                SET status = 'running', error = '', updated_at = ?
                WHERE id = ?
                """,
                (timestamp, run_id),
            )

    def queued_items(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM historical_fetch_items
                WHERE run_id = ? AND status = 'queued'
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_item_fetching(self, item_id: int, attempts: int) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE historical_fetch_items
                SET status = 'fetching', attempts = ?, started_at = COALESCE(started_at, ?),
                    updated_at = ?, error = ''
                WHERE id = ?
                """,
                (attempts, timestamp, timestamp, item_id),
            )
            self._touch_run(conn, item_id, timestamp)

    def mark_item_done(self, item_id: int, candles_received: int) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE historical_fetch_items
                SET status = 'done', candles_received = ?, error = '',
                    finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (candles_received, timestamp, timestamp, item_id),
            )
            self._touch_run(conn, item_id, timestamp)

    def mark_item_no_new_data(self, item_id: int, reason: str) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE historical_fetch_items
                SET status = 'skipped_no_new_data', candles_received = 0, error = ?,
                    archive_status = CASE
                        WHEN archive_status = 'older_history_backfill' THEN archive_status
                        ELSE 'waiting_for_next_session'
                    END,
                    source_floor_reason = ?,
                    finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (reason[:1000], reason, timestamp, timestamp, item_id),
            )
            self._touch_run(conn, item_id, timestamp)

    def mark_item_failed(self, item_id: int, error: str) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE historical_fetch_items
                SET status = 'failed', error = ?, finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (error[:1000], timestamp, timestamp, item_id),
            )
            self._touch_run(conn, item_id, timestamp)

    def fail_remaining(self, run_id: int, error: str) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE historical_fetch_items
                SET status = 'failed', error = ?, finished_at = ?, updated_at = ?
                WHERE run_id = ? AND status IN ('queued', 'fetching')
                """,
                (error[:1000], timestamp, timestamp, run_id),
            )
            conn.execute(
                """
                UPDATE historical_fetch_runs
                SET status = 'failed', error = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (error[:1000], timestamp, timestamp, run_id),
            )

    def upsert_candles(
        self,
        item: dict[str, Any],
        candles: list[dict[str, Any]],
        exchange_segment: str,
        instrument: str,
    ) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            for candle in candles:
                conn.execute(
                    """
                    INSERT INTO daily_candles (
                        instrument_id, security_id, exchange_segment, instrument, trading_date,
                        source_timestamp, open, high, low, close, volume, open_interest,
                        source, raw_json, fetched_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'dhan_historical', ?, ?, ?)
                    ON CONFLICT(instrument_id, trading_date) DO UPDATE SET
                        security_id = excluded.security_id,
                        exchange_segment = excluded.exchange_segment,
                        instrument = excluded.instrument,
                        source_timestamp = excluded.source_timestamp,
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        volume = excluded.volume,
                        open_interest = excluded.open_interest,
                        source = excluded.source,
                        raw_json = excluded.raw_json,
                        fetched_at = excluded.fetched_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item["instrument_id"],
                        item["security_id"],
                        exchange_segment,
                        instrument,
                        candle["trading_date"],
                        candle["timestamp"],
                        candle["open"],
                        candle["high"],
                        candle["low"],
                        candle["close"],
                        candle["volume"],
                        candle.get("open_interest"),
                        json.dumps(candle, sort_keys=True),
                        timestamp,
                        timestamp,
                    ),
                )

    def record_fetch_outcome(self, item: dict[str, Any], candles: list[dict[str, Any]], request_from: date, request_to: date) -> str:
        timestamp = now_utc().isoformat()
        retry_after = (now_utc() + timedelta(hours=12)).isoformat()
        instrument_id = int(item["instrument_id"])
        security_id = str(item["security_id"])
        symbol = str(item["symbol"])
        returned_first = min((candle["trading_date"] for candle in candles), default=None)
        with self._connect() as conn:
            stored = conn.execute(
                """
                SELECT MIN(trading_date) AS first_stored_candle_date,
                       MAX(trading_date) AS latest_stored_candle_date
                FROM daily_candles
                WHERE instrument_id = ?
                """,
                (instrument_id,),
            ).fetchone()
            existing = conn.execute(
                """
                SELECT * FROM historical_instrument_archive
                WHERE instrument_id = ? AND source_provider = ? AND interval = ?
                """,
                (instrument_id, ARCHIVE_PROVIDER, ARCHIVE_INTERVAL),
            ).fetchone()
            first_stored = stored["first_stored_candle_date"]
            latest_stored = stored["latest_stored_candle_date"]
            existing_floor_reached = bool(existing["source_floor_reached"]) if existing else False
            existing_complete = bool(existing["complete_available_history"]) if existing else False
            existing_floor_date = existing["source_floor_date"] if existing else None
            existing_floor_reason = existing["source_floor_reason"] if existing else "unknown"

            source_floor_reached = existing_floor_reached
            complete_available_history = existing_complete
            source_floor_date = existing_floor_date
            source_floor_reason = existing_floor_reason
            last_successful_fetch_at = existing["last_successful_fetch_at"] if existing else None
            last_no_new_data_at = existing["last_no_new_data_at"] if existing else None
            next_retry_after = existing["next_retry_after"] if existing else None
            last_error = ""

            if candles:
                last_successful_fetch_at = timestamp
                next_retry_after = None
                archive_status = item.get("archive_status")
                if archive_status == "initial_capture" and returned_first and returned_first > request_from.isoformat():
                    source_floor_reached = True
                    complete_available_history = True
                    source_floor_date = returned_first
                    source_floor_reason = "stock_listed_recently"
                elif archive_status == "older_history_backfill" and returned_first and returned_first > request_from.isoformat():
                    source_floor_reached = True
                    complete_available_history = True
                    source_floor_date = returned_first
                    source_floor_reason = "no_older_data_from_dhan"
                elif archive_status in ("initial_capture", "older_history_backfill"):
                    source_floor_reached = True
                    complete_available_history = True
                    source_floor_date = request_from.isoformat()
                    source_floor_reason = "dhan_5_year_limit"
            else:
                last_no_new_data_at = timestamp
                if item.get("archive_status") == "older_history_backfill" and first_stored:
                    next_retry_after = None
                    source_floor_reached = True
                    complete_available_history = True
                    source_floor_date = first_stored
                    source_floor_reason = "no_older_data_from_dhan"
                elif first_stored:
                    next_retry_after = retry_after
                    source_floor_reason = "no_new_data_available_yet"
                else:
                    next_retry_after = None
                    source_floor_reached = True
                    complete_available_history = True
                    source_floor_date = request_from.isoformat()
                    source_floor_reason = "no_older_data_from_dhan"

            conn.execute(
                """
                INSERT INTO historical_instrument_archive (
                    instrument_id, security_id, symbol, source_provider, interval,
                    first_stored_candle_date, latest_stored_candle_date,
                    source_floor_reached, source_floor_date, source_floor_reason,
                    complete_available_history, last_successful_fetch_at,
                    last_no_new_data_at, next_retry_after, last_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id, source_provider, interval) DO UPDATE SET
                    security_id = excluded.security_id,
                    symbol = excluded.symbol,
                    first_stored_candle_date = excluded.first_stored_candle_date,
                    latest_stored_candle_date = excluded.latest_stored_candle_date,
                    source_floor_reached = excluded.source_floor_reached,
                    source_floor_date = excluded.source_floor_date,
                    source_floor_reason = excluded.source_floor_reason,
                    complete_available_history = excluded.complete_available_history,
                    last_successful_fetch_at = excluded.last_successful_fetch_at,
                    last_no_new_data_at = excluded.last_no_new_data_at,
                    next_retry_after = excluded.next_retry_after,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    instrument_id,
                    security_id,
                    symbol,
                    ARCHIVE_PROVIDER,
                    ARCHIVE_INTERVAL,
                    first_stored,
                    latest_stored,
                    1 if source_floor_reached else 0,
                    source_floor_date,
                    source_floor_reason,
                    1 if complete_available_history else 0,
                    last_successful_fetch_at,
                    last_no_new_data_at,
                    next_retry_after,
                    last_error,
                    timestamp,
                    timestamp,
                ),
            )
            return source_floor_reason

    def finish_run_if_complete(self, run_id: int) -> None:
        summary = self.status(run_id=run_id)
        if not summary:
            return
        if summary["queued_count"] > 0 or summary["fetching_count"] > 0:
            return
        timestamp = now_utc().isoformat()
        if summary["done_count"] == 0 and summary["failed_count"] > 0:
            status = "failed"
            error = "All mapped historical fetches failed."
        elif summary["failed_count"] > 0 or summary["skipped_count"] > 0:
            status = "completed_with_errors"
            error = ""
        else:
            status = "completed"
            error = ""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE historical_fetch_runs
                SET status = ?, error = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, error, timestamp, timestamp, run_id),
            )

    def status(self, run_id: int | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            if run_id is None:
                run = conn.execute(
                    """
                    SELECT * FROM historical_fetch_runs
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
            else:
                run = conn.execute("SELECT * FROM historical_fetch_runs WHERE id = ?", (run_id,)).fetchone()
            if not run:
                return None
            counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued_count,
                    SUM(CASE WHEN status = 'fetching' THEN 1 ELSE 0 END) AS fetching_count,
                    SUM(CASE WHEN status IN ('done', 'skipped_up_to_date', 'skipped_no_new_data', 'skipped_retry_later') THEN 1 ELSE 0 END) AS done_count,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN status = 'skipped_unmapped' THEN 1 ELSE 0 END) AS skipped_count,
                    SUM(candles_received) AS candles_received
                FROM historical_fetch_items
                WHERE run_id = ?
                """,
                (run["id"],),
            ).fetchone()
            candle_count = conn.execute(
                """
                SELECT COUNT(*) AS candle_count
                FROM daily_candles
                WHERE trading_date >= ? AND trading_date < ?
                  AND instrument_id IN (
                    SELECT instrument_id FROM historical_fetch_items
                    WHERE run_id = ? AND instrument_id IS NOT NULL
                  )
                """,
                (run["from_date"], run["to_date_exclusive"], run["id"]),
            ).fetchone()
            archive = conn.execute(
                """
                SELECT
                    MIN(first_stored_candle_date) AS first_stored_candle_date,
                    MAX(latest_stored_candle_date) AS latest_stored_candle_date,
                    SUM(CASE WHEN source_floor_reached = 1 THEN 1 ELSE 0 END) AS source_floor_reached_count,
                    SUM(CASE WHEN complete_available_history = 1 THEN 1 ELSE 0 END) AS complete_available_history_count,
                    MIN(next_retry_after) AS next_retry_after
                FROM historical_instrument_archive
                WHERE source_provider = ? AND interval = ?
                  AND instrument_id IN (
                    SELECT instrument_id FROM historical_fetch_items
                    WHERE run_id = ? AND instrument_id IS NOT NULL
                  )
                """,
                (ARCHIVE_PROVIDER, ARCHIVE_INTERVAL, run["id"]),
            ).fetchone()
        data = dict(run)
        data.update(
            {
                "queued_count": int(counts["queued_count"] or 0),
                "fetching_count": int(counts["fetching_count"] or 0),
                "done_count": int(counts["done_count"] or 0),
                "failed_count": int(counts["failed_count"] or 0),
                "skipped_count": int(counts["skipped_count"] or 0),
                "candles_received": int(counts["candles_received"] or 0),
                "stored_candle_count": int(candle_count["candle_count"] or 0),
                "first_stored_candle_date": archive["first_stored_candle_date"],
                "latest_stored_candle_date": archive["latest_stored_candle_date"],
                "source_floor_reached_count": int(archive["source_floor_reached_count"] or 0),
                "complete_available_history_count": int(archive["complete_available_history_count"] or 0),
                "next_retry_after": archive["next_retry_after"],
            }
        )
        return data

    def items(self, run_id: int, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = [run_id]
        where = "run_id = ?"
        if status:
            where += " AND status = ?"
            params.append(status)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM historical_fetch_items
                WHERE {where}
                ORDER BY id
                LIMIT ?
                """,
                (*params, min(max(limit, 1), 500)),
            ).fetchall()
        return [dict(row) for row in rows]

    def candles_for_symbol(self, symbol: str, limit: int = 80) -> list[dict[str, Any]]:
        with self._connect() as conn:
            instrument = conn.execute(
                """
                SELECT id FROM instruments
                WHERE active = 1 AND exchange_id = 'NSE' AND segment = 'E'
                  AND UPPER(underlying_symbol) = UPPER(?)
                ORDER BY CASE WHEN series = 'EQ' THEN 0 ELSE 1 END, id
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if not instrument:
                return []
            rows = conn.execute(
                """
                SELECT * FROM daily_candles
                WHERE instrument_id = ?
                ORDER BY trading_date DESC
                LIMIT ?
                """,
                (instrument["id"], min(max(limit, 1), 500)),
            ).fetchall()
        return [candle_row_to_dict(row) for row in rows]

    def prune_candles_before(self, cutoff_date: date) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM daily_candles
                WHERE trading_date < ?
                """,
                (cutoff_date.isoformat(),),
            )
            return int(cursor.rowcount if cursor.rowcount is not None else 0)

    def _touch_run(self, conn, item_id: int, timestamp: str) -> None:
        conn.execute(
            """
            UPDATE historical_fetch_runs
            SET updated_at = ?
            WHERE id = (SELECT run_id FROM historical_fetch_items WHERE id = ?)
            """,
            (timestamp, item_id),
        )


class HistoricalDataService:
    def __init__(
        self,
        settings: Settings,
        token_store: TokenStore,
        store: HistoricalDataStore,
        dhan_client: DhanClient | None = None,
    ) -> None:
        self.settings = settings
        self.token_store = token_store
        self.store = store
        self.dhan_client = dhan_client or DhanClient(settings.dhan_api_base_url)
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start_or_resume_nifty_500_fetch(self) -> dict[str, Any]:
        async with self._lock:
            active_run = self.store.active_run(NIFTY_500_INDEX_NAME)
            if active_run is None:
                if self._task is not None and not self._task.done():
                    raise ValueError("Another historical fetch is already running.")
                self._access_token()
                window = clamp_window_to_dhan_floor(self.settings, historical_window(self.settings))
                latest_run = self.store.latest_run(NIFTY_500_INDEX_NAME)
                latest_status = self.store.status(int(latest_run["id"])) if latest_run else None
                if reusable_current_window_run(
                    latest_status,
                    self.settings.historical_lookback_calendar_days,
                    window,
                ):
                    return latest_status or {}
                coverage = self.store.coverage_status(
                    NIFTY_500_INDEX_NAME,
                    self.settings.historical_lookback_calendar_days,
                    window,
                )
                if coverage["status"] == "up_to_date":
                    return coverage
                run_id = self.store.create_run(
                    NIFTY_500_INDEX_NAME,
                    self.settings.historical_lookback_calendar_days,
                    window,
                )
            else:
                run_id = int(active_run["id"])
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(asyncio.to_thread(self._run_fetch_sync, run_id))
            status = self.store.status(run_id)
            return status or {}

    async def start_or_resume_constituent_fetch(
        self,
        universe_name: str,
        constituent_ids: list[int],
        lookback_calendar_days: int,
        source_universe_name: str = NIFTY_500_INDEX_NAME,
    ) -> dict[str, Any]:
        async with self._lock:
            active_run = self.store.active_run(universe_name)
            if active_run is None:
                if self._task is not None and not self._task.done():
                    raise ValueError("Another historical fetch is already running.")
                self._access_token()
                window = clamp_window_to_dhan_floor(self.settings, historical_window(self.settings, lookback_calendar_days))
                coverage = self.store.coverage_status_for_constituent_ids(
                    universe_name,
                    lookback_calendar_days,
                    window,
                    constituent_ids,
                    source_universe_name,
                )
                if coverage["status"] in ("up_to_date", "no_matches"):
                    return coverage
                run_id = self.store.create_run_for_constituent_ids(
                    universe_name,
                    lookback_calendar_days,
                    window,
                    constituent_ids,
                    source_universe_name,
                )
            else:
                run_id = int(active_run["id"])
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(asyncio.to_thread(self._run_fetch_sync, run_id))
            status = self.store.status(run_id)
            return status or {}

    def latest_status(self, universe_name: str | None = None) -> dict[str, Any] | None:
        if universe_name:
            run = self.store.latest_run(universe_name)
            return self.store.status(int(run["id"])) if run else None
        return self.store.status()

    def items(self, run_id: int, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.items(run_id, status, limit)

    def candles_for_symbol(self, symbol: str, limit: int = 80) -> list[dict[str, Any]]:
        return self.store.candles_for_symbol(symbol, limit)

    def prune_retention_window(self) -> dict[str, Any]:
        window = historical_window(self.settings, self.settings.data_retention_calendar_days)
        deleted_count = self.store.prune_candles_before(window.from_date)
        return {
            "cutoff_date": window.from_date.isoformat(),
            "deleted_candle_count": deleted_count,
        }

    def _run_fetch_sync(self, run_id: int) -> None:
        asyncio.run(self._run_fetch(run_id))

    async def _run_fetch(self, run_id: int) -> None:
        self.store.prepare_run(run_id)
        try:
            access_token = self._access_token()
        except ValueError as exc:
            self.store.fail_remaining(run_id, str(exc))
            return

        interval_seconds = 1 / self.settings.dhan_historical_rps
        next_request_at = 0.0
        items = self.store.queued_items(run_id)
        for item in items:
            attempts = 0
            while attempts <= self.settings.dhan_historical_max_retries:
                attempts += 1
                self.store.mark_item_fetching(item["id"], attempts)
                wait_for = next_request_at - asyncio.get_running_loop().time()
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
                next_request_at = asyncio.get_running_loop().time() + interval_seconds

                request_from_text = ""
                request_to_text = ""
                try:
                    run = self.store.status(run_id)
                    if not run:
                        raise ValueError("Historical fetch run no longer exists.")
                    request_from_text = item.get("request_from_date") or run["from_date"]
                    request_to_text = item.get("request_to_date") or run["to_date_exclusive"]
                    payload = await self.dhan_client.historical_daily(
                        access_token=access_token,
                        security_id=item["security_id"],
                        exchange_segment=self.settings.dhan_historical_exchange_segment,
                        instrument=self.settings.dhan_historical_instrument,
                        from_date=request_from_text,
                        to_date=request_to_text,
                    )
                    candles = parse_historical_payload(payload)
                    request_from = date.fromisoformat(request_from_text)
                    request_to = date.fromisoformat(request_to_text)
                    if candles:
                        self.store.upsert_candles(
                            item,
                            candles,
                            self.settings.dhan_historical_exchange_segment,
                            self.settings.dhan_historical_instrument,
                        )
                        self.store.record_fetch_outcome(item, candles, request_from, request_to)
                        self.store.mark_item_done(item["id"], len(candles))
                    else:
                        reason = self.store.record_fetch_outcome(item, candles, request_from, request_to)
                        self.store.mark_item_no_new_data(item["id"], reason)
                    break
                except FatalHistoricalError as exc:
                    message = str(exc)
                    self.store.mark_item_failed(item["id"], message)
                    self.store.fail_remaining(run_id, message)
                    return
                except Exception as exc:
                    if is_no_data_error(exc):
                        request_from = date.fromisoformat(request_from_text)
                        request_to = date.fromisoformat(request_to_text)
                        reason = self.store.record_fetch_outcome(item, [], request_from, request_to)
                        self.store.mark_item_no_new_data(item["id"], reason)
                        break
                    if is_fatal_error(exc):
                        message = readable_error(exc)
                        self.store.mark_item_failed(item["id"], message)
                        self.store.fail_remaining(run_id, message)
                        return
                    retryable = is_retryable_error(exc)
                    if retryable and attempts <= self.settings.dhan_historical_max_retries:
                        await asyncio.sleep(min(30, 2 ** attempts))
                        continue
                    self.store.mark_item_failed(item["id"], readable_error(exc))
                    break

            self.store.finish_run_if_complete(run_id)

        self.store.finish_run_if_complete(run_id)

    def _access_token(self) -> str:
        token = self.token_store.get()
        if token is None:
            raise ValueError("No Dhan token has been stored.")
        token_state = "expired" if token.expiry_time is not None and token.expiry_time <= now_utc() else "active"
        _, allowed, reason = derive_data_api_status(token_state, token.profile.get("dataPlan"))
        if not allowed:
            raise ValueError(reason)
        return TokenCrypto(self.settings.app_secret_key).decrypt(token.encrypted_access_token)


def historical_window(
    settings: Settings,
    lookback_calendar_days: int | None = None,
    as_of: datetime | None = None,
) -> HistoricalWindow:
    now_ist = as_of.astimezone(IST) if as_of else datetime.now(tz=IST)
    end_date = now_ist.date() - timedelta(days=1)
    lookback_days = lookback_calendar_days or settings.historical_lookback_calendar_days
    from_date = end_date - timedelta(days=lookback_days - 1)
    return HistoricalWindow(from_date=from_date, to_date_exclusive=end_date + timedelta(days=1))


def dhan_earliest_supported_date(settings: Settings, as_of: datetime | None = None) -> date:
    now_ist = as_of.astimezone(IST) if as_of else datetime.now(tz=IST)
    return now_ist.date() - timedelta(days=settings.dhan_historical_daily_supported_years * 365)


def clamp_window_to_dhan_floor(settings: Settings, window: HistoricalWindow, as_of: datetime | None = None) -> HistoricalWindow:
    floor = dhan_earliest_supported_date(settings, as_of)
    return HistoricalWindow(from_date=max(window.from_date, floor), to_date_exclusive=window.to_date_exclusive)


def reusable_current_window_run(
    run: dict[str, Any] | None,
    lookback_days: int,
    window: HistoricalWindow,
) -> bool:
    if not run or run.get("status") not in REUSABLE_TERMINAL_FETCH_STATUSES:
        return False
    if int(run.get("failed_count") or 0) > 0:
        return False
    return (
        int(run.get("lookback_calendar_days") or 0) == lookback_days
        and run.get("from_date") == window.from_date.isoformat()
        and run.get("to_date_exclusive") == window.to_date_exclusive.isoformat()
    )


def normalized_ids(values: list[int]) -> list[int]:
    return sorted({int(value) for value in values if int(value) > 0})


def fetch_plan_for_instrument(conn, instrument_id: int, security_id: str, symbol: str, window: HistoricalWindow) -> dict[str, Any]:
    stored = conn.execute(
        """
        SELECT MIN(trading_date) AS first_stored_candle_date,
               MAX(trading_date) AS latest_stored_candle_date
        FROM daily_candles
        WHERE instrument_id = ?
        """,
        (instrument_id,),
    ).fetchone()
    archive = conn.execute(
        """
        SELECT * FROM historical_instrument_archive
        WHERE instrument_id = ? AND source_provider = ? AND interval = ?
        """,
        (instrument_id, ARCHIVE_PROVIDER, ARCHIVE_INTERVAL),
    ).fetchone()
    now_text = now_utc().isoformat()
    first_stored = stored["first_stored_candle_date"]
    latest_stored = stored["latest_stored_candle_date"]
    if archive is None:
        conn.execute(
            """
            INSERT INTO historical_instrument_archive (
                instrument_id, security_id, symbol, source_provider, interval,
                first_stored_candle_date, latest_stored_candle_date, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instrument_id,
                security_id,
                symbol,
                ARCHIVE_PROVIDER,
                ARCHIVE_INTERVAL,
                first_stored,
                latest_stored,
                now_text,
                now_text,
            ),
        )
    else:
        retry_after = archive["next_retry_after"]
        if retry_after and retry_after > now_text:
            return {
                "status": "skipped_retry_later",
                "error": "Waiting until next retry window for Dhan historical data.",
                "request_from_date": None,
                "request_to_date": None,
                "archive_status": "waiting_for_next_session",
                "source_floor_reason": archive["source_floor_reason"],
            }

    latest_expected = window.to_date_exclusive - timedelta(days=1)
    source_floor_reached = bool(archive["source_floor_reached"]) if archive else False
    complete_available_history = bool(archive["complete_available_history"]) if archive else False
    source_floor_reason = archive["source_floor_reason"] if archive else ""

    if latest_stored and first_stored:
        first_stored_date = date.fromisoformat(first_stored)
        if first_stored_date > window.from_date and not source_floor_reached and not complete_available_history:
            return {
                "status": "queued",
                "error": "",
                "request_from_date": window.from_date.isoformat(),
                "request_to_date": (first_stored_date - timedelta(days=1)).isoformat(),
                "archive_status": "older_history_backfill",
                "source_floor_reason": source_floor_reason,
            }

    if latest_stored and date.fromisoformat(latest_stored) >= latest_expected:
        return {
            "status": "skipped_up_to_date",
            "error": "Already up to date.",
            "request_from_date": None,
            "request_to_date": None,
            "archive_status": "up_to_date",
            "source_floor_reason": source_floor_reason,
        }

    if latest_stored:
        request_from = max(window.from_date, date.fromisoformat(latest_stored) + timedelta(days=1))
        archive_status = "incremental_update"
    else:
        request_from = window.from_date
        archive_status = "initial_capture"

    if request_from >= window.to_date_exclusive:
        return {
            "status": "skipped_up_to_date",
            "error": "Already up to date.",
            "request_from_date": None,
            "request_to_date": None,
            "archive_status": "up_to_date",
            "source_floor_reason": source_floor_reason,
        }

    return {
        "status": "queued",
        "error": "",
        "request_from_date": request_from.isoformat(),
        "request_to_date": latest_expected.isoformat(),
        "archive_status": archive_status,
        "source_floor_reason": source_floor_reason,
    }


def archive_row_to_dict(row) -> dict[str, Any]:
    data = dict(row)
    data["source_floor_reached"] = bool(data["source_floor_reached"])
    data["complete_available_history"] = bool(data["complete_available_history"])
    return data


def ensure_columns(conn, table_name: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


def empty_historical_status(
    universe_name: str,
    lookback_days: int,
    window: HistoricalWindow,
    status: str,
    error: str,
    timestamp: str,
) -> dict[str, Any]:
    return {
        "id": 0,
        "universe_name": universe_name,
        "lookback_calendar_days": lookback_days,
        "from_date": window.from_date.isoformat(),
        "to_date_exclusive": window.to_date_exclusive.isoformat(),
        "status": status,
        "total_symbols": 0,
        "mapped_symbols": 0,
        "skipped_symbols": 0,
        "queued_count": 0,
        "fetching_count": 0,
        "done_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "candles_received": 0,
        "stored_candle_count": 0,
        "first_stored_candle_date": None,
        "latest_stored_candle_date": None,
        "source_floor_reached_count": 0,
        "complete_available_history_count": 0,
        "next_retry_after": None,
        "error": error,
        "started_at": timestamp,
        "updated_at": timestamp,
        "completed_at": timestamp,
    }


def parse_historical_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    timestamps = payload.get("timestamp") or []
    opens = payload.get("open") or []
    highs = payload.get("high") or []
    lows = payload.get("low") or []
    closes = payload.get("close") or []
    volumes = payload.get("volume") or []
    open_interests = payload.get("open_interest") or payload.get("openInterest") or []
    lengths = {len(timestamps), len(opens), len(highs), len(lows), len(closes), len(volumes)}
    if len(lengths) != 1:
        raise ValueError("Dhan historical response arrays have mismatched lengths.")
    if open_interests and len(open_interests) != len(timestamps):
        raise ValueError("Dhan historical open interest array length does not match timestamps.")

    candles: list[dict[str, Any]] = []
    for index, raw_timestamp in enumerate(timestamps):
        source_timestamp = int(raw_timestamp)
        timestamp_seconds = source_timestamp / 1000 if source_timestamp > 10_000_000_000 else source_timestamp
        trading_date = datetime.fromtimestamp(timestamp_seconds, tz=IST).date().isoformat()
        candles.append(
            {
                "timestamp": source_timestamp,
                "trading_date": trading_date,
                "open": float(opens[index]),
                "high": float(highs[index]),
                "low": float(lows[index]),
                "close": float(closes[index]),
                "volume": float(volumes[index]),
                "open_interest": float(open_interests[index]) if open_interests else None,
            }
        )
    return candles


def is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))


def is_no_data_error(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code != 400:
        return False
    detail = exc.response.text.lower()
    return "no data present" in detail


def is_fatal_error(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403)


def readable_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (401, 403):
            return "Dhan rejected the stored token while fetching historical data."
        detail = exc.response.text[:500]
        return f"Dhan historical request failed with HTTP {exc.response.status_code}: {detail}"
    return str(exc)


def candle_row_to_dict(row) -> dict[str, Any]:
    return {
        "instrument_id": row["instrument_id"],
        "security_id": row["security_id"],
        "exchange_segment": row["exchange_segment"],
        "instrument": row["instrument"],
        "trading_date": row["trading_date"],
        "source_timestamp": row["source_timestamp"],
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
        "volume": row["volume"],
        "open_interest": row["open_interest"],
        "source": row["source"],
        "fetched_at": row["fetched_at"],
    }
