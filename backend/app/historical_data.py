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


@dataclass(frozen=True)
class HistoricalWindow:
    from_date: date
    to_date_exclusive: date


class FatalHistoricalError(Exception):
    pass


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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_historical_fetch_runs_status ON historical_fetch_runs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_historical_fetch_items_run_status ON historical_fetch_items(run_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_candles_security_date ON daily_candles(security_id, trading_date)")

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
                    status = "queued"
                    instrument_id = instrument["id"]
                    security_id = instrument["security_id"]
                    error = ""
                else:
                    skipped_symbols += 1
                    status = "skipped_unmapped"
                    instrument_id = None
                    security_id = ""
                    error = "No active Dhan NSE equity instrument matched this Nifty 500 ISIN."
                conn.execute(
                    """
                    INSERT INTO historical_fetch_items (
                        run_id, index_constituent_id, instrument_id, company_name, industry,
                        symbol, isin, security_id, status, error, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count,
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
                self._access_token()
                window = historical_window(self.settings)
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

    def latest_status(self) -> dict[str, Any] | None:
        return self.store.status()

    def items(self, run_id: int, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.items(run_id, status, limit)

    def candles_for_symbol(self, symbol: str, limit: int = 80) -> list[dict[str, Any]]:
        return self.store.candles_for_symbol(symbol, limit)

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

                try:
                    run = self.store.status(run_id)
                    if not run:
                        raise ValueError("Historical fetch run no longer exists.")
                    payload = await self.dhan_client.historical_daily(
                        access_token=access_token,
                        security_id=item["security_id"],
                        exchange_segment=self.settings.dhan_historical_exchange_segment,
                        instrument=self.settings.dhan_historical_instrument,
                        from_date=run["from_date"],
                        to_date=run["to_date_exclusive"],
                    )
                    candles = parse_historical_payload(payload)
                    self.store.upsert_candles(
                        item,
                        candles,
                        self.settings.dhan_historical_exchange_segment,
                        self.settings.dhan_historical_instrument,
                    )
                    self.store.mark_item_done(item["id"], len(candles))
                    break
                except FatalHistoricalError as exc:
                    message = str(exc)
                    self.store.mark_item_failed(item["id"], message)
                    self.store.fail_remaining(run_id, message)
                    return
                except Exception as exc:
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
        return TokenCrypto(self.settings.app_secret_key).decrypt(token.encrypted_access_token)


def historical_window(settings: Settings) -> HistoricalWindow:
    now_ist = datetime.now(tz=IST)
    end_date = now_ist.date()
    if now_ist.hour < settings.historical_finalized_after_hour_ist:
        end_date -= timedelta(days=1)
    from_date = end_date - timedelta(days=settings.historical_lookback_calendar_days - 1)
    return HistoricalWindow(from_date=from_date, to_date_exclusive=end_date + timedelta(days=1))


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
