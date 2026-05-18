from datetime import timedelta

import pytest

from app.config import Settings
from app.data_maintenance import DataMaintenanceScheduler
from app.schemas import TokenStatusResponse
from app.timezone import now_utc


class FakeTokenService:
    def __init__(self, status: TokenStatusResponse, message: str = "Token does not need renewal yet.") -> None:
        self.status = status
        self.message = message
        self.calls = 0

    async def renew_if_needed(self, force: bool = False):
        self.calls += 1
        return False, self.status, self.message


class FakeHistoricalService:
    def __init__(self, status: dict) -> None:
        self.status = status
        self.fetch_calls = 0
        self.prune_calls = 0

    async def start_or_resume_nifty_500_fetch(self) -> dict:
        self.fetch_calls += 1
        return self.status

    def prune_retention_window(self) -> dict:
        self.prune_calls += 1
        return {"cutoff_date": "2025-05-18", "deleted_candle_count": 12}


def active_token_status() -> TokenStatusResponse:
    return TokenStatusResponse(
        state="active",
        has_token=True,
        expiry_time=now_utc() + timedelta(hours=20),
    )


@pytest.mark.asyncio
async def test_data_maintenance_skips_when_token_is_expired(tmp_path):
    scheduler = DataMaintenanceScheduler(
        Settings(app_secret_key="a" * 44, data_dir=tmp_path),
        FakeTokenService(
            TokenStatusResponse(
                state="expired",
                has_token=True,
                expiry_time=now_utc() - timedelta(minutes=1),
            ),
            "Token is expired. Use the manual fallback update flow.",
        ),
        FakeHistoricalService({"status": "up_to_date", "id": 0}),
    )

    result = await scheduler.run_once()

    assert result["status"] == "skipped"
    assert result["token_state"] == "expired"
    assert scheduler.historical_service.fetch_calls == 0


@pytest.mark.asyncio
async def test_data_maintenance_fetches_and_prunes_when_current_window_is_fresh(tmp_path):
    historical = FakeHistoricalService({"status": "up_to_date", "id": 0})
    scheduler = DataMaintenanceScheduler(
        Settings(app_secret_key="a" * 44, data_dir=tmp_path),
        FakeTokenService(active_token_status()),
        historical,
    )

    result = await scheduler.run_once()

    assert result["status"] == "ok"
    assert result["historical_status"] == "up_to_date"
    assert result["deleted_candle_count"] == 12
    assert historical.fetch_calls == 1
    assert historical.prune_calls == 1


@pytest.mark.asyncio
async def test_data_maintenance_does_not_prune_while_fetch_is_running(tmp_path):
    historical = FakeHistoricalService({"status": "running", "id": 10})
    scheduler = DataMaintenanceScheduler(
        Settings(app_secret_key="a" * 44, data_dir=tmp_path),
        FakeTokenService(active_token_status()),
        historical,
    )

    result = await scheduler.run_once()

    assert result["status"] == "ok"
    assert result["historical_status"] == "running"
    assert historical.fetch_calls == 1
    assert historical.prune_calls == 0
