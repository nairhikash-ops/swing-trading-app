from typing import Any, Literal

from app.candlesticks import classify_candles
from app.regime import classify_regime_series
from app.store import TokenStore
from app.support_resistance import (
    DEFAULT_PIVOT_LEFT,
    DEFAULT_PIVOT_RIGHT,
    SupportResistanceStore,
    detect_support_resistance,
)


OpportunityStage = Literal[
    "downtrend_only",
    "near_support",
    "indecision_near_support",
    "support_reclaim",
    "bullish_reversal_watch",
    "confirmed_reversal",
    "entry_watch",
    "ignore",
]
SuggestedNextAction = Literal[
    "watch_only",
    "wait_for_confirmation",
    "wait_for_breakout",
    "wait_for_pullback",
    "ready_for_drishti_review",
    "ignore",
]

STRONG_BULLISH_REVERSAL_SCORE = 45.0
BEARISH_REVERSAL_BLOCKERS = {
    "shooting_star",
    "dark_cloud_cover",
    "bearish_harami",
    "bearish_engulfing",
    "evening_star",
    "evening_doji_star",
    "tweezer_top_reversal",
}


class ReversalOpportunityService:
    def __init__(self, token_store: TokenStore, store: SupportResistanceStore | None = None) -> None:
        self.store = store or SupportResistanceStore(token_store)

    def scan_nifty_500(
        self,
        limit: int = 500,
        include_watch_only: bool = True,
        min_score: float = 0,
        min_entry_quality_score: float = 0,
    ) -> list[dict[str, Any]]:
        response_limit = min(max(limit, 1), 500)
        items: list[dict[str, Any]] = []
        for instrument in self.store.nifty_500_instruments(limit=500):
            candles = self.store.candles_for_instrument(int(instrument["id"]), limit=365)
            item = classify_reversal_opportunity(instrument, candles)
            if item is None:
                continue
            if not include_watch_only and item["suggested_next_action"] == "watch_only":
                continue
            if float(item["opportunity_score"]) < min_score:
                continue
            if float(item["entry_quality_score"]) < min_entry_quality_score:
                continue
            items.append(item)
        return sorted(
            items,
            key=lambda item: (
                -float(item["entry_quality_score"]),
                -float(item["opportunity_score"]),
                stage_rank(str(item["opportunity_stage"])),
                str(item["symbol"]),
            ),
        )[:response_limit]


def classify_reversal_opportunity(
    instrument: dict[str, Any],
    candles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(candles) < max(DEFAULT_PIVOT_LEFT + DEFAULT_PIVOT_RIGHT + 1, 5):
        return None

    regime_rows = classify_regime_series(candles)
    if not regime_rows:
        return None
    latest_regime = regime_rows[-1]
    if latest_regime["regime"] != "DOWNTREND":
        return None

    support_report = detect_support_resistance(candles)
    candle_items = classify_candles(candles)
    return build_opportunity_item(instrument, candles, latest_regime, support_report, candle_items)


def build_opportunity_item(
    instrument: dict[str, Any],
    candles: list[dict[str, Any]],
    latest_regime: dict[str, Any],
    support_report: dict[str, Any],
    candle_items: list[dict[str, Any]],
) -> dict[str, Any]:
    current = candles[-1]
    latest_candle = candle_items[-1] if candle_items else {}
    sources = recent_signal_sources(candles, candle_items)
    indecision_score = float(sources["indecision_score"])
    bullish_reversal_score = float(sources["bullish_reversal_score"])
    latest_bearish = latest_has_bearish_evidence(latest_candle)
    reversal_bias = "bearish" if latest_bearish else latest_reversal_bias(latest_candle, sources["recent_items"])
    confirmed, confirmation_source = bullish_confirmation(
        candles,
        candle_items,
        bullish_reversal_score,
        latest_bearish=latest_bearish,
    )

    near_support = bool(support_report.get("near_support"))
    inside_support_zone = bool(support_report.get("inside_support_zone"))
    support_reclaim = bool(support_report.get("support_reclaim"))
    latest_close = float(current["close"])
    support_quality = support_quality_fields(support_report, latest_close, latest_bearish)
    quality_support_reclaim = bool(support_quality["quality_support_reclaim"])
    stage = classify_stage(
        near_support=near_support,
        inside_support_zone=inside_support_zone,
        support_reclaim=support_reclaim,
        indecision_score=indecision_score,
        reversal_bias=reversal_bias,
        reversal_score=bullish_reversal_score,
        confirmed=confirmed,
        latest_bearish=latest_bearish,
    )
    score = opportunity_score(
        near_support=near_support,
        inside_support_zone=inside_support_zone,
        support_reclaim=support_reclaim,
        quality_support_reclaim=quality_support_reclaim,
        indecision_score=indecision_score,
        reversal_score=bullish_reversal_score if reversal_bias in ("bullish", "mixed") else 0,
        confirmed=confirmed,
        latest_bearish=latest_bearish,
        support_strength=support_quality["support_strength"],
        support_touch_count=support_quality["support_touch_count"],
        support_recency_sessions=support_quality["support_recency_sessions"],
    )
    entry_score = entry_quality_score(
        candles=candles,
        reversal_bias=reversal_bias,
        reversal_score=bullish_reversal_score,
        confirmed=confirmed,
        latest_bearish=latest_bearish,
        near_support=near_support,
        inside_support_zone=inside_support_zone,
        quality_support_reclaim=quality_support_reclaim,
        support_strength=support_quality["support_strength"],
        support_touch_count=support_quality["support_touch_count"],
        support_recency_sessions=support_quality["support_recency_sessions"],
    )
    return {
        "symbol": instrument.get("underlying_symbol") or instrument.get("symbol") or "",
        "company_name": instrument.get("company_name") or instrument.get("display_name") or "",
        "industry": instrument.get("industry") or "",
        "isin": instrument.get("isin") or "",
        "security_id": instrument.get("security_id") or "",
        "latest_date": current["trading_date"],
        "latest_close": float(current["close"]),
        "regime": latest_regime["regime"],
        "regime_confidence": float(latest_regime.get("confidence") or 0),
        "opportunity_stage": stage,
        "opportunity_score": score,
        "entry_quality_score": entry_score,
        "reasons": opportunity_reasons(
            support_report=support_report,
            latest_patterns=list(latest_candle.get("patterns") or []),
            latest_reversal_patterns=list(latest_candle.get("reversal_patterns") or []),
            indecision_score=indecision_score,
            reversal_bias=reversal_bias,
            reversal_score=bullish_reversal_score,
            confirmed=confirmed,
            latest_bearish=latest_bearish,
            quality_support_reclaim=quality_support_reclaim,
            support_quality=support_quality,
        ),
        "near_support": near_support,
        "inside_support_zone": inside_support_zone,
        "support_reclaim": support_reclaim,
        "quality_support_reclaim": quality_support_reclaim,
        "support_distance_percent": support_report.get("support_distance_percent"),
        "nearest_support": support_report.get("nearest_support"),
        "support_strength": support_quality["support_strength"],
        "support_touch_count": support_quality["support_touch_count"],
        "support_recency_sessions": support_quality["support_recency_sessions"],
        "latest_patterns": list(latest_candle.get("patterns") or []),
        "latest_reversal_patterns": list(latest_candle.get("reversal_patterns") or []),
        "recent_patterns": sources["recent_patterns"],
        "recent_reversal_patterns": sources["recent_reversal_patterns"],
        "recent_indecision_date": sources["recent_indecision_date"],
        "recent_reversal_date": sources["recent_reversal_date"],
        "bullish_reversal_source_date": sources["bullish_reversal_source_date"],
        "confirmation_source": confirmation_source,
        "indecision_score": round(indecision_score, 2),
        "reversal_score": round(bullish_reversal_score, 2),
        "reversal_bias": reversal_bias,
        "suggested_next_action": suggested_next_action(stage, entry_score, latest_bearish),
    }


def classify_stage(
    *,
    near_support: bool,
    inside_support_zone: bool,
    support_reclaim: bool,
    indecision_score: float,
    reversal_bias: str,
    reversal_score: float,
    confirmed: bool,
    latest_bearish: bool,
) -> OpportunityStage:
    if confirmed and not latest_bearish:
        return "confirmed_reversal"
    if not latest_bearish and reversal_bias in ("bullish", "mixed") and reversal_score >= 35:
        return "bullish_reversal_watch"
    if support_reclaim:
        return "support_reclaim"
    if (near_support or inside_support_zone) and indecision_score > 0:
        return "indecision_near_support"
    if near_support or inside_support_zone:
        return "near_support"
    return "downtrend_only"


def opportunity_score(
    *,
    near_support: bool,
    inside_support_zone: bool,
    support_reclaim: bool,
    quality_support_reclaim: bool,
    indecision_score: float,
    reversal_score: float,
    confirmed: bool,
    latest_bearish: bool,
    support_strength: float | None,
    support_touch_count: int | None,
    support_recency_sessions: int | None,
) -> float:
    score = 20.0
    if near_support:
        score += 15
    if inside_support_zone:
        score += 20
    if support_reclaim:
        score += 15
    if quality_support_reclaim:
        score += 10
    score += min(max(indecision_score, 0), 100) * 0.15
    score += min(max(reversal_score, 0), 100) * 0.25
    if confirmed:
        score += 15
    if latest_bearish:
        score -= 25
    if support_strength is not None and support_strength < 40:
        score -= 10
    if support_touch_count == 1:
        score -= 8
    if support_recency_sessions is not None and support_recency_sessions > 90:
        score -= 8
    if latest_bearish:
        score = min(score, 65)
    return round(min(max(score, 0), 100), 2)


def entry_quality_score(
    *,
    candles: list[dict[str, Any]],
    reversal_bias: str,
    reversal_score: float,
    confirmed: bool,
    latest_bearish: bool,
    near_support: bool,
    inside_support_zone: bool,
    quality_support_reclaim: bool,
    support_strength: float | None,
    support_touch_count: int | None,
    support_recency_sessions: int | None,
) -> float:
    score = 0.0
    close_above_prior_high = len(candles) >= 2 and float(candles[-1]["close"]) > float(candles[-2]["high"])
    if confirmed and not latest_bearish:
        score += 30
    if reversal_bias in ("bullish", "mixed") and not latest_bearish:
        score += 15
    if close_above_prior_high and not latest_bearish:
        score += 10
    if quality_support_reclaim:
        score += 20
    if inside_support_zone:
        score += 10
    elif near_support:
        score += 5
    if support_strength is not None:
        if support_strength >= 70:
            score += 15
        elif support_strength >= 40:
            score += 8
        else:
            score -= 20
    if support_touch_count == 1:
        score -= 15
    if support_recency_sessions is not None and support_recency_sessions > 90:
        score -= 15
    if not latest_bearish:
        score += 10
    else:
        score -= 35
    if reversal_score <= 0 and not close_above_prior_high:
        score = min(score, 55)
    if support_strength is not None and support_strength < 40:
        score = min(score, 55)
    if support_touch_count == 1:
        score = min(score, 50)
    if support_recency_sessions is not None and support_recency_sessions > 90:
        score = min(score, 55)
    if latest_bearish:
        score = min(score, 30)
    return round(min(max(score, 0), 100), 2)


def support_quality_fields(
    support_report: dict[str, Any],
    latest_close: float,
    latest_bearish: bool,
) -> dict[str, Any]:
    nearest_support = support_report.get("nearest_support") or {}
    support_strength = optional_float(nearest_support.get("strength"))
    support_touch_count = optional_int(nearest_support.get("touch_count"))
    support_recency_sessions = optional_int(nearest_support.get("recency_sessions"))
    mid_price = optional_float(nearest_support.get("mid_price"))
    close_reclaimed_mid = mid_price is not None and latest_close > mid_price
    quality_support_reclaim = (
        bool(support_report.get("support_reclaim"))
        and (bool(support_report.get("inside_support_zone")) or close_reclaimed_mid)
        and not latest_bearish
    )
    return {
        "quality_support_reclaim": quality_support_reclaim,
        "support_strength": support_strength,
        "support_touch_count": support_touch_count,
        "support_recency_sessions": support_recency_sessions,
    }


def recent_signal_sources(candles: list[dict[str, Any]], candle_items: list[dict[str, Any]]) -> dict[str, Any]:
    start = max(0, len(candle_items) - 3)
    recent_pairs = [(index, candle_items[index]) for index in range(start, len(candle_items))]
    recent_patterns = sorted(
        {
            pattern
            for _, item in recent_pairs
            for pattern in list(item.get("patterns") or [])
        }
    )
    recent_reversal_patterns = sorted(
        {
            pattern
            for _, item in recent_pairs
            for pattern in list(item.get("reversal_patterns") or [])
        }
    )
    indecision_source = max(
        recent_pairs,
        key=lambda pair: float(pair[1].get("indecision_score") or 0),
        default=None,
    )
    reversal_source = max(
        recent_pairs,
        key=lambda pair: float(pair[1].get("reversal_score") or 0),
        default=None,
    )
    bullish_source = max(
        (
            pair
            for pair in recent_pairs
            if pair[1].get("reversal_bias") in ("bullish", "mixed")
        ),
        key=lambda pair: float(pair[1].get("reversal_score") or 0),
        default=None,
    )
    indecision_score = float(indecision_source[1].get("indecision_score") or 0) if indecision_source else 0.0
    reversal_score = float(reversal_source[1].get("reversal_score") or 0) if reversal_source else 0.0
    bullish_reversal_score = float(bullish_source[1].get("reversal_score") or 0) if bullish_source else 0.0
    return {
        "recent_items": [item for _, item in recent_pairs],
        "recent_patterns": recent_patterns,
        "recent_reversal_patterns": recent_reversal_patterns,
        "indecision_score": indecision_score,
        "bullish_reversal_score": bullish_reversal_score,
        "recent_indecision_date": source_date(candles, indecision_source) if indecision_score > 0 else None,
        "recent_reversal_date": source_date(candles, reversal_source) if reversal_score > 0 else None,
        "bullish_reversal_source_date": (
            source_date(candles, bullish_source) if bullish_reversal_score > 0 else None
        ),
    }


def latest_has_bearish_evidence(latest_candle: dict[str, Any]) -> bool:
    if latest_candle.get("reversal_bias") == "bearish":
        return True
    latest_reversal_patterns = set(latest_candle.get("reversal_patterns") or [])
    return bool(latest_reversal_patterns & BEARISH_REVERSAL_BLOCKERS)


def source_date(candles: list[dict[str, Any]], source: tuple[int, dict[str, Any]] | None) -> str | None:
    if source is None:
        return None
    index, item = source
    return str(item.get("trading_date") or candles[index]["trading_date"])


def latest_reversal_bias(latest_candle: dict[str, Any], recent_candles: list[dict[str, Any]]) -> str:
    latest_bias = str(latest_candle.get("reversal_bias") or "none")
    if latest_bias in ("bullish", "mixed"):
        return latest_bias
    if latest_bias == "bearish":
        return "bearish"
    if any(
        item.get("reversal_bias") in ("bullish", "mixed")
        and float(item.get("reversal_score") or 0) > 0
        for item in recent_candles
    ):
        return "bullish"
    return latest_bias if latest_bias in ("bearish", "none") else "none"


def bullish_confirmation(
    candles: list[dict[str, Any]],
    candle_items: list[dict[str, Any]],
    bullish_reversal_score: float,
    latest_bearish: bool = False,
) -> tuple[bool, str | None]:
    if latest_bearish or bullish_reversal_score < STRONG_BULLISH_REVERSAL_SCORE or len(candles) < 2:
        return False, None
    latest_close = float(candles[-1]["close"])
    if latest_close > float(candles[-2]["high"]):
        return True, "latest_close_above_prior_high"
    start = max(0, len(candle_items) - 3)
    for index in range(start, len(candle_items) - 1):
        item = candle_items[index]
        if item.get("reversal_bias") not in ("bullish", "mixed"):
            continue
        if float(item.get("reversal_score") or 0) < STRONG_BULLISH_REVERSAL_SCORE:
            continue
        if latest_close > float(candles[index]["high"]):
            return True, "latest_close_above_bullish_reversal_high"
    return False, None


def opportunity_reasons(
    *,
    support_report: dict[str, Any],
    latest_patterns: list[str],
    latest_reversal_patterns: list[str],
    indecision_score: float,
    reversal_bias: str,
    reversal_score: float,
    confirmed: bool,
    latest_bearish: bool,
    quality_support_reclaim: bool,
    support_quality: dict[str, Any],
) -> list[str]:
    reasons = ["regime_downtrend"]
    if support_report.get("inside_support_zone"):
        reasons.append("inside_support_zone")
    elif support_report.get("near_support"):
        distance = support_report.get("support_distance_percent")
        reasons.append(f"near_support_{distance}%")
    if support_report.get("support_reclaim"):
        reasons.append("support_reclaim")
    if quality_support_reclaim:
        reasons.append("quality_support_reclaim")
    if latest_bearish:
        reasons.append("latest_bearish_reversal_evidence")
    if support_quality.get("support_strength") is not None and float(support_quality["support_strength"]) < 40:
        reasons.append("weak_support_strength")
    if support_quality.get("support_touch_count") == 1:
        reasons.append("single_touch_support")
    if (
        support_quality.get("support_recency_sessions") is not None
        and int(support_quality["support_recency_sessions"]) > 90
    ):
        reasons.append("old_support_zone")
    if indecision_score > 0:
        reasons.append("recent_indecision")
    if latest_patterns:
        reasons.append("latest_patterns:" + ",".join(latest_patterns))
    if reversal_bias in ("bullish", "mixed") and reversal_score > 0:
        reasons.append("bullish_reversal_watch")
    if latest_reversal_patterns:
        reasons.append("latest_reversal_patterns:" + ",".join(latest_reversal_patterns))
    if confirmed:
        reasons.append("latest_close_confirmed_above_reversal_high")
    if len(reasons) == 1:
        reasons.append("no_support_or_candle_clue")
    return reasons


def suggested_next_action(stage: str, entry_quality: float = 0, latest_bearish: bool = False) -> SuggestedNextAction:
    if latest_bearish and entry_quality < 30:
        return "ignore"
    if latest_bearish:
        return "wait_for_confirmation"
    if stage == "downtrend_only":
        return "watch_only"
    if stage in ("near_support", "indecision_near_support", "support_reclaim"):
        return "wait_for_confirmation"
    if stage == "bullish_reversal_watch":
        return "wait_for_breakout"
    if stage == "confirmed_reversal":
        if entry_quality < 55:
            return "wait_for_confirmation"
        return "ready_for_drishti_review"
    if stage == "entry_watch":
        return "wait_for_pullback"
    return "ignore"


def stage_rank(stage: str) -> int:
    ranks = {
        "confirmed_reversal": 0,
        "entry_watch": 1,
        "bullish_reversal_watch": 2,
        "support_reclaim": 3,
        "indecision_near_support": 4,
        "near_support": 5,
        "downtrend_only": 6,
        "ignore": 7,
    }
    return ranks.get(stage, 99)


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
