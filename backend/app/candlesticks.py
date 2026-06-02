from typing import Any, Literal

from app.store import TokenStore
from app.timezone import now_utc


DOJI_BODY_MAX = 0.10
SMALL_BODY_MAX = 0.30
LONG_WICK_MIN = 0.60
BALANCED_WICK_MIN = 0.25
HIGH_WAVE_WICK_MIN = 0.35
BODY_INSIDE_TOLERANCE_PERCENT = 0.5
TWEEZER_TOLERANCE_PERCENT = 0.5

CandleDirection = Literal["green", "red", "flat"]


class CandlestickStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store

    def _connect(self):
        return self.token_store._connect()

    def candles_for_symbol(self, symbol: str, limit: int = 120) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        with self._connect() as conn:
            instrument = conn.execute(
                """
                SELECT id, security_id, isin, display_name, underlying_symbol
                FROM instruments
                WHERE active = 1 AND exchange_id = 'NSE' AND segment = 'E'
                  AND instrument = 'EQUITY'
                  AND UPPER(underlying_symbol) = UPPER(?)
                ORDER BY CASE WHEN series = 'EQ' THEN 0 ELSE 1 END, id
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if not instrument:
                return None, []
            rows = conn.execute(
                """
                SELECT trading_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = ?
                ORDER BY trading_date DESC
                LIMIT ?
                """,
                (instrument["id"], min(max(limit, 5), 365)),
            ).fetchall()
        return dict(instrument), [dict(row) for row in reversed(rows)]


class CandlestickService:
    def __init__(self, token_store: TokenStore, store: CandlestickStore | None = None) -> None:
        self.store = store or CandlestickStore(token_store)

    def report_for_symbol(self, symbol: str, limit: int = 120) -> dict[str, Any]:
        instrument, candles = self.store.candles_for_symbol(symbol, limit=limit)
        if instrument is None:
            return empty_candlestick_report(symbol, "instrument_not_found")
        if not candles:
            return empty_candlestick_report(symbol, "not_enough_candles")
        items = classify_candles(candles)
        report = candlestick_report(items)
        report.update(
            {
                "symbol": instrument["underlying_symbol"],
                "instrument_id": instrument["id"],
                "security_id": instrument["security_id"],
                "isin": instrument["isin"],
                "display_name": instrument["display_name"],
            }
        )
        return report


def classify_candles(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    for index, candle in enumerate(candles):
        previous = classified[index - 1] if index > 0 else None
        previous_raw = candles[index - 1] if index > 0 else None
        metrics = candle_metrics(candle)
        patterns = single_candle_patterns(metrics)
        patterns.extend(two_candle_patterns(metrics, previous, previous_raw))
        classified.append(
            {
                "trading_date": candle["trading_date"],
                "open": metrics["open"],
                "high": metrics["high"],
                "low": metrics["low"],
                "close": metrics["close"],
                "volume": metrics["volume"],
                "direction": metrics["direction"],
                "body_percent": round(metrics["body_ratio"] * 100, 2),
                "upper_wick_percent": round(metrics["upper_wick_ratio"] * 100, 2),
                "lower_wick_percent": round(metrics["lower_wick_ratio"] * 100, 2),
                "range_amount": round(metrics["range"], 2),
                "patterns": sorted(set(patterns)),
                "indecision_score": indecision_score(patterns),
            }
        )
    return classified


def candle_metrics(candle: dict[str, Any]) -> dict[str, Any]:
    open_price = float(candle["open"])
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])
    candle_range = max(high - low, 0)
    body = abs(close - open_price)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    if close > open_price:
        direction: CandleDirection = "green"
    elif close < open_price:
        direction = "red"
    else:
        direction = "flat"
    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": float(candle.get("volume") or 0),
        "range": candle_range,
        "body": body,
        "upper_wick": max(upper_wick, 0),
        "lower_wick": max(lower_wick, 0),
        "body_ratio": body / candle_range if candle_range > 0 else 0,
        "upper_wick_ratio": upper_wick / candle_range if candle_range > 0 else 0,
        "lower_wick_ratio": lower_wick / candle_range if candle_range > 0 else 0,
        "direction": direction,
    }


def single_candle_patterns(metrics: dict[str, Any]) -> list[str]:
    patterns: list[str] = []
    body_ratio = metrics["body_ratio"]
    upper = metrics["upper_wick_ratio"]
    lower = metrics["lower_wick_ratio"]
    if metrics["range"] <= 0:
        patterns.append("four_price_doji")
        return patterns
    if body_ratio <= DOJI_BODY_MAX:
        patterns.append("doji")
        if upper >= BALANCED_WICK_MIN and lower >= BALANCED_WICK_MIN:
            patterns.append("long_legged_doji")
        if lower >= LONG_WICK_MIN and upper <= 0.15:
            patterns.append("dragonfly_doji")
        if upper >= LONG_WICK_MIN and lower <= 0.15:
            patterns.append("gravestone_doji")
    if body_ratio <= SMALL_BODY_MAX and upper >= 0.20 and lower >= 0.20:
        patterns.append("spinning_top")
    if body_ratio <= 0.25 and upper >= HIGH_WAVE_WICK_MIN and lower >= HIGH_WAVE_WICK_MIN:
        patterns.append("high_wave")
    if lower >= LONG_WICK_MIN and body_ratio <= SMALL_BODY_MAX:
        patterns.append("long_lower_wick_indecision")
    if upper >= LONG_WICK_MIN and body_ratio <= SMALL_BODY_MAX:
        patterns.append("long_upper_wick_indecision")
    return patterns


def two_candle_patterns(
    metrics: dict[str, Any],
    previous: dict[str, Any] | None,
    previous_raw: dict[str, Any] | None,
) -> list[str]:
    if previous is None or previous_raw is None:
        return []
    patterns: list[str] = []
    if metrics["high"] <= float(previous_raw["high"]) and metrics["low"] >= float(previous_raw["low"]):
        patterns.append("inside_bar")
    if body_inside_previous(metrics, previous_raw) and metrics["body_ratio"] <= SMALL_BODY_MAX:
        patterns.append("harami")
        if "doji" in single_candle_patterns(metrics):
            patterns.append("harami_cross")
    if previous["direction"] == "red" and metrics["direction"] == "green":
        if price_distance_percent(metrics["low"], float(previous_raw["low"])) <= TWEEZER_TOLERANCE_PERCENT:
            patterns.append("tweezer_bottom")
    if previous["direction"] == "green" and metrics["direction"] == "red":
        if price_distance_percent(metrics["high"], float(previous_raw["high"])) <= TWEEZER_TOLERANCE_PERCENT:
            patterns.append("tweezer_top")
    return patterns


def body_inside_previous(metrics: dict[str, Any], previous_raw: dict[str, Any]) -> bool:
    current_low = min(metrics["open"], metrics["close"])
    current_high = max(metrics["open"], metrics["close"])
    previous_low = min(float(previous_raw["open"]), float(previous_raw["close"]))
    previous_high = max(float(previous_raw["open"]), float(previous_raw["close"]))
    tolerance = max(previous_high * (BODY_INSIDE_TOLERANCE_PERCENT / 100), 0.01)
    return current_low >= previous_low - tolerance and current_high <= previous_high + tolerance


def price_distance_percent(left: float, right: float) -> float:
    reference = (abs(left) + abs(right)) / 2
    if reference <= 0:
        return 0.0
    return abs(left - right) / reference * 100


def indecision_score(patterns: list[str]) -> float:
    weights = {
        "doji": 35,
        "long_legged_doji": 25,
        "dragonfly_doji": 20,
        "gravestone_doji": 20,
        "four_price_doji": 40,
        "spinning_top": 25,
        "high_wave": 35,
        "long_lower_wick_indecision": 20,
        "long_upper_wick_indecision": 20,
        "inside_bar": 20,
        "harami": 25,
        "harami_cross": 35,
        "tweezer_bottom": 25,
        "tweezer_top": 25,
    }
    return float(min(100, sum(weights.get(pattern, 0) for pattern in set(patterns))))


def candlestick_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    pattern_counts: dict[str, int] = {}
    for item in items:
        for pattern in item["patterns"]:
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
    return {
        "symbol": "",
        "instrument_id": None,
        "security_id": "",
        "isin": "",
        "display_name": "",
        "status": "ok",
        "generated_at": now_utc().isoformat(),
        "candle_count": len(items),
        "latest_date": items[-1]["trading_date"] if items else "",
        "latest_patterns": items[-1]["patterns"] if items else [],
        "pattern_counts": pattern_counts,
        "items": items,
    }


def empty_candlestick_report(symbol: str, status: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "instrument_id": None,
        "security_id": "",
        "isin": "",
        "display_name": "",
        "status": status,
        "generated_at": now_utc().isoformat(),
        "candle_count": 0,
        "latest_date": "",
        "latest_patterns": [],
        "pattern_counts": {},
        "items": [],
    }
