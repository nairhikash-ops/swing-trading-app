import json
from datetime import date

import pytest
from cryptography.fernet import Fernet

from app.ai_credentials import GEMINI_PROVIDER, AiCredentialStore
from app.ai_reviews import AiSignalReviewService
from app.crypto import TokenCrypto
from app.demo_automation import DemoAutomationService
from app.demo_trading import DemoTradingService
from app.drishti import DrishtiSignalService
from app.learning import LearningStore
from app.store import TokenStore
from test_demo_trading import seed_drishti_hit


class FakeGeminiReviewClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.call_count = 0

    async def review(self, api_key: str, prompt: str):
        self.call_count += 1
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(self.payload),
                            }
                        ]
                    }
                }
            ]
        }


def seed_gemini_key(settings, token_store) -> None:
    AiCredentialStore(token_store).upsert_key(
        provider=GEMINI_PROVIDER,
        encrypted_api_key=TokenCrypto(settings.app_secret_key).encrypt("AIzaSyTestGeminiApiKeyValue123456"),
        validated=True,
    )


def build_automation(settings, token_store, fake_client) -> tuple[DemoAutomationService, DemoTradingService]:
    settings.demo_automation_review_engine = GEMINI_PROVIDER
    demo_service = DemoTradingService(settings, token_store)
    automation = DemoAutomationService(
        settings=settings,
        token_store=token_store,
        drishti_signal_service=DrishtiSignalService(settings, token_store),
        ai_signal_review_service=AiSignalReviewService(settings, token_store, gemini_client=fake_client),
        demo_trading_service=demo_service,
    )
    return automation, demo_service


@pytest.mark.asyncio
async def test_demo_automation_places_order_only_after_enter_review(tmp_path):
    settings, token_store, _ = seed_drishti_hit(
        tmp_path,
        include_next_session=False,
    )
    settings.app_secret_key = Fernet.generate_key().decode()
    seed_gemini_key(settings, token_store)
    fake = FakeGeminiReviewClient(
        {
            "decision": "ENTER",
            "confidence": 80,
            "summary": "Signal is valid for demo tracking.",
            "support_price": 95,
            "resistance_price": 130,
            "entry_low": 100,
            "entry_high": 113,
            "stop_loss": 90,
            "target_1": 130,
            "target_2": 145,
            "trailing_stop_loss": 104,
            "risk_reward": 2.4,
            "wait_until": "",
            "invalidation": "Close below support.",
        }
    )
    automation, demo_service = build_automation(settings, token_store, fake)

    result = await automation.run_once({"id": 1, "status": "completed", "failed_count": 0})

    assert result["status"] == "ok"
    assert result["fresh_hit_count"] == 1
    assert result["ai_reviewed_count"] == 1
    assert result["enter_count"] == 1
    assert result["orders_created_count"] == 1
    orders = demo_service.orders()
    learning_status = LearningStore(token_store).status()
    with token_store._connect() as conn:
        candidate = conn.execute("SELECT * FROM watchlist_candidates").fetchone()
    assert len(orders) == 1
    assert learning_status["decision_snapshot_count"] == 1
    assert candidate["status"] == "entered"
    assert candidate["entered_order_id"] == orders[0]["id"]
    assert orders[0]["status"] == "pending_entry"
    assert orders[0]["ai_review_id"] is not None
    assert orders[0]["entry_low"] == 100
    assert orders[0]["entry_high"] == 113
    assert orders[0]["stop_loss"] == 90
    assert orders[0]["target_price"] == 130
    assert orders[0]["trailing_stop_loss"] == 104
    assert orders[0]["risk_reward"] == 2.4


@pytest.mark.asyncio
async def test_demo_automation_does_not_order_when_ai_ignores_signal(tmp_path):
    settings, token_store, _ = seed_drishti_hit(tmp_path, include_next_session=False)
    settings.app_secret_key = Fernet.generate_key().decode()
    seed_gemini_key(settings, token_store)
    fake = FakeGeminiReviewClient(
        {
            "decision": "IGNORE",
            "confidence": 55,
            "summary": "Too noisy.",
            "support_price": None,
            "resistance_price": None,
            "entry_low": None,
            "entry_high": None,
            "stop_loss": None,
            "target_1": None,
            "target_2": None,
            "trailing_stop_loss": None,
            "risk_reward": None,
            "wait_until": "",
            "invalidation": "No valid setup.",
        }
    )
    automation, demo_service = build_automation(settings, token_store, fake)

    result = await automation.run_once({"id": 1, "status": "completed", "failed_count": 0})

    assert result["status"] == "ok"
    assert result["fresh_hit_count"] == 1
    assert result["ai_reviewed_count"] == 1
    assert result["enter_count"] == 0
    assert result["orders_created_count"] == 0
    with token_store._connect() as conn:
        candidate = conn.execute("SELECT * FROM watchlist_candidates").fetchone()
    assert candidate["status"] == "ignored"
    assert demo_service.orders() == []


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
async def test_demo_automation_uses_local_discipline_engine_without_gemini_key(tmp_path):
    settings, token_store, _ = seed_drishti_hit(tmp_path, include_next_session=False)
    demo_service = DemoTradingService(settings, token_store)
    automation = DemoAutomationService(
        settings=settings,
        token_store=token_store,
        drishti_signal_service=DrishtiSignalService(settings, token_store),
        ai_signal_review_service=AiSignalReviewService(
            settings,
            token_store,
            gemini_client=FakeGeminiReviewClient({"decision": "IGNORE"}),
        ),
        demo_trading_service=demo_service,
    )

    result = await automation.run_once({"id": 1, "status": "completed", "failed_count": 0})

    assert result["status"] == "ok"
    assert result["fresh_hit_count"] == 1
    assert result["ai_reviewed_count"] == 1
    with token_store._connect() as conn:
        reviews = conn.execute("SELECT * FROM ai_signal_reviews WHERE provider = 'local'").fetchall()
        candidates = conn.execute("SELECT * FROM watchlist_candidates").fetchall()
    assert len(reviews) == 1
    assert len(candidates) == 1


@pytest.mark.asyncio
async def test_demo_automation_tracks_recent_signal_until_confirmation(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    demo_service = DemoTradingService(settings, token_store)
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
    automation = DemoAutomationService(
        settings=settings,
        token_store=token_store,
        drishti_signal_service=DrishtiSignalService(settings, token_store),
        ai_signal_review_service=AiSignalReviewService(
            settings,
            token_store,
            gemini_client=FakeGeminiReviewClient({"decision": "IGNORE"}),
        ),
        demo_trading_service=demo_service,
    )

    result = await automation.run_once({"id": 1, "status": "completed", "failed_count": 0})

    assert result["status"] == "ok"
    assert result["fresh_hit_count"] == 1
    assert result["ai_reviewed_count"] == 1
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
