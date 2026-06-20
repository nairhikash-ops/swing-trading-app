from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_kurma_v2"
MODEL_ALIAS = "Kurma 2"
MODEL_FAMILY = "LogisticRegression"
SPLIT_VERSION = "timesplit_regime_v2"

DEFAULT_TRAIN_CSV = Path("/app/data/exports/timesplit_regime_v2/train.csv")
FORBIDDEN_TEST_CSV = Path("/app/data/exports/timesplit_regime_v2/test.csv")
DEFAULT_SCHEMA_JSON = Path("/app/data/models/stock_opportunity_hgb_regime_v1/feature_schema.json")
DEFAULT_OUTPUT_DIR = Path(f"/app/data/models/{MODEL_VERSION}")

KURMA_1_MODEL_VERSION = "stock_opportunity_ohlcv_regime_v1"
VARAHA_1_MODEL_VERSION = "stock_opportunity_hgb_regime_v1"
PROTECTED_MODEL_DIRS = {KURMA_1_MODEL_VERSION, VARAHA_1_MODEL_VERSION}

METADATA_COLUMNS = ["symbol", "sample_date", "outcome"]
ALLOWED_OUTCOMES = {"WIN", "LOSS", "TIMEOUT"}
LABEL_ENCODING = {"WIN": 1, "LOSS": 0, "TIMEOUT": 0}


def encode_label(outcome: str) -> int:
    try:
        return LABEL_ENCODING[outcome]
    except KeyError as exc:
        raise ValueError(f"Unknown outcome: {outcome}") from exc


def get_git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
    except Exception:
        return "unknown"


def load_feature_schema(schema_path: str | Path) -> list[str]:
    path = Path(schema_path)
    if not path.exists():
        raise FileNotFoundError(f"Feature schema not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        feature_schema = data
    elif isinstance(data, dict):
        feature_schema = data.get("features") or data.get("feature_names") or data.get("columns")
    else:
        feature_schema = None

    if not isinstance(feature_schema, list) or not all(
        isinstance(feature, str) for feature in feature_schema
    ):
        raise ValueError(f"Feature schema at {path} must be a list of feature names")
    if len(feature_schema) != 308:
        raise ValueError(f"Expected 308 features in schema, got {len(feature_schema)}")
    if any(feature in METADATA_COLUMNS for feature in feature_schema):
        raise ValueError("Feature schema must not contain metadata columns")

    return feature_schema


def _validate_required_columns(columns: Iterable[str]) -> None:
    column_set = set(columns)
    missing = [column for column in METADATA_COLUMNS if column not in column_set]
    if missing:
        raise ValueError(f"Train CSV is missing required columns: {missing}")


def _feature_columns(columns: Iterable[str]) -> list[str]:
    return [column for column in columns if column not in METADATA_COLUMNS]


def _validate_output_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir)
    if path.name in PROTECTED_MODEL_DIRS:
        raise ValueError(f"Refusing to write Kurma 2 artifacts to protected model dir: {path}")
    if path.name != MODEL_VERSION:
        raise ValueError(
            f"Unsafe output directory. Expected directory name {MODEL_VERSION}, got {path}"
        )
    return path


def _validate_feature_columns(feature_columns: list[str], feature_schema: list[str]) -> bool:
    if len(feature_columns) != 308:
        raise ValueError(f"Expected 308 feature columns in train CSV, got {len(feature_columns)}")

    feature_schema_match = feature_columns == feature_schema
    if not feature_schema_match:
        missing = [feature for feature in feature_schema if feature not in feature_columns]
        extra = [feature for feature in feature_columns if feature not in feature_schema]
        raise ValueError(
            "Feature schema does not match train CSV columns. "
            f"missing={missing[:10]} extra={extra[:10]}"
        )

    return True


def _validate_dates(
    df: pd.DataFrame,
    cutoff_date: str,
    expected_max_train_sample_date: str,
) -> tuple[str, str]:
    sample_dates = pd.to_datetime(df["sample_date"], errors="raise").dt.strftime("%Y-%m-%d")
    min_train_sample_date = str(sample_dates.min())
    max_train_sample_date = str(sample_dates.max())

    unsafe_dates = sorted(sample_dates[sample_dates >= cutoff_date].unique().tolist())
    if unsafe_dates:
        raise ValueError(
            f"Train CSV contains sample_date >= {cutoff_date}: {unsafe_dates[:10]}"
        )
    if max_train_sample_date != expected_max_train_sample_date:
        raise ValueError(
            "Max train sample_date does not match expected split boundary. "
            f"expected={expected_max_train_sample_date} actual={max_train_sample_date}"
        )

    df["sample_date"] = sample_dates
    return min_train_sample_date, max_train_sample_date


def _validate_outcomes(df: pd.DataFrame) -> dict[str, int]:
    observed = set(df["outcome"].dropna().astype(str).unique())
    unsupported = sorted(observed - ALLOWED_OUTCOMES)
    if unsupported:
        raise ValueError(f"Train CSV contains unsupported outcomes: {unsupported}")

    missing_outcomes = sorted(ALLOWED_OUTCOMES - observed)
    if missing_outcomes:
        raise ValueError(f"Train CSV is missing required outcome classes: {missing_outcomes}")

    counts = df["outcome"].value_counts().reindex(["WIN", "LOSS", "TIMEOUT"], fill_value=0)
    return {outcome: int(count) for outcome, count in counts.items()}


def _validate_feature_values(df: pd.DataFrame, feature_schema: list[str]) -> None:
    if df[feature_schema].isna().any().any():
        raise ValueError("NaN values found in feature columns")
    feature_values = df[feature_schema].to_numpy(dtype=np.float32, copy=False)
    if not np.isfinite(feature_values).all():
        raise ValueError("Infinite values found in feature columns")


def train_timesplit_kurma_v2(
    train_csv_path: str | Path = DEFAULT_TRAIN_CSV,
    schema_path: str | Path = DEFAULT_SCHEMA_JSON,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    expected_train_rows: int = 367071,
    expected_feature_count: int = 308,
    cutoff_date: str = "2025-07-09",
    expected_max_train_sample_date: str = "2025-07-08",
) -> dict:
    train_path = Path(train_csv_path)
    output_path = _validate_output_dir(output_dir)

    if not train_path.exists():
        raise FileNotFoundError(f"Train CSV not found: {train_path}")

    feature_schema = load_feature_schema(schema_path)
    if len(feature_schema) != expected_feature_count:
        raise ValueError(
            f"Feature schema count {len(feature_schema)} does not match expected "
            f"{expected_feature_count}"
        )

    print(f"Loading train CSV header: {train_path}")
    header_columns = list(pd.read_csv(train_path, nrows=0).columns)
    _validate_required_columns(header_columns)
    feature_columns = _feature_columns(header_columns)
    feature_schema_match = _validate_feature_columns(feature_columns, feature_schema)

    req_cols = METADATA_COLUMNS + feature_schema
    dtype_dict = {feature: np.float32 for feature in feature_schema}
    dtype_dict["symbol"] = "category"

    print(f"Loading train-only dataset: {train_path}")
    df = pd.read_csv(train_path, usecols=req_cols, dtype=dtype_dict)

    if len(df) != expected_train_rows:
        raise ValueError(f"Train row count {len(df)} does not match expected {expected_train_rows}")

    min_train_sample_date, max_train_sample_date = _validate_dates(
        df=df,
        cutoff_date=cutoff_date,
        expected_max_train_sample_date=expected_max_train_sample_date,
    )
    train_outcome_counts = _validate_outcomes(df)
    _validate_feature_values(df, feature_schema)

    df = df.sort_values(["sample_date", "symbol"]).reset_index(drop=True)
    y = df["outcome"].map(LABEL_ENCODING).astype(np.int8)
    X = df[feature_schema]

    print(
        "Training Kurma 2 LogisticRegression baseline on "
        f"{len(df)} train-only rows and {len(feature_schema)} features..."
    )
    model = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(max_iter=1000, random_state=42)),
        ]
    )

    t0 = time.perf_counter()
    model.fit(X, y)
    elapsed = time.perf_counter() - t0
    print(f"Training completed in {elapsed:.2f} seconds.")

    output_path.mkdir(parents=True, exist_ok=True)
    model_path = output_path / "model.joblib"
    schema_output_path = output_path / "feature_schema.json"
    metadata_path = output_path / "model_metadata.json"

    print(f"Saving model to {model_path}")
    joblib.dump(model, model_path)

    print(f"Saving feature schema to {schema_output_path}")
    schema_output_path.write_text(json.dumps(feature_schema, indent=2), encoding="utf-8")

    metadata = {
        "model_version": MODEL_VERSION,
        "model_alias": MODEL_ALIAS,
        "model_family": MODEL_FAMILY,
        "training_source_csv": str(train_path),
        "forbidden_test_csv": str(FORBIDDEN_TEST_CSV),
        "train_row_count": int(len(df)),
        "feature_count": int(len(feature_schema)),
        "min_train_sample_date": min_train_sample_date,
        "max_train_sample_date": max_train_sample_date,
        "train_outcome_counts": train_outcome_counts,
        "label_encoding": LABEL_ENCODING,
        "train_only": True,
        "test_data_used": False,
        "split_version": SPLIT_VERSION,
        "feature_schema_match": feature_schema_match,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "warning": "time-split baseline only; not deployed for live/demo trading",
        "training_time_seconds": round(elapsed, 4),
    }

    print(f"Saving metadata to {metadata_path}")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("Kurma 2 time-split train-only baseline completed successfully.")
    return metadata


if __name__ == "__main__":
    train_timesplit_kurma_v2()
