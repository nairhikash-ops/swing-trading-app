from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.dhan_client import DhanProfile, DhanRenewedToken
from app.store import TokenStore
from app.timezone import now_utc
from app.token_service import TokenService, derive_data_api_status


class FakeDhanClient:
    def __init__(self) -> None:
        self.profile_calls = 0
        self.renew_calls = 0

    async def profile(self, access_token: str) -> DhanProfile:
        self.profile_calls += 1
        return DhanProfile(
            dhan_client_id="123456",
            token_validity=now_utc() + timedelta(hours=20),
            active_segment="Equity",
            ddpi="Active",
            mtf="Deactive",
            data_plan="Active",
            data_validity="2026-12-31 23:59:59.0",
            raw={
                "dhanClientId": "123456",
                "tokenValidity": "31/12/2026 23:59",
                "activeSegment": "Equity",
                "ddpi": "Active",
                "mtf": "Deactive",
                "dataPlan": "Active",
                "dataValidity": "2026-12-31 23:59:59.0",
            },
        )

    async def renew_token(self, access_token: str, dhan_client_id: str) -> DhanRenewedToken:
        self.renew_calls += 1
        return DhanRenewedToken(
            access_token="renewed-token-value-1234567890",
            expiry_time=now_utc() + timedelta(hours=24),
            raw={"accessToken": "renewed-token-value-1234567890"},
        )


def make_service(tmp_path, renew_before_minutes: int = 180) -> tuple[TokenService, FakeDhanClient]:
    fake = FakeDhanClient()
    settings = Settings(
        app_secret_key=Fernet.generate_key().decode(),
        data_dir=tmp_path,
        dhan_renew_before_minutes=renew_before_minutes,
    )
    return TokenService(settings, TokenStore(settings.database_path), fake), fake


@pytest.mark.asyncio
async def test_manual_token_is_saved_encrypted_and_status_is_masked(tmp_path):
    service, fake = make_service(tmp_path)

    status = await service.save_manual_token(
        dhan_client_id="123456",
        access_token="manual-token-value-1234567890",
        expiry_time=None,
        validate_with_dhan=True,
    )

    assert status.state == "active"
    assert status.masked_token == "manual...7890"
    assert status.active_segment == "Equity"
    assert status.data_plan == "Active"
    assert status.data_api_active is True
    assert status.historical_fetch_allowed is True
    assert status.historical_block_reason == ""
    assert fake.profile_calls == 1
    stored = service.store.get()
    assert stored is not None
    assert "manual-token-value" not in stored.encrypted_access_token


@pytest.mark.asyncio
async def test_auto_renew_runs_when_token_is_inside_renewal_window(tmp_path):
    service, fake = make_service(tmp_path, renew_before_minutes=180)
    await service.save_manual_token(
        dhan_client_id="123456",
        access_token="manual-token-value-1234567890",
        expiry_time=now_utc() + timedelta(minutes=100),
        validate_with_dhan=False,
    )

    renewed, status, message = await service.renew_if_needed(force=False)

    assert renewed is True
    assert status.token_source == "renewed"
    assert status.masked_token == "renewe...7890"
    assert message == "Token renewed successfully."
    assert fake.renew_calls == 1


@pytest.mark.asyncio
async def test_expired_token_requires_manual_fallback(tmp_path):
    service, fake = make_service(tmp_path)
    await service.save_manual_token(
        dhan_client_id="123456",
        access_token="manual-token-value-1234567890",
        expiry_time=now_utc() - timedelta(minutes=1),
        validate_with_dhan=False,
    )

    renewed, status, message = await service.renew_if_needed(force=False)

    assert renewed is False
    assert status.state == "expired"
    assert "manual fallback" in message
    assert fake.renew_calls == 0


@pytest.mark.asyncio
async def test_force_renew_still_calls_dhan_when_local_expiry_is_stale(tmp_path):
    service, fake = make_service(tmp_path)
    await service.save_manual_token(
        dhan_client_id="123456",
        access_token="manual-token-value-1234567890",
        expiry_time=now_utc() - timedelta(minutes=1),
        validate_with_dhan=False,
    )

    renewed, status, message = await service.renew_if_needed(force=True)

    assert renewed is True
    assert status.token_source == "renewed"
    assert message == "Token renewed successfully."
    assert fake.renew_calls == 1


@pytest.mark.asyncio
async def test_active_token_with_deactive_data_plan_blocks_historical_fetch(tmp_path):
    service, _ = make_service(tmp_path)
    service.store.upsert_token(
        dhan_client_id="123456",
        encrypted_access_token=service._crypto().encrypt("manual-token-value-1234567890"),
        token_source="manual",
        expiry_time=now_utc() + timedelta(hours=20),
        profile={
            "dhanClientId": "123456",
            "tokenValidity": "31/12/2026 23:59",
            "dataPlan": "Deactive",
            "dataValidity": "NA",
        },
    )

    status = service.status()

    assert status.state == "active"
    assert status.data_plan == "Deactive"
    assert status.data_api_active is False
    assert status.historical_fetch_allowed is False
    assert status.historical_block_reason == "Dhan data API is inactive or pending renewal."


def test_expiring_soon_token_with_active_data_plan_can_fetch_historical_data():
    data_api_active, historical_fetch_allowed, reason = derive_data_api_status("expiring_soon", "Active")

    assert data_api_active is True
    assert historical_fetch_allowed is True
    assert reason == ""
