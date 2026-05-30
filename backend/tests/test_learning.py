import json

import pytest
from cryptography.fernet import Fernet

from app.ai_credentials import GEMINI_PROVIDER, AiCredentialStore
from app.ai_reviews import AiSignalReviewService
from app.crypto import TokenCrypto
from app.demo_trading import DemoTradingService
from app.learning import LearningStore
from test_demo_trading import seed_drishti_hit


class FakeGeminiReviewClient:
    async def review(self, api_key: str, prompt: str):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "decision": "ENTER",
                                        "confidence": 78,
                                        "summary": "Valid demand shock with clean demo math.",
                                        "support_price": 95,
                                        "resistance_price": 130,
                                        "entry_low": 100,
                                        "entry_high": 113,
                                        "stop_loss": 90,
                                        "target_1": 130,
                                        "target_2": 145,
                                        "trailing_stop_loss": 104,
                                        "risk_reward": 2.2,
                                        "wait_until": "",
                                        "invalidation": "Close below support.",
                                    }
                                ),
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


@pytest.mark.asyncio
async def test_ai_review_creates_learning_snapshot_and_links_review(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path, include_next_session=False)
    settings.app_secret_key = Fernet.generate_key().decode()
    seed_gemini_key(settings, token_store)

    review = await AiSignalReviewService(
        settings,
        token_store,
        gemini_client=FakeGeminiReviewClient(),
    ).review_drishti_hit(int(hit["id"]))

    learning = LearningStore(token_store)
    snapshot = learning.snapshot_for_hit(int(hit["id"]))
    assert snapshot is not None
    assert review["decision_snapshot_id"] == snapshot["id"]
    assert snapshot["source_signal_hit_id"] == hit["id"]
    assert snapshot["symbol"] == hit["symbol"]
    assert snapshot["context"]["review_mode"] == "alert_time_only_no_future_candles"
    assert snapshot["features"]["candle_count"] >= 20


def test_demo_trade_writes_learning_outcome_with_path_metrics(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path)
    service = DemoTradingService(settings, token_store)

    result = service.place_order_from_drishti_hit(int(hit["id"]))

    learning = LearningStore(token_store)
    snapshot = learning.snapshot_for_hit(int(hit["id"]))
    outcomes = learning.latest_trade_outcomes()
    assert snapshot is not None
    assert result["order"]["decision_snapshot_id"] == snapshot["id"]
    assert result["position"]["decision_snapshot_id"] == snapshot["id"]
    assert len(outcomes) == 1
    assert outcomes[0]["source_signal_hit_id"] == hit["id"]
    assert outcomes[0]["decision_snapshot_id"] == snapshot["id"]
    assert outcomes[0]["outcome_label"] == "winner"
    assert outcomes[0]["target_hit"] is True
    assert outcomes[0]["max_favorable_percent"] > 0
    assert outcomes[0]["max_adverse_percent"] <= 0
