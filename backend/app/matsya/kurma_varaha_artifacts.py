from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.matsya.latest_regime_v3_snapshot import (
    FEATURE_NAMES,
    MODEL_FEATURE_COUNT,
    REGIME_FEATURE_NAMES,
)


KURMA_3_MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_kurma_v3"
VARAHA_3_MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_varaha_v3"
DATASET_VERSION = "stock_opportunity_ohlcv_regime_v3"
SPLIT_VERSION = "timesplit_regime_v3"

DEFAULT_KURMA_3_ARTIFACT_DIR = Path(f"/app/data/models/{KURMA_3_MODEL_VERSION}")
DEFAULT_VARAHA_3_ARTIFACT_DIR = Path(f"/app/data/models/{VARAHA_3_MODEL_VERSION}")

REQUIRED_ARTIFACT_FILES = ("model.joblib", "feature_schema.json", "model_metadata.json")
EXPECTED_FIRST_10_FEATURES = [
    "c00_open_rel",
    "c00_high_rel",
    "c00_low_rel",
    "c00_close_rel",
    "c00_volume_rel",
    "c00_body_to_range",
    "c00_upper_wick_to_range",
    "c00_lower_wick_to_range",
    "c00_close_position_in_range",
    "c00_signed_body_to_range",
]
EXPECTED_LAST_8_FEATURES = REGIME_FEATURE_NAMES


@dataclass(frozen=True)
class ModelArtifactSpec:
    model_key: str
    model_version: str
    model_alias: str
    model_family: str
    dataset_version: str
    split_version: str
    feature_count: int
    artifact_dir: Path


@dataclass(frozen=True)
class ModelArtifactValidationReport:
    status: str
    model_key: str
    model_version: str
    artifact_dir: str
    required_files_present: dict[str, bool]
    feature_count: int | None
    feature_schema_matches_phase1: bool
    metadata_matches_expected: bool
    checksums: dict[str, str]
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "model_key": self.model_key,
            "model_version": self.model_version,
            "artifact_dir": self.artifact_dir,
            "required_files_present": self.required_files_present,
            "feature_count": self.feature_count,
            "feature_schema_matches_phase1": self.feature_schema_matches_phase1,
            "metadata_matches_expected": self.metadata_matches_expected,
            "checksums": self.checksums,
        }
        if self.failure_reason:
            payload["failure_reason"] = self.failure_reason
        return payload


@dataclass(frozen=True)
class ArtifactRegistryValidationReport:
    status: str
    models: dict[str, ModelArtifactValidationReport]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "models": {
                model_key: report.to_dict()
                for model_key, report in self.models.items()
            },
        }


def kurma_3_spec(artifact_dir: str | Path = DEFAULT_KURMA_3_ARTIFACT_DIR) -> ModelArtifactSpec:
    return ModelArtifactSpec(
        model_key="kurma_3",
        model_version=KURMA_3_MODEL_VERSION,
        model_alias="Kurma 3",
        model_family="LogisticRegression",
        dataset_version=DATASET_VERSION,
        split_version=SPLIT_VERSION,
        feature_count=MODEL_FEATURE_COUNT,
        artifact_dir=Path(artifact_dir),
    )


def varaha_3_spec(artifact_dir: str | Path = DEFAULT_VARAHA_3_ARTIFACT_DIR) -> ModelArtifactSpec:
    return ModelArtifactSpec(
        model_key="varaha_3",
        model_version=VARAHA_3_MODEL_VERSION,
        model_alias="Varaha 3",
        model_family="HistGradientBoostingClassifier",
        dataset_version=DATASET_VERSION,
        split_version=SPLIT_VERSION,
        feature_count=MODEL_FEATURE_COUNT,
        artifact_dir=Path(artifact_dir),
    )


def validate_kurma_varaha_artifact_registry(
    *,
    kurma_artifact_dir: str | Path = DEFAULT_KURMA_3_ARTIFACT_DIR,
    varaha_artifact_dir: str | Path = DEFAULT_VARAHA_3_ARTIFACT_DIR,
) -> ArtifactRegistryValidationReport:
    reports = {
        "kurma_3": validate_model_artifacts(kurma_3_spec(kurma_artifact_dir)),
        "varaha_3": validate_model_artifacts(varaha_3_spec(varaha_artifact_dir)),
    }
    status = "valid" if all(report.status == "valid" for report in reports.values()) else "invalid"
    return ArtifactRegistryValidationReport(status=status, models=reports)


def validate_model_artifacts(spec: ModelArtifactSpec) -> ModelArtifactValidationReport:
    required_files_present = {name: False for name in REQUIRED_ARTIFACT_FILES}
    checksums: dict[str, str] = {}
    feature_count: int | None = None
    feature_schema_matches_phase1 = False
    metadata_matches_expected = False

    def invalid(reason: str) -> ModelArtifactValidationReport:
        return ModelArtifactValidationReport(
            status="invalid",
            model_key=spec.model_key,
            model_version=spec.model_version,
            artifact_dir=_path_text(spec.artifact_dir),
            required_files_present=required_files_present,
            feature_count=feature_count,
            feature_schema_matches_phase1=feature_schema_matches_phase1,
            metadata_matches_expected=metadata_matches_expected,
            checksums=checksums,
            failure_reason=reason,
        )

    if not spec.artifact_dir.is_dir():
        return invalid(f"Artifact directory missing: {_path_text(spec.artifact_dir)}")

    artifact_paths = {name: spec.artifact_dir / name for name in REQUIRED_ARTIFACT_FILES}
    required_files_present.update(
        {name: path.is_file() for name, path in artifact_paths.items()}
    )
    missing_files = [name for name, present in required_files_present.items() if not present]
    if missing_files:
        return invalid(f"Required artifact file missing: {missing_files[0]}")

    try:
        feature_schema = _read_json(artifact_paths["feature_schema.json"])
    except ValueError as exc:
        return invalid(str(exc))
    if not isinstance(feature_schema, list):
        return invalid("feature_schema.json must be a JSON list")
    if not all(isinstance(name, str) for name in feature_schema):
        return invalid("feature_schema.json must contain only string feature names")

    feature_count = len(feature_schema)
    if feature_count != spec.feature_count:
        return invalid(f"Feature count must be exactly {spec.feature_count}, got {feature_count}")
    if feature_schema[:10] != EXPECTED_FIRST_10_FEATURES:
        return invalid("First 10 features do not match locked Dataset V3 feature order")
    if feature_schema[-8:] != EXPECTED_LAST_8_FEATURES:
        return invalid("Last 8 features do not match locked Regime V3 feature order")
    if feature_schema != FEATURE_NAMES:
        return invalid("Feature schema does not exactly match locked Phase 1 FEATURE_NAMES")
    feature_schema_matches_phase1 = True

    try:
        metadata = _read_json(artifact_paths["model_metadata.json"])
    except ValueError as exc:
        return invalid(str(exc))
    if not isinstance(metadata, dict):
        return invalid("model_metadata.json must be a JSON object")

    metadata_mismatches = _metadata_mismatches(metadata, spec)
    if metadata_mismatches:
        return invalid(f"Model metadata mismatch: {metadata_mismatches[0]}")
    metadata_matches_expected = True

    try:
        checksums = {
            name: _sha256_file(path)
            for name, path in artifact_paths.items()
        }
    except OSError as exc:
        return invalid(f"Checksum cannot be computed: {exc}")

    return ModelArtifactValidationReport(
        status="valid",
        model_key=spec.model_key,
        model_version=spec.model_version,
        artifact_dir=_path_text(spec.artifact_dir),
        required_files_present=required_files_present,
        feature_count=feature_count,
        feature_schema_matches_phase1=feature_schema_matches_phase1,
        metadata_matches_expected=metadata_matches_expected,
        checksums=checksums,
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path.name}: {exc.msg}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc


def _metadata_mismatches(metadata: dict[str, Any], spec: ModelArtifactSpec) -> list[str]:
    expected = {
        "model_version": spec.model_version,
        "model_alias": spec.model_alias,
        "model_family": spec.model_family,
        "dataset_version": spec.dataset_version,
        "split_version": spec.split_version,
    }
    mismatches = [
        f"{key} expected {value!r}, got {metadata.get(key)!r}"
        for key, value in expected.items()
        if metadata.get(key) != value
    ]
    if str(metadata.get("feature_count")) != str(spec.feature_count):
        mismatches.append(
            f"feature_count expected {spec.feature_count!r}, got {metadata.get('feature_count')!r}"
        )
    if "train_only" in metadata and metadata["train_only"] is not True:
        mismatches.append(f"train_only expected True when present, got {metadata.get('train_only')!r}")
    if "test_data_used" in metadata and metadata["test_data_used"] is not False:
        mismatches.append(
            f"test_data_used expected False when present, got {metadata.get('test_data_used')!r}"
        )
    return mismatches


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_text(path: Path) -> str:
    return path.as_posix()
