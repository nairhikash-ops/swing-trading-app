from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from app.matsya.kurma_varaha_artifacts import (
    DEFAULT_KURMA_3_ARTIFACT_DIR,
    DEFAULT_VARAHA_3_ARTIFACT_DIR,
    FEATURE_NAMES,
    MODEL_FEATURE_COUNT,
    kurma_3_spec,
    validate_kurma_varaha_artifact_registry,
    varaha_3_spec,
)
from app.matsya.kurma_varaha_model_loader import (
    EXPECTED_COMPATIBLE_CLASS,
    _is_compatible_loaded_class,
)


METADATA_COLUMNS = ["symbol", "sample_date"]


@dataclass(frozen=True)
class ScoringDryRunReport:
    status: str
    dry_run: bool
    row_count: int
    feature_count: int
    kurma_model_version: str | None
    varaha_model_version: str | None
    kurma_model_checksum: str | None
    varaha_model_checksum: str | None
    rows: list[dict[str, Any]]
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "dry_run": self.dry_run,
            "row_count": self.row_count,
            "feature_count": self.feature_count,
            "kurma_model_version": self.kurma_model_version,
            "varaha_model_version": self.varaha_model_version,
            "kurma_model_checksum": self.kurma_model_checksum,
            "varaha_model_checksum": self.varaha_model_checksum,
            "rows": self.rows,
        }
        if self.failure_reason:
            payload["failure_reason"] = self.failure_reason
        return payload


def score_kurma_varaha_dry_run(
    *,
    snapshot_csv: str | Path,
    kurma_artifact_dir: str | Path = DEFAULT_KURMA_3_ARTIFACT_DIR,
    varaha_artifact_dir: str | Path = DEFAULT_VARAHA_3_ARTIFACT_DIR,
    output_path: str | Path,
    limit: int | None = None,
) -> ScoringDryRunReport:
    try:
        snapshot = _load_and_validate_snapshot(snapshot_csv, limit=limit)
        registry_report = validate_kurma_varaha_artifact_registry(
            kurma_artifact_dir=kurma_artifact_dir,
            varaha_artifact_dir=varaha_artifact_dir,
        )
        if registry_report.status != "valid":
            return _invalid_report(
                reason="Artifact registry validation failed",
                row_count=snapshot.row_count,
            )

        kurma_model = _load_validated_model(
            model_key="kurma_3",
            artifact_dir=Path(kurma_artifact_dir),
            expected_checksum=registry_report.models["kurma_3"].checksums["model.joblib"],
        )
        varaha_model = _load_validated_model(
            model_key="varaha_3",
            artifact_dir=Path(varaha_artifact_dir),
            expected_checksum=registry_report.models["varaha_3"].checksums["model.joblib"],
        )

        kurma_probs = _positive_probabilities(kurma_model, snapshot.features, model_key="kurma_3")
        varaha_probs = _positive_probabilities(varaha_model, snapshot.features, model_key="varaha_3")
        if len(kurma_probs) != snapshot.row_count or len(varaha_probs) != snapshot.row_count:
            return _invalid_report(
                reason="Probability row count mismatch",
                row_count=snapshot.row_count,
                registry_report=registry_report,
            )

        rows = [
            {
                "symbol": str(row.symbol),
                "sample_date": str(row.sample_date),
                "kurma_prob": float(kurma_probs[index]),
                "varaha_prob": float(varaha_probs[index]),
            }
            for index, row in snapshot.metadata.iterrows()
        ]
        report = ScoringDryRunReport(
            status="valid",
            dry_run=True,
            row_count=snapshot.row_count,
            feature_count=MODEL_FEATURE_COUNT,
            kurma_model_version=registry_report.models["kurma_3"].model_version,
            varaha_model_version=registry_report.models["varaha_3"].model_version,
            kurma_model_checksum=registry_report.models["kurma_3"].checksums["model.joblib"],
            varaha_model_checksum=registry_report.models["varaha_3"].checksums["model.joblib"],
            rows=rows,
        )
        _write_report(output_path, report)
        return report
    except Exception as exc:
        return _invalid_report(reason=str(exc), row_count=0)


@dataclass(frozen=True)
class _ValidatedSnapshot:
    metadata: pd.DataFrame
    features: pd.DataFrame
    row_count: int


def _load_and_validate_snapshot(snapshot_csv: str | Path, *, limit: int | None = None) -> _ValidatedSnapshot:
    path = Path(snapshot_csv)
    if not path.is_file():
        raise ValueError(f"Snapshot CSV missing: {path}")
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError("Snapshot CSV must contain at least one row")

    missing_metadata = [column for column in METADATA_COLUMNS if column not in df.columns]
    if missing_metadata:
        raise ValueError(f"Snapshot missing metadata columns: {missing_metadata}")

    missing_features = [column for column in FEATURE_NAMES if column not in df.columns]
    if missing_features:
        raise ValueError(f"Snapshot missing feature columns: {missing_features[:5]}")

    expected_columns = METADATA_COLUMNS + FEATURE_NAMES
    actual_prefix = [column for column in df.columns if column in expected_columns][: len(expected_columns)]
    if actual_prefix != expected_columns:
        raise ValueError("Snapshot feature order does not match locked Phase 1 FEATURE_NAMES")

    sample_dates = df["sample_date"].astype(str).dropna().unique().tolist()
    if len(sample_dates) != 1:
        raise ValueError(f"Snapshot must contain exactly one sample_date, got {sample_dates}")

    if limit is not None:
        if limit <= 0:
            raise ValueError(f"limit must be positive when provided, got {limit}")
        df = df.head(limit)
        if df.empty:
            raise ValueError("Snapshot limit produced zero rows")

    feature_frame = df.loc[:, FEATURE_NAMES]
    if feature_frame.isna().any().any():
        raise ValueError("Snapshot feature values contain missing values")

    feature_values = feature_frame.to_numpy(dtype=np.float64, copy=False)
    if not np.isfinite(feature_values).all():
        raise ValueError("Snapshot feature values contain NaN or infinite values")

    return _ValidatedSnapshot(
        metadata=df.loc[:, METADATA_COLUMNS].copy(),
        features=feature_frame,
        row_count=len(df),
    )


def _load_validated_model(
    *,
    model_key: str,
    artifact_dir: Path,
    expected_checksum: str,
) -> Any:
    model_path = artifact_dir / "model.joblib"
    actual_checksum = _sha256_file(model_path)
    if actual_checksum != expected_checksum:
        raise ValueError(f"{model_key} model checksum changed after validation")

    model = joblib.load(model_path)
    if not _is_compatible_loaded_class(model, EXPECTED_COMPATIBLE_CLASS[model_key]):
        raise ValueError(f"{model_key} loaded class is not compatible with expected family")
    return model


def _positive_probabilities(model: Any, features: pd.DataFrame, *, model_key: str) -> np.ndarray:
    probability_method = getattr(model, "predict" + "_proba", None)
    if not callable(probability_method):
        raise ValueError(f"{model_key} predict_proba is unavailable")
    probabilities = np.asarray(probability_method(features))
    if probabilities.ndim != 2 or probabilities.shape[0] != len(features) or probabilities.shape[1] < 2:
        raise ValueError(f"{model_key} probability shape unexpected: {probabilities.shape}")
    positive = probabilities[:, 1].astype(float, copy=False)
    if not np.isfinite(positive).all():
        raise ValueError(f"{model_key} positive probabilities contain NaN or infinite values")
    return positive


def _invalid_report(
    *,
    reason: str,
    row_count: int,
    registry_report: Any | None = None,
) -> ScoringDryRunReport:
    kurma_report = registry_report.models["kurma_3"] if registry_report else None
    varaha_report = registry_report.models["varaha_3"] if registry_report else None
    return ScoringDryRunReport(
        status="invalid",
        dry_run=True,
        row_count=row_count,
        feature_count=MODEL_FEATURE_COUNT,
        kurma_model_version=kurma_report.model_version if kurma_report else None,
        varaha_model_version=varaha_report.model_version if varaha_report else None,
        kurma_model_checksum=kurma_report.checksums.get("model.joblib") if kurma_report else None,
        varaha_model_checksum=varaha_report.checksums.get("model.joblib") if varaha_report else None,
        rows=[],
        failure_reason=reason,
    )


def _write_report(output_path: str | Path, report: ScoringDryRunReport) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
