from datetime import date

from fastapi.testclient import TestClient

from app.config import Settings
from app.historical_data import HistoricalDataStore
from app.main import app, get_reversal_opportunity_service_dep
from app.reversal_opportunities import (
    ReversalOpportunityService,
    ReversalOpportunityStore,
    build_opportunity_item,
    classify_reversal_opportunity,
)
from app.store import TokenStore


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


def test_scan_filters_by_min_entry_quality_score(monkeypatch):
    class FakeStore:
        def nifty_500_instruments(self, limit: int = 500):
            return [instrument("LOW"), instrument("HIGH")]

        def candles_for_instrument(self, instrument_id: int, limit: int = 365):
            return []

    def fake_classify(candidate, candles):
        is_high = candidate["underlying_symbol"] == "HIGH"
        return {
            **fake_response_item(candidate["underlying_symbol"]),
            "opportunity_score": 80,
            "entry_quality_score": 60 if is_high else 30,
        }

    monkeypatch.setattr("app.reversal_opportunities.classify_reversal_opportunity", fake_classify)

    items = ReversalOpportunityService(None, store=FakeStore()).scan_nifty_500(
        min_entry_quality_score=55,
    )

    assert [item["symbol"] for item in items] == ["HIGH"]


def test_scan_min_score_still_filters_by_opportunity_score(monkeypatch):
    class FakeStore:
        def nifty_500_instruments(self, limit: int = 500):
            return [instrument("LOWOPP"), instrument("HIGHOPP")]

        def candles_for_instrument(self, instrument_id: int, limit: int = 365):
            return []

    def fake_classify(candidate, candles):
        is_high = candidate["underlying_symbol"] == "HIGHOPP"
        return {
            **fake_response_item(candidate["underlying_symbol"]),
            "opportunity_score": 70 if is_high else 30,
            "entry_quality_score": 80,
        }

    monkeypatch.setattr("app.reversal_opportunities.classify_reversal_opportunity", fake_classify)

    items = ReversalOpportunityService(None, store=FakeStore()).scan_nifty_500(min_score=50)

    assert [item["symbol"] for item in items] == ["HIGHOPP"]


def test_reversal_opportunity_endpoint_returns_typed_items():
    class FakeService:
        def scan_nifty_500(
            self,
            limit: int,
            include_watch_only: bool,
            min_score: float,
            min_entry_quality_score: float,
        ):
            assert limit == 1
            assert include_watch_only is False
            assert min_score == 50
            assert min_entry_quality_score == 55
            return [fake_response_item("BEML")]

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).get(
            "/api/research/reversal-opportunities/nifty500",
            params={
                "limit": 1,
                "include_watch_only": "false",
                "min_score": 50,
                "min_entry_quality_score": 55,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "BEML"
    assert response.json()[0]["opportunity_stage"] == "downtrend_only"


def test_refresh_creates_run_and_saves_items(tmp_path, monkeypatch):
    service = persisted_service(tmp_path, monkeypatch)

    snapshot = service.refresh_nifty_500_snapshot(limit=10, min_entry_quality_score=55)

    assert snapshot["item_count"] == 1
    assert snapshot["items"][0]["symbol"] == "BEML"
    assert snapshot["items"][0]["outcome_status"] == "pending"


def test_latest_snapshot_reads_saved_items_without_recalculating(tmp_path, monkeypatch):
    service = persisted_service(tmp_path, monkeypatch)
    service.refresh_nifty_500_snapshot(limit=10, min_entry_quality_score=55)

    def fail_if_live_scan_runs(candidate, candles):
        raise AssertionError("latest snapshot should not recalculate live scan")

    monkeypatch.setattr("app.reversal_opportunities.classify_reversal_opportunity", fail_if_live_scan_runs)

    latest = service.latest_snapshot(limit=10, min_entry_quality_score=55)

    assert latest is not None
    assert latest["items"][0]["symbol"] == "BEML"


def test_symbol_history_returns_previous_appearances(tmp_path, monkeypatch):
    service = persisted_service(tmp_path, monkeypatch)
    service.refresh_nifty_500_snapshot(limit=10, min_entry_quality_score=55)
    service.refresh_nifty_500_snapshot(limit=10, min_entry_quality_score=55)

    history = service.history_for_symbol("BEML")

    assert len(history) == 2
    assert {item["symbol"] for item in history} == {"BEML"}


def test_outcome_refresh_calculates_forward_returns_and_excursions(tmp_path, monkeypatch):
    service = persisted_service(tmp_path, monkeypatch, nearest=nearest_support(mid_price=100))
    snapshot = service.refresh_nifty_500_snapshot(limit=10, min_entry_quality_score=55)
    token_store = service.persistence_store.token_store
    seed_future_candles(token_store, closes=[102, 104, 106, 104, 105, 107, 109, 111, 113, 115])

    result = service.update_outcomes()
    item = result["items"][0]

    assert result["complete_count"] == 1
    assert item["outcome_status"] == "complete"
    assert item["outcome_1d_return_percent"] == 2.0
    assert item["outcome_3d_return_percent"] == 6.0
    assert item["outcome_5d_return_percent"] == 5.0
    assert item["outcome_10d_return_percent"] == 15.0
    assert item["max_favorable_10d_percent"] == 20.0
    assert item["max_adverse_10d_percent"] == -6.0
    assert item["support_broken_10d"] is True
    assert snapshot["items"][0]["outcome_status"] == "pending"


def test_outcome_refresh_marks_partial_when_fewer_than_ten_future_candles(tmp_path, monkeypatch):
    service = persisted_service(tmp_path, monkeypatch)
    service.refresh_nifty_500_snapshot(limit=10, min_entry_quality_score=55)
    token_store = service.persistence_store.token_store
    seed_future_candles(token_store, closes=[101, 102, 103])

    result = service.update_outcomes()
    item = result["items"][0]

    assert result["partial_count"] == 1
    assert item["outcome_status"] == "partial"
    assert item["outcome_1d_return_percent"] == 1.0
    assert item["outcome_3d_return_percent"] == 3.0
    assert item["outcome_5d_return_percent"] is None
    assert item["outcome_10d_return_percent"] is None


def test_outcome_refresh_marks_not_enough_when_no_future_candles(tmp_path, monkeypatch):
    service = persisted_service(tmp_path, monkeypatch)
    service.refresh_nifty_500_snapshot(limit=10, min_entry_quality_score=55)

    result = service.update_outcomes()
    item = result["items"][0]

    assert result["not_enough_future_candles_count"] == 1
    assert item["outcome_status"] == "not_enough_future_candles"
    assert item["outcome_1d_return_percent"] is None
    assert item["max_favorable_10d_percent"] is None
    assert item["support_broken_10d"] is False


def test_latest_snapshot_endpoint_returns_saved_items():
    class FakeService:
        def latest_snapshot(self, limit: int, min_entry_quality_score: float, stage: str | None):
            assert limit == 1
            assert min_entry_quality_score == 55
            assert stage == "confirmed_reversal"
            return fake_run_response(items=[fake_snapshot_item("BEML")])

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).get(
            "/api/research/reversal-opportunities/nifty500/latest",
            params={"limit": 1, "min_entry_quality_score": 55, "stage": "confirmed_reversal"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["symbol"] == "BEML"


def test_refresh_endpoint_returns_typed_saved_snapshot():
    class FakeService:
        def refresh_nifty_500_snapshot(
            self,
            limit: int,
            include_watch_only: bool,
            min_score: float,
            min_entry_quality_score: float,
        ):
            assert limit == 1
            assert include_watch_only is False
            assert min_score == 0
            assert min_entry_quality_score == 55
            return fake_run_response(items=[fake_snapshot_item("BEML")])

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).post(
            "/api/research/reversal-opportunities/nifty500/refresh",
            params={
                "limit": 1,
                "include_watch_only": "false",
                "min_score": 0,
                "min_entry_quality_score": 55,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["item_count"] == 1
    assert response.json()["items"][0]["outcome_status"] == "pending"


def test_symbol_history_endpoint_returns_typed_items():
    class FakeService:
        def history_for_symbol(self, symbol: str, limit: int):
            assert symbol == "BEML"
            assert limit == 1
            return [fake_snapshot_item("BEML")]

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).get(
            "/api/research/reversal-opportunities/symbol/BEML/history",
            params={"limit": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "BEML"


def test_outcome_refresh_endpoint_returns_typed_response():
    class FakeService:
        def update_outcomes(self, limit: int):
            assert limit == 1
            return {
                "checked_count": 1,
                "updated_count": 1,
                "complete_count": 0,
                "partial_count": 1,
                "not_enough_future_candles_count": 0,
                "generated_at": "2026-01-10T00:00:00+00:00",
                "items": [{**fake_snapshot_item("BEML"), "outcome_status": "partial"}],
            }

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).post(
            "/api/research/reversal-opportunities/outcomes/refresh",
            params={"limit": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["partial_count"] == 1


def test_as_of_scan_uses_only_candles_on_or_before_replay_date(monkeypatch):
    candles = [candle(index, 100 - index, 101 - index, 99 - index, 100 - index) for index in range(12)]
    captured_dates = []

    class FakeAsOfStore:
        def nifty_500_instruments(self, limit: int = 500):
            return [instrument("BEML")]

        def candles_for_instrument_as_of(self, instrument_id: int, replay_date: str, limit: int = 365):
            return [row for row in candles if row["trading_date"] <= replay_date]

    def fake_classify(candidate, passed_candles):
        captured_dates.extend(row["trading_date"] for row in passed_candles)
        return {
            **fake_response_item(candidate["underlying_symbol"]),
            "instrument_id": candidate["id"],
            "latest_date": passed_candles[-1]["trading_date"],
            "entry_quality_score": 60,
            "suggested_next_action": "wait_for_confirmation",
        }

    monkeypatch.setattr("app.reversal_opportunities.classify_reversal_opportunity", fake_classify)
    replay_date = candles[6]["trading_date"]

    items = ReversalOpportunityService(None, store=FakeAsOfStore()).scan_nifty_500_as_of(
        replay_date,
        min_entry_quality_score=55,
    )

    assert items[0]["latest_date"] == replay_date
    assert captured_dates
    assert all(item_date <= replay_date for item_date in captured_dates)
    assert candles[7]["trading_date"] not in captured_dates


def test_as_of_scan_does_not_call_live_candle_loader(monkeypatch):
    candles = [candle(index, 100 - index, 101 - index, 99 - index, 100 - index) for index in range(8)]

    class FakeAsOfOnlyStore:
        def nifty_500_instruments(self, limit: int = 500):
            return [instrument("BEML")]

        def candles_for_instrument(self, instrument_id: int, limit: int = 365):
            raise AssertionError("as-of scan must not use the live candle loader")

        def candles_for_instrument_as_of(self, instrument_id: int, replay_date: str, limit: int = 365):
            return [row for row in candles if row["trading_date"] <= replay_date]

    def fake_classify(candidate, passed_candles):
        return {
            **fake_response_item(candidate["underlying_symbol"]),
            "instrument_id": candidate["id"],
            "latest_date": passed_candles[-1]["trading_date"],
            "entry_quality_score": 60,
            "suggested_next_action": "wait_for_confirmation",
        }

    monkeypatch.setattr("app.reversal_opportunities.classify_reversal_opportunity", fake_classify)

    items = ReversalOpportunityService(None, store=FakeAsOfOnlyStore()).scan_nifty_500_as_of(
        candles[5]["trading_date"],
        min_entry_quality_score=55,
    )

    assert items[0]["latest_date"] == candles[5]["trading_date"]


def test_backfill_excludes_latest_ten_sessions_by_default(tmp_path, monkeypatch):
    service, token_store, session_candles = backfill_service(tmp_path, monkeypatch)
    seed_candles_for_instrument(token_store, 1, session_candles)

    result = service.backfill_reversal_opportunities(sample_every_n_sessions=1, max_dates=30)

    assert result["run_count"] == 15
    assert result["item_count"] == 15
    latest_signal_date = max(item["signal_date"] for item in service._persistence().backfill_items())
    assert latest_signal_date == session_candles[-11]["trading_date"]
    assert session_candles[-10]["trading_date"] not in {item["signal_date"] for item in service._persistence().backfill_items()}


def test_backfill_creates_runs_items_and_complete_outcomes(tmp_path, monkeypatch):
    service, token_store, session_candles = backfill_service(tmp_path, monkeypatch)
    seed_candles_for_instrument(token_store, 1, session_candles)
    replay_date = session_candles[5]["trading_date"]

    result = service.backfill_reversal_opportunities(
        start_date=replay_date,
        end_date=replay_date,
        sample_every_n_sessions=1,
        max_dates=1,
    )

    assert result["run_count"] == 1
    assert result["item_count"] == 1
    assert result["complete_count"] == 1
    item = service._persistence().backfill_items()[0]
    assert item["outcome_status"] == "complete"
    assert item["outcome_10d_return_percent"] is not None


def test_backfill_marks_partial_when_stock_has_limited_future_candles(tmp_path, monkeypatch):
    service, token_store, session_candles = backfill_service(tmp_path, monkeypatch)
    seed_candles_for_instrument(token_store, 2, session_candles)
    seed_candles_for_instrument(token_store, 1, session_candles[:9])
    replay_date = session_candles[5]["trading_date"]

    result = service.backfill_reversal_opportunities(
        start_date=replay_date,
        end_date=replay_date,
        sample_every_n_sessions=1,
        max_dates=1,
    )

    assert result["partial_count"] == 1
    item = service._persistence().backfill_items()[0]
    assert item["outcome_status"] == "partial"
    assert item["outcome_1d_return_percent"] is not None
    assert item["outcome_10d_return_percent"] is None


def test_backfill_marks_not_enough_when_stock_has_no_future_candles(tmp_path, monkeypatch):
    service, token_store, session_candles = backfill_service(tmp_path, monkeypatch)
    seed_candles_for_instrument(token_store, 2, session_candles)
    seed_candles_for_instrument(token_store, 1, session_candles[:6])
    replay_date = session_candles[5]["trading_date"]

    result = service.backfill_reversal_opportunities(
        start_date=replay_date,
        end_date=replay_date,
        sample_every_n_sessions=1,
        max_dates=1,
    )

    assert result["not_enough_future_candles_count"] == 1
    item = service._persistence().backfill_items()[0]
    assert item["outcome_status"] == "not_enough_future_candles"


def test_backfill_summary_groups_by_stage_and_entry_quality_bucket(tmp_path, monkeypatch):
    service, token_store, session_candles = backfill_service(
        tmp_path,
        monkeypatch,
        symbols=("BEML", "HFCL"),
    )
    seed_candles_for_instrument(token_store, 1, session_candles)
    seed_candles_for_instrument(token_store, 2, session_candles)
    replay_date = session_candles[5]["trading_date"]

    result = service.backfill_reversal_opportunities(
        start_date=replay_date,
        end_date=replay_date,
        sample_every_n_sessions=1,
        max_dates=1,
    )

    stage_groups = {item["group"]: item for item in result["stage_summary"]}
    bucket_groups = {item["group"]: item for item in result["entry_quality_summary"]}
    assert stage_groups["confirmed_reversal"]["count"] == 1
    assert stage_groups["support_reclaim"]["count"] == 1
    assert bucket_groups["75_plus"]["count"] == 1
    assert bucket_groups["55_64"]["count"] == 1


def test_backfill_endpoint_returns_typed_summary():
    class FakeService:
        def backfill_reversal_opportunities(self, **kwargs):
            assert kwargs["sample_every_n_sessions"] == 1
            assert kwargs["max_dates"] == 1
            return fake_backfill_response()

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).post(
            "/api/research/reversal-opportunities/backfill",
            params={"sample_every_n_sessions": 1, "max_dates": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["run_count"] == 1
    assert response.json()["stage_summary"][0]["group"] == "confirmed_reversal"


def test_backfill_run_get_endpoint_uses_safe_defaults():
    class FakeService:
        def backfill_reversal_opportunities(self, **kwargs):
            assert kwargs == {
                "start_date": None,
                "end_date": None,
                "sample_every_n_sessions": 5,
                "limit_per_date": 50,
                "min_score": 0,
                "min_entry_quality_score": 55,
                "include_watch_only": False,
                "max_dates": 20,
            }
            return fake_backfill_response()

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).get("/api/research/reversal-opportunities/backfill/run")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["run_count"] == 1


def test_backfill_run_get_endpoint_passes_query_params():
    class FakeService:
        def backfill_reversal_opportunities(self, **kwargs):
            assert kwargs == {
                "start_date": "2026-04-01",
                "end_date": "2026-05-01",
                "sample_every_n_sessions": 2,
                "limit_per_date": 10,
                "min_score": 25,
                "min_entry_quality_score": 65,
                "include_watch_only": True,
                "max_dates": 3,
            }
            return fake_backfill_response()

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).get(
            "/api/research/reversal-opportunities/backfill/run",
            params={
                "start_date": "2026-04-01",
                "end_date": "2026-05-01",
                "sample_every_n_sessions": 2,
                "limit_per_date": 10,
                "min_score": 25,
                "min_entry_quality_score": 65,
                "include_watch_only": "true",
                "max_dates": 3,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["entry_quality_summary"][0]["group"] == "75_plus"


def test_backfill_summary_endpoint_returns_saved_summary():
    class FakeService:
        def backfill_summary(self, limit: int):
            assert limit == 10
            return fake_backfill_response()

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).get(
            "/api/research/reversal-opportunities/backfill/summary",
            params={"limit": 10},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["entry_quality_summary"][0]["group"] == "75_plus"


def test_promotion_marks_confirmed_reversal_candidate_eligible(tmp_path):
    service, run_id, _ = promotion_service_with_items(
        tmp_path,
        [promotion_source_item("BEML", stage="confirmed_reversal", entry_quality_score=75)],
    )

    result = service.promote_to_watchlist(run_id=run_id, dry_run=True)

    assert result["eligible_count"] == 1
    assert result["items"][0]["status"] == "eligible"


def test_promotion_marks_support_reclaim_candidate_eligible(tmp_path):
    service, run_id, _ = promotion_service_with_items(
        tmp_path,
        [promotion_source_item("HFCL", instrument_id=2, stage="support_reclaim", entry_quality_score=70)],
    )

    result = service.promote_to_watchlist(run_id=run_id, dry_run=True)

    assert result["eligible_count"] == 1
    assert result["items"][0]["symbol"] == "HFCL"
    assert result["items"][0]["status"] == "eligible"


def test_promotion_rejects_low_score_and_bullish_watch(tmp_path):
    service, run_id, _ = promotion_service_with_items(
        tmp_path,
        [
            promotion_source_item("LOW", stage="confirmed_reversal", entry_quality_score=60),
            promotion_source_item("WATCH", instrument_id=2, stage="bullish_reversal_watch", entry_quality_score=82),
        ],
    )

    result = service.promote_to_watchlist(run_id=run_id, dry_run=True)
    statuses = {item["symbol"]: item["status"] for item in result["items"]}

    assert result["eligible_count"] == 0
    assert statuses == {"LOW": "ineligible_low_score", "WATCH": "ineligible_stage"}


def test_promotion_rejects_bearish_latest_evidence(tmp_path):
    item = promotion_source_item("BEAR", stage="confirmed_reversal", entry_quality_score=82)
    item["latest_reversal_patterns"] = ["shooting_star"]
    item["reasons"] = ["regime_downtrend", "latest_bearish_reversal_evidence"]
    service, run_id, _ = promotion_service_with_items(tmp_path, [item])

    result = service.promote_to_watchlist(run_id=run_id, dry_run=True)

    assert result["eligible_count"] == 0
    assert result["items"][0]["status"] == "ineligible_stage"
    assert result["items"][0]["reason"] == "bearish_latest_evidence"


def test_promotion_dry_run_does_not_write_watchlist_items(tmp_path):
    service, run_id, token_store = promotion_service_with_items(
        tmp_path,
        [promotion_source_item("BEML", stage="confirmed_reversal", entry_quality_score=75)],
    )

    result = service.promote_to_watchlist(run_id=run_id, dry_run=True)

    with token_store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM watchlist_candidates").fetchone()["count"]
    assert result["promoted_count"] == 0
    assert count == 0


def test_promotion_creates_watchlist_review_candidate(tmp_path):
    service, run_id, token_store = promotion_service_with_items(
        tmp_path,
        [promotion_source_item("BEML", stage="confirmed_reversal", entry_quality_score=75)],
    )

    result = service.promote_to_watchlist(run_id=run_id, dry_run=False)

    with token_store._connect() as conn:
        candidate = conn.execute("SELECT * FROM watchlist_candidates").fetchone()
        hit = conn.execute("SELECT * FROM drishti_signal_hits").fetchone()
    assert result["promoted_count"] == 1
    assert candidate["source_signal_id"] == "reversal_radar"
    assert candidate["status"] == "active"
    assert candidate["decision"] == "WAIT"
    assert candidate["source_signal_hit_id"] == hit["id"]
    assert hit["signal_id"] == "reversal_radar"


def test_duplicate_promotion_is_skipped(tmp_path):
    service, run_id, _ = promotion_service_with_items(
        tmp_path,
        [promotion_source_item("BEML", stage="confirmed_reversal", entry_quality_score=75)],
    )

    first = service.promote_to_watchlist(run_id=run_id, dry_run=False)
    second = service.promote_to_watchlist(run_id=run_id, dry_run=False)

    assert first["promoted_count"] == 1
    assert second["promoted_count"] == 0
    assert second["skipped_duplicate_count"] == 1
    assert second["items"][0]["status"] == "duplicate"


def test_promotion_uses_latest_live_snapshot_when_run_id_omitted(tmp_path):
    service, _, _ = promotion_service_with_items(
        tmp_path,
        [promotion_source_item("OLD", stage="confirmed_reversal", entry_quality_score=75)],
    )
    second_run_id = insert_promotion_run(
        service,
        [promotion_source_item("NEW", instrument_id=2, stage="support_reclaim", entry_quality_score=70)],
    )

    result = service.promote_to_watchlist(dry_run=True)

    assert result["run_id"] == second_run_id
    assert [item["symbol"] for item in result["items"]] == ["NEW"]


def test_promotion_endpoint_returns_typed_response():
    class FakeService:
        def promote_to_watchlist(self, run_id, min_entry_quality_score: float, limit: int, dry_run: bool):
            assert run_id == 10
            assert min_entry_quality_score == 65
            assert limit == 5
            assert dry_run is False
            return fake_promotion_response()

    app.dependency_overrides[get_reversal_opportunity_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).post(
            "/api/research/reversal-opportunities/promote-to-watchlist",
            params={
                "run_id": 10,
                "min_entry_quality_score": 65,
                "limit": 5,
                "dry_run": "false",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "eligible"


class FakePersistenceStoreScanStore:
    def __init__(self, symbol: str = "BEML") -> None:
        self._symbol = symbol

    def nifty_500_instruments(self, limit: int = 500):
        return [instrument(self._symbol)]

    def candles_for_instrument(self, instrument_id: int, limit: int = 365):
        return []


def persisted_service(tmp_path, monkeypatch, nearest: dict | None = None) -> ReversalOpportunityService:
    settings = Settings(app_secret_key="test-secret", data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    HistoricalDataStore(token_store)
    persistence_store = ReversalOpportunityStore(token_store)

    def fake_classify(candidate, candles):
        return {
            **fake_response_item(candidate["underlying_symbol"]),
            "instrument_id": candidate["id"],
            "latest_date": "2026-01-05",
            "latest_close": 100.0,
            "opportunity_score": 80.0,
            "entry_quality_score": 60.0,
            "suggested_next_action": "wait_for_confirmation",
            "nearest_support": nearest,
        }

    monkeypatch.setattr("app.reversal_opportunities.classify_reversal_opportunity", fake_classify)
    return ReversalOpportunityService(
        token_store,
        store=FakePersistenceStoreScanStore(),
        persistence_store=persistence_store,
    )


def seed_future_candles(token_store: TokenStore, closes: list[float]) -> None:
    historical_store = HistoricalDataStore(token_store)
    candles = []
    for index, close in enumerate(closes, start=1):
        low = 94 if index == 6 else close - 1
        high = 120 if index == 8 else close + 1
        candles.append(
            {
                "timestamp": index,
                "trading_date": date.fromordinal(date(2026, 1, 5).toordinal() + index).isoformat(),
                "open": close - 0.5,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000 + index,
            }
        )
    historical_store.upsert_candles(
        {"instrument_id": 1, "security_id": "395"},
        candles,
        "NSE_EQ",
        "EQUITY",
    )


class FakeBackfillScanStore:
    def __init__(self, candles: list[dict], symbols: tuple[str, ...] = ("BEML",)) -> None:
        self.candles = candles
        self.symbols = symbols

    def nifty_500_instruments(self, limit: int = 500):
        return [instrument_with_id(symbol, index + 1) for index, symbol in enumerate(self.symbols)]

    def candles_for_instrument_as_of(self, instrument_id: int, replay_date: str, limit: int = 365):
        return [row for row in self.candles if row["trading_date"] <= replay_date][-limit:]


def instrument_with_id(symbol: str, instrument_id: int) -> dict:
    item = instrument(symbol)
    item["id"] = instrument_id
    item["isin"] = f"INE00000000{instrument_id}"
    item["security_id"] = str(394 + instrument_id)
    return item


def backfill_service(
    tmp_path,
    monkeypatch,
    symbols: tuple[str, ...] = ("BEML",),
) -> tuple[ReversalOpportunityService, TokenStore, list[dict]]:
    settings = Settings(app_secret_key="test-secret", data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    HistoricalDataStore(token_store)
    persistence_store = ReversalOpportunityStore(token_store)
    session_candles = [candle(index, 100 + index, 102 + index, 99 + index, 100 + index) for index in range(25)]

    def fake_classify(candidate, passed_candles):
        symbol = candidate["underlying_symbol"]
        high_quality = symbol == "HFCL"
        return {
            **fake_response_item(symbol),
            "instrument_id": candidate["id"],
            "latest_date": passed_candles[-1]["trading_date"],
            "latest_close": float(passed_candles[-1]["close"]),
            "opportunity_stage": "confirmed_reversal" if high_quality else "support_reclaim",
            "opportunity_score": 90.0 if high_quality else 75.0,
            "entry_quality_score": 80.0 if high_quality else 60.0,
            "suggested_next_action": "ready_for_drishti_review" if high_quality else "wait_for_confirmation",
            "nearest_support": nearest_support(mid_price=95),
            "support_reclaim": not high_quality,
            "quality_support_reclaim": not high_quality,
        }

    monkeypatch.setattr("app.reversal_opportunities.classify_reversal_opportunity", fake_classify)
    return (
        ReversalOpportunityService(
            token_store,
            store=FakeBackfillScanStore(session_candles, symbols=symbols),
            persistence_store=persistence_store,
        ),
        token_store,
        session_candles,
    )


def seed_candles_for_instrument(token_store: TokenStore, instrument_id: int, candles: list[dict]) -> None:
    HistoricalDataStore(token_store).upsert_candles(
        {"instrument_id": instrument_id, "security_id": str(394 + instrument_id)},
        [
            {
                "timestamp": index,
                "trading_date": item["trading_date"],
                "open": item["open"],
                "high": item["high"],
                "low": item["low"],
                "close": item["close"],
                "volume": item["volume"],
            }
            for index, item in enumerate(candles, start=1)
        ],
        "NSE_EQ",
        "EQUITY",
    )


def promotion_source_item(
    symbol: str,
    *,
    instrument_id: int = 1,
    stage: str = "confirmed_reversal",
    entry_quality_score: float = 75,
    action: str | None = None,
) -> dict:
    item = fake_response_item(symbol)
    item.update(
        {
            "instrument_id": instrument_id,
            "isin": f"INE00000000{instrument_id}",
            "security_id": str(394 + instrument_id),
            "latest_date": "2026-01-05",
            "latest_close": 100.0,
            "opportunity_stage": stage,
            "opportunity_score": 85.0,
            "entry_quality_score": entry_quality_score,
            "suggested_next_action": action
            or ("ready_for_drishti_review" if stage == "confirmed_reversal" else "wait_for_confirmation"),
            "support_reclaim": stage == "support_reclaim",
            "quality_support_reclaim": stage == "support_reclaim",
            "near_support": True,
            "inside_support_zone": stage == "support_reclaim",
            "support_distance_percent": 0.8,
            "support_strength": 82.0,
            "support_touch_count": 4,
            "support_recency_sessions": 6,
            "nearest_support": nearest_support(strength=82, touch_count=4, recency_sessions=6, mid_price=95),
            "reversal_bias": "bullish",
            "reversal_score": 55.0,
            "recent_reversal_patterns": ["bullish_engulfing"],
            "latest_reversal_patterns": ["bullish_engulfing"] if stage == "confirmed_reversal" else [],
            "confirmation_source": "latest_close_above_prior_high" if stage == "confirmed_reversal" else None,
            "reasons": ["regime_downtrend", stage],
        }
    )
    return item


def promotion_service_with_items(
    tmp_path,
    items: list[dict],
) -> tuple[ReversalOpportunityService, int, TokenStore]:
    settings = Settings(app_secret_key="test-secret", data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    HistoricalDataStore(token_store)
    persistence_store = ReversalOpportunityStore(token_store)
    service = ReversalOpportunityService(
        token_store,
        store=FakePersistenceStoreScanStore(),
        persistence_store=persistence_store,
        settings=settings,
    )
    run_id = insert_promotion_run(service, items)
    for item in items:
        seed_promotion_candles(token_store, int(item["instrument_id"]), str(item["security_id"]))
    return service, run_id, token_store


def insert_promotion_run(service: ReversalOpportunityService, items: list[dict]) -> int:
    run_id = service._persistence().create_run(
        universe_name="NIFTY_500",
        run_date="2026-01-05",
        min_score=0,
        min_entry_quality_score=55,
        include_watch_only=False,
        limit=50,
        item_count=len(items),
    )
    service._persistence().insert_items(run_id, items)
    return run_id


def seed_promotion_candles(token_store: TokenStore, instrument_id: int, security_id: str) -> None:
    HistoricalDataStore(token_store).upsert_candles(
        {"instrument_id": instrument_id, "security_id": security_id},
        [
            {
                "timestamp": 1,
                "trading_date": "2026-01-04",
                "open": 96,
                "high": 99,
                "low": 93,
                "close": 95,
                "volume": 1000,
            },
            {
                "timestamp": 2,
                "trading_date": "2026-01-05",
                "open": 98,
                "high": 102,
                "low": 96,
                "close": 100,
                "volume": 1400,
            },
        ],
        "NSE_EQ",
        "EQUITY",
    )


def fake_promotion_response() -> dict:
    return {
        "run_id": 10,
        "dry_run": False,
        "min_entry_quality_score": 65,
        "scanned_count": 1,
        "eligible_count": 1,
        "promoted_count": 0,
        "skipped_duplicate_count": 0,
        "skipped_ineligible_count": 0,
        "items": [
            {
                "radar_item_id": 1,
                "run_id": 10,
                "symbol": "BEML",
                "opportunity_stage": "confirmed_reversal",
                "entry_quality_score": 75,
                "opportunity_score": 85,
                "suggested_next_action": "ready_for_drishti_review",
                "status": "eligible",
                "reason": "qualified_for_watchlist_review",
                "watchlist_candidate_id": None,
                "source_signal_hit_id": None,
            }
        ],
    }


def fake_run_response(items: list[dict]) -> dict:
    return {
        "id": 1,
        "universe_name": "NIFTY_500",
        "run_date": "2026-01-05",
        "generated_at": "2026-01-05T00:00:00+00:00",
        "min_score": 0.0,
        "min_entry_quality_score": 55.0,
        "include_watch_only": False,
        "limit": 500,
        "item_count": len(items),
        "run_type": "live",
        "source": "manual",
        "items": items,
    }


def fake_backfill_response() -> dict:
    return {
        "run_count": 1,
        "run_ids": [1],
        "item_count": 1,
        "complete_count": 1,
        "partial_count": 0,
        "not_enough_future_candles_count": 0,
        "date_range": {"start_date": "2026-01-05", "end_date": "2026-01-05"},
        "sample_every_n_sessions": 1,
        "min_entry_quality_score": 55.0,
        "stage_summary": [
            {
                "group": "confirmed_reversal",
                "count": 1,
                "average_1d_return_percent": 1.0,
                "average_3d_return_percent": 2.0,
                "average_5d_return_percent": 3.0,
                "average_10d_return_percent": 4.0,
                "average_max_favorable_10d_percent": 5.0,
                "average_max_adverse_10d_percent": -1.0,
                "support_broken_rate": 0.0,
            }
        ],
        "entry_quality_summary": [
            {
                "group": "75_plus",
                "count": 1,
                "average_1d_return_percent": 1.0,
                "average_3d_return_percent": 2.0,
                "average_5d_return_percent": 3.0,
                "average_10d_return_percent": 4.0,
                "average_max_favorable_10d_percent": 5.0,
                "average_max_adverse_10d_percent": -1.0,
                "support_broken_rate": 0.0,
            }
        ],
    }


def fake_snapshot_item(symbol: str) -> dict:
    return {
        "id": 1,
        "run_id": 1,
        "instrument_id": 1,
        "symbol": symbol,
        "company_name": f"{symbol} Ltd.",
        "industry": "Capital Goods",
        "isin": "INE000000001",
        "security_id": "395",
        "signal_date": "2026-01-05",
        "latest_close": 100.0,
        "regime": "DOWNTREND",
        "regime_confidence": 80.0,
        "opportunity_stage": "downtrend_only",
        "opportunity_score": 20.0,
        "entry_quality_score": 60.0,
        "suggested_next_action": "watch_only",
        "near_support": False,
        "inside_support_zone": False,
        "support_reclaim": False,
        "quality_support_reclaim": False,
        "support_distance_percent": None,
        "support_strength": None,
        "support_touch_count": None,
        "support_recency_sessions": None,
        "indecision_score": 0.0,
        "reversal_score": 0.0,
        "reversal_bias": "none",
        "recent_indecision_date": None,
        "recent_reversal_date": None,
        "bullish_reversal_source_date": None,
        "confirmation_source": None,
        "reasons": ["regime_downtrend"],
        "latest_patterns": [],
        "latest_reversal_patterns": [],
        "recent_patterns": [],
        "recent_reversal_patterns": [],
        "nearest_support": None,
        "outcome_1d_return_percent": None,
        "outcome_3d_return_percent": None,
        "outcome_5d_return_percent": None,
        "outcome_10d_return_percent": None,
        "max_favorable_10d_percent": None,
        "max_adverse_10d_percent": None,
        "support_broken_10d": None,
        "outcome_status": "pending",
        "outcome_checked_at": None,
    }


def fake_response_item(symbol: str) -> dict:
    return {
        "instrument_id": 1,
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
