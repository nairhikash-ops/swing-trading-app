import json

import pytest
from cryptography.fernet import Fernet

from app.ai_credentials import GEMINI_PROVIDER, AiCredentialStore
from app.ai_reviews import AiSignalReviewService
from app.config import Settings
from app.crypto import TokenCrypto
from app.drishti import DrishtiSignalService
from app.historical_data import HistoricalDataStore, historical_window
from app.index_universe import IndexUniverseStore
from app.instrument_master import InstrumentMasterStore
from app.store import TokenStore
from test_drishti import historical_candle, sample_signal_candles, seed_symbol


class FakeGeminiReviewClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    async def review(self, api_key: str, prompt: str):
        self.prompts.append(prompt)
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


class RateLimitedGeminiReviewClient:
    async def review(self, api_key: str, prompt: str):
        import httpx

        response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
        raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)


def seed_signal_hit(tmp_path):
    settings = Settings(
        app_secret_key=Fernet.generate_key().decode(),
        data_dir=tmp_path,
        historical_lookback_calendar_days=90,
    )
    token_store = TokenStore(settings.database_path)
    universe_store = IndexUniverseStore(token_store)
    instrument_store = InstrumentMasterStore(token_store)
    historical_store = HistoricalDataStore(token_store)
    seed_symbol(universe_store, instrument_store)
    window = historical_window(settings)
    run_id = historical_store.create_run("NIFTY_500", settings.historical_lookback_calendar_days, window)
    item = historical_store.items(run_id, status="queued")[0]
    candles = sample_signal_candles(window.from_date)
    historical_store.upsert_candles(item, [historical_candle(candle) for candle in candles], "NSE_EQ", "EQUITY")
    report = DrishtiSignalService(settings, token_store).refresh_nifty_500_signal_01()
    credential_store = AiCredentialStore(token_store)
    credential_store.upsert_key(
        provider=GEMINI_PROVIDER,
        encrypted_api_key=TokenCrypto(settings.app_secret_key).encrypt("AIzaSyTestGeminiApiKeyValue123456"),
        validated=True,
    )
    return settings, token_store, int(report["items"][0]["id"])


@pytest.mark.asyncio
async def test_ai_review_for_drishti_hit_uses_trigger_time_context_and_stores_result(tmp_path):
    settings, token_store, hit_id = seed_signal_hit(tmp_path)
    fake = FakeGeminiReviewClient(
        {
            "decision": "ENTER",
            "confidence": 78,
            "summary": "Valid demand shock with a clean 1:2 demo structure.",
            "support_price": 95,
            "resistance_price": 130,
            "entry_low": 112,
            "entry_high": 115,
            "stop_loss": 90,
            "target_1": 165,
            "target_2": 180,
            "trailing_stop_loss": 104,
            "risk_reward": 2.2,
            "wait_until": "",
            "invalidation": "Close below the anchor low.",
        }
    )
    service = AiSignalReviewService(settings, token_store, gemini_client=fake)

    review = await service.review_drishti_hit(hit_id)

    assert review["decision"] == "ENTER"
    assert review["status"] == "completed"
    assert review["grounding_enabled"] is False
    assert review["trailing_stop_loss"] == 104
    assert review["risk_reward"] == 2.2
    assert service.latest_review_for_hit(hit_id)["id"] == review["id"]
    assert "alert_time_only_no_future_candles" in fake.prompts[0]
    assert "2026-02-16" not in fake.prompts[0]


@pytest.mark.asyncio
async def test_ai_review_downgrades_invalid_trade_math_to_watch(tmp_path):
    settings, token_store, hit_id = seed_signal_hit(tmp_path)
    fake = FakeGeminiReviewClient(
        {
            "decision": "ENTER",
            "confidence": 90,
            "summary": "Bad math should not be trusted.",
            "entry_low": 100,
            "entry_high": 102,
            "stop_loss": 105,
            "target_1": 103,
            "trailing_stop_loss": 104,
            "risk_reward": 0.5,
            "wait_until": "",
            "invalidation": "None.",
        }
    )
    service = AiSignalReviewService(settings, token_store, gemini_client=fake)

    review = await service.review_drishti_hit(hit_id)

    assert review["decision"] == "WAIT"
    assert review["confidence"] == 50
    assert "failed validation" in review["invalidation"]
    assert "risk/reward >= 2" in review["wait_until"]


@pytest.mark.asyncio
async def test_ai_review_marks_429_as_quota_limited(tmp_path):
    settings, token_store, hit_id = seed_signal_hit(tmp_path)
    service = AiSignalReviewService(settings, token_store, gemini_client=RateLimitedGeminiReviewClient())

    review = await service.review_drishti_hit(hit_id)

    assert review["status"] == "quota_limited"
    assert review["decision"] == "IGNORE"
    assert "HTTP 429" in review["error"]
    assert "quota" in review["summary"].lower()
