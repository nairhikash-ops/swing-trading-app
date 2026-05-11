from datetime import date
from typing import Any

from app.config import Settings
from app.historical_data import HistoricalWindow, historical_window
from app.index_universe import NIFTY_500_INDEX_NAME
from app.store import TokenStore
from app.timezone import now_utc


class MoveEventStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS move_event_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    universe_name TEXT NOT NULL,
                    threshold_percent REAL NOT NULL,
                    pullback_percent REAL NOT NULL,
                    from_date TEXT NOT NULL,
                    to_date_exclusive TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_symbols INTEGER NOT NULL DEFAULT 0,
                    scanned_symbols INTEGER NOT NULL DEFAULT 0,
                    candidate_symbols INTEGER NOT NULL DEFAULT 0,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS move_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    index_constituent_id INTEGER NOT NULL,
                    instrument_id INTEGER NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    event_number INTEGER NOT NULL,
                    bucket TEXT NOT NULL,
                    low_date TEXT NOT NULL,
                    low_price REAL NOT NULL,
                    high_date TEXT NOT NULL,
                    high_price REAL NOT NULL,
                    move_percent REAL NOT NULL,
                    duration_calendar_days INTEGER NOT NULL,
                    duration_trading_sessions INTEGER NOT NULL,
                    threshold_percent REAL NOT NULL,
                    pullback_percent REAL NOT NULL,
                    split_pullback_date TEXT,
                    split_pullback_close REAL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, instrument_id, event_number)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_move_event_runs_universe ON move_event_runs(universe_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_move_events_run_bucket ON move_events(run_id, bucket)")

    def create_run(
        self,
        universe_name: str,
        threshold_percent: float,
        pullback_percent: float,
        window: HistoricalWindow,
    ) -> int:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO move_event_runs (
                    universe_name, threshold_percent, pullback_percent, from_date,
                    to_date_exclusive, status, started_at
                )
                VALUES (?, ?, ?, ?, ?, 'running', ?)
                """,
                (
                    universe_name,
                    threshold_percent,
                    pullback_percent,
                    window.from_date.isoformat(),
                    window.to_date_exclusive.isoformat(),
                    timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def candle_groups(self, universe_name: str, window: HistoricalWindow) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    ic.id AS index_constituent_id,
                    ic.company_name,
                    ic.industry,
                    ic.symbol,
                    ic.isin,
                    i.id AS instrument_id,
                    i.security_id,
                    dc.trading_date,
                    dc.low,
                    dc.high,
                    dc.close
                FROM index_constituents ic
                JOIN instruments i ON i.active = 1
                  AND i.exchange_id = 'NSE'
                  AND i.segment = 'E'
                  AND i.instrument = 'EQUITY'
                  AND i.isin = ic.isin
                LEFT JOIN daily_candles dc ON dc.instrument_id = i.id
                  AND dc.trading_date >= ?
                  AND dc.trading_date < ?
                WHERE ic.index_name = ? AND ic.active = 1
                ORDER BY ic.symbol, dc.trading_date
                """,
                (window.from_date.isoformat(), window.to_date_exclusive.isoformat(), universe_name),
            ).fetchall()

        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            instrument_id = int(row["instrument_id"])
            item = grouped.setdefault(
                instrument_id,
                {
                    "index_constituent_id": row["index_constituent_id"],
                    "instrument_id": instrument_id,
                    "company_name": row["company_name"],
                    "industry": row["industry"],
                    "symbol": row["symbol"],
                    "isin": row["isin"],
                    "security_id": row["security_id"],
                    "candles": [],
                },
            )
            if row["trading_date"]:
                item["candles"].append(
                    {
                        "trading_date": row["trading_date"],
                        "low": float(row["low"]),
                        "high": float(row["high"]),
                        "close": float(row["close"]),
                    }
                )
        return list(grouped.values())

    def insert_events(
        self,
        run_id: int,
        symbol_group: dict[str, Any],
        events: list[dict[str, Any]],
        threshold_percent: float,
        pullback_percent: float,
    ) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            for event_number, event in enumerate(events, start=1):
                conn.execute(
                    """
                    INSERT INTO move_events (
                        run_id, index_constituent_id, instrument_id, company_name, industry,
                        symbol, isin, security_id, event_number, bucket, low_date, low_price,
                        high_date, high_price, move_percent, duration_calendar_days,
                        duration_trading_sessions, threshold_percent, pullback_percent,
                        split_pullback_date, split_pullback_close, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        symbol_group["index_constituent_id"],
                        symbol_group["instrument_id"],
                        symbol_group["company_name"],
                        symbol_group["industry"],
                        symbol_group["symbol"],
                        symbol_group["isin"],
                        symbol_group["security_id"],
                        event_number,
                        move_bucket(event["move_percent"]),
                        event["low_date"],
                        event["low_price"],
                        event["high_date"],
                        event["high_price"],
                        event["move_percent"],
                        event["duration_calendar_days"],
                        event["duration_trading_sessions"],
                        threshold_percent,
                        pullback_percent,
                        event.get("split_pullback_date"),
                        event.get("split_pullback_close"),
                        timestamp,
                    ),
                )

    def finish_run(
        self,
        run_id: int,
        total_symbols: int,
        scanned_symbols: int,
        candidate_symbols: int,
        event_count: int,
        error: str = "",
    ) -> None:
        timestamp = now_utc().isoformat()
        status = "completed" if not error else "failed"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE move_event_runs
                SET status = ?, total_symbols = ?, scanned_symbols = ?, candidate_symbols = ?,
                    event_count = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, total_symbols, scanned_symbols, candidate_symbols, event_count, error, timestamp, run_id),
            )

    def latest_report(self, universe_name: str, bucket: str = "", limit: int = 500) -> dict[str, Any] | None:
        with self._connect() as conn:
            run = conn.execute(
                """
                SELECT * FROM move_event_runs
                WHERE universe_name = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (universe_name,),
            ).fetchone()
            if not run:
                return None
            params: list[Any] = [run["id"]]
            where = "run_id = ?"
            if bucket:
                where += " AND bucket = ?"
                params.append(bucket)
            rows = conn.execute(
                f"""
                SELECT * FROM move_events
                WHERE {where}
                ORDER BY move_percent DESC, symbol, event_number
                LIMIT ?
                """,
                (*params, min(max(limit, 1), 1000)),
            ).fetchall()
        data = dict(run)
        data["items"] = [move_event_row_to_dict(row) for row in rows]
        return move_event_report_dict(data)


class MoveEventService:
    def __init__(self, settings: Settings, token_store: TokenStore) -> None:
        self.settings = settings
        self.store = MoveEventStore(token_store)

    def refresh_nifty_500_events(self, threshold_percent: float = 10.0, pullback_percent: float = 5.0) -> dict[str, Any]:
        window = historical_window(self.settings)
        run_id = self.store.create_run(NIFTY_500_INDEX_NAME, threshold_percent, pullback_percent, window)
        try:
            groups = self.store.candle_groups(NIFTY_500_INDEX_NAME, window)
            total_symbols = len(groups)
            scanned_symbols = 0
            candidate_symbols = 0
            event_count = 0
            for group in groups:
                candles = group["candles"]
                if len(candles) < 2:
                    continue
                scanned_symbols += 1
                events = detect_move_events(candles, threshold_percent, pullback_percent)
                if not events:
                    continue
                candidate_symbols += 1
                event_count += len(events)
                self.store.insert_events(run_id, group, events, threshold_percent, pullback_percent)
            self.store.finish_run(run_id, total_symbols, scanned_symbols, candidate_symbols, event_count)
        except Exception as exc:
            self.store.finish_run(run_id, 0, 0, 0, 0, str(exc))
            raise
        report = self.store.latest_report(NIFTY_500_INDEX_NAME)
        return report or empty_move_event_report(NIFTY_500_INDEX_NAME, threshold_percent, pullback_percent, window)

    def latest_nifty_500_report(self, bucket: str = "", limit: int = 500) -> dict[str, Any] | None:
        return self.store.latest_report(NIFTY_500_INDEX_NAME, bucket=bucket, limit=limit)


def detect_move_events(
    candles: list[dict[str, Any]],
    threshold_percent: float = 10.0,
    pullback_percent: float = 5.0,
) -> list[dict[str, Any]]:
    if len(candles) < 2:
        return []

    segments = split_continuous_move_segments(candles, pullback_percent)
    events: list[dict[str, Any]] = []
    for start_index, end_index, split_pullback_date, split_pullback_close in segments:
        event = best_upward_event(candles, start_index, end_index)
        if event is None or event["move_percent"] < threshold_percent:
            continue
        event["split_pullback_date"] = split_pullback_date
        event["split_pullback_close"] = split_pullback_close
        events.append(event)
    return events


def split_continuous_move_segments(
    candles: list[dict[str, Any]],
    pullback_percent: float,
) -> list[tuple[int, int, str | None, float | None]]:
    start_index = 0
    running_high = float(candles[0]["high"])
    running_high_index = 0
    segments: list[tuple[int, int, str | None, float | None]] = []

    for index in range(1, len(candles)):
        candle = candles[index]
        high = float(candle["high"])
        close = float(candle["close"])
        if high > running_high:
            running_high = high
            running_high_index = index
        if index > running_high_index and running_high > 0:
            pullback = ((running_high - close) / running_high) * 100
            if pullback >= pullback_percent:
                segments.append((start_index, index, candle["trading_date"], close))
                start_index = index
                running_high = high
                running_high_index = index

    segments.append((start_index, len(candles) - 1, None, None))
    return segments


def best_upward_event(candles: list[dict[str, Any]], start_index: int, end_index: int) -> dict[str, Any] | None:
    lowest_low = None
    lowest_low_date = None
    lowest_low_index = None
    best = None

    for index in range(start_index, end_index + 1):
        candle = candles[index]
        low = float(candle["low"])
        high = float(candle["high"])
        trading_date = candle["trading_date"]

        if lowest_low is not None and lowest_low > 0 and lowest_low_index is not None and lowest_low_index < index:
            move_percent = ((high - lowest_low) / lowest_low) * 100
            if best is None or move_percent > best["move_percent"]:
                best = {
                    "low_date": lowest_low_date,
                    "low_price": lowest_low,
                    "low_index": lowest_low_index,
                    "high_date": trading_date,
                    "high_price": high,
                    "high_index": index,
                    "move_percent": move_percent,
                    "duration_calendar_days": (
                        date.fromisoformat(trading_date) - date.fromisoformat(str(lowest_low_date))
                    ).days,
                    "duration_trading_sessions": index - lowest_low_index,
                }

        if lowest_low is None or low < lowest_low:
            lowest_low = low
            lowest_low_date = trading_date
            lowest_low_index = index

    return best


def move_bucket(move_percent: float) -> str:
    if move_percent < 20:
        return "10-20"
    if move_percent < 30:
        return "20-30"
    if move_percent < 50:
        return "30-50"
    return "50+"


def move_event_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "index_constituent_id": row["index_constituent_id"],
        "instrument_id": row["instrument_id"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "symbol": row["symbol"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "event_number": row["event_number"],
        "bucket": row["bucket"],
        "low_date": row["low_date"],
        "low_price": row["low_price"],
        "high_date": row["high_date"],
        "high_price": row["high_price"],
        "move_percent": row["move_percent"],
        "duration_calendar_days": row["duration_calendar_days"],
        "duration_trading_sessions": row["duration_trading_sessions"],
        "threshold_percent": row["threshold_percent"],
        "pullback_percent": row["pullback_percent"],
        "split_pullback_date": row["split_pullback_date"],
        "split_pullback_close": row["split_pullback_close"],
        "created_at": row["created_at"],
    }


def move_event_report_dict(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run["id"],
        "universe_name": run["universe_name"],
        "threshold_percent": run["threshold_percent"],
        "pullback_percent": run["pullback_percent"],
        "from_date": run["from_date"],
        "to_date_exclusive": run["to_date_exclusive"],
        "status": run["status"],
        "total_symbols": run["total_symbols"],
        "scanned_symbols": run["scanned_symbols"],
        "candidate_symbols": run["candidate_symbols"],
        "event_count": run["event_count"],
        "error": run["error"],
        "generated_at": run["completed_at"] or run["started_at"],
        "items": run["items"],
    }


def empty_move_event_report(
    universe_name: str,
    threshold_percent: float,
    pullback_percent: float,
    window: HistoricalWindow,
) -> dict[str, Any]:
    return {
        "run_id": None,
        "universe_name": universe_name,
        "threshold_percent": threshold_percent,
        "pullback_percent": pullback_percent,
        "from_date": window.from_date.isoformat(),
        "to_date_exclusive": window.to_date_exclusive.isoformat(),
        "status": "missing",
        "total_symbols": 0,
        "scanned_symbols": 0,
        "candidate_symbols": 0,
        "event_count": 0,
        "error": "",
        "generated_at": now_utc(),
        "items": [],
    }
