from typing import Any

from app.store import TokenStore
from app.timezone import now_utc


DEFAULT_PIVOT_LEFT = 2
DEFAULT_PIVOT_RIGHT = 2
DEFAULT_CLUSTER_TOLERANCE_PERCENT = 1.5
DEFAULT_ZONE_PERCENT = 1.5
DEFAULT_ZONE_ATR_MULTIPLIER = 0.5


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

    def candles_for_instrument(self, instrument_id: int, limit: int = 365) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT trading_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = ?
                ORDER BY trading_date DESC
                LIMIT ?
                """,
                (instrument_id, min(max(limit, 20), 365)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def nifty_500_instruments(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    i.id,
                    i.security_id,
                    i.isin,
                    i.display_name,
                    i.underlying_symbol,
                    i.series,
                    c.company_name,
                    c.industry,
                    c.symbol
                FROM index_constituents c
                JOIN instruments i ON i.isin = c.isin
                WHERE c.index_name = 'NIFTY_500'
                  AND c.active = 1
                  AND i.active = 1
                  AND i.exchange_id = 'NSE'
                  AND i.segment = 'E'
                  AND i.instrument = 'EQUITY'
                ORDER BY c.symbol, CASE WHEN i.series = 'EQ' THEN 0 ELSE 1 END, i.id
                LIMIT ?
                """,
                (min(max(limit * 3, limit), 2000),),
            ).fetchall()
        instruments: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            key = str(row["isin"] or row["symbol"])
            if key in seen:
                continue
            seen.add(key)
            instruments.append(dict(row))
            if len(instruments) >= limit:
                break
        return instruments


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

    def nifty_500_near_support(self, limit: int = 500, max_distance_percent: float = 2.0) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for instrument in self.store.nifty_500_instruments(limit=limit):
            candles = self.store.candles_for_instrument(int(instrument["id"]))
            if len(candles) < DEFAULT_PIVOT_LEFT + DEFAULT_PIVOT_RIGHT + 1:
                continue
            report = detect_support_resistance(candles)
            nearest_support = report["nearest_support"]
            if nearest_support is None:
                continue
            inside_support_zone = bool(report["inside_support_zone"])
            support_distance_percent = float(report["support_distance_percent"])
            near_support = inside_support_zone or support_distance_percent <= max_distance_percent
            if not near_support:
                continue
            support_zone_state = "inside_support_zone" if inside_support_zone else "near_support"
            items.append(
                {
                    "symbol": instrument["underlying_symbol"] or instrument["symbol"],
                    "company_name": instrument["company_name"],
                    "industry": instrument["industry"],
                    "isin": instrument["isin"],
                    "security_id": instrument["security_id"],
                    "latest_date": report["latest_date"],
                    "latest_close": report["latest_close"],
                    "nearest_support": nearest_support,
                    "support_distance_percent": support_distance_percent,
                    "inside_support_zone": inside_support_zone,
                    "near_support": near_support,
                    "support_zone_state": support_zone_state,
                    "support_reclaim": report["support_reclaim"],
                    "broke_below_support_recently": report["broke_below_support_recently"],
                    "reclaimed_support_on_latest_close": report["reclaimed_support_on_latest_close"],
                }
            )
        return sorted(
            items,
            key=lambda item: (
                0 if item["inside_support_zone"] else 1,
                float(item["support_distance_percent"] or 0),
                str(item["symbol"]),
            ),
        )


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
    atr_14 = average_true_range(candles, 14)
    pivots = find_price_pivots(candles, pivot_left=pivot_left, pivot_right=pivot_right)
    pivots.extend(recent_extreme_pivots(candles))
    clusters = cluster_pivots(pivots, cluster_tolerance_percent=cluster_tolerance_percent)
    levels = [level_from_cluster(cluster, current_close, len(candles), atr_14) for cluster in clusters]
    levels = [level for level in levels if level["mid_price"] > 0]
    supports = sorted(
        [level for level in levels if level["role"] == "support"],
        key=lambda item: (item["distance_percent"], -item["strength"]),
    )[:max_levels]
    resistances = sorted(
        [level for level in levels if level["role"] == "resistance"],
        key=lambda item: (item["distance_percent"], -item["strength"]),
    )[:max_levels]
    support_state = support_state_fields(supports[0] if supports else None, current_close, candles)
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
        "atr_14": atr_14,
        "pivot_left": pivot_left,
        "pivot_right": pivot_right,
        "cluster_tolerance_percent": cluster_tolerance_percent,
        "zone_percent": DEFAULT_ZONE_PERCENT,
        "zone_atr_multiplier": DEFAULT_ZONE_ATR_MULTIPLIER,
        "nearest_support": supports[0] if supports else None,
        "nearest_resistance": resistances[0] if resistances else None,
        "supports": supports,
        "resistances": resistances,
        **support_state,
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
            pivots.append(pivot_dict(candles, index, low, "swing_low", pivot_right=pivot_right))
        if high >= max(left_highs + right_highs):
            pivots.append(pivot_dict(candles, index, high, "swing_high", pivot_right=pivot_right))
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
        pivots.append(pivot_dict(candles, slice_start + lowest[0], float(lowest[1]["low"]), f"low_{window}d"))
        pivots.append(pivot_dict(candles, slice_start + highest[0], float(highest[1]["high"]), f"high_{window}d"))
    return pivots


def pivot_dict(
    candles: list[dict[str, Any]],
    index: int,
    price: float,
    source: str,
    pivot_right: int = 0,
) -> dict[str, Any]:
    candle = candles[index]
    # Recent 45/90-day extremes are rolling-window facts, so their "confirmed" date is the
    # extreme candle itself rather than a delayed swing-pivot confirmation.
    confirmed_index = min(index + pivot_right, len(candles) - 1)
    return {
        "price": price,
        "date": candle["trading_date"],
        "index": index,
        "confirmed_index": confirmed_index,
        "confirmed_date": candles[confirmed_index]["trading_date"],
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


def level_from_cluster(
    cluster: dict[str, Any],
    current_close: float,
    candle_count: int,
    atr_14: float,
) -> dict[str, Any]:
    touches = cluster["touches"]
    latest_touch = max(touches, key=lambda item: item["index"])
    first_touch = min(touches, key=lambda item: item["index"])
    mid_price = float(cluster["price"])
    zone_width = max(mid_price * (DEFAULT_ZONE_PERCENT / 100), atr_14 * DEFAULT_ZONE_ATR_MULTIPLIER)
    zone_low = max(0, mid_price - zone_width)
    zone_high = mid_price + zone_width
    inside_zone = zone_low <= current_close <= zone_high
    role = "support" if mid_price <= current_close else "resistance"
    recency_sessions = max(0, candle_count - 1 - int(latest_touch["index"]))
    if inside_zone or current_close <= 0:
        distance = 0
    elif role == "support":
        distance = ((current_close - zone_high) / current_close) * 100
    else:
        distance = ((zone_low - current_close) / current_close) * 100
    return {
        "price": round(mid_price, 2),
        "mid_price": round(mid_price, 2),
        "zone_low": round(zone_low, 2),
        "zone_high": round(zone_high, 2),
        "zone_width": round(zone_width, 2),
        "role": role,
        "inside_zone": inside_zone,
        "touch_count": len(touches),
        "first_touch_date": first_touch["date"],
        "last_touch_date": latest_touch["date"],
        "recency_sessions": recency_sessions,
        "distance_percent": round(max(distance, 0), 2),
        "strength": support_resistance_strength(len(touches), recency_sessions),
        "sources": sorted({touch["source"] for touch in touches}),
        "touches": sorted(touches, key=lambda item: item["index"]),
    }


def support_state_fields(
    nearest_support: dict[str, Any] | None,
    current_close: float,
    candles: list[dict[str, Any]],
    max_near_distance_percent: float = 2.0,
) -> dict[str, Any]:
    if nearest_support is None:
        return {
            "near_support": False,
            "inside_support_zone": False,
            "support_distance_percent": None,
            "support_zone_state": "no_support",
            "support_reclaim": False,
            "broke_below_support_recently": False,
            "reclaimed_support_on_latest_close": False,
        }

    zone_low = float(nearest_support["zone_low"])
    inside_support_zone = bool(nearest_support["inside_zone"])
    support_distance_percent = float(nearest_support["distance_percent"])
    near_support = inside_support_zone or support_distance_percent <= max_near_distance_percent
    if current_close < zone_low:
        support_zone_state = "below_support_broken"
    elif inside_support_zone:
        support_zone_state = "inside_support_zone"
    elif near_support:
        support_zone_state = "near_support"
    else:
        support_zone_state = "above_support"

    recent_candles = candles[-5:]
    broke_below_support_recently = any(float(candle["low"]) < zone_low for candle in recent_candles)
    reclaimed_support_on_latest_close = current_close >= zone_low
    support_reclaim = broke_below_support_recently and reclaimed_support_on_latest_close
    return {
        "near_support": near_support,
        "inside_support_zone": inside_support_zone,
        "support_distance_percent": support_distance_percent,
        "support_zone_state": support_zone_state,
        "support_reclaim": support_reclaim,
        "broke_below_support_recently": broke_below_support_recently,
        "reclaimed_support_on_latest_close": reclaimed_support_on_latest_close,
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


def average_true_range(candles: list[dict[str, Any]], period: int) -> float:
    if len(candles) < 2:
        return 0.0
    ranges: list[float] = []
    start = max(1, len(candles) - period)
    for index in range(start, len(candles)):
        high = float(candles[index]["high"])
        low = float(candles[index]["low"])
        previous_close = float(candles[index - 1]["close"])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return sum(ranges) / len(ranges) if ranges else 0.0


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
        "atr_14": 0,
        "pivot_left": DEFAULT_PIVOT_LEFT,
        "pivot_right": DEFAULT_PIVOT_RIGHT,
        "cluster_tolerance_percent": DEFAULT_CLUSTER_TOLERANCE_PERCENT,
        "zone_percent": DEFAULT_ZONE_PERCENT,
        "zone_atr_multiplier": DEFAULT_ZONE_ATR_MULTIPLIER,
        "nearest_support": None,
        "nearest_resistance": None,
        "supports": [],
        "resistances": [],
        "near_support": False,
        "inside_support_zone": False,
        "support_distance_percent": None,
        "support_zone_state": "no_support",
        "support_reclaim": False,
        "broke_below_support_recently": False,
        "reclaimed_support_on_latest_close": False,
    }
