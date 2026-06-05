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
REVERSAL_TREND_LOOKBACK = 5
REVERSAL_TREND_THRESHOLD_PERCENT = 2.0
LARGE_BODY_MIN = 0.50

CandleDirection = Literal["green", "red", "flat"]
SetupTrend = Literal["up", "down", "sideways", "unknown"]
ReversalBias = Literal["bullish", "bearish", "mixed", "none"]


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
    metrics_series = [candle_metrics(candle) for candle in candles]
    for index, candle in enumerate(candles):
        previous = classified[index - 1] if index > 0 else None
        previous_raw = candles[index - 1] if index > 0 else None
        metrics = metrics_series[index]
        setup = setup_trend(candles, index)
        indecision_patterns = single_candle_patterns(metrics)
        indecision_patterns.extend(two_candle_patterns(metrics, previous, previous_raw))
        reversal_patterns = single_candle_reversal_patterns(metrics, indecision_patterns, setup)
        reversal_patterns.extend(two_candle_reversal_patterns(metrics_series, candles, index, setup))
        reversal_patterns.extend(three_candle_reversal_patterns(metrics_series, index, setup))
        patterns = sorted(set(indecision_patterns + reversal_patterns))
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
                "setup_trend": setup,
                "patterns": patterns,
                "indecision_score": indecision_score(indecision_patterns),
                "reversal_patterns": sorted(set(reversal_patterns)),
                "reversal_bias": reversal_bias(reversal_patterns),
                "reversal_score": reversal_score(reversal_patterns),
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


def setup_trend(candles: list[dict[str, Any]], index: int) -> SetupTrend:
    if index < 3:
        return "unknown"
    start = max(0, index - REVERSAL_TREND_LOOKBACK)
    window = candles[start:index]
    if len(window) < 3:
        return "unknown"
    closes = [float(candle["close"]) for candle in window]
    change = price_change_percent(closes[0], closes[-1])
    up_steps = sum(1 for left, right in zip(closes, closes[1:]) if right > left)
    down_steps = sum(1 for left, right in zip(closes, closes[1:]) if right < left)
    if change >= REVERSAL_TREND_THRESHOLD_PERCENT and up_steps >= down_steps:
        return "up"
    if change <= -REVERSAL_TREND_THRESHOLD_PERCENT and down_steps >= up_steps:
        return "down"
    return "sideways"


def single_candle_reversal_patterns(
    metrics: dict[str, Any],
    indecision_patterns: list[str],
    setup: SetupTrend,
) -> list[str]:
    patterns: list[str] = []
    body_ratio = metrics["body_ratio"]
    lower = metrics["lower_wick_ratio"]
    upper = metrics["upper_wick_ratio"]
    body_near_high = max(metrics["open"], metrics["close"]) >= metrics["low"] + metrics["range"] * 0.65
    body_near_low = min(metrics["open"], metrics["close"]) <= metrics["low"] + metrics["range"] * 0.35
    long_lower = lower >= 0.50 and metrics["lower_wick"] >= max(metrics["body"] * 2, 0.01)
    long_upper = upper >= 0.50 and metrics["upper_wick"] >= max(metrics["body"] * 2, 0.01)

    if body_ratio <= SMALL_BODY_MAX and long_lower and upper <= 0.25 and body_near_high:
        if setup == "down":
            patterns.append("hammer")
        elif setup == "up":
            patterns.append("hanging_man")
    if body_ratio <= SMALL_BODY_MAX and long_upper and lower <= 0.25 and body_near_low:
        if setup == "down":
            patterns.append("inverted_hammer")
        elif setup == "up":
            patterns.append("shooting_star")
    if setup == "down" and any(pattern in indecision_patterns for pattern in ("dragonfly_doji", "doji")):
        patterns.append("bullish_doji_reversal_watch")
    if setup == "up" and any(pattern in indecision_patterns for pattern in ("gravestone_doji", "doji")):
        patterns.append("bearish_doji_reversal_watch")
    return patterns


def two_candle_reversal_patterns(
    metrics_series: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    index: int,
    setup: SetupTrend,
) -> list[str]:
    if index < 1:
        return []
    previous = metrics_series[index - 1]
    current = metrics_series[index]
    patterns: list[str] = []
    previous_midpoint = (previous["open"] + previous["close"]) / 2

    if setup == "down" and previous["direction"] == "red" and current["direction"] == "green":
        if body_engulfs(current, previous):
            patterns.append("bullish_engulfing")
        if current["close"] > previous_midpoint and current["close"] < previous["open"]:
            patterns.append("piercing_pattern")
        if body_inside_previous(current, candles[index - 1]) and current["body_ratio"] <= SMALL_BODY_MAX:
            patterns.append("bullish_harami")
        if price_distance_percent(current["low"], previous["low"]) <= TWEEZER_TOLERANCE_PERCENT:
            patterns.append("tweezer_bottom_reversal")

    if setup == "up" and previous["direction"] == "green" and current["direction"] == "red":
        if body_engulfs(current, previous):
            patterns.append("bearish_engulfing")
        if current["close"] < previous_midpoint and current["close"] > previous["open"]:
            patterns.append("dark_cloud_cover")
        if body_inside_previous(current, candles[index - 1]) and current["body_ratio"] <= SMALL_BODY_MAX:
            patterns.append("bearish_harami")
        if price_distance_percent(current["high"], previous["high"]) <= TWEEZER_TOLERANCE_PERCENT:
            patterns.append("tweezer_top_reversal")

    if setup == "down" and previous["direction"] == "red" and current["direction"] == "green":
        if current["open"] > previous["open"] and current["low"] > previous["high"]:
            patterns.append("bullish_kicker")
    if setup == "up" and previous["direction"] == "green" and current["direction"] == "red":
        if current["open"] < previous["open"] and current["high"] < previous["low"]:
            patterns.append("bearish_kicker")
    return patterns


def three_candle_reversal_patterns(
    metrics_series: list[dict[str, Any]],
    index: int,
    setup: SetupTrend,
) -> list[str]:
    if index < 2:
        return []
    first = metrics_series[index - 2]
    middle = metrics_series[index - 1]
    current = metrics_series[index]
    patterns: list[str] = []
    first_midpoint = (first["open"] + first["close"]) / 2

    if (
        setup == "down"
        and first["direction"] == "red"
        and first["body_ratio"] >= LARGE_BODY_MIN
        and middle["body_ratio"] <= SMALL_BODY_MAX
        and current["direction"] == "green"
        and current["close"] > first_midpoint
    ):
        patterns.append("morning_star")
        if middle["body_ratio"] <= DOJI_BODY_MAX:
            patterns.append("morning_doji_star")
    if (
        setup == "up"
        and first["direction"] == "green"
        and first["body_ratio"] >= LARGE_BODY_MIN
        and middle["body_ratio"] <= SMALL_BODY_MAX
        and current["direction"] == "red"
        and current["close"] < first_midpoint
    ):
        patterns.append("evening_star")
        if middle["body_ratio"] <= DOJI_BODY_MAX:
            patterns.append("evening_doji_star")

    last_three = metrics_series[index - 2 : index + 1]
    if setup == "down" and all(item["direction"] == "green" and item["body_ratio"] >= 0.45 for item in last_three):
        if last_three[0]["close"] < last_three[1]["close"] < last_three[2]["close"]:
            patterns.append("three_white_soldiers")
    if setup == "up" and all(item["direction"] == "red" and item["body_ratio"] >= 0.45 for item in last_three):
        if last_three[0]["close"] > last_three[1]["close"] > last_three[2]["close"]:
            patterns.append("three_black_crows")
    return patterns


def body_inside_previous(metrics: dict[str, Any], previous_raw: dict[str, Any]) -> bool:
    current_low = min(metrics["open"], metrics["close"])
    current_high = max(metrics["open"], metrics["close"])
    previous_low = min(float(previous_raw["open"]), float(previous_raw["close"]))
    previous_high = max(float(previous_raw["open"]), float(previous_raw["close"]))
    tolerance = max(previous_high * (BODY_INSIDE_TOLERANCE_PERCENT / 100), 0.01)
    return current_low >= previous_low - tolerance and current_high <= previous_high + tolerance


def body_engulfs(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    return body_low(current) <= body_low(previous) and body_high(current) >= body_high(previous)


def body_low(metrics: dict[str, Any]) -> float:
    return min(metrics["open"], metrics["close"])


def body_high(metrics: dict[str, Any]) -> float:
    return max(metrics["open"], metrics["close"])


def price_distance_percent(left: float, right: float) -> float:
    reference = (abs(left) + abs(right)) / 2
    if reference <= 0:
        return 0.0
    return abs(left - right) / reference * 100


def price_change_percent(base: float, value: float) -> float:
    if base <= 0:
        return 0.0
    return ((value - base) / base) * 100


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


def reversal_bias(patterns: list[str]) -> ReversalBias:
    bullish = any(pattern in BULLISH_REVERSAL_PATTERNS for pattern in patterns)
    bearish = any(pattern in BEARISH_REVERSAL_PATTERNS for pattern in patterns)
    if bullish and bearish:
        return "mixed"
    if bullish:
        return "bullish"
    if bearish:
        return "bearish"
    return "none"


def reversal_score(patterns: list[str]) -> float:
    return float(min(100, sum(REVERSAL_PATTERN_WEIGHTS.get(pattern, 0) for pattern in set(patterns))))


BULLISH_REVERSAL_PATTERNS = {
    "hammer",
    "inverted_hammer",
    "bullish_doji_reversal_watch",
    "bullish_engulfing",
    "piercing_pattern",
    "bullish_harami",
    "tweezer_bottom_reversal",
    "bullish_kicker",
    "morning_star",
    "morning_doji_star",
    "three_white_soldiers",
}

BEARISH_REVERSAL_PATTERNS = {
    "hanging_man",
    "shooting_star",
    "bearish_doji_reversal_watch",
    "bearish_engulfing",
    "dark_cloud_cover",
    "bearish_harami",
    "tweezer_top_reversal",
    "bearish_kicker",
    "evening_star",
    "evening_doji_star",
    "three_black_crows",
}

REVERSAL_PATTERN_WEIGHTS = {
    "hammer": 45,
    "inverted_hammer": 35,
    "hanging_man": 35,
    "shooting_star": 45,
    "bullish_doji_reversal_watch": 25,
    "bearish_doji_reversal_watch": 25,
    "bullish_engulfing": 60,
    "bearish_engulfing": 60,
    "piercing_pattern": 45,
    "dark_cloud_cover": 45,
    "bullish_harami": 35,
    "bearish_harami": 35,
    "tweezer_bottom_reversal": 35,
    "tweezer_top_reversal": 35,
    "bullish_kicker": 70,
    "bearish_kicker": 70,
    "morning_star": 70,
    "morning_doji_star": 80,
    "evening_star": 70,
    "evening_doji_star": 80,
    "three_white_soldiers": 70,
    "three_black_crows": 70,
}


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
        "latest_reversal_patterns": items[-1]["reversal_patterns"] if items else [],
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
        "latest_reversal_patterns": [],
        "pattern_counts": {},
        "items": [],
    }
