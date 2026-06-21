from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline


MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_kurma_v3"
MODEL_ALIAS = "Kurma 3"
MODEL_FAMILY = "LogisticRegression"
SPLIT_VERSION = "timesplit_regime_v3"
DATASET_VERSION = "stock_opportunity_ohlcv_regime_v3"

DEFAULT_MODEL_DIR = Path(f"/app/data/models/{MODEL_VERSION}")
DEFAULT_MODEL_PATH = DEFAULT_MODEL_DIR / "model.joblib"
DEFAULT_SCHEMA_PATH = DEFAULT_MODEL_DIR / "feature_schema.json"
DEFAULT_MODEL_METADATA_PATH = DEFAULT_MODEL_DIR / "model_metadata.json"
DEFAULT_TEST_CSV = Path("/app/data/exports/timesplit_regime_v3/test.csv")
FORBIDDEN_TRAIN_CSV = Path("/app/data/exports/timesplit_regime_v3/train.csv")
DEFAULT_SPLIT_META_JSON = Path("/app/data/exports/timesplit_regime_v3/split_meta.json")
DEFAULT_OUTPUT_DIR = Path(f"/app/data/evaluations/{MODEL_VERSION}")

KURMA_1_MODEL_VERSION = "stock_opportunity_ohlcv_regime_v1"
VARAHA_1_MODEL_VERSION = "stock_opportunity_hgb_regime_v1"
KURMA_2_MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_kurma_v2"
VARAHA_2_MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_varaha_v2"
PROTECTED_OUTPUT_DIRS = {
    KURMA_1_MODEL_VERSION,
    VARAHA_1_MODEL_VERSION,
    KURMA_2_MODEL_VERSION,
    VARAHA_2_MODEL_VERSION,
}
ALLOWED_OUTPUT_FILES = {
    "test_predictions.csv",
    "evaluation_metrics.json",
    "score_metadata.json",
}

METADATA_COLUMNS = ["symbol", "sample_date", "outcome"]
ALLOWED_OUTCOMES = {"WIN", "LOSS", "TIMEOUT"}
EXPECTED_TEST_OUTCOME_COUNTS = {"WIN": 22325, "LOSS": 63727, "TIMEOUT": 5745}
LABEL_ENCODING = {"WIN": 1, "LOSS": 0, "TIMEOUT": 0}


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


def _atomic_write_csv(path: Path, df: pd.DataFrame) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _validate_model_artifact_paths(
    model_path: Path,
    schema_path: Path,
    model_metadata_path: Path,
) -> None:
    expected_names = {
        model_path: "model.joblib",
        schema_path: "feature_schema.json",
        model_metadata_path: "model_metadata.json",
    }
    for path, expected_name in expected_names.items():
        if path.name != expected_name:
            raise ValueError(f"Unexpected Kurma 3 artifact file name: {path}")
        if path.parent.name != MODEL_VERSION:
            raise ValueError(f"Kurma 3 artifacts must come from {MODEL_VERSION}: {path}")
        if not path.exists():
            raise FileNotFoundError(f"Kurma 3 artifact not found: {path}")


def _validate_test_path(test_path: Path) -> None:
    if not test_path.exists():
        raise FileNotFoundError(f"Test CSV not found: {test_path}")
    if test_path.name != "test.csv":
        raise ValueError(f"Scoring source must be test.csv, got {test_path.name}")
    if test_path.parent.name != SPLIT_VERSION:
        raise ValueError(
            f"Scoring source parent must be {SPLIT_VERSION}, got {test_path.parent.name}"
        )
    if test_path == FORBIDDEN_TRAIN_CSV or test_path.name == "train.csv":
        raise ValueError(f"Refusing to score forbidden train CSV: {test_path}")


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
    if path.name in PROTECTED_OUTPUT_DIRS:
        raise ValueError(f"Refusing to write Kurma 3 evaluation to protected dir: {path}")
    if path.name != MODEL_VERSION:
        raise ValueError(
            f"Unsafe output directory. Expected directory name {MODEL_VERSION}, got {path.name}"
        )
    if path.parent.name != "evaluations":
        raise ValueError(f"Output directory must be under an evaluations directory: {path}")
    if any(part == "models" for part in path.parts):
        raise ValueError(f"Refusing to write evaluation artifacts inside a models path: {path}")
    return path


def _validate_output_dir_contents(output_path: Path) -> None:
    if not output_path.exists():
        return

    existing_files = {path.name for path in output_path.iterdir() if path.is_file()}
    unexpected_files = sorted(existing_files - ALLOWED_OUTPUT_FILES)
    if unexpected_files:
        raise ValueError(
            f"Refusing to write into Kurma 3 evaluation dir with unexpected files: {unexpected_files}"
        )


def load_feature_schema(schema_path: str | Path, expected_feature_count: int = 608) -> list[str]:
    path = Path(schema_path)
    if not path.exists():
        raise FileNotFoundError(f"Feature schema not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(feature, str) for feature in data):
        raise ValueError(f"Feature schema at {path} must be a list of feature names")
    if len(data) != expected_feature_count:
        raise ValueError(f"Expected {expected_feature_count} features in schema, got {len(data)}")

    metadata_inside_features = sorted(set(METADATA_COLUMNS).intersection(data))
    if metadata_inside_features:
        raise ValueError(
            f"Feature schema must not contain metadata columns: {metadata_inside_features}"
        )
    return data


def _validate_model_metadata(
    model_metadata_path: Path,
    *,
    expected_train_rows: int,
    expected_feature_count: int,
) -> dict:
    metadata = json.loads(model_metadata_path.read_text(encoding="utf-8"))
    required_values = {
        "model_version": MODEL_VERSION,
        "model_alias": MODEL_ALIAS,
        "model_family": MODEL_FAMILY,
        "dataset_version": DATASET_VERSION,
        "split_version": SPLIT_VERSION,
        "train_row_count": expected_train_rows,
        "feature_count": expected_feature_count,
        "train_only": True,
        "test_data_used": False,
        "old_model_loaded": False,
        "old_schema_loaded": False,
        "feature_schema_source": "train_csv_header",
        "feature_schema_match": True,
        "training_source_csv": str(FORBIDDEN_TRAIN_CSV),
        "forbidden_test_csv": str(DEFAULT_TEST_CSV),
    }
    mismatches = {
        key: {"expected": expected, "actual": metadata.get(key)}
        for key, expected in required_values.items()
        if metadata.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"Kurma 3 model metadata validation failed: {mismatches}")
    return metadata


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
        "expected_feature_count": expected_feature_count,
        "cutoff_date": cutoff_date,
        "max_train_sample_date": expected_max_train_sample_date,
        "min_test_sample_date": expected_min_test_sample_date,
        "sample_date_overlap_count": 0,
        "leakage_safe": True,
    }
    mismatches = {
        key: {"expected": expected, "actual": meta.get(key)}
        for key, expected in required_values.items()
        if meta.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"Split metadata is not the locked v3 leakage-safe split: {mismatches}")
    return meta


def _validate_test_header(
    test_path: Path,
    feature_schema: list[str],
    expected_feature_count: int,
) -> bool:
    header_columns = list(pd.read_csv(test_path, nrows=0).columns)
    if header_columns[:3] != METADATA_COLUMNS:
        raise ValueError(f"First three columns must be exactly {METADATA_COLUMNS}")
    if len(header_columns) != len(METADATA_COLUMNS) + expected_feature_count:
        raise ValueError(
            "Total test column count must be exactly "
            f"{len(METADATA_COLUMNS) + expected_feature_count}, got {len(header_columns)}"
        )

    feature_columns = header_columns[3:]
    if len(feature_columns) != expected_feature_count:
        raise ValueError(
            f"Expected {expected_feature_count} feature columns in test CSV, got "
            f"{len(feature_columns)}"
        )
    if feature_columns != feature_schema:
        missing = [feature for feature in feature_schema if feature not in feature_columns]
        extra = [feature for feature in feature_columns if feature not in feature_schema]
        raise ValueError(
            "Feature schema does not match test CSV columns. "
            f"missing={missing[:10]} extra={extra[:10]}"
        )
    return True


def _validate_dates(
    df: pd.DataFrame,
    cutoff_date: str,
    expected_min_test_sample_date: str,
) -> tuple[str, str]:
    sample_dates = pd.to_datetime(df["sample_date"], errors="raise").dt.strftime("%Y-%m-%d")
    min_test_sample_date = str(sample_dates.min())
    max_test_sample_date = str(sample_dates.max())

    unsafe_dates = sorted(sample_dates[sample_dates < cutoff_date].unique().tolist())
    if unsafe_dates:
        raise ValueError(f"Test CSV contains sample_date < {cutoff_date}: {unsafe_dates[:10]}")
    if min_test_sample_date != expected_min_test_sample_date:
        raise ValueError(
            "Min test sample_date does not match expected split boundary. "
            f"expected={expected_min_test_sample_date} actual={min_test_sample_date}"
        )

    df["sample_date"] = sample_dates
    return min_test_sample_date, max_test_sample_date


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


def _validate_outcomes(
    df: pd.DataFrame,
    expected_test_outcome_counts: dict[str, int] | None,
) -> dict[str, int]:
    if df["outcome"].isna().any():
        raise ValueError("Test CSV contains null outcomes")

    observed = set(df["outcome"].astype(str).unique())
    unsupported = sorted(observed - ALLOWED_OUTCOMES)
    if unsupported:
        raise ValueError(f"Test CSV contains unsupported outcomes: {unsupported}")

    missing_outcomes = sorted(ALLOWED_OUTCOMES - observed)
    if missing_outcomes:
        raise ValueError(f"Test CSV is missing required outcome classes: {missing_outcomes}")

    counts = df["outcome"].value_counts().reindex(["WIN", "LOSS", "TIMEOUT"], fill_value=0)
    outcome_counts = {outcome: int(count) for outcome, count in counts.items()}
    if expected_test_outcome_counts is not None and outcome_counts != expected_test_outcome_counts:
        raise ValueError(
            "Test outcome counts do not match expected v3 split. "
            f"expected={expected_test_outcome_counts} actual={outcome_counts}"
        )
    return outcome_counts


def _validate_feature_values(df: pd.DataFrame, feature_schema: list[str]) -> None:
    if df[feature_schema].isna().any().any():
        raise ValueError("NaN values found in feature columns")
    feature_values = df[feature_schema].to_numpy(dtype=np.float32, copy=False)
    if not np.isfinite(feature_values).all():
        raise ValueError("Infinite values found in feature columns")


def _validate_model(model: Any) -> Pipeline:
    if not isinstance(model, Pipeline):
        raise ValueError(f"Kurma 3 model must be a sklearn Pipeline, got {type(model).__name__}")
    if list(model.named_steps.keys()) != ["scaler", "lr"]:
        raise ValueError(f"Kurma 3 pipeline steps must be ['scaler', 'lr'], got {list(model.named_steps.keys())}")
    if not isinstance(model.named_steps["lr"], LogisticRegression):
        raise ValueError(
            "Kurma 3 final estimator must be LogisticRegression, got "
            f"{type(model.named_steps['lr']).__name__}"
        )
    if not hasattr(model, "predict_proba"):
        raise ValueError("Kurma 3 model must support predict_proba")
    return model


def _build_metrics(
    y_true: pd.Series,
    y_pred: np.ndarray,
    y_prob: np.ndarray,
    outcome_counts: dict[str, int],
    feature_count: int,
) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    roc_auc: float | None
    if len(set(y_true.tolist())) == 2:
        roc_auc = float(roc_auc_score(y_true, y_prob))
    else:
        roc_auc = None

    return {
        "row_count": int(len(y_true)),
        "feature_count": int(feature_count),
        "outcome_counts": outcome_counts,
        "positive_label_rate": float(y_true.mean()),
        "classification_threshold": 0.5,
        "predicted_positive_count": int(y_pred.sum()),
        "predicted_positive_rate": float(y_pred.mean()),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": roc_auc,
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
    }


def score_timesplit_kurma_v3(
    model_path: str | Path = DEFAULT_MODEL_PATH,
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    model_metadata_path: str | Path = DEFAULT_MODEL_METADATA_PATH,
    test_csv_path: str | Path = DEFAULT_TEST_CSV,
    split_meta_json: str | Path = DEFAULT_SPLIT_META_JSON,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    expected_train_rows: int = 367071,
    expected_test_rows: int = 91797,
    expected_total_rows: int = 458868,
    expected_feature_count: int = 608,
    expected_test_outcome_counts: dict[str, int] | None = EXPECTED_TEST_OUTCOME_COUNTS,
    cutoff_date: str = "2025-07-09",
    expected_max_train_sample_date: str = "2025-07-08",
    expected_min_test_sample_date: str = "2025-07-09",
) -> tuple[dict, dict]:
    model_file = Path(model_path)
    schema_file = Path(schema_path)
    model_metadata_file = Path(model_metadata_path)
    test_path = Path(test_csv_path)
    split_meta_path = Path(split_meta_json)
    output_path = _validate_output_dir(output_dir)
    _validate_output_dir_contents(output_path)

    _validate_model_artifact_paths(model_file, schema_file, model_metadata_file)
    _validate_test_path(test_path)
    _validate_model_metadata(
        model_metadata_file,
        expected_train_rows=expected_train_rows,
        expected_feature_count=expected_feature_count,
    )
    _validate_split_metadata(
        split_meta_path,
        expected_train_rows=expected_train_rows,
        expected_test_rows=expected_test_rows,
        expected_total_rows=expected_total_rows,
        expected_feature_count=expected_feature_count,
        cutoff_date=cutoff_date,
        expected_max_train_sample_date=expected_max_train_sample_date,
        expected_min_test_sample_date=expected_min_test_sample_date,
    )

    feature_schema = load_feature_schema(schema_file, expected_feature_count=expected_feature_count)

    print(f"Loading test CSV header: {test_path}")
    feature_schema_match = _validate_test_header(
        test_path,
        feature_schema,
        expected_feature_count=expected_feature_count,
    )

    req_cols = METADATA_COLUMNS + feature_schema
    dtype_dict = {feature: np.float32 for feature in feature_schema}
    dtype_dict["symbol"] = "category"

    print(f"Loading Kurma 3 test-only dataset: {test_path}")
    df = pd.read_csv(test_path, usecols=req_cols, dtype=dtype_dict)
    if len(df) != expected_test_rows:
        raise ValueError(f"Test row count {len(df)} does not match expected {expected_test_rows}")

    min_test_sample_date, max_test_sample_date = _validate_dates(
        df,
        cutoff_date=cutoff_date,
        expected_min_test_sample_date=expected_min_test_sample_date,
    )
    _validate_no_duplicate_samples(df)
    outcome_counts = _validate_outcomes(df, expected_test_outcome_counts)
    _validate_feature_values(df, feature_schema)

    print(f"Loading Kurma 3 model: {model_file}")
    model = _validate_model(joblib.load(model_file))

    df = df.sort_values(["sample_date", "symbol"]).reset_index(drop=True)
    y_true = df["outcome"].map(LABEL_ENCODING).astype(np.int8)
    X = df[feature_schema]

    print(f"Scoring Kurma 3 on {len(df)} test-only rows and {len(feature_schema)} features...")
    win_probabilities = model.predict_proba(X)[:, 1]
    predictions = (win_probabilities >= 0.5).astype(np.int8)

    metrics = _build_metrics(
        y_true=y_true,
        y_pred=predictions,
        y_prob=win_probabilities,
        outcome_counts=outcome_counts,
        feature_count=len(feature_schema),
    )

    output_path.mkdir(parents=True, exist_ok=True)
    predictions_path = output_path / "test_predictions.csv"
    metrics_path = output_path / "evaluation_metrics.json"
    metadata_path = output_path / "score_metadata.json"

    predictions_df = pd.DataFrame(
        {
            "symbol": df["symbol"].astype(str),
            "sample_date": df["sample_date"],
            "outcome": df["outcome"],
            "target": y_true,
            "win_probability": win_probabilities,
            "predicted_label": predictions,
        }
    )

    print(f"Saving test predictions to {predictions_path}")
    _atomic_write_csv(predictions_path, predictions_df)

    print(f"Saving evaluation metrics to {metrics_path}")
    _atomic_write_json(metrics_path, metrics)

    metadata = {
        "model_version": MODEL_VERSION,
        "model_alias": MODEL_ALIAS,
        "model_family": MODEL_FAMILY,
        "dataset_version": DATASET_VERSION,
        "split_version": SPLIT_VERSION,
        "scoring_source_csv": str(test_path),
        "forbidden_train_csv": str(FORBIDDEN_TRAIN_CSV),
        "model_path": str(model_file),
        "feature_schema_path": str(schema_file),
        "model_metadata_path": str(model_metadata_file),
        "split_meta_json": str(split_meta_path),
        "output_dir": str(output_path),
        "test_row_count": int(len(df)),
        "feature_count": int(len(feature_schema)),
        "min_test_sample_date": min_test_sample_date,
        "max_test_sample_date": max_test_sample_date,
        "test_outcome_counts": outcome_counts,
        "label_encoding": LABEL_ENCODING,
        "test_only": True,
        "train_data_used": False,
        "db_mutation": False,
        "deployed": False,
        "champion_selected": False,
        "feature_schema_match": feature_schema_match,
        "model_metadata_validated": True,
        "split_metadata_validated": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "warning": "Kurma 3 offline time-split evaluation only; not deployed for live/demo trading",
    }

    print(f"Saving score metadata to {metadata_path}")
    _atomic_write_json(metadata_path, metadata)

    print("Kurma 3 time-split test-only scoring completed successfully.")
    return metrics, metadata


if __name__ == "__main__":
    score_timesplit_kurma_v3()
