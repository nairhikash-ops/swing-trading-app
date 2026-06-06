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


class FakeReversalOpportunityService:
    def __init__(self, snapshot_error: Exception | None = None, outcome_error: Exception | None = None) -> None:
        self.snapshot_error = snapshot_error
        self.outcome_error = outcome_error
        self.snapshot_calls = 0
        self.outcome_calls = 0
        self.snapshot_kwargs: dict | None = None
        self.outcome_limit: int | None = None

    def refresh_nifty_500_snapshot(self, **kwargs) -> dict:
        self.snapshot_calls += 1
        self.snapshot_kwargs = kwargs
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return {"id": 25, "item_count": 7}

    def update_outcomes(self, limit: int) -> dict:
        self.outcome_calls += 1
        self.outcome_limit = limit
        if self.outcome_error is not None:
            raise self.outcome_error
        return {
            "checked_count": 7,
            "updated_count": 6,
            "complete_count": 2,
            "partial_count": 3,
            "not_enough_future_candles_count": 1,
        }


class FakeDemoAutomationService:
    def __init__(self) -> None:
        self.calls = 0
        self.historical_statuses: list[dict] = []

    async def run_once(self, historical_status: dict) -> dict:
        self.calls += 1
        self.historical_statuses.append(historical_status)
        return {"status": "ok", "id": 99}


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
async def test_data_maintenance_prunes_even_when_fetch_is_running(tmp_path):
    historical = FakeHistoricalService({"status": "running", "id": 10})
    scheduler = DataMaintenanceScheduler(
        Settings(app_secret_key="a" * 44, data_dir=tmp_path),
        FakeTokenService(active_token_status()),
        historical,
    )

    result = await scheduler.run_once()

    assert result["status"] == "ok"
    assert result["historical_status"] == "running"
    assert result["deleted_candle_count"] == 12
    assert historical.fetch_calls == 1
    assert historical.prune_calls == 1


@pytest.mark.parametrize("status", ["up_to_date", "completed", "completed_with_errors"])
@pytest.mark.asyncio
async def test_data_maintenance_refreshes_reversal_snapshot_when_historical_is_usable(tmp_path, status):
    historical = FakeHistoricalService({"status": status, "id": 10})
    reversal = FakeReversalOpportunityService()
    scheduler = DataMaintenanceScheduler(
        Settings(
            app_secret_key="a" * 44,
            data_dir=tmp_path,
            reversal_opportunity_min_entry_quality_score=65,
            reversal_opportunity_limit=123,
            reversal_opportunity_outcome_refresh_limit=456,
        ),
        FakeTokenService(active_token_status()),
        historical,
        reversal_opportunity_service=reversal,
    )

    result = await scheduler.run_once()

    assert reversal.snapshot_calls == 1
    assert reversal.snapshot_kwargs == {
        "limit": 123,
        "include_watch_only": False,
        "min_score": 0.0,
        "min_entry_quality_score": 65.0,
    }
    assert result["reversal_snapshot_status"] == "ok"
    assert result["reversal_snapshot_run_id"] == 25
    assert result["reversal_snapshot_item_count"] == 7
    assert reversal.outcome_calls == 1
    assert reversal.outcome_limit == 456
    assert result["reversal_outcome_status"] == "ok"
    assert result["reversal_outcome_checked_count"] == 7


@pytest.mark.asyncio
async def test_data_maintenance_skips_reversal_snapshot_when_historical_is_not_usable(tmp_path):
    historical = FakeHistoricalService({"status": "running", "id": 10})
    reversal = FakeReversalOpportunityService()
    scheduler = DataMaintenanceScheduler(
        Settings(app_secret_key="a" * 44, data_dir=tmp_path),
        FakeTokenService(active_token_status()),
        historical,
        reversal_opportunity_service=reversal,
    )

    result = await scheduler.run_once()

    assert reversal.snapshot_calls == 0
    assert result["reversal_snapshot_status"] == "skipped"
    assert reversal.outcome_calls == 1
    assert result["reversal_outcome_status"] == "ok"


@pytest.mark.asyncio
async def test_data_maintenance_reversal_snapshot_failure_does_not_stop_demo_automation(tmp_path):
    reversal = FakeReversalOpportunityService(snapshot_error=RuntimeError("snapshot broke"))
    demo = FakeDemoAutomationService()
    scheduler = DataMaintenanceScheduler(
        Settings(app_secret_key="a" * 44, data_dir=tmp_path),
        FakeTokenService(active_token_status()),
        FakeHistoricalService({"status": "up_to_date", "id": 10}),
        demo_automation_service=demo,
        reversal_opportunity_service=reversal,
    )

    result = await scheduler.run_once()

    assert result["reversal_snapshot_status"] == "error"
    assert "snapshot broke" in str(result["reversal_snapshot_error"])
    assert result["reversal_outcome_status"] == "ok"
    assert demo.calls == 1
    assert result["demo_automation_status"] == "ok"


@pytest.mark.asyncio
async def test_data_maintenance_reversal_outcome_failure_does_not_stop_demo_automation(tmp_path):
    reversal = FakeReversalOpportunityService(outcome_error=RuntimeError("outcome broke"))
    demo = FakeDemoAutomationService()
    scheduler = DataMaintenanceScheduler(
        Settings(app_secret_key="a" * 44, data_dir=tmp_path),
        FakeTokenService(active_token_status()),
        FakeHistoricalService({"status": "up_to_date", "id": 10}),
        demo_automation_service=demo,
        reversal_opportunity_service=reversal,
    )

    result = await scheduler.run_once()

    assert result["reversal_snapshot_status"] == "ok"
    assert result["reversal_outcome_status"] == "error"
    assert "outcome broke" in str(result["reversal_outcome_error"])
    assert demo.calls == 1
    assert result["demo_automation_status"] == "ok"


@pytest.mark.asyncio
async def test_data_maintenance_skips_reversal_automation_when_disabled(tmp_path):
    reversal = FakeReversalOpportunityService()
    scheduler = DataMaintenanceScheduler(
        Settings(
            app_secret_key="a" * 44,
            data_dir=tmp_path,
            reversal_opportunity_automation_enabled=False,
        ),
        FakeTokenService(active_token_status()),
        FakeHistoricalService({"status": "up_to_date", "id": 10}),
        reversal_opportunity_service=reversal,
    )

    result = await scheduler.run_once()

    assert reversal.snapshot_calls == 0
    assert reversal.outcome_calls == 0
    assert result["reversal_snapshot_status"] == "disabled"
    assert result["reversal_outcome_status"] == "disabled"
