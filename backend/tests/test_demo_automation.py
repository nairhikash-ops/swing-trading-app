from datetime import date

import pytest

from app.demo_automation import DemoAutomationService
from app.demo_trading import DemoTradingService
from app.drishti import DrishtiSignalService
from app.learning import LearningStore
from test_demo_trading import seed_drishti_hit


def build_automation(settings, token_store) -> tuple[DemoAutomationService, DemoTradingService]:
    demo_service = DemoTradingService(settings, token_store)
    automation = DemoAutomationService(
        settings=settings,
        token_store=token_store,
        drishti_signal_service=DrishtiSignalService(settings, token_store),
        demo_trading_service=demo_service,
    )
    return automation, demo_service


@pytest.mark.asyncio
async def test_demo_automation_uses_algo_engine_without_external_ai_key(tmp_path):
    settings, token_store, _ = seed_drishti_hit(tmp_path, include_next_session=False)
    automation, demo_service = build_automation(settings, token_store)

    result = await automation.run_once({"id": 1, "status": "completed", "failed_count": 0})

    assert result["status"] == "ok"
    assert result["fresh_hit_count"] == 1
    assert result["algo_analyzed_count"] == 1
    assert result["ai_reviewed_count"] == 1
    assert result["enter_count"] == 0
    assert result["orders_created_count"] == 0
    learning_status = LearningStore(token_store).status()
    with token_store._connect() as conn:
        reviews = conn.execute("SELECT * FROM ai_signal_reviews WHERE provider = 'algo'").fetchall()
        candidates = conn.execute("SELECT * FROM watchlist_candidates").fetchall()
    assert len(reviews) == 1
    assert len(candidates) == 1
    assert candidates[0]["status"] == "active"
    assert candidates[0]["decision"] == "WAIT"
    assert demo_service.orders() == []
    assert learning_status["decision_snapshot_count"] == 1


def test_demo_ledger_reset_clears_orders_positions_and_cash(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path)
    demo_service = DemoTradingService(settings, token_store)
    demo_service.place_order_from_drishti_hit(hit["id"])

    result = demo_service.reset_ledger()

    assert result["deleted_orders"] == 1
    assert result["deleted_positions"] == 1
    assert result["summary"]["cash_balance"] == settings.demo_initial_cash
    assert result["summary"]["realized_pnl"] == 0
    assert demo_service.orders() == []
    assert demo_service.positions() == []


@pytest.mark.asyncio
async def test_demo_automation_tracks_recent_algo_signal_until_confirmation(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    automation, demo_service = build_automation(settings, token_store)
    confirmation_date = date.fromordinal(date.fromisoformat(hit["trigger_date"]).toordinal() + 1).isoformat()
    with token_store._connect() as conn:
        conn.execute(
            """
            INSERT INTO daily_candles (
                instrument_id, security_id, exchange_segment, instrument, trading_date,
                source_timestamp, open, high, low, close, volume, open_interest, source, raw_json, fetched_at, updated_at
            )
            VALUES (?, ?, 'NSE_EQ', 'EQUITY', ?, 1714526100, 125, 132, 124, 130, 2500, NULL, 'test', '{}', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (hit["instrument_id"], hit["security_id"], confirmation_date),
        )

    result = await automation.run_once({"id": 1, "status": "completed", "failed_count": 0})

    assert result["status"] == "ok"
    assert result["fresh_hit_count"] == 1
    assert result["algo_analyzed_count"] == 1
    assert result["enter_count"] == 0
    assert result["orders_created_count"] == 1
    assert result["skipped_count"] == 0
    with token_store._connect() as conn:
        candidate = conn.execute("SELECT * FROM watchlist_candidates").fetchone()
    orders = demo_service.orders()
    assert candidate["status"] == "entered"
    assert orders[0]["status"] == "pending_entry"
    assert orders[0]["fill_after_date"] == confirmation_date

    second_result = await automation.run_once({"id": 1, "status": "completed", "failed_count": 0})

    assert second_result["status"] == "ok"
    assert second_result["fresh_hit_count"] == 0
    assert second_result["orders_created_count"] == 0
    assert len(demo_service.orders()) == 1
