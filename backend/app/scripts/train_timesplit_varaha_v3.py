from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier


MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_varaha_v3"
MODEL_ALIAS = "Varaha 3"
MODEL_FAMILY = "HistGradientBoostingClassifier"
SPLIT_VERSION = "timesplit_regime_v3"
DATASET_VERSION = "stock_opportunity_ohlcv_regime_v3"

DEFAULT_TRAIN_CSV = Path("/app/data/exports/timesplit_regime_v3/train.csv")
FORBIDDEN_TEST_CSV = Path("/app/data/exports/timesplit_regime_v3/test.csv")
DEFAULT_SPLIT_META_JSON = Path("/app/data/exports/timesplit_regime_v3/split_meta.json")
DEFAULT_OUTPUT_DIR = Path("/app/data/models/stock_opportunity_ohlcv_regime_timesplit_varaha_v3")

KURMA_1_MODEL_VERSION = "stock_opportunity_ohlcv_regime_v1"
VARAHA_1_MODEL_VERSION = "stock_opportunity_hgb_regime_v1"
KURMA_2_MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_kurma_v2"
VARAHA_2_MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_varaha_v2"
KURMA_3_MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_kurma_v3"
PROTECTED_MODEL_DIRS = {
    KURMA_1_MODEL_VERSION,
    VARAHA_1_MODEL_VERSION,
    KURMA_2_MODEL_VERSION,
    VARAHA_2_MODEL_VERSION,
    KURMA_3_MODEL_VERSION,
}
ALLOWED_OUTPUT_FILES = {"model.joblib", "feature_schema.json", "model_metadata.json"}

METADATA_COLUMNS = ["symbol", "sample_date", "outcome"]
ALLOWED_OUTCOMES = {"WIN", "LOSS", "TIMEOUT"}
REQUIRED_OUTCOME_ORDER = ["WIN", "LOSS", "TIMEOUT"]
EXPECTED_TRAIN_OUTCOME_COUNTS = {"WIN": 120505, "LOSS": 228899, "TIMEOUT": 17667}
LABEL_ENCODING = {"WIN": 1, "LOSS": 0, "TIMEOUT": 0}

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
EXPECTED_LAST_8_REGIME_FEATURES = [
    "market_median_20d_return",
    "market_breakout_rate",
    "market_breakdown_rate",
    "market_breadth_delta",
    "market_cross_sectional_volatility",
    "stock_20d_return_minus_market_median",
    "stock_is_stronger_than_market",
    "stock_breakout_while_market_weak",
]


def encode_label(outcome: str) -> int:
    try:
        return LABEL_ENCODING[outcome]
    except KeyError as exc:
        raise ValueError(f"Unknown outcome: {outcome}") from exc


def get_git_commit() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"])
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return "unknown"


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _atomic_dump_joblib(path: Path, payload: Any) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        joblib.dump(payload, tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _validate_train_path(train_path: Path) -> None:
    if not train_path.exists():
        raise FileNotFoundError(f"Train CSV not found: {train_path}")
    if train_path.name != "train.csv":
        raise ValueError(f"Training source must be train.csv, got {train_path.name}")
    if train_path.parent.name != SPLIT_VERSION:
        raise ValueError(
            f"Training source parent must be {SPLIT_VERSION}, got {train_path.parent.name}"
        )
    if train_path == FORBIDDEN_TEST_CSV or train_path.name == "test.csv":
        raise ValueError(f"Refusing to train from forbidden test CSV: {train_path}")


def _validate_split_meta_path(split_meta_path: Path) -> None:
    if not split_meta_path.exists():
        raise FileNotFoundError(f"Split metadata not found: {split_meta_path}")
    if split_meta_path.name != "split_meta.json":
        raise ValueError(f"Split metadata file must be split_meta.json, got {split_meta_path.name}")
    if split_meta_path.parent.name != SPLIT_VERSION:
        raise ValueError(
            f"Split metadata parent must be {SPLIT_VERSION}, got {split_meta_path.parent.name}"
        )


def _validate_output_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir)
    protected_parts = sorted(set(path.parts).intersection(PROTECTED_MODEL_DIRS))
    if protected_parts:
        raise ValueError(f"Refusing to write Varaha 3 artifacts inside protected model dir: {path}")
    if path.name != MODEL_VERSION:
        raise ValueError(
            f"Unsafe output directory. Expected directory name {MODEL_VERSION}, got {path.name}"
        )
    return path


def _validate_output_dir_contents(output_path: Path) -> None:
    if not output_path.exists():
        return

    existing_files = {path.name for path in output_path.iterdir() if path.is_file()}
    unexpected_files = sorted(existing_files - ALLOWED_OUTPUT_FILES)
    if unexpected_files:
        raise ValueError(
            f"Refusing to write into Varaha 3 output dir with unexpected files: {unexpected_files}"
        )


def _metadata_name_from_pandas_duplicate(column_name: str) -> str | None:
    for metadata_column in METADATA_COLUMNS:
        prefix = f"{metadata_column}."
        if column_name.startswith(prefix) and column_name[len(prefix) :].isdigit():
            return metadata_column
    return None


def derive_feature_schema_from_train_header(
    train_csv_path: str | Path,
    expected_feature_count: int = 608,
) -> list[str]:
    train_path = Path(train_csv_path)
    _validate_train_path(train_path)

    header_columns = list(pd.read_csv(train_path, nrows=0).columns)
    if header_columns[:3] != METADATA_COLUMNS:
        raise ValueError(f"First three columns must be exactly {METADATA_COLUMNS}")

    feature_schema = header_columns[3:]
    expected_total_columns = len(METADATA_COLUMNS) + expected_feature_count
    if len(header_columns) != expected_total_columns:
        raise ValueError(
            f"Total train column count must be exactly {expected_total_columns}, "
            f"got {len(header_columns)}"
        )
    if len(feature_schema) != expected_feature_count:
        raise ValueError(
            f"Feature count must be exactly {expected_feature_count}, got {len(feature_schema)}"
        )

    metadata_inside_features = sorted(
        {
            feature
            for feature in feature_schema
            if feature in METADATA_COLUMNS or _metadata_name_from_pandas_duplicate(feature)
        }
    )
    if metadata_inside_features:
        raise ValueError(
            f"Feature schema must not contain metadata columns: {metadata_inside_features}"
        )

    if feature_schema[:10] != EXPECTED_FIRST_10_FEATURES:
        raise ValueError(
            "Feature schema does not start with the expected Dataset v3 candle anatomy features"
        )
    if feature_schema[-8:] != EXPECTED_LAST_8_REGIME_FEATURES:
        raise ValueError("Feature schema does not end with the expected Dataset v3 regime features")

    return feature_schema


def _validate_split_metadata(
    split_meta_path: Path,
    *,
    expected_train_rows: int,
    expected_test_rows: int,
    expected_total_rows: int,
    expected_feature_count: int,
    cutoff_date: str,
    expected_max_train_sample_date: str,
    expected_min_test_sample_date: str,
) -> dict:
    _validate_split_meta_path(split_meta_path)
    meta = json.loads(split_meta_path.read_text(encoding="utf-8"))

    required_values = {
        "dataset_version": SPLIT_VERSION,
        "source_dataset_version": DATASET_VERSION,
        "train_row_count": expected_train_rows,
        "test_row_count": expected_test_rows,
        "total_eligible_row_count": expected_total_rows,
        "feature_count": expected_feature_count,
        "cutoff_date": cutoff_date,
        "max_train_sample_date": expected_max_train_sample_date,
        "min_test_sample_date": expected_min_test_sample_date,
        "sample_date_overlap_count": 0,
        "leakage_safe": True,
    }
    if "expected_feature_count" in meta:
        required_values["expected_feature_count"] = expected_feature_count

    mismatches = {
        key: {"expected": expected, "actual": meta.get(key)}
        for key, expected in required_values.items()
        if meta.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"Split metadata is not the locked v3 leakage-safe split: {mismatches}")

    return meta


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
        raise ValueError(f"Train CSV contains sample_date >= {cutoff_date}: {unsafe_dates[:10]}")
    if max_train_sample_date != expected_max_train_sample_date:
        raise ValueError(
            "Max train sample_date does not match expected split boundary. "
            f"expected={expected_max_train_sample_date} actual={max_train_sample_date}"
        )

    df["sample_date"] = sample_dates
    return min_train_sample_date, max_train_sample_date


def _validate_outcomes(
    df: pd.DataFrame,
    expected_train_outcome_counts: dict[str, int],
) -> dict[str, int]:
    if df["outcome"].isna().any():
        raise ValueError("Train CSV contains null outcomes")

    observed = set(df["outcome"].astype(str).unique())
    unsupported = sorted(observed - ALLOWED_OUTCOMES)
    if unsupported:
        raise ValueError(f"Train CSV contains unsupported outcomes: {unsupported}")

    missing_outcomes = sorted(ALLOWED_OUTCOMES - observed)
    if missing_outcomes:
        raise ValueError(f"Train CSV is missing required outcome classes: {missing_outcomes}")

    counts = df["outcome"].value_counts().reindex(REQUIRED_OUTCOME_ORDER, fill_value=0)
    actual_counts = {outcome: int(count) for outcome, count in counts.items()}
    if actual_counts != expected_train_outcome_counts:
        raise ValueError(
            "Train outcome counts do not match locked v3 split. "
            f"expected={expected_train_outcome_counts} actual={actual_counts}"
        )

    return actual_counts


def _validate_no_duplicate_samples(df: pd.DataFrame) -> None:
    duplicate_mask = df.duplicated(subset=["symbol", "sample_date"], keep=False)
    if duplicate_mask.any():
        duplicates = (
            df.loc[duplicate_mask, ["symbol", "sample_date"]]
            .drop_duplicates()
            .head(10)
            .to_dict("records")
        )
        raise ValueError(f"Duplicate symbol+sample_date rows found: {duplicates}")


def _validate_feature_values(df: pd.DataFrame, feature_schema: list[str]) -> None:
    if df[feature_schema].isna().any().any():
        raise ValueError("NaN values found in feature columns")
    feature_values = df[feature_schema].to_numpy(dtype=np.float32, copy=False)
    if not np.isfinite(feature_values).all():
        raise ValueError("Infinite values found in feature columns")


def train_timesplit_varaha_v3(
    train_csv_path: str | Path = DEFAULT_TRAIN_CSV,
    split_meta_json: str | Path = DEFAULT_SPLIT_META_JSON,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    expected_train_rows: int = 367071,
    expected_test_rows: int = 91797,
    expected_total_rows: int = 458868,
    expected_feature_count: int = 608,
    expected_train_outcome_counts: dict[str, int] | None = None,
    cutoff_date: str = "2025-07-09",
    expected_max_train_sample_date: str = "2025-07-08",
    expected_min_test_sample_date: str = "2025-07-09",
) -> dict:
    train_path = Path(train_csv_path)
    split_meta_path = Path(split_meta_json)
    output_path = _validate_output_dir(output_dir)
    _validate_output_dir_contents(output_path)

    _validate_train_path(train_path)
    split_meta = _validate_split_metadata(
        split_meta_path,
        expected_train_rows=expected_train_rows,
        expected_test_rows=expected_test_rows,
        expected_total_rows=expected_total_rows,
        expected_feature_count=expected_feature_count,
        cutoff_date=cutoff_date,
        expected_max_train_sample_date=expected_max_train_sample_date,
        expected_min_test_sample_date=expected_min_test_sample_date,
    )

    print(f"Loading train CSV header: {train_path}")
    feature_schema = derive_feature_schema_from_train_header(
        train_path,
        expected_feature_count=expected_feature_count,
    )

    req_cols = METADATA_COLUMNS + feature_schema
    dtype_dict = {feature: np.float32 for feature in feature_schema}
    dtype_dict["symbol"] = "category"

    print(f"Loading Varaha 3 train-only dataset: {train_path}")
    df = pd.read_csv(train_path, usecols=req_cols, dtype=dtype_dict)

    if len(df) != expected_train_rows:
        raise ValueError(f"Train row count {len(df)} does not match expected {expected_train_rows}")

    min_train_sample_date, max_train_sample_date = _validate_dates(
        df=df,
        cutoff_date=cutoff_date,
        expected_max_train_sample_date=expected_max_train_sample_date,
    )
    train_outcome_counts = _validate_outcomes(
        df,
        expected_train_outcome_counts or EXPECTED_TRAIN_OUTCOME_COUNTS,
    )
    _validate_no_duplicate_samples(df)
    _validate_feature_values(df, feature_schema)

    df = df.sort_values(["sample_date", "symbol"]).reset_index(drop=True)
    X = df[feature_schema]
    y = df["outcome"].map(LABEL_ENCODING).astype(np.int8)

    print(
        "Training Varaha 3 HistGradientBoostingClassifier challenger on "
        f"{len(df)} train-only rows and {len(feature_schema)} features..."
    )
    model = HistGradientBoostingClassifier(random_state=42)

    t0 = time.perf_counter()
    model.fit(X, y)
    elapsed = time.perf_counter() - t0
    print(f"Training completed in {elapsed:.2f} seconds.")

    output_path.mkdir(parents=True, exist_ok=True)
    model_path = output_path / "model.joblib"
    schema_output_path = output_path / "feature_schema.json"
    metadata_path = output_path / "model_metadata.json"

    print(f"Saving model to {model_path}")
    _atomic_dump_joblib(model_path, model)

    print(f"Saving feature schema to {schema_output_path}")
    _atomic_write_json(schema_output_path, feature_schema)

    metadata = {
        "model_version": MODEL_VERSION,
        "model_alias": MODEL_ALIAS,
        "model_family": MODEL_FAMILY,
        "dataset_version": DATASET_VERSION,
        "split_version": SPLIT_VERSION,
        "training_source_csv": str(train_path),
        "forbidden_test_csv": str(FORBIDDEN_TEST_CSV),
        "split_meta_json": str(split_meta_path),
        "train_row_count": int(len(df)),
        "feature_count": int(len(feature_schema)),
        "min_train_sample_date": min_train_sample_date,
        "max_train_sample_date": max_train_sample_date,
        "train_outcome_counts": train_outcome_counts,
        "label_encoding": LABEL_ENCODING,
        "train_only": True,
        "test_data_used": False,
        "old_model_loaded": False,
        "old_schema_loaded": False,
        "feature_schema_source": "train_csv_header",
        "feature_schema_match": True,
        "split_metadata_validated": True,
        "db_mutation": False,
        "deployed": False,
        "champion_selected": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "warning": (
            "Varaha 3 offline time-split HGB challenger only; "
            "not deployed for live/demo trading"
        ),
        "training_time_seconds": round(elapsed, 4),
    }

    print(f"Saving metadata to {metadata_path}")
    _atomic_write_json(metadata_path, metadata)

    print(
        "Varaha 3 clean train-only HGB challenger completed successfully "
        f"from {split_meta['dataset_version']}."
    )
    return metadata


if __name__ == "__main__":
    train_timesplit_varaha_v3()
