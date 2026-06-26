from __future__ import annotations

import inspect
import json
from pathlib import Path

from app.matsya import kurma_varaha_artifacts as artifacts
from app.matsya.kurma_varaha_artifacts import (
    DATASET_VERSION,
    FEATURE_NAMES,
    KURMA_3_MODEL_VERSION,
    MODEL_FEATURE_COUNT,
    SPLIT_VERSION,
    VARAHA_3_MODEL_VERSION,
    kurma_3_spec,
    validate_kurma_varaha_artifact_registry,
    validate_model_artifacts,
    varaha_3_spec,
)


def _write_artifact_dir(
    artifact_dir: Path,
    *,
    model_version: str,
    model_alias: str,
    model_family: str,
    feature_schema: list[str] | None = None,
    metadata_overrides: dict[str, object] | None = None,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    features = feature_schema or FEATURE_NAMES
    (artifact_dir / "model.joblib").write_bytes(b"synthetic model bytes; not loaded")
    (artifact_dir / "feature_schema.json").write_text(json.dumps(features), encoding="utf-8")
    metadata = {
        "model_version": model_version,
        "model_alias": model_alias,
        "model_family": model_family,
        "dataset_version": DATASET_VERSION,
        "split_version": SPLIT_VERSION,
        "feature_count": str(MODEL_FEATURE_COUNT),
        "train_only": True,
        "test_data_used": False,
    }
    metadata.update(metadata_overrides or {})
    (artifact_dir / "model_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def _write_kurma(artifact_dir: Path, **kwargs: object) -> None:
    _write_artifact_dir(
        artifact_dir,
        model_version=KURMA_3_MODEL_VERSION,
        model_alias="Kurma 3",
        model_family="LogisticRegression",
        **kwargs,
    )


def _write_varaha(artifact_dir: Path, **kwargs: object) -> None:
    _write_artifact_dir(
        artifact_dir,
        model_version=VARAHA_3_MODEL_VERSION,
        model_alias="Varaha 3",
        model_family="HistGradientBoostingClassifier",
        **kwargs,
    )


def test_valid_synthetic_kurma_3_artifact_passes(tmp_path: Path) -> None:
    artifact_dir = tmp_path / KURMA_3_MODEL_VERSION
    _write_kurma(artifact_dir)

    report = validate_model_artifacts(kurma_3_spec(artifact_dir))

    assert report.status == "valid"
    assert report.model_key == "kurma_3"
    assert report.feature_count == 608
    assert report.feature_schema_matches_phase1 is True
    assert report.metadata_matches_expected is True


def test_valid_synthetic_varaha_3_artifact_passes(tmp_path: Path) -> None:
    artifact_dir = tmp_path / VARAHA_3_MODEL_VERSION
    _write_varaha(artifact_dir)

    report = validate_model_artifacts(varaha_3_spec(artifact_dir))

    assert report.status == "valid"
    assert report.model_key == "varaha_3"
    assert report.feature_count == 608
    assert report.feature_schema_matches_phase1 is True
    assert report.metadata_matches_expected is True


def test_missing_directory_fails_closed(tmp_path: Path) -> None:
    report = validate_model_artifacts(kurma_3_spec(tmp_path / "missing"))

    assert report.status == "invalid"
    assert "directory missing" in report.failure_reason.lower()


def test_missing_required_file_fails_closed(tmp_path: Path) -> None:
    artifact_dir = tmp_path / KURMA_3_MODEL_VERSION
    _write_kurma(artifact_dir)
    (artifact_dir / "model_metadata.json").unlink()

    report = validate_model_artifacts(kurma_3_spec(artifact_dir))

    assert report.status == "invalid"
    assert report.required_files_present["model_metadata.json"] is False
    assert "required artifact file missing" in report.failure_reason.lower()


def test_wrong_feature_count_fails_closed(tmp_path: Path) -> None:
    artifact_dir = tmp_path / KURMA_3_MODEL_VERSION
    _write_kurma(artifact_dir, feature_schema=FEATURE_NAMES[:-1])

    report = validate_model_artifacts(kurma_3_spec(artifact_dir))

    assert report.status == "invalid"
    assert report.feature_count == 607
    assert "feature count" in report.failure_reason.lower()


def test_wrong_feature_order_fails_closed(tmp_path: Path) -> None:
    artifact_dir = tmp_path / KURMA_3_MODEL_VERSION
    wrong_features = FEATURE_NAMES.copy()
    wrong_features[0], wrong_features[1] = wrong_features[1], wrong_features[0]
    _write_kurma(artifact_dir, feature_schema=wrong_features)

    report = validate_model_artifacts(kurma_3_spec(artifact_dir))

    assert report.status == "invalid"
    assert "first 10 features" in report.failure_reason.lower()


def test_wrong_dataset_version_fails_closed(tmp_path: Path) -> None:
    artifact_dir = tmp_path / KURMA_3_MODEL_VERSION
    _write_kurma(
        artifact_dir,
        metadata_overrides={"dataset_version": "stock_opportunity_ohlcv_regime_v2"},
    )

    report = validate_model_artifacts(kurma_3_spec(artifact_dir))

    assert report.status == "invalid"
    assert "dataset_version" in report.failure_reason


def test_wrong_model_family_fails_closed(tmp_path: Path) -> None:
    artifact_dir = tmp_path / VARAHA_3_MODEL_VERSION
    _write_varaha(artifact_dir, metadata_overrides={"model_family": "LogisticRegression"})

    report = validate_model_artifacts(varaha_3_spec(artifact_dir))

    assert report.status == "invalid"
    assert "model_family" in report.failure_reason


def test_registry_is_valid_only_when_both_models_pass(tmp_path: Path) -> None:
    kurma_dir = tmp_path / KURMA_3_MODEL_VERSION
    varaha_dir = tmp_path / VARAHA_3_MODEL_VERSION
    _write_kurma(kurma_dir)

    missing_varaha_report = validate_kurma_varaha_artifact_registry(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )
    assert missing_varaha_report.status == "invalid"
    assert missing_varaha_report.models["kurma_3"].status == "valid"
    assert missing_varaha_report.models["varaha_3"].status == "invalid"

    _write_varaha(varaha_dir)
    valid_report = validate_kurma_varaha_artifact_registry(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )
    assert valid_report.status == "valid"


def test_checksums_are_included(tmp_path: Path) -> None:
    artifact_dir = tmp_path / KURMA_3_MODEL_VERSION
    _write_kurma(artifact_dir)

    report = validate_model_artifacts(kurma_3_spec(artifact_dir))

    assert set(report.checksums) == {
        "model.joblib",
        "feature_schema.json",
        "model_metadata.json",
    }
    assert all(len(value) == 64 for value in report.checksums.values())


def test_no_model_inference_is_performed() -> None:
    source = inspect.getsource(artifacts)

    assert "joblib.load" not in source
    assert (".pre" + "dict(") not in source
    assert ("predict" + "_proba") not in source
    assert (".f" + "it(") not in source
