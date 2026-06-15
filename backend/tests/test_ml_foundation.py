from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.data_maintenance import DataMaintenanceScheduler
from app.main import app, get_ml_service_dep
from app.ml_foundation import (
    ML_LABEL_NAME,
    ML_MODEL_NAME,
    MLFoundationService,
    MLFoundationStore,
)
from app.schemas import TokenStatusResponse
from app.store import TokenStore
from app.timezone import now_utc


def make_ml_service(tmp_path) -> MLFoundationService:
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    return MLFoundationService(settings=settings, store=MLFoundationStore(token_store))


def test_ml_status_returns_safe_default(tmp_path):
    service = make_ml_service(tmp_path)

    status = service.status()

    assert status["status"] == "not_started"
    assert status["current_job"] is None
    assert status["active_model"] is None
    assert status["model_count"] == 0
    assert status["training_available"] is False
    assert status["contract"]["model_name"] == ML_MODEL_NAME
    assert status["contract"]["label_name"] == ML_LABEL_NAME


def test_ml_training_state_transitions_do_not_run_training(tmp_path):
    service = make_ml_service(tmp_path)

    started = service.start_training()
    paused = service.pause_training()
    resumed = service.resume_training()
    cancelled = service.cancel_training()

    assert started["status"] == "running"
    assert started["phase"] == "idle"
    assert started["total_instruments"] == 0
    assert started["generated_samples"] == 0
    assert paused["status"] == "paused"
    assert resumed["status"] == "running"
    assert cancelled["status"] == "cancelled"
    assert cancelled["generated_samples"] == 0
    assert cancelled["trainable_samples"] == 0


def test_ml_start_rejects_existing_active_job(tmp_path):
    service = make_ml_service(tmp_path)

    service.start_training()

    with pytest.raises(ValueError, match="already running or paused"):
        service.start_training()


def test_ml_model_registry_list_is_empty_by_default(tmp_path):
    service = make_ml_service(tmp_path)

    assert service.models() == []
    assert service.model(1) is None


def test_ml_api_endpoints_are_manual_and_safe(tmp_path):
    service = make_ml_service(tmp_path)
    app.dependency_overrides[get_ml_service_dep] = lambda: service
    try:
        client = TestClient(app)
        status = client.get("/api/ml/status")
        started = client.post("/api/ml/training/start")
        training_status = client.get("/api/ml/training/status")
        models = client.get("/api/ml/models")
        missing_model = client.get("/api/ml/models/999")
    finally:
        app.dependency_overrides.clear()

    assert status.status_code == 200
    assert status.json()["status"] == "not_started"
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert started.json()["generated_samples"] == 0
    assert training_status.status_code == 200
    assert training_status.json()["current_job"]["status"] == "running"
    assert models.status_code == 200
    assert models.json() == []
    assert missing_model.status_code == 404


class FakeTokenService:
    async def renew_if_needed(self, force: bool = False):
        return (
            False,
            TokenStatusResponse(
                state="active",
                has_token=True,
                expiry_time=now_utc() + timedelta(hours=1),
                data_plan="Active",
                data_api_active=True,
                historical_fetch_allowed=True,
            ),
            "ok",
        )


class FakeHistoricalService:
    def __init__(self) -> None:
        self.fetch_calls = 0

    async def start_or_resume_nifty_500_fetch(self):
        self.fetch_calls += 1
        return {"status": "up_to_date", "id": 1}

    def prune_retention_window(self):
        raise AssertionError("Pruning must not run in this ML foundation test.")


@pytest.mark.asyncio
async def test_data_maintenance_does_not_start_ml(tmp_path):
    historical = FakeHistoricalService()
    scheduler = DataMaintenanceScheduler(
        Settings(app_secret_key="a" * 44, data_dir=tmp_path),
        FakeTokenService(),
        historical,
    )

    result = await scheduler.run_once()

    assert result["status"] == "ok"
    assert historical.fetch_calls == 1
    assert "ml_status" not in result
    assert "ml_training_status" not in result
