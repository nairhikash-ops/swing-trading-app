import json
from typing import Any, Literal

from app.index_universe import NIFTY_500_INDEX_NAME
from app.store import TokenStore
from app.timezone import now_utc


RegimeLabel = Literal["UPTREND", "DOWNTREND", "SIDEWAYS"]
SMA_WINDOW = 50
SLOPE_LOOKBACK = 10
RANGE_WINDOW = 45
UPTREND_SLOPE_MIN_PERCENT = 1.0
DOWNTREND_SLOPE_MAX_PERCENT = -1.0
UPTREND_RANGE_POSITION_MIN = 0.55
DOWNTREND_RANGE_POSITION_MAX = 0.45


class StockRegimeStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_regime_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    universe_name TEXT NOT NULL,
                    from_date TEXT NOT NULL,
                    to_date_exclusive TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_symbols INTEGER NOT NULL DEFAULT 0,
                    scanned_symbols INTEGER NOT NULL DEFAULT 0,
                    classified_count INTEGER NOT NULL DEFAULT 0,
                    uptrend_count INTEGER NOT NULL DEFAULT 0,
                    downtrend_count INTEGER NOT NULL DEFAULT 0,
                    sideways_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_regime_daily (
                    instrument_id INTEGER NOT NULL,
                    trading_date TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    index_constituent_id INTEGER NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    isin TEXT NOT NULL,
                    security_id TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0,
                    close REAL NOT NULL,
                    sma_50 REAL NOT NULL,
                    sma_50_slope_10d_percent REAL NOT NULL,
                    low_45 REAL NOT NULL,
                    high_45 REAL NOT NULL,
                    range_position REAL NOT NULL,
                    reason_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (instrument_id, trading_date)
                )
                """
            )
            existing_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(stock_regime_daily)").fetchall()
            }
            if "confidence" not in existing_columns:
                conn.execute("ALTER TABLE stock_regime_daily ADD COLUMN confidence REAL NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_regime_daily_symbol_date ON stock_regime_daily(symbol, trading_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_regime_daily_regime ON stock_regime_daily(regime, trading_date)")

    def create_run(self, universe_name: str, from_date: str, to_date_exclusive: str) -> int:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO stock_regime_runs (
                    universe_name, from_date, to_date_exclusive, status, started_at
                )
                VALUES (?, ?, ?, 'running', ?)
                """,
                (universe_name, from_date, to_date_exclusive, timestamp),
            )
            return int(cursor.lastrowid)

    def candle_groups(self, universe_name: str, from_date: str, to_date_exclusive: str) -> list[dict[str, Any]]:
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
                    dc.high,
                    dc.low,
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
                (from_date, to_date_exclusive, universe_name),
            ).fetchall()

        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            instrument_id = int(row["instrument_id"])
            group = grouped.setdefault(
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
                group["candles"].append(
                    {
                        "trading_date": row["trading_date"],
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                    }
                )
        return list(grouped.values())

    def upsert_regimes(self, run_id: int, group: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            for item in rows:
                conn.execute(
                    """
                    INSERT INTO stock_regime_daily (
                        instrument_id, trading_date, run_id, index_constituent_id,
                        company_name, industry, symbol, isin, security_id, regime,
                        confidence, close, sma_50, sma_50_slope_10d_percent, low_45, high_45,
                        range_position, reason_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(instrument_id, trading_date) DO UPDATE SET
                        run_id = excluded.run_id,
                        index_constituent_id = excluded.index_constituent_id,
                        company_name = excluded.company_name,
                        industry = excluded.industry,
                        symbol = excluded.symbol,
                        isin = excluded.isin,
                        security_id = excluded.security_id,
                        regime = excluded.regime,
                        confidence = excluded.confidence,
                        close = excluded.close,
                        sma_50 = excluded.sma_50,
                        sma_50_slope_10d_percent = excluded.sma_50_slope_10d_percent,
                        low_45 = excluded.low_45,
                        high_45 = excluded.high_45,
                        range_position = excluded.range_position,
                        reason_json = excluded.reason_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        group["instrument_id"],
                        item["trading_date"],
                        run_id,
                        group["index_constituent_id"],
                        group["company_name"],
                        group["industry"],
                        group["symbol"],
                        group["isin"],
                        group["security_id"],
                        item["regime"],
                        item["confidence"],
                        item["close"],
                        item["sma_50"],
                        item["sma_50_slope_10d_percent"],
                        item["low_45"],
                        item["high_45"],
                        item["range_position"],
                        json.dumps(item["reason"], sort_keys=True),
                        timestamp,
                        timestamp,
                    ),
                )

    def finish_run(
        self,
        run_id: int,
        total_symbols: int,
        scanned_symbols: int,
        classified_count: int,
        regime_counts: dict[str, int],
        error: str = "",
    ) -> None:
        timestamp = now_utc().isoformat()
        status = "completed" if not error else "failed"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE stock_regime_runs
                SET status = ?, total_symbols = ?, scanned_symbols = ?, classified_count = ?,
                    uptrend_count = ?, downtrend_count = ?, sideways_count = ?,
                    error = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    total_symbols,
                    scanned_symbols,
                    classified_count,
                    int(regime_counts.get("UPTREND", 0)),
                    int(regime_counts.get("DOWNTREND", 0)),
                    int(regime_counts.get("SIDEWAYS", 0)),
                    error,
                    timestamp,
                    run_id,
                ),
            )

    def latest_run(self, universe_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM stock_regime_runs
                WHERE universe_name = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (universe_name,),
            ).fetchone()
        return dict(row) if row else None

    def latest_for_universe(
        self,
        universe_name: str,
        regime: str | None = None,
        query: str = "",
        limit: int = 500,
    ) -> dict[str, Any] | None:
        run = self.latest_run(universe_name)
        if not run:
            return None
        params: list[Any] = [universe_name]
        filters = [
            """
            rd.trading_date = (
                SELECT MAX(rd2.trading_date)
                FROM stock_regime_daily rd2
                WHERE rd2.instrument_id = rd.instrument_id
            )
            """,
            """
            rd.instrument_id IN (
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
        ]
        if regime:
            filters.append("rd.regime = ?")
            params.append(regime.upper())
        if query.strip():
            filters.append("(UPPER(rd.symbol) LIKE ? OR UPPER(rd.company_name) LIKE ? OR UPPER(rd.industry) LIKE ?)")
            like = f"%{query.strip().upper()}%"
            params.extend([like, like, like])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT rd.*
                FROM stock_regime_daily rd
                WHERE {" AND ".join(filters)}
                ORDER BY rd.regime, rd.symbol
                LIMIT ?
                """,
                (*params, min(max(limit, 1), 1000)),
            ).fetchall()
        return {
            "run": run,
            "items": [regime_row_to_dict(row) for row in rows],
        }

    def history_for_symbol(self, symbol: str, limit: int = 365) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM stock_regime_daily
                WHERE UPPER(symbol) = UPPER(?)
                ORDER BY trading_date DESC
                LIMIT ?
                """,
                (symbol, min(max(limit, 1), 365)),
            ).fetchall()
        return [regime_row_to_dict(row) for row in reversed(rows)]


class StockRegimeService:
    def __init__(self, token_store: TokenStore, store: StockRegimeStore | None = None) -> None:
        self.store = store or StockRegimeStore(token_store)

    def refresh_nifty_500_regimes(self) -> dict[str, Any]:
        latest_bounds = self._latest_candle_bounds(NIFTY_500_INDEX_NAME)
        if latest_bounds is None:
            return empty_regime_report(NIFTY_500_INDEX_NAME, "missing", "No Nifty 500 candles are available.")
        from_date, to_date_exclusive = latest_bounds
        run_id = self.store.create_run(NIFTY_500_INDEX_NAME, from_date, to_date_exclusive)
        regime_counts = {"UPTREND": 0, "DOWNTREND": 0, "SIDEWAYS": 0}
        total_symbols = 0
        scanned_symbols = 0
        classified_count = 0
        try:
            groups = self.store.candle_groups(NIFTY_500_INDEX_NAME, from_date, to_date_exclusive)
            total_symbols = len(groups)
            for group in groups:
                rows = classify_regime_series(group["candles"])
                if not rows:
                    continue
                scanned_symbols += 1
                classified_count += len(rows)
                latest_regime = rows[-1]["regime"]
                regime_counts[latest_regime] += 1
                self.store.upsert_regimes(run_id, group, rows)
            self.store.finish_run(run_id, total_symbols, scanned_symbols, classified_count, regime_counts)
        except Exception as exc:
            self.store.finish_run(run_id, total_symbols, scanned_symbols, classified_count, regime_counts, str(exc))
            raise
        report = self.latest_nifty_500_regimes(limit=1000)
        return report or empty_regime_report(NIFTY_500_INDEX_NAME, "missing", "Regime run completed without rows.")

    def latest_nifty_500_regimes(
        self,
        regime: str | None = None,
        query: str = "",
        limit: int = 500,
    ) -> dict[str, Any] | None:
        latest = self.store.latest_for_universe(NIFTY_500_INDEX_NAME, regime=regime, query=query, limit=limit)
        if latest is None:
            return None
        return regime_report_dict(latest["run"], latest["items"])

    def history_for_symbol(self, symbol: str, limit: int = 365) -> list[dict[str, Any]]:
        return self.store.history_for_symbol(symbol, limit=limit)

    def _latest_candle_bounds(self, universe_name: str) -> tuple[str, str] | None:
        with self.store._connect() as conn:
            row = conn.execute(
                """
                SELECT MIN(dc.trading_date) AS from_date, MAX(dc.trading_date) AS latest_date
                FROM daily_candles dc
                JOIN instruments i ON i.id = dc.instrument_id AND i.active = 1
                JOIN index_constituents ic ON ic.isin = i.isin AND ic.active = 1
                WHERE ic.index_name = ?
                """,
                (universe_name,),
            ).fetchone()
        if not row or not row["from_date"] or not row["latest_date"]:
            return None
        from datetime import date, timedelta

        to_date = date.fromisoformat(str(row["latest_date"])) + timedelta(days=1)
        return str(row["from_date"]), to_date.isoformat()


def classify_regime_series(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if len(candles) < SMA_WINDOW + SLOPE_LOOKBACK:
        return rows
    closes = [float(candle["close"]) for candle in candles]
    lows = [float(candle["low"]) for candle in candles]
    highs = [float(candle["high"]) for candle in candles]
    for index in range(SMA_WINDOW + SLOPE_LOOKBACK - 1, len(candles)):
        close = closes[index]
        sma_50 = average(closes[index - SMA_WINDOW + 1 : index + 1])
        previous_sma_50 = average(closes[index - SLOPE_LOOKBACK - SMA_WINDOW + 1 : index - SLOPE_LOOKBACK + 1])
        slope_percent = percent_change(previous_sma_50, sma_50)
        range_low = min(lows[index - RANGE_WINDOW + 1 : index + 1])
        range_high = max(highs[index - RANGE_WINDOW + 1 : index + 1])
        range_width = range_high - range_low
        range_position = (close - range_low) / range_width if range_width > 0 else 0.5
        regime = classify_regime(close, sma_50, slope_percent, range_position)
        confidence = regime_confidence(close, sma_50, slope_percent, range_position, regime)
        reason = {
            "rule": "close_vs_sma50_plus_sma50_slope_plus_45d_range_position",
            "close_above_sma50": close > sma_50,
            "sma50_slope_10d_percent": slope_percent,
            "range_position": range_position,
        }
        rows.append(
            {
                "trading_date": candles[index]["trading_date"],
                "regime": regime,
                "confidence": confidence,
                "close": close,
                "sma_50": sma_50,
                "sma_50_slope_10d_percent": slope_percent,
                "low_45": range_low,
                "high_45": range_high,
                "range_position": range_position,
                "reason": reason,
            }
        )
    return rows


def classify_regime(close: float, sma_50: float, slope_percent: float, range_position: float) -> RegimeLabel:
    if close > sma_50 and slope_percent > UPTREND_SLOPE_MIN_PERCENT and range_position > UPTREND_RANGE_POSITION_MIN:
        return "UPTREND"
    if close < sma_50 and slope_percent < DOWNTREND_SLOPE_MAX_PERCENT and range_position < DOWNTREND_RANGE_POSITION_MAX:
        return "DOWNTREND"
    return "SIDEWAYS"


def regime_confidence(close: float, sma_50: float, slope_percent: float, range_position: float, regime: RegimeLabel) -> float:
    if sma_50 <= 0:
        return 0.0
    distance_from_sma = abs((close - sma_50) / sma_50) * 100
    slope_strength = min(abs(slope_percent) * 6, 24)
    distance_strength = min(distance_from_sma * 4, 24)
    if regime == "UPTREND":
        range_strength = min(max(range_position - UPTREND_RANGE_POSITION_MIN, 0) * 80, 16)
        return round(min(100, 55 + slope_strength + distance_strength + range_strength), 2)
    if regime == "DOWNTREND":
        range_strength = min(max(DOWNTREND_RANGE_POSITION_MAX - range_position, 0) * 80, 16)
        return round(min(100, 55 + slope_strength + distance_strength + range_strength), 2)
    neutral_slope = max(0, 1.0 - min(abs(slope_percent), 1.0)) * 20
    range_midpoint = max(0, 1.0 - min(abs(range_position - 0.5) * 2, 1.0)) * 20
    return round(min(100, 45 + neutral_slope + range_midpoint), 2)


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percent_change(base: float, value: float) -> float:
    if base <= 0:
        return 0.0
    return ((value - base) / base) * 100


def regime_row_to_dict(row) -> dict[str, Any]:
    return {
        "instrument_id": row["instrument_id"],
        "trading_date": row["trading_date"],
        "run_id": row["run_id"],
        "index_constituent_id": row["index_constituent_id"],
        "company_name": row["company_name"],
        "industry": row["industry"],
        "symbol": row["symbol"],
        "isin": row["isin"],
        "security_id": row["security_id"],
        "regime": row["regime"],
        "confidence": row["confidence"],
        "close": row["close"],
        "sma_50": row["sma_50"],
        "sma_50_slope_10d_percent": row["sma_50_slope_10d_percent"],
        "low_45": row["low_45"],
        "high_45": row["high_45"],
        "range_position": row["range_position"],
        "reason": json.loads(row["reason_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def regime_report_dict(run: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_id": run["id"],
        "universe_name": run["universe_name"],
        "from_date": run["from_date"],
        "to_date_exclusive": run["to_date_exclusive"],
        "status": run["status"],
        "total_symbols": run["total_symbols"],
        "scanned_symbols": run["scanned_symbols"],
        "classified_count": run["classified_count"],
        "uptrend_count": run["uptrend_count"],
        "downtrend_count": run["downtrend_count"],
        "sideways_count": run["sideways_count"],
        "error": run["error"],
        "generated_at": run["completed_at"] or run["started_at"],
        "items": items,
    }


def empty_regime_report(universe_name: str, status: str, error: str) -> dict[str, Any]:
    timestamp = now_utc().isoformat()
    return {
        "run_id": None,
        "universe_name": universe_name,
        "from_date": "",
        "to_date_exclusive": "",
        "status": status,
        "total_symbols": 0,
        "scanned_symbols": 0,
        "classified_count": 0,
        "uptrend_count": 0,
        "downtrend_count": 0,
        "sideways_count": 0,
        "error": error,
        "generated_at": timestamp,
        "items": [],
    }
