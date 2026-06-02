import json
from datetime import date
from typing import Any

from app.config import Settings
from app.historical_data import HistoricalWindow, historical_window
from app.index_universe import NIFTY_500_INDEX_NAME
from app.regime import classify_regime_series
from app.store import TokenStore
from app.timezone import now_utc


DRISHTI_SIGNAL_01_ID = "DRISHTI_SIGNAL_01_LOCAL_LOW_REVERSAL"
DRISHTI_SIGNAL_01_NAME = "Signal 01: Downtrend Local Low Reversal"


class DrishtiSignalStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()
        self.upsert_signal_01_definition()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS drishti_signal_definitions (
                    signal_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS drishti_signal_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT NOT NULL,
                    universe_name TEXT NOT NULL,
                    lookback_sessions INTEGER NOT NULL,
                    volume_sma_sessions INTEGER NOT NULL,
                    min_volume_ratio_1d REAL NOT NULL,
                    min_volume_vs_sma REAL NOT NULL,
                    from_date TEXT NOT NULL,
                    to_date_exclusive TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_symbols INTEGER NOT NULL DEFAULT 0,
                    scanned_symbols INTEGER NOT NULL DEFAULT 0,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    outcome_ge_10_count INTEGER NOT NULL DEFAULT 0,
                    outcome_ge_20_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS drishti_signal_hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    signal_id TEXT NOT NULL,
                    index_constituent_id INTEGER NOT NULL,
                    instrument_id INTEGER NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    anchor_date TEXT NOT NULL,
                    trigger_date TEXT NOT NULL,
                    anchor_open REAL NOT NULL,
                    anchor_high REAL NOT NULL,
                    anchor_low REAL NOT NULL,
                    anchor_close REAL NOT NULL,
                    anchor_volume REAL NOT NULL,
                    anchor_regime TEXT NOT NULL DEFAULT '',
                    anchor_regime_confidence REAL NOT NULL DEFAULT 0,
                    anchor_sma_50 REAL NOT NULL DEFAULT 0,
                    anchor_sma_50_slope_10d_percent REAL NOT NULL DEFAULT 0,
                    anchor_range_position REAL NOT NULL DEFAULT 0,
                    trigger_open REAL NOT NULL,
                    trigger_high REAL NOT NULL,
                    trigger_low REAL NOT NULL,
                    trigger_close REAL NOT NULL,
                    trigger_volume REAL NOT NULL,
                    volume_ratio_1d REAL NOT NULL,
                    volume_vs_sma REAL NOT NULL,
                    close_to_anchor_high_ratio REAL NOT NULL,
                    future_high REAL NOT NULL,
                    future_high_date TEXT NOT NULL,
                    outcome_from_trigger_percent REAL NOT NULL,
                    outcome_from_anchor_percent REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, instrument_id, trigger_date)
                )
                """
            )
            existing_hit_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(drishti_signal_hits)").fetchall()
            }
            for column_name, ddl in {
                "anchor_regime": "ALTER TABLE drishti_signal_hits ADD COLUMN anchor_regime TEXT NOT NULL DEFAULT ''",
                "anchor_regime_confidence": (
                    "ALTER TABLE drishti_signal_hits ADD COLUMN anchor_regime_confidence REAL NOT NULL DEFAULT 0"
                ),
                "anchor_sma_50": "ALTER TABLE drishti_signal_hits ADD COLUMN anchor_sma_50 REAL NOT NULL DEFAULT 0",
                "anchor_sma_50_slope_10d_percent": (
                    "ALTER TABLE drishti_signal_hits ADD COLUMN anchor_sma_50_slope_10d_percent REAL NOT NULL DEFAULT 0"
                ),
                "anchor_range_position": (
                    "ALTER TABLE drishti_signal_hits ADD COLUMN anchor_range_position REAL NOT NULL DEFAULT 0"
                ),
            }.items():
                if column_name not in existing_hit_columns:
                    conn.execute(ddl)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_drishti_runs_signal ON drishti_signal_runs(signal_id, universe_name)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_drishti_hits_run ON drishti_signal_hits(run_id)")

    def upsert_signal_01_definition(self) -> None:
        timestamp = now_utc().isoformat()
        config = {
            "lookback_sessions": 45,
            "volume_sma_sessions": 20,
            "min_volume_ratio_1d": 1.2,
            "min_volume_vs_sma": 1.0,
            "rules": [
                "Anchor candle low is the lowest low in the lookback window.",
                "Anchor candle is red.",
                "Trigger candle is the next trading candle and is green.",
                "Trigger close is above anchor high.",
                "Trigger volume is at least 1.2x anchor volume.",
                "Trigger volume is at least average 20-session volume.",
                "Anchor candle regime is DOWNTREND by SMA50, SMA50 slope, and 45-session range position.",
            ],
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO drishti_signal_definitions (
                    signal_id, name, description, version, active, config_json, created_at, updated_at
                )
                VALUES (?, ?, ?, 1, 1, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    version = excluded.version,
                    active = excluded.active,
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (
                    DRISHTI_SIGNAL_01_ID,
                    DRISHTI_SIGNAL_01_NAME,
                    "Early-watch signal for a stock already in downtrend that makes a fresh local low, then shows immediate upside demand and volume confirmation.",
                    json.dumps(config, sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )

    def create_run(
        self,
        universe_name: str,
        window: HistoricalWindow,
        lookback_sessions: int,
        volume_sma_sessions: int,
        min_volume_ratio_1d: float,
        min_volume_vs_sma: float,
    ) -> int:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO drishti_signal_runs (
                    signal_id, universe_name, lookback_sessions, volume_sma_sessions,
                    min_volume_ratio_1d, min_volume_vs_sma, from_date, to_date_exclusive,
                    status, started_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)
                """,
                (
                    DRISHTI_SIGNAL_01_ID,
                    universe_name,
                    lookback_sessions,
                    volume_sma_sessions,
                    min_volume_ratio_1d,
                    min_volume_vs_sma,
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
                    dc.open,
                    dc.high,
                    dc.low,
                    dc.close,
                    dc.volume
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
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]),
                    }
                )
        return list(grouped.values())

    def insert_hits(self, run_id: int, symbol_group: dict[str, Any], hits: list[dict[str, Any]]) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            for hit in hits:
                conn.execute(
                    """
                    INSERT INTO drishti_signal_hits (
                        run_id, signal_id, index_constituent_id, instrument_id, company_name,
                        industry, symbol, isin, security_id, anchor_date, trigger_date,
                        anchor_open, anchor_high, anchor_low, anchor_close, anchor_volume,
                        anchor_regime, anchor_regime_confidence, anchor_sma_50,
                        anchor_sma_50_slope_10d_percent, anchor_range_position,
                        trigger_open, trigger_high, trigger_low, trigger_close, trigger_volume,
                        volume_ratio_1d, volume_vs_sma, close_to_anchor_high_ratio,
                        future_high, future_high_date, outcome_from_trigger_percent,
                        outcome_from_anchor_percent, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        DRISHTI_SIGNAL_01_ID,
                        symbol_group["index_constituent_id"],
                        symbol_group["instrument_id"],
                        symbol_group["company_name"],
                        symbol_group["industry"],
                        symbol_group["symbol"],
                        symbol_group["isin"],
                        symbol_group["security_id"],
                        hit["anchor_date"],
                        hit["trigger_date"],
                        hit["anchor_open"],
                        hit["anchor_high"],
                        hit["anchor_low"],
                        hit["anchor_close"],
                        hit["anchor_volume"],
                        hit["anchor_regime"],
                        hit["anchor_regime_confidence"],
                        hit["anchor_sma_50"],
                        hit["anchor_sma_50_slope_10d_percent"],
                        hit["anchor_range_position"],
                        hit["trigger_open"],
                        hit["trigger_high"],
                        hit["trigger_low"],
                        hit["trigger_close"],
                        hit["trigger_volume"],
                        hit["volume_ratio_1d"],
                        hit["volume_vs_sma"],
                        hit["close_to_anchor_high_ratio"],
                        hit["future_high"],
                        hit["future_high_date"],
                        hit["outcome_from_trigger_percent"],
                        hit["outcome_from_anchor_percent"],
                        timestamp,
                    ),
                )

    def finish_run(
        self,
        run_id: int,
        total_symbols: int,
        scanned_symbols: int,
        hit_count: int,
        outcome_ge_10_count: int,
        outcome_ge_20_count: int,
        error: str = "",
    ) -> None:
        timestamp = now_utc().isoformat()
        status = "completed" if not error else "failed"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE drishti_signal_runs
                SET status = ?, total_symbols = ?, scanned_symbols = ?, hit_count = ?,
                    outcome_ge_10_count = ?, outcome_ge_20_count = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    total_symbols,
                    scanned_symbols,
                    hit_count,
                    outcome_ge_10_count,
                    outcome_ge_20_count,
                    error,
                    timestamp,
                    run_id,
                ),
            )

    def latest_signal_01_report(self, universe_name: str, limit: int = 500) -> dict[str, Any] | None:
        with self._connect() as conn:
            definition = conn.execute(
                "SELECT * FROM drishti_signal_definitions WHERE signal_id = ?",
                (DRISHTI_SIGNAL_01_ID,),
            ).fetchone()
            run = conn.execute(
                """
                SELECT * FROM drishti_signal_runs
                WHERE signal_id = ? AND universe_name = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (DRISHTI_SIGNAL_01_ID, universe_name),
            ).fetchone()
            if not run:
                return None
            rows = conn.execute(
                """
                SELECT * FROM drishti_signal_hits
                WHERE run_id = ?
                ORDER BY outcome_from_trigger_percent DESC, symbol, trigger_date
                LIMIT ?
                """,
                (run["id"], min(max(limit, 1), 1000)),
            ).fetchall()
        data = dict(run)
        data["definition"] = drishti_definition_row_to_dict(definition) if definition else None
        data["items"] = [drishti_hit_row_to_dict(row) for row in rows]
        return drishti_signal_report_dict(data)


class DrishtiSignalService:
    def __init__(self, settings: Settings, token_store: TokenStore) -> None:
        self.settings = settings
        self.store = DrishtiSignalStore(token_store)

    def refresh_nifty_500_signal_01(
        self,
        lookback_sessions: int = 45,
        volume_sma_sessions: int = 20,
        min_volume_ratio_1d: float = 1.2,
        min_volume_vs_sma: float = 1.0,
    ) -> dict[str, Any]:
        window = historical_window(self.settings)
        run_id = self.store.create_run(
            NIFTY_500_INDEX_NAME,
            window,
            lookback_sessions,
            volume_sma_sessions,
            min_volume_ratio_1d,
            min_volume_vs_sma,
        )
        try:
            groups = self.store.candle_groups(NIFTY_500_INDEX_NAME, window)
            total_symbols = len(groups)
            scanned_symbols = 0
            hit_count = 0
            outcome_ge_10_count = 0
            outcome_ge_20_count = 0
            for group in groups:
                candles = group["candles"]
                if len(candles) < max(lookback_sessions + 1, volume_sma_sessions + 1):
                    continue
                scanned_symbols += 1
                hits = detect_signal_01_local_low_reversal(
                    candles,
                    lookback_sessions=lookback_sessions,
                    volume_sma_sessions=volume_sma_sessions,
                    min_volume_ratio_1d=min_volume_ratio_1d,
                    min_volume_vs_sma=min_volume_vs_sma,
                )
                if not hits:
                    continue
                hit_count += len(hits)
                outcome_ge_10_count += sum(1 for hit in hits if hit["outcome_from_trigger_percent"] >= 10)
                outcome_ge_20_count += sum(1 for hit in hits if hit["outcome_from_trigger_percent"] >= 20)
                self.store.insert_hits(run_id, group, hits)
            self.store.finish_run(
                run_id,
                total_symbols,
                scanned_symbols,
                hit_count,
                outcome_ge_10_count,
                outcome_ge_20_count,
            )
        except Exception as exc:
            self.store.finish_run(run_id, 0, 0, 0, 0, 0, str(exc))
            raise
        report = self.store.latest_signal_01_report(NIFTY_500_INDEX_NAME)
        return report or empty_drishti_signal_report(NIFTY_500_INDEX_NAME, window)

    def latest_nifty_500_signal_01_report(self, limit: int = 500) -> dict[str, Any] | None:
        return self.store.latest_signal_01_report(NIFTY_500_INDEX_NAME, limit=limit)


def detect_signal_01_local_low_reversal(
    candles: list[dict[str, Any]],
    lookback_sessions: int = 45,
    volume_sma_sessions: int = 20,
    min_volume_ratio_1d: float = 1.2,
    min_volume_vs_sma: float = 1.0,
) -> list[dict[str, Any]]:
    if len(candles) < max(lookback_sessions + 1, volume_sma_sessions + 1):
        return []

    regime_by_date = {
        row["trading_date"]: row
        for row in classify_regime_series(candles)
    }
    hits: list[dict[str, Any]] = []
    for trigger_index in range(1, len(candles)):
        anchor_index = trigger_index - 1
        if anchor_index + 1 < lookback_sessions or trigger_index < volume_sma_sessions:
            continue

        anchor = candles[anchor_index]
        trigger = candles[trigger_index]
        anchor_low = float(anchor["low"])
        anchor_open = float(anchor["open"])
        anchor_high = float(anchor["high"])
        anchor_close = float(anchor["close"])
        anchor_volume = float(anchor["volume"])
        trigger_open = float(trigger["open"])
        trigger_close = float(trigger["close"])
        trigger_volume = float(trigger["volume"])

        lookback = candles[anchor_index - lookback_sessions + 1 : anchor_index + 1]
        if anchor_low != min(float(candle["low"]) for candle in lookback):
            continue
        if anchor_close >= anchor_open:
            continue
        anchor_regime = regime_by_date.get(str(anchor["trading_date"]))
        if anchor_regime is None or anchor_regime["regime"] != "DOWNTREND":
            continue
        if trigger_close <= trigger_open:
            continue
        if trigger_close <= anchor_high:
            continue
        if anchor_volume <= 0:
            continue

        volume_ratio_1d = trigger_volume / anchor_volume
        if volume_ratio_1d < min_volume_ratio_1d:
            continue

        volume_window = candles[trigger_index - volume_sma_sessions : trigger_index]
        average_volume = sum(float(candle["volume"]) for candle in volume_window) / volume_sma_sessions
        if average_volume <= 0:
            continue
        volume_vs_sma = trigger_volume / average_volume
        if volume_vs_sma < min_volume_vs_sma:
            continue

        future_high, future_high_date = max_future_high(candles, trigger_index)
        hits.append(
            {
                "anchor_date": anchor["trading_date"],
                "trigger_date": trigger["trading_date"],
                "anchor_open": anchor_open,
                "anchor_high": anchor_high,
                "anchor_low": anchor_low,
                "anchor_close": anchor_close,
                "anchor_volume": anchor_volume,
                "anchor_regime": anchor_regime["regime"],
                "anchor_regime_confidence": anchor_regime["confidence"],
                "anchor_sma_50": anchor_regime["sma_50"],
                "anchor_sma_50_slope_10d_percent": anchor_regime["sma_50_slope_10d_percent"],
                "anchor_range_position": anchor_regime["range_position"],
                "trigger_open": trigger_open,
                "trigger_high": float(trigger["high"]),
                "trigger_low": float(trigger["low"]),
                "trigger_close": trigger_close,
                "trigger_volume": trigger_volume,
                "volume_ratio_1d": volume_ratio_1d,
                "volume_vs_sma": volume_vs_sma,
                "close_to_anchor_high_ratio": trigger_close / anchor_high if anchor_high > 0 else 0,
                "future_high": future_high,
                "future_high_date": future_high_date,
                "outcome_from_trigger_percent": (
                    ((future_high - trigger_close) / trigger_close) * 100 if trigger_close > 0 else 0
                ),
                "outcome_from_anchor_percent": ((future_high - anchor_low) / anchor_low) * 100
                if anchor_low > 0
                else 0,
            }
        )
    return hits


def max_future_high(candles: list[dict[str, Any]], start_index: int) -> tuple[float, str]:
    best = candles[start_index]
    best_high = float(best["high"])
    best_date = best["trading_date"]
    for candle in candles[start_index + 1 :]:
        high = float(candle["high"])
        if high > best_high:
            best_high = high
            best_date = candle["trading_date"]
    return best_high, best_date


def drishti_definition_row_to_dict(row) -> dict[str, Any]:
    return {
        "signal_id": row["signal_id"],
        "name": row["name"],
        "description": row["description"],
        "version": row["version"],
        "active": bool(row["active"]),
        "config": json.loads(row["config_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def drishti_hit_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "signal_id": row["signal_id"],
        "index_constituent_id": row["index_constituent_id"],
        "instrument_id": row["instrument_id"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "symbol": row["symbol"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "anchor_date": row["anchor_date"],
        "trigger_date": row["trigger_date"],
        "anchor_open": row["anchor_open"],
        "anchor_high": row["anchor_high"],
        "anchor_low": row["anchor_low"],
        "anchor_close": row["anchor_close"],
        "anchor_volume": row["anchor_volume"],
        "anchor_regime": row["anchor_regime"],
        "anchor_regime_confidence": row["anchor_regime_confidence"],
        "anchor_sma_50": row["anchor_sma_50"],
        "anchor_sma_50_slope_10d_percent": row["anchor_sma_50_slope_10d_percent"],
        "anchor_range_position": row["anchor_range_position"],
        "trigger_open": row["trigger_open"],
        "trigger_high": row["trigger_high"],
        "trigger_low": row["trigger_low"],
        "trigger_close": row["trigger_close"],
        "trigger_volume": row["trigger_volume"],
        "volume_ratio_1d": row["volume_ratio_1d"],
        "volume_vs_sma": row["volume_vs_sma"],
        "close_to_anchor_high_ratio": row["close_to_anchor_high_ratio"],
        "future_high": row["future_high"],
        "future_high_date": row["future_high_date"],
        "outcome_from_trigger_percent": row["outcome_from_trigger_percent"],
        "outcome_from_anchor_percent": row["outcome_from_anchor_percent"],
        "created_at": row["created_at"],
    }


def drishti_signal_report_dict(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run["id"],
        "signal_id": run["signal_id"],
        "signal_name": run["definition"]["name"] if run.get("definition") else DRISHTI_SIGNAL_01_NAME,
        "description": run["definition"]["description"] if run.get("definition") else "",
        "universe_name": run["universe_name"],
        "lookback_sessions": run["lookback_sessions"],
        "volume_sma_sessions": run["volume_sma_sessions"],
        "min_volume_ratio_1d": run["min_volume_ratio_1d"],
        "min_volume_vs_sma": run["min_volume_vs_sma"],
        "from_date": run["from_date"],
        "to_date_exclusive": run["to_date_exclusive"],
        "status": run["status"],
        "total_symbols": run["total_symbols"],
        "scanned_symbols": run["scanned_symbols"],
        "hit_count": run["hit_count"],
        "outcome_ge_10_count": run["outcome_ge_10_count"],
        "outcome_ge_20_count": run["outcome_ge_20_count"],
        "error": run["error"],
        "generated_at": run["completed_at"] or run["started_at"],
        "items": run["items"],
    }


def empty_drishti_signal_report(universe_name: str, window: HistoricalWindow) -> dict[str, Any]:
    return {
        "run_id": None,
        "signal_id": DRISHTI_SIGNAL_01_ID,
        "signal_name": DRISHTI_SIGNAL_01_NAME,
        "description": "",
        "universe_name": universe_name,
        "lookback_sessions": 45,
        "volume_sma_sessions": 20,
        "min_volume_ratio_1d": 1.2,
        "min_volume_vs_sma": 1.0,
        "from_date": window.from_date.isoformat(),
        "to_date_exclusive": window.to_date_exclusive.isoformat(),
        "status": "missing",
        "total_symbols": 0,
        "scanned_symbols": 0,
        "hit_count": 0,
        "outcome_ge_10_count": 0,
        "outcome_ge_20_count": 0,
        "error": "",
        "generated_at": now_utc(),
        "items": [],
    }
