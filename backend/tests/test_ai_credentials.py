import pytest
from cryptography.fernet import Fernet

from app.ai_credentials import AiCredentialService, AiCredentialStore
from app.config import Settings
from app.store import TokenStore


class FakeGeminiClient:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.validate_calls = 0

    async def validate_api_key(self, api_key: str):
        self.validate_calls += 1
        if self.should_fail:
            raise ValueError("Gemini rejected the API key.")
        return {"models": [{"name": "models/gemini-test"}]}


def make_service(tmp_path, fake: FakeGeminiClient | None = None):
    settings = Settings(app_secret_key=Fernet.generate_key().decode(), data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    store = AiCredentialStore(token_store)
    client = fake or FakeGeminiClient()
    return AiCredentialService(settings, store, client), client


@pytest.mark.asyncio
async def test_gemini_key_is_saved_encrypted_and_status_is_masked(tmp_path):
    service, fake = make_service(tmp_path)

    status = await service.save_gemini_key("AIzaSyTestGeminiApiKeyValue123456", validate_with_gemini=True)

    assert status.state == "active"
    assert status.has_key is True
    assert status.masked_key == "AIzaSy...3456"
    assert status.last_validated_at is not None
    assert fake.validate_calls == 1
    stored = service.store.get("gemini")
    assert stored is not None
    assert "AIzaSyTest" not in stored.encrypted_api_key


@pytest.mark.asyncio
async def test_gemini_key_can_be_saved_without_validation(tmp_path):
    service, fake = make_service(tmp_path)

    status = await service.save_gemini_key("AIzaSyTestGeminiApiKeyValue123456", validate_with_gemini=False)

    assert status.state == "active"
    assert status.last_validated_at is None
    assert fake.validate_calls == 0


@pytest.mark.asyncio
async def test_validate_saved_gemini_key_marks_failure_without_exposing_key(tmp_path):
    service, fake = make_service(tmp_path)
    await service.save_gemini_key("AIzaSyTestGeminiApiKeyValue123456", validate_with_gemini=False)
    fake.should_fail = True

    status = await service.validate_saved_gemini_key()

    assert status.state == "validation_failed"
    assert status.masked_key == "AIzaSy...3456"
    assert "AIzaSyTest" not in status.last_error
