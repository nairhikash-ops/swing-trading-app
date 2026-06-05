from typing import Any

from app.ai_reviews import (
    AiReviewStore,
    GeminiReviewResult,
    build_review_context,
    enforce_review_safety,
)
from app.config import Settings
from app.learning import LearningStore
from app.store import TokenStore
from app.support_resistance import detect_support_resistance


LOCAL_DISCIPLINE_PROVIDER = "local"


class LocalDisciplineReviewService:
    def __init__(
        self,
        settings: Settings,
        token_store: TokenStore,
        store: AiReviewStore | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or AiReviewStore(token_store)
        self.learning_store = LearningStore(token_store)

    def latest_review_for_hit(self, hit_id: int) -> dict[str, Any] | None:
        return self.store.latest_for_hit(hit_id, provider=LOCAL_DISCIPLINE_PROVIDER)

    async def review_drishti_hit(self, hit_id: int) -> dict[str, Any]:
        hit = self.store.signal_hit(hit_id)
        if not hit:
            raise ValueError("Drishti signal hit was not found.")

        candles = self.store.candles_until_trigger(
            int(hit["instrument_id"]),
            hit["trigger_date"],
            self.settings.local_discipline_candle_limit,
        )
        if len(candles) < 45:
            raise ValueError("Not enough cached candles to create a local discipline review.")

        context = build_review_context(hit, candles)
        features = compute_discipline_features(hit, candles)
        context["ai_mode"] = {
            "provider": LOCAL_DISCIPLINE_PROVIDER,
            "model": self.settings.local_discipline_model,
            "grounding_enabled": False,
            "mode_label": "local-disciplined-rules",
        }
        context["discipline_features"] = features
        snapshot = self.learning_store.ensure_snapshot_for_hit(hit_id, context=context)
        result = enforce_review_safety(build_local_review_result(hit, features), hit)
        return self.store.insert_review(
            hit_id=hit_id,
            provider=LOCAL_DISCIPLINE_PROVIDER,
            model=self.settings.local_discipline_model,
            context=context,
            result=result,
            decision_snapshot_id=snapshot.get("id"),
        )


def compute_discipline_features(hit: dict[str, Any], candles: list[dict[str, Any]]) -> dict[str, Any]:
    opens = [float(candle["open"]) for candle in candles]
    highs = [float(candle["high"]) for candle in candles]
    lows = [float(candle["low"]) for candle in candles]
    closes = [float(candle["close"]) for candle in candles]
    volumes = [float(candle["volume"]) for candle in candles]
    trigger_open = float(hit["trigger_open"])
    trigger_high = float(hit["trigger_high"])
    trigger_low = float(hit["trigger_low"])
    trigger_close = float(hit["trigger_close"])
    anchor_low = float(hit["anchor_low"])
    anchor_high = float(hit["anchor_high"])
    anchor_close = float(hit["anchor_close"])
    candle_range = trigger_high - trigger_low
    atr_14 = average_true_range(highs, lows, closes, 14)
    sma_20 = average(closes[-20:])
    sma_50 = average(closes[-50:]) if len(closes) >= 50 else None
    sma_200 = average(closes[-200:]) if len(closes) >= 200 else None
    sma_20_prev = average(closes[-25:-5]) if len(closes) >= 25 else None
    sma_50_prev = average(closes[-55:-5]) if len(closes) >= 55 else None
    high_45 = max(highs[-45:])
    low_45 = min(lows[-45:])
    high_90 = max(highs[-90:]) if len(highs) >= 90 else high_45
    avg_volume_20 = average(volumes[-20:])
    support_resistance = detect_support_resistance(candles, max_levels=5)
    nearest_support = support_resistance["nearest_support"]
    nearest_resistance = support_resistance["nearest_resistance"]
    recent_return_5d = percent_change(closes[-6], closes[-1]) if len(closes) >= 6 else 0
    recent_return_20d = percent_change(closes[-21], closes[-1]) if len(closes) >= 21 else 0
    stop_loss = max(0.01, anchor_low - atr_14 * 0.25)
    entry_low = max(anchor_high, trigger_close - atr_14 * 0.35)
    entry_high = trigger_close * 1.01
    if entry_low > entry_high:
        entry_low = min(trigger_close, entry_high)
    risk_amount = entry_high - stop_loss
    risk_percent = (risk_amount / entry_high) * 100 if entry_high > 0 else 100
    target_1 = entry_high + risk_amount * 2
    target_2 = entry_high + risk_amount * 3
    rr_to_45d_high = (high_45 - entry_high) / risk_amount if risk_amount > 0 else 0
    return {
        "candle_count": len(candles),
        "trigger_close_strength": (trigger_close - trigger_low) / candle_range if candle_range > 0 else 0,
        "trigger_body_percent": abs(trigger_close - trigger_open) / candle_range if candle_range > 0 else 0,
        "gap_percent": percent_change(anchor_close, trigger_open),
        "atr_14": atr_14,
        "avg_volume_20": avg_volume_20,
        "trigger_volume_vs_20d_avg": float(hit["trigger_volume"]) / avg_volume_20 if avg_volume_20 > 0 else 0,
        "volume_ratio_1d": float(hit["volume_ratio_1d"]),
        "volume_vs_sma": float(hit["volume_vs_sma"]),
        "low_45": low_45,
        "high_45": high_45,
        "high_90": high_90,
        "nearest_support_price": nearest_support["price"] if nearest_support else None,
        "nearest_support_distance_percent": nearest_support["distance_percent"] if nearest_support else None,
        "nearest_resistance_price": nearest_resistance["price"] if nearest_resistance else None,
        "nearest_resistance_distance_percent": nearest_resistance["distance_percent"] if nearest_resistance else None,
        "support_resistance": support_resistance,
        "move_from_45d_low_percent": percent_change(low_45, trigger_close),
        "distance_to_45d_high_percent": percent_change(trigger_close, high_45),
        "distance_to_90d_high_percent": percent_change(trigger_close, high_90),
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "sma_20_slope_percent": percent_change(sma_20_prev, sma_20) if sma_20_prev else 0,
        "sma_50_slope_percent": percent_change(sma_50_prev, sma_50) if sma_50_prev and sma_50 else 0,
        "distance_to_sma_20_percent": percent_change(sma_20, trigger_close) if sma_20 else 0,
        "distance_to_sma_50_percent": percent_change(sma_50, trigger_close) if sma_50 else 0,
        "distance_to_sma_200_percent": percent_change(sma_200, trigger_close) if sma_200 else 0,
        "recent_return_5d_percent": recent_return_5d,
        "recent_return_20d_percent": recent_return_20d,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "trailing_stop_loss": max(stop_loss, entry_low - atr_14 * 0.5),
        "risk_amount": risk_amount,
        "risk_percent": risk_percent,
        "rr_to_45d_high": rr_to_45d_high,
    }


def build_local_review_result(hit: dict[str, Any], features: dict[str, Any]) -> GeminiReviewResult:
    close_strength = float(features["trigger_close_strength"])
    volume_vs_avg = float(features["trigger_volume_vs_20d_avg"])
    risk_percent = float(features["risk_percent"])
    distance_to_sma_20 = float(features["distance_to_sma_20_percent"])
    recent_return_5d = float(features["recent_return_5d_percent"])
    confidence = 50
    reasons: list[str] = []

    if close_strength >= 0.7:
        confidence += 12
        reasons.append("trigger closed strongly near the session high")
    elif close_strength < 0.45:
        confidence -= 20
        reasons.append("trigger did not close strongly enough")

    if volume_vs_avg >= 1.4:
        confidence += 10
        reasons.append("volume was meaningfully above the 20-session average")
    elif volume_vs_avg < 1.0:
        confidence -= 15
        reasons.append("volume confirmation was weak")

    if risk_percent <= 8:
        confidence += 10
        reasons.append("risk is controlled against the anchor low")
    elif risk_percent > 14:
        confidence -= 25
        reasons.append("stop distance is too wide for disciplined entry")

    if distance_to_sma_20 > 12 or recent_return_5d > 12:
        confidence -= 12
        reasons.append("price is stretched, so chasing is not disciplined")

    confidence = min(max(confidence, 0), 100)
    support_price = optional_feature_float(features.get("nearest_support_price")) or float(features["low_45"])
    resistance_price = optional_feature_float(features.get("nearest_resistance_price")) or float(features["high_45"])

    if risk_percent > 25 or close_strength < 0.35:
        return GeminiReviewResult(
            status="completed",
            decision="IGNORE",
            confidence=confidence,
            summary=local_summary(hit, "IGNORE", reasons),
            support_price=support_price,
            resistance_price=resistance_price,
            entry_low=None,
            entry_high=None,
            stop_loss=None,
            target_1=None,
            target_2=None,
            trailing_stop_loss=None,
            risk_reward=None,
            wait_until="",
            invalidation="Local discipline rules rejected the setup because entry risk or candle quality was unacceptable.",
            sources=[],
            raw_response={"provider": LOCAL_DISCIPLINE_PROVIDER, "features": features},
        )

    decision = "WAIT"
    wait_until = (
        f"Wait for price to hold above {features['stop_loss']:.2f} and confirm with a strong close above "
        f"{hit['trigger_high']:.2f}, or wait for a controlled pullback into "
        f"{features['entry_low']:.2f}-{features['entry_high']:.2f} without invalidation."
    )
    invalidation = f"Invalidate if price closes below {features['stop_loss']:.2f} before entry."

    return GeminiReviewResult(
        status="completed",
        decision=decision,
        confidence=confidence,
        summary=local_summary(hit, decision, reasons),
        support_price=support_price,
        resistance_price=resistance_price,
        entry_low=float(features["entry_low"]),
        entry_high=float(features["entry_high"]),
        stop_loss=float(features["stop_loss"]),
        target_1=float(features["target_1"]),
        target_2=float(features["target_2"]),
        trailing_stop_loss=float(features["trailing_stop_loss"]),
        risk_reward=2.0,
        wait_until=wait_until,
        invalidation=invalidation,
        sources=[],
        raw_response={"provider": LOCAL_DISCIPLINE_PROVIDER, "features": features},
    )


def local_summary(hit: dict[str, Any], decision: str, reasons: list[str]) -> str:
    detail = "; ".join(reasons) if reasons else "setup passed the basic discipline checks"
    return f"{hit['symbol']} local discipline review: {decision}. {detail}."


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def optional_feature_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def percent_change(base: float | None, value: float | None) -> float:
    if base is None or value is None or base <= 0:
        return 0.0
    return ((value - base) / base) * 100


def average_true_range(highs: list[float], lows: list[float], closes: list[float], period: int) -> float:
    if len(highs) < 2:
        return 0.0
    ranges: list[float] = []
    start = max(1, len(highs) - period)
    for index in range(start, len(highs)):
        ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    return average(ranges)
