from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.matsya.latest_regime_v3_snapshot import MODEL_FEATURE_COUNT, SnapshotResult
from app.matsya.latest_regime_v3_worker import (
    SNAPSHOT_FILENAME,
    SNAPSHOT_META_FILENAME,
    run_latest_regime_v3_snapshot_worker,
)


class FakeWorkerRepository:
    def __init__(self, readiness: dict[str, Any] | None = None) -> None:
        self._readiness = readiness or clean_readiness()
        self.readiness_calls = 0
        self.mapped_symbols_calls = 0
        self.latest_candles_calls = 0

    def readiness(self) -> dict[str, Any]:
        self.readiness_calls += 1
        return self._readiness

    def mapped_symbols(self) -> list[dict[str, Any]]:
        self.mapped_symbols_calls += 1
        return []

    def latest_candles(self, security_id: str, limit: int = 60) -> list[dict[str, Any]]:
        self.latest_candles_calls += 1
        return []


class RecordingGenerator:
    def __init__(self, *, sample_date: str = "2026-06-25", row_count: int = 2) -> None:
        self.sample_date = sample_date
        self.row_count = row_count
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, repository: Any, output_path: str | Path, meta_path: str | Path) -> SnapshotResult:
        output_file = Path(output_path)
        meta_file = Path(meta_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("symbol,security_id,sample_date\nAAA,1001,2026-06-25\n", encoding="utf-8")
        metadata = {
            "sample_date": self.sample_date,
            "row_count": self.row_count,
            "feature_count": MODEL_FEATURE_COUNT,
            "matsya_readiness_status": "ready",
        }
        meta_file.write_text(json.dumps(metadata), encoding="utf-8")
        self.calls.append(
            {
                "repository": repository,
                "output_path": output_file,
                "meta_path": meta_file,
            }
        )
        return SnapshotResult(
            output_path=str(output_file),
            meta_path=str(meta_file),
            metadata=metadata,
            feature_names=[f"feature_{index}" for index in range(MODEL_FEATURE_COUNT)],
        )


def clean_readiness() -> dict[str, Any]:
    return {
        "status": "ready",
        "latest_ohlcv_date": "2026-06-25",
        "latest_stored_candle_date": "2026-06-25",
        "expected_latest_candle_date": "2026-06-25",
        "latest_ohlcv_run_status": "completed",
        "expected_symbol_count": 2,
        "mapped_symbols": 2,
        "zero_candle_symbols": 0,
        "stale_symbols": 0,
        "missing_recent_symbol_dates": 0,
        "duplicate_count": 0,
        "null_count": 0,
        "null_ohlcv_count": 0,
        "bad_ohlc_count": 0,
        "negative_volume_count": 0,
    }


def test_worker_returns_not_ready_without_writing_snapshot_when_readiness_fails(tmp_path: Path) -> None:
    readiness = clean_readiness()
    readiness["status"] = "not_ready"
    readiness["latest_ohlcv_date"] = None
    generator = RecordingGenerator()

    result = run_latest_regime_v3_snapshot_worker(
        repository=FakeWorkerRepository(readiness),
        output_dir=tmp_path,
        generator=generator,
    )

    assert result.status == "not_ready"
    assert result.readiness_status == "not_ready"
    assert "Matsya readiness is not ready" in str(result.failure_reason)
    assert generator.calls == []
    assert not (tmp_path / SNAPSHOT_FILENAME).exists()
    assert not (tmp_path / SNAPSHOT_META_FILENAME).exists()


def test_worker_calls_snapshot_generator_when_readiness_is_ready(tmp_path: Path) -> None:
    repository = FakeWorkerRepository()
    generator = RecordingGenerator()

    result = run_latest_regime_v3_snapshot_worker(
        repository=repository,
        output_dir=tmp_path,
        generator=generator,
    )

    assert result.status == "success"
    assert repository.readiness_calls == 1
    assert len(generator.calls) == 1
    assert generator.calls[0]["repository"] is repository


def test_worker_returns_success_metadata_after_generation(tmp_path: Path) -> None:
    result = run_latest_regime_v3_snapshot_worker(
        repository=FakeWorkerRepository(),
        output_dir=tmp_path,
        generator=RecordingGenerator(sample_date="2026-06-25", row_count=3),
    )

    assert result.status == "success"
    assert result.sample_date == "2026-06-25"
    assert result.row_count == 3
    assert result.feature_count == 608
    assert result.readiness_status == "ready"
    assert result.failure_reason is None


def test_worker_preserves_phase1_output_paths(tmp_path: Path) -> None:
    result = run_latest_regime_v3_snapshot_worker(
        repository=FakeWorkerRepository(),
        output_dir=tmp_path,
        generator=RecordingGenerator(),
    )

    assert result.output_path == str(tmp_path / SNAPSHOT_FILENAME)
    assert result.meta_path == str(tmp_path / SNAPSHOT_META_FILENAME)


def test_worker_does_not_create_train_or_test_split_files(tmp_path: Path) -> None:
    run_latest_regime_v3_snapshot_worker(
        repository=FakeWorkerRepository(),
        output_dir=tmp_path,
        generator=RecordingGenerator(),
    )

    assert not (tmp_path / "train.csv").exists()
    assert not (tmp_path / "test.csv").exists()


def test_worker_is_idempotent_for_same_sample_date(tmp_path: Path) -> None:
    generator = RecordingGenerator()

    first = run_latest_regime_v3_snapshot_worker(
        repository=FakeWorkerRepository(),
        output_dir=tmp_path,
        generator=generator,
    )
    second = run_latest_regime_v3_snapshot_worker(
        repository=FakeWorkerRepository(),
        output_dir=tmp_path,
        generator=generator,
    )

    assert first.status == "success"
    assert second.status == "success"
    assert first.sample_date == second.sample_date == "2026-06-25"
    assert len(generator.calls) == 2
    assert (tmp_path / SNAPSHOT_FILENAME).exists()
    assert (tmp_path / SNAPSHOT_META_FILENAME).exists()


def test_worker_failure_returns_clear_error_without_partial_output(tmp_path: Path) -> None:
    def failing_generator(*, repository: Any, output_path: str | Path, meta_path: str | Path) -> SnapshotResult:
        output_file = Path(output_path)
        meta_file = Path(meta_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("partial csv", encoding="utf-8")
        output_file.with_suffix(output_file.suffix + ".tmp").write_text("temp csv", encoding="utf-8")
        meta_file.with_suffix(meta_file.suffix + ".tmp").write_text("temp meta", encoding="utf-8")
        raise RuntimeError("simulated snapshot failure")

    result = run_latest_regime_v3_snapshot_worker(
        repository=FakeWorkerRepository(),
        output_dir=tmp_path,
        generator=failing_generator,
    )

    assert result.status == "failed"
    assert result.failure_reason == "simulated snapshot failure"
    assert not (tmp_path / SNAPSHOT_FILENAME).exists()
    assert not (tmp_path / f"{SNAPSHOT_FILENAME}.tmp").exists()
    assert not (tmp_path / SNAPSHOT_META_FILENAME).exists()
    assert not (tmp_path / f"{SNAPSHOT_META_FILENAME}.tmp").exists()


def test_worker_source_does_not_call_scoring_model_predict_or_order_code() -> None:
    source = Path("app/matsya/latest_regime_v3_worker.py").read_text(encoding="utf-8").lower()
    script_source = Path("scripts/matsya_latest_regime_v3_worker.py").read_text(encoding="utf-8").lower()
    combined = source + script_source

    assert "joblib" not in combined
    assert "predict_proba" not in combined
    assert "score_timesplit" not in combined
    assert "kurma" not in combined
    assert "varaha" not in combined
    assert "dhanclient" not in combined
    assert "/orders" not in combined
    assert "broker" not in combined


def test_worker_source_does_not_mutate_matsya_ohlcv_data() -> None:
    source = Path("app/matsya/latest_regime_v3_worker.py").read_text(encoding="utf-8").upper()

    assert "INSERT INTO MATSYA.OHLCV_DAILY" not in source
    assert "UPDATE MATSYA.OHLCV_DAILY" not in source
    assert "DELETE FROM MATSYA.OHLCV_DAILY" not in source
    assert "TRUNCATE MATSYA.OHLCV_DAILY" not in source


def test_worker_hook_is_not_wired_into_scheduled_ohlcv_worker() -> None:
    source = Path("app/matsya/ohlcv_worker.py").read_text(encoding="utf-8")

    assert "latest_regime_v3_worker" not in source
    assert "run_latest_regime_v3_snapshot_worker" not in source
