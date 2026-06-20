from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_kurma_v2"
MODEL_ALIAS = "Kurma 2"
SPLIT_VERSION = "timesplit_regime_v2"

DEFAULT_MODEL_DIR = Path(f"/app/data/models/{MODEL_VERSION}")
DEFAULT_MODEL_PATH = DEFAULT_MODEL_DIR / "model.joblib"
DEFAULT_SCHEMA_PATH = DEFAULT_MODEL_DIR / "feature_schema.json"
DEFAULT_TEST_CSV = Path("/app/data/exports/timesplit_regime_v2/test.csv")
FORBIDDEN_TRAIN_CSV = Path("/app/data/exports/timesplit_regime_v2/train.csv")
DEFAULT_OUTPUT_DIR = Path(f"/app/data/evaluations/{MODEL_VERSION}")

KURMA_1_MODEL_VERSION = "stock_opportunity_ohlcv_regime_v1"
VARAHA_1_MODEL_VERSION = "stock_opportunity_hgb_regime_v1"
PROTECTED_MODEL_DIRS = {KURMA_1_MODEL_VERSION, VARAHA_1_MODEL_VERSION, MODEL_VERSION}

METADATA_COLUMNS = ["symbol", "sample_date", "outcome"]
ALLOWED_OUTCOMES = {"WIN", "LOSS", "TIMEOUT"}
LABEL_ENCODING = {"WIN": 1, "LOSS": 0, "TIMEOUT": 0}


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
        raise ValueError(f"Test CSV is missing required columns: {missing}")


def _feature_columns(columns: Iterable[str]) -> list[str]:
    return [column for column in columns if column not in METADATA_COLUMNS]


def _validate_output_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir)
    if path.name != MODEL_VERSION:
        raise ValueError(
            f"Unsafe output directory. Expected directory name {MODEL_VERSION}, got {path}"
        )
    if path.parent.name != "evaluations":
        raise ValueError(f"Output directory must be under an evaluations directory: {path}")
    if any(part in PROTECTED_MODEL_DIRS for part in path.parent.parts):
        raise ValueError(f"Refusing to write evaluation artifacts inside a model directory: {path}")
    return path


def _validate_feature_columns(feature_columns: list[str], feature_schema: list[str]) -> bool:
    if len(feature_columns) != 308:
        raise ValueError(f"Expected 308 feature columns in test CSV, got {len(feature_columns)}")

    feature_schema_match = feature_columns == feature_schema
    if not feature_schema_match:
        missing = [feature for feature in feature_schema if feature not in feature_columns]
        extra = [feature for feature in feature_columns if feature not in feature_schema]
        raise ValueError(
            "Feature schema does not match test CSV columns. "
            f"missing={missing[:10]} extra={extra[:10]}"
        )

    return True


def _validate_dates(df: pd.DataFrame, cutoff_date: str) -> tuple[str, str]:
    sample_dates = pd.to_datetime(df["sample_date"], errors="raise").dt.strftime("%Y-%m-%d")
    unsafe_dates = sorted(sample_dates[sample_dates < cutoff_date].unique().tolist())
    if unsafe_dates:
        raise ValueError(f"Test CSV contains sample_date < {cutoff_date}: {unsafe_dates[:10]}")

    df["sample_date"] = sample_dates
    return str(sample_dates.min()), str(sample_dates.max())


def _validate_outcomes(df: pd.DataFrame) -> dict[str, int]:
    observed = set(df["outcome"].dropna().astype(str).unique())
    unsupported = sorted(observed - ALLOWED_OUTCOMES)
    if unsupported:
        raise ValueError(f"Test CSV contains unsupported outcomes: {unsupported}")

    missing_outcomes = sorted(ALLOWED_OUTCOMES - observed)
    if missing_outcomes:
        raise ValueError(f"Test CSV is missing required outcome classes: {missing_outcomes}")

    counts = df["outcome"].value_counts().reindex(["WIN", "LOSS", "TIMEOUT"], fill_value=0)
    return {outcome: int(count) for outcome, count in counts.items()}


def _validate_feature_values(df: pd.DataFrame, feature_schema: list[str]) -> None:
    if df[feature_schema].isna().any().any():
        raise ValueError("NaN values found in feature columns")
    feature_values = df[feature_schema].to_numpy(dtype=np.float32, copy=False)
    if not np.isfinite(feature_values).all():
        raise ValueError("Infinite values found in feature columns")


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
        "predicted_positive_count_at_threshold_0_5": int(y_pred.sum()),
        "predicted_positive_rate_at_threshold_0_5": float(y_pred.mean()),
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


def score_timesplit_kurma_v2(
    model_path: str | Path = DEFAULT_MODEL_PATH,
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    test_csv_path: str | Path = DEFAULT_TEST_CSV,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    expected_test_rows: int = 91797,
    expected_feature_count: int = 308,
    cutoff_date: str = "2025-07-09",
) -> tuple[dict, dict]:
    model_file = Path(model_path)
    schema_file = Path(schema_path)
    test_path = Path(test_csv_path)
    output_path = _validate_output_dir(output_dir)

    if not model_file.exists():
        raise FileNotFoundError(f"Model not found: {model_file}")
    if not test_path.exists():
        raise FileNotFoundError(f"Test CSV not found: {test_path}")
    if test_path.as_posix().rstrip("/") == FORBIDDEN_TRAIN_CSV.as_posix():
        raise ValueError(f"Refusing to score train CSV: {test_path}")

    feature_schema = load_feature_schema(schema_file)
    if len(feature_schema) != expected_feature_count:
        raise ValueError(
            f"Feature schema count {len(feature_schema)} does not match expected "
            f"{expected_feature_count}"
        )

    print(f"Loading test CSV header: {test_path}")
    header_columns = list(pd.read_csv(test_path, nrows=0).columns)
    _validate_required_columns(header_columns)
    feature_columns = _feature_columns(header_columns)
    feature_schema_match = _validate_feature_columns(feature_columns, feature_schema)

    req_cols = METADATA_COLUMNS + feature_schema
    dtype_dict = {feature: np.float32 for feature in feature_schema}
    dtype_dict["symbol"] = "category"

    print(f"Loading test-only dataset: {test_path}")
    df = pd.read_csv(test_path, usecols=req_cols, dtype=dtype_dict)
    if len(df) != expected_test_rows:
        raise ValueError(f"Test row count {len(df)} does not match expected {expected_test_rows}")

    min_test_sample_date, max_test_sample_date = _validate_dates(df, cutoff_date=cutoff_date)
    outcome_counts = _validate_outcomes(df)
    _validate_feature_values(df, feature_schema)

    print(f"Loading Kurma 2 model: {model_file}")
    model = joblib.load(model_file)

    df = df.sort_values(["sample_date", "symbol"]).reset_index(drop=True)
    y_true = df["outcome"].map(LABEL_ENCODING).astype(np.int8)
    X = df[feature_schema]

    print(f"Scoring Kurma 2 on {len(df)} test-only rows and {len(feature_schema)} features...")
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
    predictions_df.to_csv(predictions_path, index=False)

    print(f"Saving evaluation metrics to {metrics_path}")
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    metadata = {
        "model_version": MODEL_VERSION,
        "model_alias": MODEL_ALIAS,
        "scoring_source_csv": str(test_path),
        "model_path": str(model_file),
        "feature_schema_path": str(schema_file),
        "output_dir": str(output_path),
        "test_row_count": int(len(df)),
        "min_test_sample_date": min_test_sample_date,
        "max_test_sample_date": max_test_sample_date,
        "test_outcome_counts": outcome_counts,
        "label_encoding": LABEL_ENCODING,
        "test_only": True,
        "train_data_used": False,
        "db_mutation": False,
        "deployed": False,
        "split_version": SPLIT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "warning": "offline time-split evaluation only; not deployed for live/demo trading",
        "feature_count": int(len(feature_schema)),
        "feature_schema_match": feature_schema_match,
    }

    print(f"Saving score metadata to {metadata_path}")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("Kurma 2 time-split test-only scoring completed successfully.")
    return metrics, metadata


if __name__ == "__main__":
    score_timesplit_kurma_v2()
