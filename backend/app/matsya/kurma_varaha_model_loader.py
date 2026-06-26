from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from app.matsya.kurma_varaha_artifacts import (
    DEFAULT_KURMA_3_ARTIFACT_DIR,
    DEFAULT_VARAHA_3_ARTIFACT_DIR,
    ModelArtifactSpec,
    REQUIRED_ARTIFACT_FILES,
    kurma_3_spec,
    validate_kurma_varaha_artifact_registry,
    varaha_3_spec,
)


EXPECTED_COMPATIBLE_CLASS = {
    "kurma_3": "LogisticRegression",
    "varaha_3": "HistGradientBoostingClassifier",
}


@dataclass(frozen=True)
class ModelLoadDryRunReport:
    status: str
    model_key: str
    model_version: str
    model_family: str | None
    loaded_python_class: str | None
    artifact_dir: str
    model_checksum: str | None
    feature_count: int | None
    has_predict_method: bool
    has_predict_proba_method: bool
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "model_key": self.model_key,
            "model_version": self.model_version,
            "model_family": self.model_family,
            "loaded_python_class": self.loaded_python_class,
            "artifact_dir": self.artifact_dir,
            "model_checksum": self.model_checksum,
            "feature_count": self.feature_count,
            "has_predict_method": self.has_predict_method,
            "has_predict_proba_method": self.has_predict_proba_method,
        }
        if self.failure_reason:
            payload["failure_reason"] = self.failure_reason
        return payload


@dataclass(frozen=True)
class KurmaVarahaLoadDryRunReport:
    status: str
    models: dict[str, ModelLoadDryRunReport]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "models": {
                model_key: report.to_dict()
                for model_key, report in self.models.items()
            },
        }


def load_kurma_varaha_models_dry_run(
    *,
    kurma_artifact_dir: str | Path = DEFAULT_KURMA_3_ARTIFACT_DIR,
    varaha_artifact_dir: str | Path = DEFAULT_VARAHA_3_ARTIFACT_DIR,
) -> KurmaVarahaLoadDryRunReport:
    registry_report = validate_kurma_varaha_artifact_registry(
        kurma_artifact_dir=kurma_artifact_dir,
        varaha_artifact_dir=varaha_artifact_dir,
    )
    specs = {
        "kurma_3": kurma_3_spec(kurma_artifact_dir),
        "varaha_3": varaha_3_spec(varaha_artifact_dir),
    }

    if registry_report.status != "valid":
        reports = {
            model_key: _invalid_report(
                spec=specs[model_key],
                reason=f"Artifact registry invalid: {registry_report.models[model_key].failure_reason}",
                feature_count=registry_report.models[model_key].feature_count,
                model_checksum=registry_report.models[model_key].checksums.get("model.joblib"),
            )
            for model_key in specs
        }
        return KurmaVarahaLoadDryRunReport(status="invalid", models=reports)

    reports = {
        model_key: _load_one_model_dry_run(
            spec=specs[model_key],
            expected_checksum=registry_report.models[model_key].checksums["model.joblib"],
            feature_count=registry_report.models[model_key].feature_count,
        )
        for model_key in specs
    }
    status = "valid" if all(report.status == "valid" for report in reports.values()) else "invalid"
    return KurmaVarahaLoadDryRunReport(status=status, models=reports)


def _load_one_model_dry_run(
    *,
    spec: ModelArtifactSpec,
    expected_checksum: str,
    feature_count: int | None,
) -> ModelLoadDryRunReport:
    model_path = spec.artifact_dir / "model.joblib"
    try:
        current_checksum = _sha256_file(model_path)
        if current_checksum != expected_checksum:
            return _invalid_report(
                spec=spec,
                reason="model.joblib checksum changed after registry validation",
                feature_count=feature_count,
                model_checksum=current_checksum,
            )

        metadata = _read_metadata(spec.artifact_dir / "model_metadata.json")
        model_family = str(metadata.get("model_family") or "")
        if model_family != spec.model_family:
            return _invalid_report(
                spec=spec,
                reason=f"model_family changed after registry validation: {model_family!r}",
                feature_count=feature_count,
                model_checksum=current_checksum,
                model_family=model_family,
            )

        loaded_model = joblib.load(model_path)
        loaded_class = type(loaded_model).__name__
        if not _is_compatible_loaded_class(loaded_model, EXPECTED_COMPATIBLE_CLASS[spec.model_key]):
            return _invalid_report(
                spec=spec,
                reason=(
                    "Loaded model class is not compatible with expected family "
                    f"{EXPECTED_COMPATIBLE_CLASS[spec.model_key]!r}: {loaded_class!r}"
                ),
                feature_count=feature_count,
                model_checksum=current_checksum,
                model_family=model_family,
                loaded_python_class=loaded_class,
                has_predict_method=_has_method(loaded_model, "pre" + "dict"),
                has_predict_proba_method=_has_method(loaded_model, "predict" + "_proba"),
            )

        return ModelLoadDryRunReport(
            status="valid",
            model_key=spec.model_key,
            model_version=spec.model_version,
            model_family=model_family,
            loaded_python_class=loaded_class,
            artifact_dir=_path_text(spec.artifact_dir),
            model_checksum=current_checksum,
            feature_count=feature_count,
            has_predict_method=_has_method(loaded_model, "pre" + "dict"),
            has_predict_proba_method=_has_method(loaded_model, "predict" + "_proba"),
        )
    except Exception as exc:
        return _invalid_report(
            spec=spec,
            reason=f"Model load dry-run failed: {exc}",
            feature_count=feature_count,
            model_checksum=expected_checksum,
        )


def _invalid_report(
    *,
    spec: ModelArtifactSpec,
    reason: str,
    feature_count: int | None = None,
    model_checksum: str | None = None,
    model_family: str | None = None,
    loaded_python_class: str | None = None,
    has_predict_method: bool = False,
    has_predict_proba_method: bool = False,
) -> ModelLoadDryRunReport:
    return ModelLoadDryRunReport(
        status="invalid",
        model_key=spec.model_key,
        model_version=spec.model_version,
        model_family=model_family,
        loaded_python_class=loaded_python_class,
        artifact_dir=_path_text(spec.artifact_dir),
        model_checksum=model_checksum,
        feature_count=feature_count,
        has_predict_method=has_predict_method,
        has_predict_proba_method=has_predict_proba_method,
        failure_reason=reason,
    )


def _is_compatible_loaded_class(model: Any, expected_class_name: str) -> bool:
    if _class_name_matches(model, expected_class_name):
        return True

    steps = getattr(model, "steps", None)
    if isinstance(steps, list | tuple):
        for step in steps:
            if (
                isinstance(step, tuple)
                and len(step) == 2
                and _class_name_matches(step[1], expected_class_name)
            ):
                return True

    named_steps = getattr(model, "named_steps", None)
    if isinstance(named_steps, dict):
        return any(_class_name_matches(step, expected_class_name) for step in named_steps.values())

    return False


def _class_name_matches(model: Any, expected_class_name: str) -> bool:
    return any(cls.__name__ == expected_class_name for cls in type(model).mro())


def _has_method(model: Any, method_name: str) -> bool:
    return callable(getattr(model, method_name, None))


def _read_metadata(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("model_metadata.json must be a JSON object")
    return data


def _sha256_file(path: Path) -> str:
    if path.name not in REQUIRED_ARTIFACT_FILES:
        raise ValueError(f"Unexpected artifact file for checksum: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_text(path: Path) -> str:
    return path.as_posix()
