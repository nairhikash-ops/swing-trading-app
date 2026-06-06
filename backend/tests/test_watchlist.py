from datetime import date

from fastapi.testclient import TestClient

from app.ai_reviews import AiReviewStore
from app.demo_trading import DemoTradingService
from app.main import app, get_watchlist_service_dep
from app.watchlist import WatchlistService
from test_demo_trading import seed_drishti_hit


def insert_local_wait_review(
    token_store,
    hit,
    decision="WAIT",
    entry_low=100,
    entry_high=113,
    stop_loss=90,
    recent_return_5d_percent=12,
):
    store = AiReviewStore(token_store)
    result = {
        "status": "completed",
        "decision": decision,
        "confidence": 62,
        "summary": "Wait for disciplined entry.",
        "support_price": 90,
        "resistance_price": 115,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "target_1": 130,
        "target_2": 145,
        "trailing_stop_loss": 104,
        "risk_reward": 2.0,
        "wait_until": "Wait for pullback.",
        "invalidation": "Close below support.",
        "sources": [],
        "raw_response": {
            "features": {
                "recent_return_5d_percent": recent_return_5d_percent,
                "risk_percent": 8,
                "breakout_price": hit["trigger_high"],
            }
        },
    }
    from app.ai_reviews import GeminiReviewResult

    return store.insert_review(
        int(hit["id"]),
        "local",
        "drishti-discipline-v1",
        {"ai_mode": {"grounding_enabled": False}},
        GeminiReviewResult(**result),
    )


def test_watchlist_wait_candidate_enters_when_pullback_range_trades(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=True)
    demo_service = DemoTradingService(settings, token_store)
    watchlist = WatchlistService(settings, token_store, demo_service)
    review = insert_local_wait_review(token_store, hit)
    candidate = watchlist.upsert_from_review(int(hit["id"]), review)

    result = watchlist.monitor_entries()

    assert candidate["status"] == "active"
    assert result["entered"][0]["source_signal_hit_id"] == hit["id"]
    assert result["entered"][0]["status"] == "entered"
    assert demo_service.orders()[0]["status"] == "pending_entry"


def test_watchlist_candidate_invalidates_before_entry(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    demo_service = DemoTradingService(settings, token_store)
    watchlist = WatchlistService(settings, token_store, demo_service)
    review = insert_local_wait_review(token_store, hit, entry_low=100, entry_high=113, stop_loss=90)
    watchlist.upsert_from_review(int(hit["id"]), review)
    next_date = date.fromordinal(date.fromisoformat(hit["trigger_date"]).toordinal() + 1).isoformat()
    with token_store._connect() as conn:
        conn.execute(
            """
            INSERT INTO daily_candles (
                instrument_id, security_id, exchange_segment, instrument, trading_date,
                source_timestamp, open, high, low, close, volume, open_interest, source, raw_json, fetched_at, updated_at
            )
            VALUES (?, ?, 'NSE_EQ', 'EQUITY', ?, 1714526100, 91, 95, 89, 90, 1000, NULL, 'test', '{}', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (
                hit["instrument_id"],
                hit["security_id"],
                next_date,
            ),
        )

    result = watchlist.monitor_entries()

    assert result["invalidated"][0]["status"] == "invalidated"
    assert demo_service.orders() == []


def test_watchlist_breakout_entry_requires_strong_confirming_close(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    demo_service = DemoTradingService(settings, token_store)
    watchlist = WatchlistService(settings, token_store, demo_service)
    review = insert_local_wait_review(
        token_store,
        hit,
        entry_low=hit["trigger_high"],
        entry_high=hit["trigger_close"] * 1.01,
        stop_loss=hit["anchor_low"],
        recent_return_5d_percent=0,
    )
    watchlist.upsert_from_review(int(hit["id"]), review)
    first_date = date.fromordinal(date.fromisoformat(hit["trigger_date"]).toordinal() + 1).isoformat()
    second_date = date.fromordinal(date.fromisoformat(hit["trigger_date"]).toordinal() + 2).isoformat()
    with token_store._connect() as conn:
        for trading_date, open_price, high, low, close in [
            (first_date, 126.5, 140.0, 120.0, 127.0),
            (second_date, 128.0, 133.0, 125.0, 132.0),
        ]:
            conn.execute(
                """
                INSERT INTO daily_candles (
                    instrument_id, security_id, exchange_segment, instrument, trading_date,
                    source_timestamp, open, high, low, close, volume, open_interest, source, raw_json, fetched_at, updated_at
                )
                VALUES (?, ?, 'NSE_EQ', 'EQUITY', ?, 1714526100, ?, ?, ?, ?, 1000, NULL, 'test', '{}', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """,
                (hit["instrument_id"], hit["security_id"], trading_date, open_price, high, low, close),
            )

    weak_result = watchlist.monitor_entries()
    strong_result = watchlist.monitor_entries()

    assert weak_result["entered"] == []
    assert weak_result["waiting"][0]["last_checked_date"] == first_date
    assert strong_result["entered"][0]["status"] == "entered"
    order = demo_service.orders()[0]
    assert order["status"] == "pending_entry"
    assert order["entry_low"] == hit["trigger_high"]
    assert order["entry_high"] == 132.0 * 1.02
    assert order["target_price"] is None


def test_active_watchlist_report_returns_active_candidates(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    watchlist = WatchlistService(settings, token_store, DemoTradingService(settings, token_store))
    review = insert_local_wait_review(token_store, hit)
    candidate = watchlist.upsert_from_review(int(hit["id"]), review)

    report = watchlist.active_report()

    assert report[0]["watchlist_candidate_id"] == candidate["id"]
    assert report[0]["symbol"] == hit["symbol"]
    assert report[0]["status"] == "active"
    assert report[0]["source_signal_id"] == hit["signal_id"]


def test_active_watchlist_report_filters_by_source(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    watchlist = WatchlistService(settings, token_store, DemoTradingService(settings, token_store))
    review = insert_local_wait_review(token_store, hit)
    candidate = watchlist.upsert_from_review(int(hit["id"]), review)

    assert watchlist.active_report(source="reversal_radar") == []
    with token_store._connect() as conn:
        conn.execute(
            "UPDATE watchlist_candidates SET source_signal_id = 'reversal_radar' WHERE id = ?",
            (candidate["id"],),
        )

    report = watchlist.active_report(source="reversal_radar")

    assert len(report) == 1
    assert report[0]["source_type"] == "reversal_radar"


def test_active_watchlist_report_excludes_inactive_candidates(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    watchlist = WatchlistService(settings, token_store, DemoTradingService(settings, token_store))
    review = insert_local_wait_review(token_store, hit)
    candidate = watchlist.upsert_from_review(int(hit["id"]), review)
    with token_store._connect() as conn:
        conn.execute(
            "UPDATE watchlist_candidates SET status = 'expired' WHERE id = ?",
            (candidate["id"],),
        )

    assert watchlist.active_report() == []


def test_active_watchlist_report_waiting_for_breakout_text(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    watchlist = WatchlistService(settings, token_store, DemoTradingService(settings, token_store))
    review = insert_local_wait_review(token_store, hit, recent_return_5d_percent=0)
    watchlist.upsert_from_review(int(hit["id"]), review)

    report = watchlist.active_report()

    assert report[0]["entry_rule"] == "wait_breakout"
    assert report[0]["waiting_for"] == f"close > {hit['trigger_high']:g} and close_strength >= 0.6"


def test_active_watchlist_report_waiting_for_pullback_text(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    watchlist = WatchlistService(settings, token_store, DemoTradingService(settings, token_store))
    review = insert_local_wait_review(token_store, hit, entry_low=100, entry_high=113, recent_return_5d_percent=12)
    watchlist.upsert_from_review(int(hit["id"]), review)

    report = watchlist.active_report()

    assert report[0]["entry_rule"] == "wait_pullback"
    assert report[0]["waiting_for"] == "price enters 100-113 zone"


def test_active_watchlist_report_demo_order_created_false_without_order(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    watchlist = WatchlistService(settings, token_store, DemoTradingService(settings, token_store))
    review = insert_local_wait_review(token_store, hit)
    watchlist.upsert_from_review(int(hit["id"]), review)

    report = watchlist.active_report()

    assert report[0]["demo_order_created"] is False


def test_active_watchlist_report_demo_order_created_true_when_entered_order_exists(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    watchlist = WatchlistService(settings, token_store, DemoTradingService(settings, token_store))
    review = insert_local_wait_review(token_store, hit)
    candidate = watchlist.upsert_from_review(int(hit["id"]), review)
    with token_store._connect() as conn:
        conn.execute(
            "UPDATE watchlist_candidates SET entered_order_id = 123 WHERE id = ?",
            (candidate["id"],),
        )

    report = watchlist.active_report()

    assert report[0]["demo_order_created"] is True


def test_active_watchlist_endpoint_returns_typed_report():
    class FakeService:
        def active_report(self, source: str | None, limit: int):
            assert source == "reversal_radar"
            assert limit == 50
            return [
                {
                    "watchlist_candidate_id": 3,
                    "symbol": "NEWGEN",
                    "status": "active",
                    "decision": "WAIT",
                    "source_signal_id": "reversal_radar",
                    "source_type": "reversal_radar",
                    "source_signal_hit_id": 13897,
                    "source_run_id": 1,
                    "trigger_date": "2026-05-29",
                    "last_checked_date": None,
                    "entry_rule": "wait_breakout",
                    "entry_low": 442.7,
                    "entry_high": 451.554,
                    "breakout_price": 442.7,
                    "stop_loss": 424.68,
                    "target_1": 478.74,
                    "target_2": 496.76,
                    "trailing_stop_loss": 424.68,
                    "invalidation_price": 424.68,
                    "entered_order_id": None,
                    "demo_order_created": False,
                    "waiting_for": "close > 442.7 and close_strength >= 0.6",
                    "invalidate_if": "low <= 424.68",
                    "expiry_date": "2026-06-14",
                    "summary": "Reversal radar watch candidate.",
                    "features": {"source": "reversal_radar"},
                }
            ]

    app.dependency_overrides[get_watchlist_service_dep] = lambda: FakeService()
    try:
        response = TestClient(app).get(
            "/api/watchlist/active",
            params={"source": "reversal_radar", "limit": 50},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["watchlist_candidate_id"] == 3
    assert response.json()[0]["waiting_for"] == "close > 442.7 and close_strength >= 0.6"
