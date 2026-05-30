from datetime import date

from app.ai_reviews import AiReviewStore
from app.demo_trading import DemoTradingService
from app.watchlist import WatchlistService
from test_demo_trading import seed_drishti_hit


def insert_local_wait_review(token_store, hit, decision="WAIT", entry_low=100, entry_high=113, stop_loss=90):
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
        "raw_response": {"features": {"recent_return_5d_percent": 12, "risk_percent": 8, "breakout_price": 115}},
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
