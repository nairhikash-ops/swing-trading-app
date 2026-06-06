from datetime import date

from fastapi.testclient import TestClient

from app.main import app, get_reversal_opportunity_service_dep
from app.reversal_opportunities import (
    ReversalOpportunityService,
    build_opportunity_item,
    classify_reversal_opportunity,
)


def instrument(symbol: str = "BEML") -> dict:
    return {
        "id": 1,
        "underlying_symbol": symbol,
        "symbol": symbol,
        "company_name": f"{symbol} Ltd.",
        "industry": "Capital Goods",
        "isin": "INE000000001",
        "security_id": "395",
        "display_name": symbol,
    }


def candle(day: int, open_price: float, high: float, low: float, close: float) -> dict:
    return {
        "trading_date": date.fromordinal(date(2026, 1, 1).toordinal() + day).isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000 + day,
    }


def base_candles() -> list[dict]:
    return [
        candle(0, 110, 112, 108, 109),
        candle(1, 108, 109, 104, 105),
        candle(2, 104, 105, 101, 102),
        candle(3, 101, 102, 98, 99),
        candle(4, 98, 101, 96, 100),
    ]


def trend_candles(kind: str) -> list[dict]:
    candles = []
    for index in range(75):
        close = 100 + index if kind == "up" else 200 - index
        candles.append(candle(index, close - 0.5, close + 1, close - 1, close))
    return candles


def latest_regime(regime: str = "DOWNTREND") -> dict:
    return {"regime": regime, "confidence": 82.5}


def support_report(**overrides) -> dict:
    data = {
        "near_support": False,
        "inside_support_zone": False,
        "support_reclaim": False,
        "support_distance_percent": None,
        "nearest_support": None,
    }
    data.update(overrides)
    return data


def nearest_support(strength: float = 80, touch_count: int = 3, recency_sessions: int = 10, mid_price: float = 95):
    return {
        "price": mid_price,
        "mid_price": mid_price,
        "zone_low": mid_price - 2,
        "zone_high": mid_price + 2,
        "zone_width": 2,
        "role": "support",
        "inside_zone": False,
        "touch_count": touch_count,
        "first_touch_date": "2025-12-01",
        "last_touch_date": "2026-01-01",
        "recency_sessions": recency_sessions,
        "distance_percent": 1.0,
        "strength": strength,
        "sources": ["swing_low"],
        "touches": [],
    }


def candle_item(
    *,
    patterns: list[str] | None = None,
    reversal_patterns: list[str] | None = None,
    indecision_score: float = 0,
    reversal_bias: str = "none",
    reversal_score: float = 0,
) -> dict:
    return {
        "patterns": patterns or [],
        "reversal_patterns": reversal_patterns or [],
        "indecision_score": indecision_score,
        "reversal_bias": reversal_bias,
        "reversal_score": reversal_score,
    }


def opportunity(**kwargs) -> dict:
    candles = kwargs.pop("candles", base_candles())
    return build_opportunity_item(
        instrument(kwargs.pop("symbol", "BEML")),
        candles,
        kwargs.pop("regime", latest_regime()),
        kwargs.pop("support", support_report()),
        kwargs.pop("candle_items", [candle_item() for _ in candles]),
    )


def test_downtrend_without_support_or_candle_clue_is_downtrend_only():
    item = opportunity()

    assert item["opportunity_stage"] == "downtrend_only"
    assert item["suggested_next_action"] == "watch_only"
    assert item["opportunity_score"] == 20
    assert item["entry_quality_score"] == 10


def test_downtrend_near_support_is_near_support():
    item = opportunity(support=support_report(near_support=True, support_distance_percent=1.4))

    assert item["opportunity_stage"] == "near_support"
    assert item["near_support"] is True
    assert item["suggested_next_action"] == "wait_for_confirmation"


def test_downtrend_near_support_with_indecision_is_indecision_near_support():
    candles = base_candles()
    item = opportunity(
        candles=candles,
        support=support_report(near_support=True, inside_support_zone=True, support_distance_percent=0),
        candle_items=[candle_item() for _ in candles[:-1]]
        + [
            candle_item(
                patterns=["doji"],
                reversal_patterns=["bullish_doji_reversal_watch"],
                indecision_score=35,
                reversal_bias="bullish",
                reversal_score=25,
            )
        ],
    )

    assert item["opportunity_stage"] == "indecision_near_support"
    assert item["indecision_score"] == 35
    assert "recent_indecision" in item["reasons"]


def test_support_reclaim_stage_is_detected():
    item = opportunity(
        support=support_report(
            near_support=True,
            support_reclaim=True,
            nearest_support=nearest_support(),
            support_distance_percent=0.5,
        )
    )

    assert item["opportunity_stage"] == "support_reclaim"
    assert item["support_reclaim"] is True


def test_bullish_reversal_watch_and_confirmed_reversal_are_detected():
    watch_candles = base_candles()
    watch_item = opportunity(
        candles=watch_candles,
        candle_items=[candle_item() for _ in watch_candles[:-1]]
        + [
            candle_item(
                reversal_patterns=["hammer"],
                reversal_bias="bullish",
                reversal_score=45,
            )
        ],
    )
    confirmed_candles = base_candles()
    confirmed_candles[-1] = candle(4, 99, 103, 96, 103)
    confirmed_item = opportunity(
        candles=confirmed_candles,
        candle_items=[candle_item() for _ in confirmed_candles[:-1]]
        + [
            candle_item(
                reversal_patterns=["bullish_engulfing"],
                reversal_bias="bullish",
                reversal_score=60,
            )
        ],
    )

    assert watch_item["opportunity_stage"] == "bullish_reversal_watch"
    assert watch_item["suggested_next_action"] == "wait_for_breakout"
    assert confirmed_item["opportunity_stage"] == "confirmed_reversal"
    assert confirmed_item["suggested_next_action"] == "ready_for_drishti_review"


def test_bearish_latest_reversal_blocks_confirmed_and_reduces_entry_quality():
    candles = base_candles()
    candles[-1] = candle(4, 103, 108, 98, 107)
    clean_item = opportunity(
        candles=candles,
        support=support_report(
            near_support=True,
            inside_support_zone=True,
            support_reclaim=True,
            nearest_support=nearest_support(strength=85, touch_count=4, recency_sessions=4, mid_price=95),
            support_distance_percent=0,
        ),
        candle_items=[candle_item() for _ in candles[:-1]]
        + [
            candle_item(
                reversal_patterns=["bullish_engulfing"],
                reversal_bias="bullish",
                reversal_score=60,
            )
        ],
    )
    bearish_item = opportunity(
        candles=candles,
        support=support_report(
            near_support=True,
            inside_support_zone=True,
            support_reclaim=True,
            nearest_support=nearest_support(strength=85, touch_count=4, recency_sessions=4, mid_price=95),
            support_distance_percent=0,
        ),
        candle_items=[candle_item() for _ in candles[:-1]]
        + [
            candle_item(
                reversal_patterns=["shooting_star"],
                reversal_bias="bearish",
                reversal_score=45,
            )
        ],
    )

    assert clean_item["opportunity_stage"] == "confirmed_reversal"
    assert bearish_item["opportunity_stage"] != "confirmed_reversal"
    assert bearish_item["opportunity_stage"] != "bullish_reversal_watch"
    assert bearish_item["entry_quality_score"] < clean_item["entry_quality_score"]
    assert bearish_item["entry_quality_score"] <= 30
    assert bearish_item["suggested_next_action"] in ("wait_for_confirmation", "ignore")


def test_weak_old_support_does_not_rank_too_high():
    item = opportunity(
        support=support_report(
            near_support=True,
            support_reclaim=True,
            nearest_support=nearest_support(strength=18, touch_count=1, recency_sessions=195),
            support_distance_percent=1.0,
        )
    )

    assert item["support_strength"] == 18
    assert item["support_touch_count"] == 1
    assert item["support_recency_sessions"] == 195
    assert item["entry_quality_score"] <= 35
    assert "weak_support_strength" in item["reasons"]
    assert "single_touch_support" in item["reasons"]
    assert "old_support_zone" in item["reasons"]


def test_quality_support_reclaim_requires_clean_reclaim():
    clean = opportunity(
        support=support_report(
            near_support=True,
            support_reclaim=True,
            nearest_support=nearest_support(mid_price=95),
            support_distance_percent=0.5,
        )
    )
    bearish = opportunity(
        support=support_report(
            near_support=True,
            support_reclaim=True,
            nearest_support=nearest_support(mid_price=95),
            support_distance_percent=0.5,
        ),
        candle_items=[candle_item() for _ in base_candles()[:-1]]
        + [
            candle_item(
                reversal_patterns=["bearish_harami"],
                reversal_bias="bearish",
                reversal_score=35,
            )
        ],
    )
    below_mid = opportunity(
        candles=[*base_candles()[:-1], candle(4, 91, 92, 88, 92)],
        support=support_report(
            near_support=True,
            support_reclaim=True,
            nearest_support=nearest_support(mid_price=95),
            support_distance_percent=0.5,
        ),
    )

    assert clean["quality_support_reclaim"] is True
    assert bearish["quality_support_reclaim"] is False
    assert below_mid["quality_support_reclaim"] is False


def test_recent_source_fields_show_non_latest_signal_date():
    candles = base_candles()
    item = opportunity(
        candles=candles,
        candle_items=[candle_item() for _ in candles[:-2]]
        + [
            candle_item(
                patterns=["doji"],
                reversal_patterns=["hammer"],
                indecision_score=35,
                reversal_bias="bullish",
                reversal_score=45,
            ),
            candle_item(),
        ],
    )

    assert item["latest_patterns"] == []
    assert "doji" in item["recent_patterns"]
    assert "hammer" in item["recent_reversal_patterns"]
    assert item["recent_indecision_date"] == candles[-2]["trading_date"]
    assert item["recent_reversal_date"] == candles[-2]["trading_date"]
    assert item["bullish_reversal_source_date"] == candles[-2]["trading_date"]


def test_non_downtrend_stock_is_excluded():
    assert classify_reversal_opportunity(instrument("UPSTOCK"), trend_candles("up")) is None


def test_scan_sorts_by_entry_quality_before_opportunity_score(monkeypatch):
    class FakeStore:
        def nifty_500_instruments(self, limit: int = 500):
            return [instrument("LOW"), instrument("HIGH")]

        def candles_for_instrument(self, instrument_id: int, limit: int = 365):
            return []

    def fake_classify(candidate, candles):
        is_high = candidate["underlying_symbol"] == "HIGH"
        return {
            **fake_response_item(candidate["underlying_symbol"]),
            "opportunity_score": 20 if is_high else 100,
            "entry_quality_score": 90 if is_high else 10,
        }

    monkeypatch.setattr("app.reversal_opportunities.classify_reversal_opportunity", fake_classify)

    items = ReversalOpportunityService(None, store=FakeStore()).scan_nifty_500(limit=1)

    assert [item["symbol"] for item in items] == ["HIGH"]


def test_reversal_opportunity_endpoint_returns_typed_items():
    class FakeService:
        def scan_nifty_500(self, limit: int, include_watch_only: bool, min_score: float):
            assert limit == 1
            assert include_watch_only is False
            assert min_score == 50
            return [fake_response_item("BEML")]

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).get(
            "/api/research/reversal-opportunities/nifty500",
            params={"limit": 1, "include_watch_only": "false", "min_score": 50},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "BEML"
    assert response.json()[0]["opportunity_stage"] == "downtrend_only"


def fake_response_item(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "company_name": f"{symbol} Ltd.",
        "industry": "Capital Goods",
        "isin": "INE000000001",
        "security_id": "395",
        "latest_date": "2026-01-05",
        "latest_close": 100.0,
        "regime": "DOWNTREND",
        "regime_confidence": 80.0,
        "opportunity_stage": "downtrend_only",
        "opportunity_score": 20.0,
        "entry_quality_score": 10.0,
        "reasons": ["regime_downtrend"],
        "near_support": False,
        "inside_support_zone": False,
        "support_reclaim": False,
        "quality_support_reclaim": False,
        "support_distance_percent": None,
        "nearest_support": None,
        "support_strength": None,
        "support_touch_count": None,
        "support_recency_sessions": None,
        "latest_patterns": [],
        "latest_reversal_patterns": [],
        "recent_patterns": [],
        "recent_reversal_patterns": [],
        "recent_indecision_date": None,
        "recent_reversal_date": None,
        "bullish_reversal_source_date": None,
        "confirmation_source": None,
        "indecision_score": 0.0,
        "reversal_score": 0.0,
        "reversal_bias": "none",
        "suggested_next_action": "watch_only",
    }
