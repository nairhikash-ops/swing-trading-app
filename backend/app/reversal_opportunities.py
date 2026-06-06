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


class ReversalOpportunityService:
    def __init__(self, token_store: TokenStore, store: SupportResistanceStore | None = None) -> None:
        self.store = store or SupportResistanceStore(token_store)

    def scan_nifty_500(
        self,
        limit: int = 500,
        include_watch_only: bool = True,
        min_score: float = 0,
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
            items.append(item)
        return sorted(
            items,
            key=lambda item: (
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
    recent_candles = candle_items[-3:] if len(candle_items) >= 3 else candle_items
    indecision_score = max((float(item.get("indecision_score") or 0) for item in recent_candles), default=0.0)
    bullish_reversal_score = max(
        (
            float(item.get("reversal_score") or 0)
            for item in recent_candles
            if item.get("reversal_bias") in ("bullish", "mixed")
        ),
        default=0.0,
    )
    reversal_bias = latest_reversal_bias(latest_candle, recent_candles)
    confirmed = reversal_bias != "bearish" and bullish_confirmation(candles, candle_items, bullish_reversal_score)

    near_support = bool(support_report.get("near_support"))
    inside_support_zone = bool(support_report.get("inside_support_zone"))
    support_reclaim = bool(support_report.get("support_reclaim"))
    stage = classify_stage(
        near_support=near_support,
        inside_support_zone=inside_support_zone,
        support_reclaim=support_reclaim,
        indecision_score=indecision_score,
        reversal_bias=reversal_bias,
        reversal_score=bullish_reversal_score,
        confirmed=confirmed,
    )
    score = opportunity_score(
        near_support=near_support,
        inside_support_zone=inside_support_zone,
        support_reclaim=support_reclaim,
        indecision_score=indecision_score,
        reversal_score=bullish_reversal_score if reversal_bias in ("bullish", "mixed") else 0,
        confirmed=confirmed,
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
        "reasons": opportunity_reasons(
            support_report=support_report,
            latest_patterns=list(latest_candle.get("patterns") or []),
            latest_reversal_patterns=list(latest_candle.get("reversal_patterns") or []),
            indecision_score=indecision_score,
            reversal_bias=reversal_bias,
            reversal_score=bullish_reversal_score,
            confirmed=confirmed,
        ),
        "near_support": near_support,
        "inside_support_zone": inside_support_zone,
        "support_reclaim": support_reclaim,
        "support_distance_percent": support_report.get("support_distance_percent"),
        "nearest_support": support_report.get("nearest_support"),
        "latest_patterns": list(latest_candle.get("patterns") or []),
        "latest_reversal_patterns": list(latest_candle.get("reversal_patterns") or []),
        "indecision_score": round(indecision_score, 2),
        "reversal_score": round(bullish_reversal_score, 2),
        "reversal_bias": reversal_bias,
        "suggested_next_action": suggested_next_action(stage),
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
) -> OpportunityStage:
    if confirmed:
        return "confirmed_reversal"
    if reversal_bias in ("bullish", "mixed") and reversal_score >= 35:
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
    indecision_score: float,
    reversal_score: float,
    confirmed: bool,
) -> float:
    score = 20.0
    if near_support:
        score += 15
    if inside_support_zone:
        score += 20
    if support_reclaim:
        score += 25
    score += min(max(indecision_score, 0), 100) * 0.15
    score += min(max(reversal_score, 0), 100) * 0.25
    if confirmed:
        score += 15
    return round(min(score, 100), 2)


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
) -> bool:
    if bullish_reversal_score < STRONG_BULLISH_REVERSAL_SCORE or len(candles) < 2:
        return False
    latest_close = float(candles[-1]["close"])
    if latest_close > float(candles[-2]["high"]):
        return True
    start = max(0, len(candle_items) - 3)
    for index in range(start, len(candle_items) - 1):
        item = candle_items[index]
        if item.get("reversal_bias") not in ("bullish", "mixed"):
            continue
        if float(item.get("reversal_score") or 0) < STRONG_BULLISH_REVERSAL_SCORE:
            continue
        if latest_close > float(candles[index]["high"]):
            return True
    return False


def opportunity_reasons(
    *,
    support_report: dict[str, Any],
    latest_patterns: list[str],
    latest_reversal_patterns: list[str],
    indecision_score: float,
    reversal_bias: str,
    reversal_score: float,
    confirmed: bool,
) -> list[str]:
    reasons = ["regime_downtrend"]
    if support_report.get("inside_support_zone"):
        reasons.append("inside_support_zone")
    elif support_report.get("near_support"):
        distance = support_report.get("support_distance_percent")
        reasons.append(f"near_support_{distance}%")
    if support_report.get("support_reclaim"):
        reasons.append("support_reclaim")
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


def suggested_next_action(stage: str) -> SuggestedNextAction:
    if stage == "downtrend_only":
        return "watch_only"
    if stage in ("near_support", "indecision_near_support", "support_reclaim"):
        return "wait_for_confirmation"
    if stage == "bullish_reversal_watch":
        return "wait_for_breakout"
    if stage == "confirmed_reversal":
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
