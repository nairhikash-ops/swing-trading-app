from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_SOURCE_CSV = Path("/app/data/exports/ml_dataset_ohlcv_regime_v1.csv")
DEFAULT_SCHEMA_JSON = Path("/app/data/models/stock_opportunity_hgb_regime_v1/feature_schema.json")
DEFAULT_OUTPUT_DIR = Path("/app/data/exports/timesplit_regime_v2")
OBSOLETE_PREVIOUS_EXPORT_PATH = "/app/data/exports/timesplit_v2/"

METADATA_COLUMNS = ["symbol", "sample_date", "outcome"]
ELIGIBLE_OUTCOMES = ["WIN", "LOSS", "TIMEOUT"]
EXCLUDED_OUTCOMES = ["AMBIGUOUS", "INSUFFICIENT_FUTURE_DATA", "null", "unknown"]


def _load_feature_schema(schema_path: str | Path) -> list[str]:
    path = Path(schema_path)
    if not path.exists():
        raise FileNotFoundError(f"Feature schema not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        features = data
    elif isinstance(data, dict):
        features = data.get("features") or data.get("feature_names") or data.get("columns") or []
    else:
        raise ValueError(f"Unsupported feature schema format at {path}")

    if not features or not all(isinstance(feature, str) for feature in features):
        raise ValueError(f"Feature schema at {path} contains no valid feature names")

    return features


def _validate_source_path(source_csv_path: str | Path) -> Path:
    path = Path(source_csv_path)
    if path.name == "ml_dataset_ohlcv_v1.csv":
        raise ValueError(
            "Unsafe source dataset: base OHLCV CSV is not valid for regime split export"
        )
    if path.name != "ml_dataset_ohlcv_regime_v1.csv":
        raise ValueError(
            "Unexpected source dataset name. Expected ml_dataset_ohlcv_regime_v1.csv, "
            f"got {path.name}"
        )
    if not path.exists():
        raise FileNotFoundError(f"Regime source dataset not found: {path}")
    return path


def _validate_output_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir)
    if path.name != "timesplit_regime_v2":
        raise ValueError(
            "Unsafe output path detected. Expected a timesplit_regime_v2 output directory, "
            f"got {path}"
        )
    if path.as_posix().rstrip("/") == "/app/data/exports/timesplit_v2":
        raise ValueError("Unsafe output path detected: old timesplit_v2 directory is obsolete")
    return path


def _validate_required_columns(columns: Iterable[str]) -> None:
    column_set = set(columns)
    missing_metadata = [column for column in METADATA_COLUMNS if column not in column_set]
    if missing_metadata:
        raise ValueError(f"Source dataset is missing metadata columns: {missing_metadata}")


def _feature_columns(columns: Iterable[str]) -> list[str]:
    return [column for column in columns if column not in METADATA_COLUMNS]


def _validate_feature_schema(
    feature_columns: list[str],
    feature_schema: list[str],
    expected_feature_count: int,
) -> tuple[bool, list[str], list[str]]:
    feature_count = len(feature_columns)
    if feature_count != expected_feature_count:
        raise ValueError(
            f"Feature count {feature_count} does not match expected {expected_feature_count}"
        )

    missing_features = [feature for feature in feature_schema if feature not in feature_columns]
    extra_features = [feature for feature in feature_columns if feature not in feature_schema]
    feature_schema_match = feature_schema == feature_columns

    if not feature_schema_match:
        raise ValueError(
            "Feature schema does not match source dataset columns. "
            f"missing={missing_features[:10]} extra={extra_features[:10]}"
        )

    return feature_schema_match, missing_features, extra_features


def _validate_date_split(train_df: pd.DataFrame, test_df: pd.DataFrame) -> tuple[set[str], set[str]]:
    train_dates = set(train_df["sample_date"].dropna().astype(str).unique())
    test_dates = set(test_df["sample_date"].dropna().astype(str).unique())
    overlap = train_dates.intersection(test_dates)
    if overlap:
        preview = sorted(overlap)[:10]
        raise ValueError(f"Train/test sample_date overlap is not zero: {preview}")
    return train_dates, test_dates


def export_timesplit(
    source_csv_path: str | Path = DEFAULT_SOURCE_CSV,
    schema_path: str | Path = DEFAULT_SCHEMA_JSON,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    cutoff_date: str = "2025-07-09",
    expected_total_rows: int = 458868,
    expected_train_rows: int = 367071,
    expected_test_rows: int = 91797,
    expected_feature_count: int = 308,
) -> dict:
    source_path = _validate_source_path(source_csv_path)
    output_path = _validate_output_dir(output_dir)
    feature_schema = _load_feature_schema(schema_path)

    print(f"Loading regime source CSV: {source_path}")
    df = pd.read_csv(source_path)
    source_columns = list(df.columns)
    _validate_required_columns(source_columns)

    feature_columns = _feature_columns(source_columns)
    feature_schema_match, missing_features, extra_features = _validate_feature_schema(
        feature_columns=feature_columns,
        feature_schema=feature_schema,
        expected_feature_count=expected_feature_count,
    )

    eligible_mask = df["outcome"].isin(ELIGIBLE_OUTCOMES)
    eligible_df = df[eligible_mask].copy()
    excluded_values = sorted(
        str(value) for value in df.loc[~eligible_mask, "outcome"].dropna().unique()
    )

    if len(eligible_df) != expected_total_rows:
        raise ValueError(
            f"Total eligible rows {len(eligible_df)} do not match expected {expected_total_rows}"
        )

    eligible_df["sample_date"] = eligible_df["sample_date"].astype(str)
    eligible_df = eligible_df.sort_values(by="sample_date").reset_index(drop=True)
    output_columns = METADATA_COLUMNS + feature_schema
    eligible_df = eligible_df[output_columns]

    print(f"Splitting data with cutoff date: {cutoff_date}")
    train_df = eligible_df[eligible_df["sample_date"] < cutoff_date].copy()
    test_df = eligible_df[eligible_df["sample_date"] >= cutoff_date].copy()

    if len(train_df) != expected_train_rows:
        raise ValueError(f"Train rows {len(train_df)} do not match expected {expected_train_rows}")
    if len(test_df) != expected_test_rows:
        raise ValueError(f"Test rows {len(test_df)} do not match expected {expected_test_rows}")
    if list(train_df.columns) != list(test_df.columns):
        raise ValueError("Train/test output columns do not match")

    train_dates, test_dates = _validate_date_split(train_df, test_df)
    max_train_date = str(train_df["sample_date"].max())
    min_test_date = str(test_df["sample_date"].min())
    if max_train_date >= cutoff_date:
        raise ValueError(f"Train split leaks past cutoff: max_train_date={max_train_date}")
    if min_test_date < cutoff_date:
        raise ValueError(f"Test split starts before cutoff: min_test_date={min_test_date}")

    cutoff_count = int((test_df["sample_date"] == cutoff_date).sum())
    train_outcomes = train_df["outcome"].value_counts().to_dict()
    test_outcomes = test_df["outcome"].value_counts().to_dict()
    output_column_count = len(output_columns)
    leakage_safe = (
        len(train_dates.intersection(test_dates)) == 0
        and max_train_date < cutoff_date
        and min_test_date >= cutoff_date
        and feature_schema_match
    )

    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source_path),
        "cutoff_date": cutoff_date,
        "train_rule": f"sample_date < '{cutoff_date}'",
        "test_rule": f"sample_date >= '{cutoff_date}'",
        "eligible_outcomes": ELIGIBLE_OUTCOMES,
        "excluded_outcomes": EXCLUDED_OUTCOMES,
        "excluded_outcomes_observed": excluded_values,
        "train_row_count": len(train_df),
        "test_row_count": len(test_df),
        "total_eligible_row_count": len(eligible_df),
        "train_unique_sample_dates": len(train_dates),
        "test_unique_sample_dates": len(test_dates),
        "min_train_sample_date": str(train_df["sample_date"].min()),
        "max_train_sample_date": max_train_date,
        "min_test_sample_date": min_test_date,
        "max_test_sample_date": str(test_df["sample_date"].max()),
        "cutoff_date_row_count": cutoff_count,
        "train_outcome_counts": train_outcomes,
        "test_outcome_counts": test_outcomes,
        "sample_date_overlap_count": len(train_dates.intersection(test_dates)),
        "source_column_count": len(source_columns),
        "output_column_count": output_column_count,
        "feature_count": len(feature_columns),
        "expected_feature_count": expected_feature_count,
        "feature_schema_match": feature_schema_match,
        "missing_features": missing_features,
        "extra_features": extra_features,
        "obsolete_previous_export_path": OBSOLETE_PREVIOUS_EXPORT_PATH,
        "leakage_safe": leakage_safe,
        "notes": (
            "Regime timesplit export uses ml_dataset_ohlcv_regime_v1.csv and writes only "
            "regenerable train/test CSVs. Previous timesplit_v2 output is obsolete/regenerable "
            "and is not read or overwritten."
        ),
    }

    print(f"Creating output directory: {output_path}")
    os.makedirs(output_path, exist_ok=True)

    train_path = output_path / "train.csv"
    test_path = output_path / "test.csv"
    meta_path = output_path / "split_meta.json"

    print(f"Writing train.csv ({len(train_df)} rows) to {train_path}")
    train_df.to_csv(train_path, index=False)

    print(f"Writing test.csv ({len(test_df)} rows) to {test_path}")
    test_df.to_csv(test_path, index=False)

    print(f"Writing split_meta.json to {meta_path}")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("Phase 1B regime split export complete.")
    return meta


if __name__ == "__main__":
    export_timesplit()
