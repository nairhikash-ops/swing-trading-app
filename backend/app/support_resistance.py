from typing import Any

from app.store import TokenStore
from app.timezone import now_utc


DEFAULT_PIVOT_LEFT = 2
DEFAULT_PIVOT_RIGHT = 2
DEFAULT_CLUSTER_TOLERANCE_PERCENT = 1.5


class SupportResistanceStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store

    def _connect(self):
        return self.token_store._connect()

    def candles_for_symbol(self, symbol: str, limit: int = 365) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
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
                (instrument["id"], min(max(limit, 20), 365)),
            ).fetchall()
        return dict(instrument), [dict(row) for row in reversed(rows)]


class SupportResistanceService:
    def __init__(self, token_store: TokenStore, store: SupportResistanceStore | None = None) -> None:
        self.store = store or SupportResistanceStore(token_store)

    def report_for_symbol(self, symbol: str, limit: int = 365) -> dict[str, Any]:
        instrument, candles = self.store.candles_for_symbol(symbol, limit=limit)
        if instrument is None:
            return empty_support_resistance_report(symbol, "instrument_not_found")
        if len(candles) < DEFAULT_PIVOT_LEFT + DEFAULT_PIVOT_RIGHT + 1:
            return empty_support_resistance_report(symbol, "not_enough_candles")
        report = detect_support_resistance(candles)
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


def detect_support_resistance(
    candles: list[dict[str, Any]],
    pivot_left: int = DEFAULT_PIVOT_LEFT,
    pivot_right: int = DEFAULT_PIVOT_RIGHT,
    cluster_tolerance_percent: float = DEFAULT_CLUSTER_TOLERANCE_PERCENT,
    max_levels: int = 8,
) -> dict[str, Any]:
    if not candles:
        return empty_support_resistance_report("", "not_enough_candles")

    current = candles[-1]
    current_close = float(current["close"])
    pivots = find_price_pivots(candles, pivot_left=pivot_left, pivot_right=pivot_right)
    pivots.extend(recent_extreme_pivots(candles))
    clusters = cluster_pivots(pivots, cluster_tolerance_percent=cluster_tolerance_percent)
    levels = [level_from_cluster(cluster, current_close, len(candles)) for cluster in clusters]
    levels = [level for level in levels if level["price"] > 0]
    supports = sorted(
        [level for level in levels if level["role"] == "support"],
        key=lambda item: (item["distance_percent"], -item["strength"]),
    )[:max_levels]
    resistances = sorted(
        [level for level in levels if level["role"] == "resistance"],
        key=lambda item: (item["distance_percent"], -item["strength"]),
    )[:max_levels]
    return {
        "symbol": "",
        "instrument_id": None,
        "security_id": "",
        "isin": "",
        "display_name": "",
        "status": "ok",
        "generated_at": now_utc().isoformat(),
        "candle_count": len(candles),
        "latest_date": current["trading_date"],
        "latest_close": current_close,
        "pivot_left": pivot_left,
        "pivot_right": pivot_right,
        "cluster_tolerance_percent": cluster_tolerance_percent,
        "nearest_support": supports[0] if supports else None,
        "nearest_resistance": resistances[0] if resistances else None,
        "supports": supports,
        "resistances": resistances,
    }


def find_price_pivots(candles: list[dict[str, Any]], pivot_left: int, pivot_right: int) -> list[dict[str, Any]]:
    highs = [float(candle["high"]) for candle in candles]
    lows = [float(candle["low"]) for candle in candles]
    pivots: list[dict[str, Any]] = []
    for index in range(pivot_left, len(candles) - pivot_right):
        left_lows = lows[index - pivot_left : index]
        right_lows = lows[index + 1 : index + pivot_right + 1]
        left_highs = highs[index - pivot_left : index]
        right_highs = highs[index + 1 : index + pivot_right + 1]
        low = lows[index]
        high = highs[index]
        if low <= min(left_lows + right_lows):
            pivots.append(pivot_dict(candles[index], index, low, "swing_low"))
        if high >= max(left_highs + right_highs):
            pivots.append(pivot_dict(candles[index], index, high, "swing_high"))
    return pivots


def recent_extreme_pivots(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pivots: list[dict[str, Any]] = []
    for window in (45, 90):
        if len(candles) < window:
            continue
        slice_start = len(candles) - window
        window_candles = candles[slice_start:]
        lowest = min(enumerate(window_candles), key=lambda item: float(item[1]["low"]))
        highest = max(enumerate(window_candles), key=lambda item: float(item[1]["high"]))
        pivots.append(pivot_dict(lowest[1], slice_start + lowest[0], float(lowest[1]["low"]), f"low_{window}d"))
        pivots.append(pivot_dict(highest[1], slice_start + highest[0], float(highest[1]["high"]), f"high_{window}d"))
    return pivots


def pivot_dict(candle: dict[str, Any], index: int, price: float, source: str) -> dict[str, Any]:
    return {
        "price": price,
        "date": candle["trading_date"],
        "index": index,
        "volume": float(candle.get("volume") or 0),
        "source": source,
    }


def cluster_pivots(pivots: list[dict[str, Any]], cluster_tolerance_percent: float) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for pivot in sorted(pivots, key=lambda item: item["price"]):
        matched = None
        for cluster in clusters:
            if price_distance_percent(cluster["price"], pivot["price"]) <= cluster_tolerance_percent:
                matched = cluster
                break
        if matched is None:
            clusters.append(
                {
                    "price": pivot["price"],
                    "touches": [pivot],
                }
            )
            continue
        matched["touches"].append(pivot)
        matched["price"] = weighted_average_price(matched["touches"])
    return clusters


def level_from_cluster(cluster: dict[str, Any], current_close: float, candle_count: int) -> dict[str, Any]:
    touches = cluster["touches"]
    latest_touch = max(touches, key=lambda item: item["index"])
    first_touch = min(touches, key=lambda item: item["index"])
    price = float(cluster["price"])
    role = "support" if price <= current_close else "resistance"
    recency_sessions = max(0, candle_count - 1 - int(latest_touch["index"]))
    distance = (
        ((current_close - price) / current_close) * 100
        if role == "support" and current_close > 0
        else ((price - current_close) / current_close) * 100 if current_close > 0 else 0
    )
    return {
        "price": round(price, 2),
        "role": role,
        "touch_count": len(touches),
        "first_touch_date": first_touch["date"],
        "last_touch_date": latest_touch["date"],
        "recency_sessions": recency_sessions,
        "distance_percent": round(max(distance, 0), 2),
        "strength": support_resistance_strength(len(touches), recency_sessions),
        "sources": sorted({touch["source"] for touch in touches}),
    }


def weighted_average_price(touches: list[dict[str, Any]]) -> float:
    weights = [max(float(touch.get("volume") or 0), 1.0) for touch in touches]
    return sum(float(touch["price"]) * weight for touch, weight in zip(touches, weights)) / sum(weights)


def price_distance_percent(left: float, right: float) -> float:
    reference = (abs(left) + abs(right)) / 2
    if reference <= 0:
        return 0.0
    return abs(left - right) / reference * 100


def support_resistance_strength(touch_count: int, recency_sessions: int) -> float:
    touch_score = min(touch_count * 18, 60)
    recency_score = max(0, 40 - recency_sessions)
    return round(min(100, touch_score + recency_score), 2)


def empty_support_resistance_report(symbol: str, status: str) -> dict[str, Any]:
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
        "latest_close": 0,
        "pivot_left": DEFAULT_PIVOT_LEFT,
        "pivot_right": DEFAULT_PIVOT_RIGHT,
        "cluster_tolerance_percent": DEFAULT_CLUSTER_TOLERANCE_PERCENT,
        "nearest_support": None,
        "nearest_resistance": None,
        "supports": [],
        "resistances": [],
    }
