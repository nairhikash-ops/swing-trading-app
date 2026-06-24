from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.crypto import TokenCrypto
from app.dhan_client import DhanClient
from app.matsya.db import connect, run_schema
from app.matsya.market_calendar import expected_latest_candle_date, is_trading_day, previous_trading_day
from app.matsya.settings import MatsyaSettings
from app.matsya.token_service import MatsyaDhanTokenService, MatsyaStoredToken, _token_state
from app.timezone import IST, now_utc


ARCHIVE_PROVIDER = "dhan"
ARCHIVE_INTERVAL = "daily"
REUSABLE_TERMINAL_FETCH_STATUSES = {"completed", "completed_with_errors"}
START_COVERAGE_GRACE_DAYS = 10
END_FRESHNESS_GRACE_DAYS = 3
INACTIVE_DATA_PLAN_VALUES = {
    "",
    "inactive",
    "in-active",
    "deactive",
    "de-active",
    "disabled",
    "disable",
    "expired",
    "pending",
    "na",
    "n/a",
    "none",
    "null",
}


@dataclass(frozen=True)
class HistoricalWindow:
    from_date: date
    to_date_exclusive: date


class FatalHistoricalError(Exception):
    pass


class MatsyaOHLCVStore:
    def __init__(self, settings: MatsyaSettings) -> None:
        self.settings = settings

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        conn = connect(self.settings)
        try:
            run_schema(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def active_run(self, universe_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return _one(
                conn.execute(
                    """
                    SELECT * FROM matsya.ohlcv_fetch_runs
                    WHERE universe_name = %s AND status IN ('queued', 'running')
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (universe_name,),
                )
            )

    def latest_run(self, universe_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return _one(
                conn.execute(
                    """
                    SELECT * FROM matsya.ohlcv_fetch_runs
                    WHERE universe_name = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (universe_name,),
                )
            )

    def coverage_status(self, universe_name: str, lookback_days: int, window: HistoricalWindow) -> dict[str, Any]:
        timestamp = now_utc()
        start_grace_date = window.from_date + timedelta(days=START_COVERAGE_GRACE_DAYS)
        end_grace_date = window.to_date_exclusive - timedelta(days=END_FRESHNESS_GRACE_DAYS)
        with self._connect() as conn:
            total = _one(
                conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_symbols,
                        SUM(CASE WHEN i.id IS NOT NULL THEN 1 ELSE 0 END) AS mapped_symbols,
                        SUM(CASE WHEN i.id IS NULL THEN 1 ELSE 0 END) AS skipped_symbols
                    FROM matsya.market_universe_members m
                    LEFT JOIN matsya.instruments i ON i.provider_code = 'dhan'
                      AND i.active = true
                      AND i.exchange_id = 'NSE'
                      AND i.segment = 'E'
                      AND i.instrument = 'EQUITY'
                      AND i.isin = m.isin
                    WHERE m.universe_name = %s AND m.active = true
                    """,
                    (universe_name,),
                )
            )
            complete_symbols = _one(
                conn.execute(
                    """
                    SELECT COUNT(*) AS complete_symbols
                    FROM (
                        SELECT i.id AS instrument_id
                        FROM matsya.market_universe_members m
                        JOIN matsya.instruments i ON i.provider_code = 'dhan'
                          AND i.active = true
                          AND i.exchange_id = 'NSE'
                          AND i.segment = 'E'
                          AND i.instrument = 'EQUITY'
                          AND i.isin = m.isin
                        JOIN matsya.ohlcv_daily dc ON dc.provider_code = 'dhan'
                          AND dc.security_id = i.security_id
                          AND dc.trading_date >= %s
                          AND dc.trading_date < %s
                        WHERE m.universe_name = %s AND m.active = true
                        GROUP BY i.id
                        HAVING MIN(dc.trading_date) <= %s AND MAX(dc.trading_date) >= %s
                    ) covered
                    """,
                    (window.from_date, window.to_date_exclusive, universe_name, start_grace_date, end_grace_date),
                )
            )
            stored_candles = _one(
                conn.execute(
                    """
                    SELECT COUNT(*) AS stored_candle_count
                    FROM matsya.ohlcv_daily dc
                    WHERE dc.provider_code = 'dhan'
                      AND dc.trading_date >= %s
                      AND dc.trading_date < %s
                      AND dc.security_id IN (
                        SELECT i.security_id
                        FROM matsya.market_universe_members m
                        JOIN matsya.instruments i ON i.provider_code = 'dhan'
                          AND i.active = true
                          AND i.exchange_id = 'NSE'
                          AND i.segment = 'E'
                          AND i.instrument = 'EQUITY'
                          AND i.isin = m.isin
                        WHERE m.universe_name = %s AND m.active = true
                      )
                    """,
                    (window.from_date, window.to_date_exclusive, universe_name),
                )
            )
        mapped_symbols = int((total or {}).get("mapped_symbols") or 0)
        complete_count = int((complete_symbols or {}).get("complete_symbols") or 0)
        complete = mapped_symbols > 0 and complete_count == mapped_symbols
        return {
            "id": 0,
            "universe_name": universe_name,
            "lookback_calendar_days": lookback_days,
            "from_date": window.from_date.isoformat(),
            "to_date_exclusive": window.to_date_exclusive.isoformat(),
            "status": "up_to_date" if complete else "missing_data",
            "total_symbols": int((total or {}).get("total_symbols") or 0),
            "mapped_symbols": mapped_symbols,
            "skipped_symbols": int((total or {}).get("skipped_symbols") or 0),
            "queued_count": 0,
            "fetching_count": 0,
            "done_count": mapped_symbols if complete else complete_count,
            "failed_count": 0,
            "skipped_count": int((total or {}).get("skipped_symbols") or 0),
            "candles_received": 0,
            "stored_candle_count": int((stored_candles or {}).get("stored_candle_count") or 0),
            "error_message": "" if complete else "Some mapped instruments do not have candles in the current window.",
            "started_at": timestamp,
            "updated_at": timestamp,
            "completed_at": timestamp,
        }

    def create_run(
        self,
        universe_name: str,
        lookback_days: int,
        window: HistoricalWindow,
        incremental_overlap_sessions: int = 0,
        trading_holidays: set[date] | None = None,
    ) -> int:
        timestamp = now_utc()
        with self._connect() as conn:
            run = _one(
                conn.execute(
                    """
                    INSERT INTO matsya.ohlcv_fetch_runs (
                        universe_name, lookback_calendar_days, from_date, to_date_exclusive, status
                    )
                    VALUES (%s, %s, %s, %s, 'queued')
                    RETURNING id
                    """,
                    (universe_name, lookback_days, window.from_date.isoformat(), window.to_date_exclusive.isoformat()),
                )
            )
            run_id = int(run["id"])
            members = _all(
                conn.execute(
                    """
                    SELECT id, company_name, industry, symbol, isin
                    FROM matsya.market_universe_members
                    WHERE universe_name = %s AND active = true
                    ORDER BY company_name, id
                    """,
                    (universe_name,),
                )
            )
            mapped_symbols = 0
            skipped_symbols = 0
            for member in members:
                instrument = _one(
                    conn.execute(
                        """
                        SELECT id, security_id
                        FROM matsya.instruments
                        WHERE provider_code = 'dhan'
                          AND active = true
                          AND exchange_id = 'NSE'
                          AND segment = 'E'
                          AND instrument = 'EQUITY'
                          AND isin = %s
                        ORDER BY CASE WHEN series = 'EQ' THEN 0 ELSE 1 END, id
                        LIMIT 1
                        """,
                        (member["isin"],),
                    )
                )
                if instrument:
                    mapped_symbols += 1
                    instrument_id = int(instrument["id"])
                    security_id = str(instrument["security_id"])
                    plan = fetch_plan_for_instrument(
                        conn,
                        instrument_id,
                        security_id,
                        str(member["symbol"]),
                        window,
                        incremental_overlap_sessions=incremental_overlap_sessions,
                        trading_holidays=trading_holidays,
                    )
                    status = plan["status"]
                    error = plan["error"]
                else:
                    skipped_symbols += 1
                    instrument_id = None
                    security_id = ""
                    status = "skipped_unmapped"
                    error = "No active Dhan NSE equity instrument matched this Nifty 500 ISIN."
                    plan = {
                        "request_from_date": None,
                        "request_to_date": None,
                        "archive_status": "",
                        "source_floor_reason": "",
                    }
                conn.execute(
                    """
                    INSERT INTO matsya.ohlcv_fetch_items (
                        run_id, universe_member_id, instrument_id, company_name, industry,
                        symbol, isin, security_id, status, error_message, request_from_date,
                        request_to_date, archive_status, source_floor_reason, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        member["id"],
                        instrument_id,
                        member["company_name"],
                        member["industry"],
                        member["symbol"],
                        member["isin"],
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
                UPDATE matsya.ohlcv_fetch_runs
                SET total_symbols = %s, mapped_symbols = %s, skipped_symbols = %s, updated_at = %s
                WHERE id = %s
                """,
                (len(members), mapped_symbols, skipped_symbols, timestamp, run_id),
            )
            return run_id

    def prepare_run(self, run_id: int) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_items
                SET status = 'queued', updated_at = %s
                WHERE run_id = %s AND status = 'fetching'
                """,
                (timestamp, run_id),
            )
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_runs
                SET status = 'running', error_message = '', updated_at = %s
                WHERE id = %s
                """,
                (timestamp, run_id),
            )

    def queued_items(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return _all(
                conn.execute(
                    """
                    SELECT * FROM matsya.ohlcv_fetch_items
                    WHERE run_id = %s AND status = 'queued'
                    ORDER BY id
                    """,
                    (run_id,),
                )
            )

    def mark_item_fetching(self, item_id: int, attempts: int) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_items
                SET status = 'fetching', attempts = %s, started_at = COALESCE(started_at, %s),
                    updated_at = %s, error_message = ''
                WHERE id = %s
                """,
                (attempts, timestamp, timestamp, item_id),
            )
            self._touch_run(conn, item_id, timestamp)

    def mark_item_done(self, item_id: int, candles_received: int) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_items
                SET status = 'done', candles_received = %s, error_message = '',
                    finished_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (candles_received, timestamp, timestamp, item_id),
            )
            self._touch_run(conn, item_id, timestamp)

    def mark_item_no_new_data(self, item_id: int, reason: str) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_items
                SET status = 'skipped_no_new_data', candles_received = 0, error_message = %s,
                    archive_status = CASE
                        WHEN archive_status = 'older_history_backfill' THEN archive_status
                        ELSE 'waiting_for_next_session'
                    END,
                    source_floor_reason = %s,
                    finished_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (reason[:1000], reason, timestamp, timestamp, item_id),
            )
            self._touch_run(conn, item_id, timestamp)

    def mark_item_waiting_for_latest_candle(self, item_id: int, candles_received: int, reason: str) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_items
                SET status = 'skipped_no_new_data', candles_received = %s, error_message = %s,
                    archive_status = 'waiting_for_next_session',
                    source_floor_reason = %s,
                    finished_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (candles_received, reason[:1000], reason, timestamp, timestamp, item_id),
            )
            self._touch_run(conn, item_id, timestamp)

    def mark_item_failed(self, item_id: int, error: str) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_items
                SET status = 'failed', error_message = %s, finished_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (error[:1000], timestamp, timestamp, item_id),
            )
            self._touch_run(conn, item_id, timestamp)

    def fail_remaining(self, run_id: int, error: str) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_items
                SET status = 'failed', error_message = %s, finished_at = %s, updated_at = %s
                WHERE run_id = %s AND status IN ('queued', 'fetching')
                """,
                (error[:1000], timestamp, timestamp, run_id),
            )
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_runs
                SET status = 'failed', error_message = %s, updated_at = %s, completed_at = %s
                WHERE id = %s
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
        timestamp = now_utc()
        with self._connect() as conn:
            for candle in candles:
                conn.execute(
                    """
                    INSERT INTO matsya.ohlcv_daily (
                        provider_code, security_id, exchange_segment, instrument, trading_date,
                        source_timestamp, open_price, high_price, low_price, close_price,
                        volume, open_interest, raw_candle, last_import_run_id
                    )
                    VALUES (
                        'dhan', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NULL
                    )
                    ON CONFLICT (provider_code, security_id, trading_date) DO UPDATE
                    SET exchange_segment = EXCLUDED.exchange_segment,
                        instrument = EXCLUDED.instrument,
                        source_timestamp = EXCLUDED.source_timestamp,
                        open_price = EXCLUDED.open_price,
                        high_price = EXCLUDED.high_price,
                        low_price = EXCLUDED.low_price,
                        close_price = EXCLUDED.close_price,
                        volume = EXCLUDED.volume,
                        open_interest = EXCLUDED.open_interest,
                        raw_candle = EXCLUDED.raw_candle,
                        updated_at = now(),
                        last_import_run_id = EXCLUDED.last_import_run_id
                    """,
                    (
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
                    ),
                )
            conn.execute(
                """
                UPDATE matsya.ohlcv_fetch_runs
                SET updated_at = %s
                WHERE id = %s
                """,
                (timestamp, item["run_id"]),
            )

    def record_fetch_outcome(
        self,
        item: dict[str, Any],
        candles: list[dict[str, Any]],
        request_from: date,
        request_to: date,
        retry_hours: int = 3,
    ) -> str:
        timestamp = now_utc()
        retry_after = now_utc() + latest_candle_retry_delay(retry_hours)
        instrument_id = int(item["instrument_id"])
        security_id = str(item["security_id"])
        symbol = str(item["symbol"])
        returned_first = min((candle["trading_date"] for candle in candles), default=None)
        with self._connect() as conn:
            stored = _one(
                conn.execute(
                    """
                    SELECT MIN(trading_date) AS first_stored_candle_date,
                           MAX(trading_date) AS latest_stored_candle_date
                    FROM matsya.ohlcv_daily
                    WHERE provider_code = 'dhan' AND security_id = %s
                    """,
                    (security_id,),
                )
            )
            existing = _one(
                conn.execute(
                    """
                    SELECT * FROM matsya.ohlcv_instrument_archive
                    WHERE instrument_id = %s AND source_provider = %s AND interval = %s
                    """,
                    (instrument_id, ARCHIVE_PROVIDER, ARCHIVE_INTERVAL),
                )
            )
            first_stored = _date_text((stored or {}).get("first_stored_candle_date"))
            latest_stored = _date_text((stored or {}).get("latest_stored_candle_date"))
            source_floor_reached = bool(existing.get("source_floor_reached")) if existing else False
            complete_available_history = bool(existing.get("complete_available_history")) if existing else False
            source_floor_date = _date_text(existing.get("source_floor_date")) if existing else None
            source_floor_reason = str(existing.get("source_floor_reason") or "unknown") if existing else "unknown"
            last_successful_fetch_at = existing.get("last_successful_fetch_at") if existing else None
            last_no_new_data_at = existing.get("last_no_new_data_at") if existing else None
            next_retry_after = existing.get("next_retry_after") if existing else None

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
                if returned_candles_are_trailing_stale(candles, request_to):
                    last_no_new_data_at = timestamp
                    next_retry_after = retry_after
                    source_floor_reason = "waiting_for_dhan_latest_candle"
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
                INSERT INTO matsya.ohlcv_instrument_archive (
                    instrument_id, security_id, symbol, source_provider, interval,
                    first_stored_candle_date, latest_stored_candle_date,
                    source_floor_reached, source_floor_date, source_floor_reason,
                    complete_available_history, last_successful_fetch_at,
                    last_no_new_data_at, next_retry_after, last_error
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '')
                ON CONFLICT (instrument_id, source_provider, interval) DO UPDATE
                SET security_id = EXCLUDED.security_id,
                    symbol = EXCLUDED.symbol,
                    first_stored_candle_date = EXCLUDED.first_stored_candle_date,
                    latest_stored_candle_date = EXCLUDED.latest_stored_candle_date,
                    source_floor_reached = EXCLUDED.source_floor_reached,
                    source_floor_date = EXCLUDED.source_floor_date,
                    source_floor_reason = EXCLUDED.source_floor_reason,
                    complete_available_history = EXCLUDED.complete_available_history,
                    last_successful_fetch_at = EXCLUDED.last_successful_fetch_at,
                    last_no_new_data_at = EXCLUDED.last_no_new_data_at,
                    next_retry_after = EXCLUDED.next_retry_after,
                    last_error = EXCLUDED.last_error,
                    updated_at = now()
                """,
                (
                    instrument_id,
                    security_id,
                    symbol,
                    ARCHIVE_PROVIDER,
                    ARCHIVE_INTERVAL,
                    first_stored,
                    latest_stored,
                    source_floor_reached,
                    source_floor_date,
                    source_floor_reason,
                    complete_available_history,
                    last_successful_fetch_at,
                    last_no_new_data_at,
                    next_retry_after,
                ),
            )
        return source_floor_reason

    def finish_run_if_complete(self, run_id: int) -> None:
        summary = self.status(run_id=run_id)
        if not summary or summary["queued_count"] > 0 or summary["fetching_count"] > 0:
            return
        timestamp = now_utc()
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
                UPDATE matsya.ohlcv_fetch_runs
                SET status = %s, error_message = %s, updated_at = %s, completed_at = %s
                WHERE id = %s
                """,
                (status, error, timestamp, timestamp, run_id),
            )

    def status(self, run_id: int | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            if run_id is None:
                run = _one(
                    conn.execute(
                        """
                        SELECT * FROM matsya.ohlcv_fetch_runs
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    )
                )
            else:
                run = _one(conn.execute("SELECT * FROM matsya.ohlcv_fetch_runs WHERE id = %s", (run_id,)))
            if not run:
                return None
            counts = _one(
                conn.execute(
                    """
                    SELECT
                        SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued_count,
                        SUM(CASE WHEN status = 'fetching' THEN 1 ELSE 0 END) AS fetching_count,
                        SUM(CASE WHEN status IN (
                            'done', 'skipped_up_to_date', 'skipped_no_new_data', 'skipped_retry_later'
                        ) THEN 1 ELSE 0 END) AS done_count,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                        SUM(CASE WHEN status = 'skipped_unmapped' THEN 1 ELSE 0 END) AS skipped_count,
                        SUM(candles_received) AS candles_received
                    FROM matsya.ohlcv_fetch_items
                    WHERE run_id = %s
                    """,
                    (run["id"],),
                )
            )
            candle_count = _one(
                conn.execute(
                    """
                    SELECT COUNT(*) AS candle_count
                    FROM matsya.ohlcv_daily
                    WHERE provider_code = 'dhan'
                      AND trading_date >= %s
                      AND trading_date < %s
                      AND security_id IN (
                        SELECT security_id FROM matsya.ohlcv_fetch_items
                        WHERE run_id = %s AND security_id <> ''
                      )
                    """,
                    (run["from_date"], run["to_date_exclusive"], run["id"]),
                )
            )
            archive = _one(
                conn.execute(
                    """
                    SELECT
                        MIN(first_stored_candle_date) AS first_stored_candle_date,
                        MAX(latest_stored_candle_date) AS latest_stored_candle_date,
                        SUM(CASE WHEN source_floor_reached THEN 1 ELSE 0 END) AS source_floor_reached_count,
                        SUM(CASE WHEN complete_available_history THEN 1 ELSE 0 END) AS complete_available_history_count,
                        MIN(next_retry_after) AS next_retry_after
                    FROM matsya.ohlcv_instrument_archive
                    WHERE source_provider = %s AND interval = %s
                      AND instrument_id IN (
                        SELECT instrument_id FROM matsya.ohlcv_fetch_items
                        WHERE run_id = %s AND instrument_id IS NOT NULL
                      )
                    """,
                    (ARCHIVE_PROVIDER, ARCHIVE_INTERVAL, run["id"]),
                )
            )
        data = dict(run)
        data.update(
            {
                "queued_count": int((counts or {}).get("queued_count") or 0),
                "fetching_count": int((counts or {}).get("fetching_count") or 0),
                "done_count": int((counts or {}).get("done_count") or 0),
                "failed_count": int((counts or {}).get("failed_count") or 0),
                "skipped_count": int((counts or {}).get("skipped_count") or 0),
                "candles_received": int((counts or {}).get("candles_received") or 0),
                "stored_candle_count": int((candle_count or {}).get("candle_count") or 0),
                "first_stored_candle_date": _date_text((archive or {}).get("first_stored_candle_date")),
                "latest_stored_candle_date": _date_text((archive or {}).get("latest_stored_candle_date")),
                "source_floor_reached_count": int((archive or {}).get("source_floor_reached_count") or 0),
                "complete_available_history_count": int((archive or {}).get("complete_available_history_count") or 0),
                "next_retry_after": (archive or {}).get("next_retry_after"),
            }
        )
        return data

    def items(self, run_id: int, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = [run_id]
        where = "run_id = %s"
        if status:
            where += " AND status = %s"
            params.append(status)
        params.append(min(max(limit, 1), 500))
        with self._connect() as conn:
            return _all(
                conn.execute(
                    f"""
                    SELECT * FROM matsya.ohlcv_fetch_items
                    WHERE {where}
                    ORDER BY id
                    LIMIT %s
                    """,
                    tuple(params),
                )
            )

    def trading_holidays(self, market_code: str) -> set[date]:
        with self._connect() as conn:
            rows = _all(
                conn.execute(
                    """
                    SELECT holiday_date
                    FROM matsya.trading_holidays
                    WHERE market_code = %s
                    """,
                    (market_code,),
                )
            )
        return {_date_value(row["holiday_date"]) for row in rows}

    def latest_stored_candle_date_for_symbol(
        self,
        *,
        symbol: str | None = None,
        security_id: str | None = None,
        instrument: str | None = None,
    ) -> date | None:
        if not symbol and not security_id:
            raise ValueError("Either symbol or security_id is required.")
        with self._connect() as conn:
            if security_id:
                query = """
                    SELECT MAX(trading_date) AS latest_stored_candle_date
                    FROM matsya.ohlcv_daily
                    WHERE provider_code = 'dhan'
                      AND security_id = %s
                """
                params: list[Any] = [security_id]
                if instrument:
                    query += " AND instrument = %s"
                    params.append(instrument)
                row = _one(
                    conn.execute(query, tuple(params))
                )
            else:
                query = """
                    SELECT MAX(dc.trading_date) AS latest_stored_candle_date
                    FROM matsya.ohlcv_daily dc
                    JOIN matsya.instruments i ON i.provider_code = 'dhan'
                      AND i.security_id = dc.security_id
                      AND i.active = true
                    WHERE dc.provider_code = 'dhan'
                      AND (UPPER(i.symbol_name) = UPPER(%s) OR UPPER(i.underlying_symbol) = UPPER(%s))
                """
                params = [symbol, symbol]
                if instrument:
                    query += " AND dc.instrument = %s"
                    params.append(instrument)
                row = _one(
                    conn.execute(query, tuple(params))
                )
        value = (row or {}).get("latest_stored_candle_date")
        return _date_value(value) if value else None

    def _touch_run(self, conn: Any, item_id: int, timestamp: datetime) -> None:
        conn.execute(
            """
            UPDATE matsya.ohlcv_fetch_runs
            SET updated_at = %s
            WHERE id = (SELECT run_id FROM matsya.ohlcv_fetch_items WHERE id = %s)
            """,
            (timestamp, item_id),
        )


class MatsyaOHLCVService:
    def __init__(
        self,
        settings: MatsyaSettings,
        store: MatsyaOHLCVStore | None = None,
        dhan_client: DhanClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or MatsyaOHLCVStore(settings)
        self.dhan_client = dhan_client or DhanClient(settings.dhan_api_base_url)
        self.token_service = MatsyaDhanTokenService(settings, self.dhan_client)

    async def start_or_resume_ohlcv_fetch(self) -> dict[str, Any]:
        active_run = self.store.active_run(self.settings.ohlcv_universe_name)
        if active_run is None:
            self._access_token()
            window = clamp_window_to_dhan_floor(self.settings, historical_window(self.settings))
            latest_run = self.store.latest_run(self.settings.ohlcv_universe_name)
            latest_status = self.store.status(int(latest_run["id"])) if latest_run else None
            if reusable_current_window_run(latest_status, self.settings.historical_lookback_calendar_days, window):
                return latest_status or {}
            coverage = self.store.coverage_status(
                self.settings.ohlcv_universe_name,
                self.settings.historical_lookback_calendar_days,
                window,
            )
            if coverage["status"] == "up_to_date":
                return coverage
            run_id = self.store.create_run(
                self.settings.ohlcv_universe_name,
                self.settings.historical_lookback_calendar_days,
                window,
                self.settings.ohlcv_incremental_overlap_sessions,
                self.store.trading_holidays(self.settings.market_code),
            )
        else:
            run_id = int(active_run["id"])
        return self.store.status(run_id) or {}

    async def start_or_resume_nifty_500_fetch(self) -> dict[str, Any]:
        return await self.start_or_resume_ohlcv_fetch()

    async def process_queued_items(self, run_id: int) -> dict[str, Any]:
        await self._run_fetch(run_id)
        return self.store.status(run_id) or {}

    async def run_once(self) -> dict[str, Any]:
        status = await self.start_or_resume_ohlcv_fetch()
        run_id = int(status.get("id") or 0)
        if run_id > 0:
            return await self.process_queued_items(run_id)
        return status

    def latest_status(self) -> dict[str, Any] | None:
        return self.store.status()

    def items(self, run_id: int, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.items(run_id, status, limit)

    def latest_stored_candle_date_for_symbol(
        self,
        *,
        symbol: str | None = None,
        security_id: str | None = None,
        instrument: str | None = None,
    ) -> date | None:
        return self.store.latest_stored_candle_date_for_symbol(
            symbol=symbol,
            security_id=security_id,
            instrument=instrument,
        )

    def prediction_freshness_status(
        self,
        *,
        symbol: str | None = None,
        security_id: str | None = None,
        instrument: str | None = None,
        now_ist: datetime | None = None,
    ) -> dict[str, Any]:
        resolved_now = now_ist.astimezone(IST) if now_ist else datetime.now(tz=IST)
        holidays = self.store.trading_holidays(self.settings.market_code)
        expected_date = expected_latest_candle_date(
            resolved_now,
            self.settings.historical_finalized_after_hour_ist,
            holidays,
        )
        latest_stored = self.latest_stored_candle_date_for_symbol(
            symbol=symbol,
            security_id=security_id,
            instrument=instrument,
        )
        today_is_trading = is_trading_day(resolved_now.date(), holidays)
        previous_session = previous_trading_day(resolved_now.date(), holidays)

        if latest_stored is None:
            state = "NO_OHLCV_DATA"
            reason = "No stored OHLCV candle is available for this instrument."
            fresh = False
        elif latest_stored >= expected_date:
            fresh = True
            if not today_is_trading and expected_date == previous_session:
                state = "NON_TRADING_DAY_USING_PREVIOUS_TRADING_DAY"
                reason = "Current IST date is not a trading day; using the previous completed trading day."
            else:
                state = "FRESH"
                reason = "Stored OHLCV data includes the expected latest completed trading day."
        elif (
            today_is_trading
            and resolved_now.hour >= self.settings.historical_finalized_after_hour_ist
            and expected_date == resolved_now.date()
            and latest_stored >= previous_session
        ):
            fresh = False
            state = "WAITING_FOR_DHAN_DATA"
            reason = "The latest completed trading day is expected, but the stored Dhan candle has not arrived yet."
        else:
            fresh = False
            state = "STALE_OHLCV_DATA"
            reason = "Stored OHLCV data is older than the expected latest completed trading day."

        return {
            "fresh": fresh,
            "latest_stored_candle_date": latest_stored.isoformat() if latest_stored else None,
            "expected_latest_candle_date": expected_date.isoformat(),
            "state": state,
            "reason": reason,
        }

    def is_prediction_data_fresh(
        self,
        *,
        symbol: str | None = None,
        security_id: str | None = None,
        instrument: str | None = None,
        now_ist: datetime | None = None,
    ) -> bool:
        return bool(
            self.prediction_freshness_status(
                symbol=symbol,
                security_id=security_id,
                instrument=instrument,
                now_ist=now_ist,
            )["fresh"]
        )

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
                self.store.mark_item_fetching(int(item["id"]), attempts)
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
                    request_from_text = str(item.get("request_from_date") or run["from_date"])
                    item_request_to_text = item.get("request_to_date")
                    request_to = inclusive_request_to_date(
                        str(item_request_to_text) if item_request_to_text else None,
                        str(run["to_date_exclusive"]),
                    )
                    request_to_text = request_to.isoformat()
                    dhan_to_date_text = dhan_exclusive_to_date(request_to).isoformat()
                    payload = await self.dhan_client.historical_daily(
                        access_token=access_token,
                        security_id=str(item["security_id"]),
                        exchange_segment=self.settings.dhan_historical_exchange_segment,
                        instrument=self.settings.dhan_historical_instrument,
                        from_date=request_from_text,
                        to_date=dhan_to_date_text,
                    )
                    candles = parse_historical_payload(payload)
                    request_from = date.fromisoformat(request_from_text)
                    if candles:
                        self.store.upsert_candles(
                            item,
                            candles,
                            self.settings.dhan_historical_exchange_segment,
                            self.settings.dhan_historical_instrument,
                        )
                        reason = self.store.record_fetch_outcome(
                            item,
                            candles,
                            request_from,
                            request_to,
                            self.settings.dhan_latest_candle_retry_hours,
                        )
                        if returned_candles_are_trailing_stale(candles, request_to):
                            self.store.mark_item_waiting_for_latest_candle(int(item["id"]), len(candles), reason)
                        else:
                            self.store.mark_item_done(int(item["id"]), len(candles))
                    else:
                        reason = self.store.record_fetch_outcome(
                            item,
                            candles,
                            request_from,
                            request_to,
                            self.settings.dhan_latest_candle_retry_hours,
                        )
                        self.store.mark_item_no_new_data(int(item["id"]), reason)
                    break
                except FatalHistoricalError as exc:
                    message = str(exc)
                    self.store.mark_item_failed(int(item["id"]), message)
                    self.store.fail_remaining(run_id, message)
                    return
                except Exception as exc:
                    if is_no_data_error(exc):
                        request_from = date.fromisoformat(request_from_text)
                        request_to = date.fromisoformat(request_to_text)
                        reason = self.store.record_fetch_outcome(
                            item,
                            [],
                            request_from,
                            request_to,
                            self.settings.dhan_latest_candle_retry_hours,
                        )
                        self.store.mark_item_no_new_data(int(item["id"]), reason)
                        break
                    if is_fatal_error(exc):
                        message = readable_error(exc)
                        self.store.mark_item_failed(int(item["id"]), message)
                        self.store.fail_remaining(run_id, message)
                        return
                    retryable = is_retryable_error(exc)
                    if retryable and attempts <= self.settings.dhan_historical_max_retries:
                        await asyncio.sleep(min(30, 2**attempts))
                        continue
                    self.store.mark_item_failed(int(item["id"]), readable_error(exc))
                    break
            self.store.finish_run_if_complete(run_id)
        self.store.finish_run_if_complete(run_id)

    def _access_token(self) -> str:
        with connect(self.settings) as conn:
            run_schema(conn)
            token = self.token_service._get(conn)
        if token is None:
            raise ValueError("No Dhan token has been stored.")
        state, allowed, reason = _historical_fetch_gate(token, self.settings)
        if not allowed:
            raise ValueError(reason or f"Dhan token is not usable for historical fetching: {state}.")
        return TokenCrypto(self.settings.app_secret_key).decrypt(token.encrypted_access_token)


def historical_window(
    settings: MatsyaSettings,
    lookback_calendar_days: int | None = None,
    as_of: datetime | None = None,
) -> HistoricalWindow:
    now_ist = as_of.astimezone(IST) if as_of else datetime.now(tz=IST)
    end_date = now_ist.date() - timedelta(days=1)
    lookback_days = lookback_calendar_days or settings.historical_lookback_calendar_days
    from_date = end_date - timedelta(days=lookback_days - 1)
    return HistoricalWindow(from_date=from_date, to_date_exclusive=end_date + timedelta(days=1))


def dhan_earliest_supported_date(settings: MatsyaSettings, as_of: datetime | None = None) -> date:
    now_ist = as_of.astimezone(IST) if as_of else datetime.now(tz=IST)
    return now_ist.date() - timedelta(days=settings.dhan_historical_daily_supported_years * 365)


def clamp_window_to_dhan_floor(
    settings: MatsyaSettings,
    window: HistoricalWindow,
    as_of: datetime | None = None,
) -> HistoricalWindow:
    floor = dhan_earliest_supported_date(settings, as_of)
    return HistoricalWindow(from_date=max(window.from_date, floor), to_date_exclusive=window.to_date_exclusive)


def incremental_request_from_date(
    latest_stored: date,
    window: HistoricalWindow,
    overlap_sessions: int,
    holidays: set[date] | None = None,
) -> date:
    request_from = latest_stored
    for _ in range(max(0, overlap_sessions)):
        request_from = previous_trading_day(request_from, holidays)
    return max(window.from_date, request_from)


def latest_candle_retry_delay(retry_hours: int) -> timedelta:
    return timedelta(hours=max(1, retry_hours))


def reusable_current_window_run(
    run: dict[str, Any] | None,
    lookback_days: int,
    window: HistoricalWindow,
) -> bool:
    if not run or run.get("status") not in REUSABLE_TERMINAL_FETCH_STATUSES:
        return False
    if int(run.get("failed_count") or 0) > 0:
        return False
    if run.get("next_retry_after"):
        return False
    latest_expected = window.to_date_exclusive - timedelta(days=1)
    latest_stored = run.get("latest_stored_candle_date")
    if not latest_stored or _date_value(latest_stored) < latest_expected:
        return False
    return (
        int(run.get("lookback_calendar_days") or 0) == lookback_days
        and run.get("from_date") == window.from_date.isoformat()
        and run.get("to_date_exclusive") == window.to_date_exclusive.isoformat()
    )


def fetch_plan_for_instrument(
    conn: Any,
    instrument_id: int,
    security_id: str,
    symbol: str,
    window: HistoricalWindow,
    *,
    incremental_overlap_sessions: int = 0,
    trading_holidays: set[date] | None = None,
) -> dict[str, Any]:
    stored = _one(
        conn.execute(
            """
            SELECT MIN(trading_date) AS first_stored_candle_date,
                   MAX(trading_date) AS latest_stored_candle_date
            FROM matsya.ohlcv_daily
            WHERE provider_code = 'dhan' AND security_id = %s
            """,
            (security_id,),
        )
    )
    archive = _one(
        conn.execute(
            """
            SELECT * FROM matsya.ohlcv_instrument_archive
            WHERE instrument_id = %s AND source_provider = %s AND interval = %s
            """,
            (instrument_id, ARCHIVE_PROVIDER, ARCHIVE_INTERVAL),
        )
    )
    now_time = now_utc()
    first_stored = _date_text((stored or {}).get("first_stored_candle_date"))
    latest_stored = _date_text((stored or {}).get("latest_stored_candle_date"))
    if archive is None:
        conn.execute(
            """
            INSERT INTO matsya.ohlcv_instrument_archive (
                instrument_id, security_id, symbol, source_provider, interval,
                first_stored_candle_date, latest_stored_candle_date
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (instrument_id, source_provider, interval) DO NOTHING
            """,
            (instrument_id, security_id, symbol, ARCHIVE_PROVIDER, ARCHIVE_INTERVAL, first_stored, latest_stored),
        )
    else:
        retry_after = archive.get("next_retry_after")
        if retry_after and retry_after > now_time:
            return {
                "status": "skipped_retry_later",
                "error": "Waiting until next retry window for Dhan historical data.",
                "request_from_date": None,
                "request_to_date": None,
                "archive_status": "waiting_for_next_session",
                "source_floor_reason": archive.get("source_floor_reason") or "",
            }

    latest_expected = window.to_date_exclusive - timedelta(days=1)
    source_floor_reached = bool(archive.get("source_floor_reached")) if archive else False
    complete_available_history = bool(archive.get("complete_available_history")) if archive else False
    source_floor_reason = str(archive.get("source_floor_reason") or "") if archive else ""

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
        request_from = incremental_request_from_date(
            date.fromisoformat(latest_stored),
            window,
            incremental_overlap_sessions,
            trading_holidays,
        )
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


def latest_returned_candle_date(candles: list[dict[str, Any]]) -> date | None:
    dates = [_date_value(candle["trading_date"]) for candle in candles if candle.get("trading_date")]
    return max(dates, default=None)


def returned_candles_are_trailing_stale(candles: list[dict[str, Any]], request_to: date) -> bool:
    returned_latest = latest_returned_candle_date(candles)
    return returned_latest is not None and returned_latest < request_to


def dhan_exclusive_to_date(request_to: date) -> date:
    return request_to + timedelta(days=1)


def inclusive_request_to_date(item_request_to: str | None, run_to_date_exclusive: str) -> date:
    if item_request_to:
        return date.fromisoformat(item_request_to)
    return date.fromisoformat(run_to_date_exclusive) - timedelta(days=1)


def is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))


def is_no_data_error(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code != 400:
        return False
    return "no data present" in exc.response.text.lower()


def is_fatal_error(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403)


def readable_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (401, 403):
            return "Dhan rejected the stored token while fetching historical data."
        detail = exc.response.text[:500]
        return f"Dhan historical request failed with HTTP {exc.response.status_code}: {detail}"
    return str(exc)


def _historical_fetch_gate(token: MatsyaStoredToken, settings: MatsyaSettings) -> tuple[str, bool, str]:
    if not settings.app_secret_key:
        return "config_error", False, "Matsya token encryption key is not configured."
    state = _token_state(token, settings.renew_before_minutes)
    if state not in ("active", "expiring_soon"):
        return state, False, "Dhan token is not active."
    normalized = str((token.profile or {}).get("dataPlan") or "").strip().lower()
    if normalized in INACTIVE_DATA_PLAN_VALUES or "deactive" in normalized or "inactive" in normalized:
        return state, False, "Dhan data API is inactive or pending renewal."
    return state, True, ""


def _one(cursor: Any) -> dict[str, Any] | None:
    rows = _all(cursor)
    return rows[0] if rows else None


def _all(cursor: Any) -> list[dict[str, Any]]:
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row, strict=False)) for row in cursor.fetchall()]


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _date_value(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
