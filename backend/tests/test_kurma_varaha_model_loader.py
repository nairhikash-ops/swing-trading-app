from __future__ import annotations

import inspect
import json
from pathlib import Path

import joblib
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from app.matsya import kurma_varaha_model_loader as loader
from app.matsya.kurma_varaha_artifacts import (
    DATASET_VERSION,
    FEATURE_NAMES,
    KURMA_3_MODEL_VERSION,
    MODEL_FEATURE_COUNT,
    SPLIT_VERSION,
    VARAHA_3_MODEL_VERSION,
)
from app.matsya.kurma_varaha_model_loader import load_kurma_varaha_models_dry_run


def _write_artifact_dir(
    artifact_dir: Path,
    *,
    model: object,
    model_version: str,
    model_alias: str,
    model_family: str,
    metadata_overrides: dict[str, object] | None = None,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, artifact_dir / "model.joblib")
    (artifact_dir / "feature_schema.json").write_text(json.dumps(FEATURE_NAMES), encoding="utf-8")
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


def _write_kurma(artifact_dir: Path, *, model: object | None = None, **kwargs: object) -> None:
    _write_artifact_dir(
        artifact_dir,
        model=model or LogisticRegression(),
        model_version=KURMA_3_MODEL_VERSION,
        model_alias="Kurma 3",
        model_family="LogisticRegression",
        **kwargs,
    )


def _write_varaha(artifact_dir: Path, *, model: object | None = None, **kwargs: object) -> None:
    _write_artifact_dir(
        artifact_dir,
        model=model or HistGradientBoostingClassifier(),
        model_version=VARAHA_3_MODEL_VERSION,
        model_alias="Varaha 3",
        model_family="HistGradientBoostingClassifier",
        **kwargs,
    )


def _write_both(tmp_path: Path) -> tuple[Path, Path]:
    kurma_dir = tmp_path / KURMA_3_MODEL_VERSION
    varaha_dir = tmp_path / VARAHA_3_MODEL_VERSION
    _write_kurma(kurma_dir)
    _write_varaha(varaha_dir)
    return kurma_dir, varaha_dir


def test_loader_does_not_load_model_if_registry_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_calls: list[Path] = []

    def fake_load(path: Path) -> object:
        load_calls.append(path)
        return object()

    monkeypatch.setattr(loader.joblib, "load", fake_load)
    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=tmp_path / "missing-kurma",
        varaha_artifact_dir=tmp_path / "missing-varaha",
    )

    assert report.status == "invalid"
    assert load_calls == []


def test_loader_loads_valid_synthetic_kurma_like_object(tmp_path: Path) -> None:
    kurma_dir, varaha_dir = _write_both(tmp_path)

    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )

    assert report.models["kurma_3"].status == "valid"
    assert report.models["kurma_3"].loaded_python_class == "LogisticRegression"


def test_loader_loads_valid_synthetic_varaha_like_object(tmp_path: Path) -> None:
    kurma_dir, varaha_dir = _write_both(tmp_path)

    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )

    assert report.models["varaha_3"].status == "valid"
    assert report.models["varaha_3"].loaded_python_class == "HistGradientBoostingClassifier"


def test_loader_reports_class_name(tmp_path: Path) -> None:
    kurma_dir, varaha_dir = _write_both(tmp_path)

    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )

    assert report.models["kurma_3"].loaded_python_class == "LogisticRegression"
    assert report.models["varaha_3"].loaded_python_class == "HistGradientBoostingClassifier"


def test_loader_reports_whether_prediction_methods_exist(tmp_path: Path) -> None:
    kurma_dir, varaha_dir = _write_both(tmp_path)

    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )

    assert report.models["kurma_3"].has_predict_method is True
    assert report.models["kurma_3"].has_predict_proba_method is True
    assert report.models["varaha_3"].has_predict_method is True
    assert report.models["varaha_3"].has_predict_proba_method is True


def test_loader_does_not_call_prediction_methods(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kurma_dir = tmp_path / KURMA_3_MODEL_VERSION
    varaha_dir = tmp_path / VARAHA_3_MODEL_VERSION
    _write_kurma(kurma_dir)
    _write_varaha(varaha_dir)
    model = LogisticRegression()

    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("model method must not be called during dry-run")

    setattr(model, "pre" + "dict", fail_if_called)
    setattr(model, "predict" + "_proba", fail_if_called)
    monkeypatch.setattr(loader.joblib, "load", lambda path: model)

    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )

    assert report.models["kurma_3"].status == "valid"


def test_wrong_loaded_class_fails_closed(tmp_path: Path) -> None:
    kurma_dir = tmp_path / KURMA_3_MODEL_VERSION
    varaha_dir = tmp_path / VARAHA_3_MODEL_VERSION
    _write_kurma(kurma_dir, model=HistGradientBoostingClassifier())
    _write_varaha(varaha_dir)

    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )

    assert report.status == "invalid"
    assert report.models["kurma_3"].status == "invalid"
    assert "not compatible" in report.models["kurma_3"].failure_reason


def test_registry_valid_but_joblib_load_failure_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kurma_dir, varaha_dir = _write_both(tmp_path)

    def fail_load(path: Path) -> object:
        raise RuntimeError("synthetic load failure")

    monkeypatch.setattr(loader.joblib, "load", fail_load)
    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )

    assert report.status == "invalid"
    assert "synthetic load failure" in report.models["kurma_3"].failure_reason


def test_both_model_dry_run_is_valid_only_when_both_load_correctly(tmp_path: Path) -> None:
    kurma_dir, varaha_dir = _write_both(tmp_path)
    valid_report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )
    assert valid_report.status == "valid"

    _write_varaha(varaha_dir, model=LogisticRegression())
    invalid_report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )
    assert invalid_report.status == "invalid"
    assert invalid_report.models["kurma_3"].status == "valid"
    assert invalid_report.models["varaha_3"].status == "invalid"


def test_no_scoring_output_is_produced(tmp_path: Path) -> None:
    kurma_dir, varaha_dir = _write_both(tmp_path)

    report = load_kurma_varaha_models_dry_run(
        kurma_artifact_dir=kurma_dir,
        varaha_artifact_dir=varaha_dir,
    )

    assert report.status == "valid"
    assert not (tmp_path / "test_predictions.csv").exists()
    assert not (tmp_path / "evaluation_metrics.json").exists()
    assert not (tmp_path / "score_metadata.json").exists()


def test_loader_source_contains_no_prediction_or_scoring_calls() -> None:
    source = inspect.getsource(loader)

    assert (".pre" + "dict(") not in source
    assert ("predict" + "_proba(") not in source
    assert "score_timesplit" not in source
