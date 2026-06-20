from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


MODEL_VERSION = "stock_opportunity_ohlcv_regime_timesplit_kurma_v2"
MODEL_ALIAS = "Kurma 2"
ANALYSIS_TYPE = "threshold_and_bucket_analysis"

DEFAULT_EVALUATION_DIR = Path(f"/app/data/evaluations/{MODEL_VERSION}")
DEFAULT_PREDICTIONS_CSV = DEFAULT_EVALUATION_DIR / "test_predictions.csv"
DEFAULT_OUTPUT_DIR = DEFAULT_EVALUATION_DIR

REQUIRED_COLUMNS = [
    "symbol",
    "sample_date",
    "outcome",
    "target",
    "win_probability",
    "predicted_label",
]
ALLOWED_OUTCOMES = {"WIN", "LOSS", "TIMEOUT"}
LABEL_ENCODING = {"WIN": 1, "LOSS": 0, "TIMEOUT": 0}
THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
TOP_BUCKETS = [
    ("top_50", "count", 50),
    ("top_100", "count", 100),
    ("top_250", "count", 250),
    ("top_500", "count", 500),
    ("top_1000", "count", 1000),
    ("top_1_percent", "percent", 1),
    ("top_5_percent", "percent", 5),
    ("top_10_percent", "percent", 10),
]


def get_git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
    except Exception:
        return "unknown"


def _validate_output_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir)
    if path.name != MODEL_VERSION:
        raise ValueError(
            f"Unsafe output directory. Expected directory name {MODEL_VERSION}, got {path}"
        )
    if path.parent.name != "evaluations":
        raise ValueError(f"Output directory must be under an evaluations directory: {path}")
    return path


def _validate_required_columns(columns: Iterable[str]) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in set(columns)]
    if missing:
        raise ValueError(f"Predictions CSV is missing required columns: {missing}")


def _validate_predictions(
    df: pd.DataFrame,
    expected_row_count: int,
    cutoff_date: str,
) -> tuple[dict[str, int], dict[str, float]]:
    if len(df) != expected_row_count:
        raise ValueError(
            f"Prediction row count {len(df)} does not match expected {expected_row_count}"
        )

    observed = set(df["outcome"].dropna().astype(str).unique())
    unsupported = sorted(observed - ALLOWED_OUTCOMES)
    if unsupported:
        raise ValueError(f"Predictions CSV contains unsupported outcomes: {unsupported}")

    expected_target = df["outcome"].map(LABEL_ENCODING)
    numeric_target = pd.to_numeric(df["target"], errors="coerce")
    if numeric_target.isna().any() or not (numeric_target.astype(int) == expected_target).all():
        raise ValueError("Target column does not match WIN=1 and LOSS/TIMEOUT=0 encoding")
    df["target"] = numeric_target.astype(int)

    probabilities = pd.to_numeric(df["win_probability"], errors="coerce")
    if probabilities.isna().any() or not np.isfinite(probabilities.to_numpy()).all():
        raise ValueError("win_probability must be numeric and finite")
    if ((probabilities < 0.0) | (probabilities > 1.0)).any():
        raise ValueError("win_probability must be between 0 and 1")
    df["win_probability"] = probabilities.astype(float)

    sample_dates = pd.to_datetime(df["sample_date"], errors="raise").dt.strftime("%Y-%m-%d")
    unsafe_dates = sorted(sample_dates[sample_dates < cutoff_date].unique().tolist())
    if unsafe_dates:
        raise ValueError(f"Predictions CSV contains sample_date < {cutoff_date}: {unsafe_dates[:10]}")
    df["sample_date"] = sample_dates

    counts = df["outcome"].value_counts().reindex(["WIN", "LOSS", "TIMEOUT"], fill_value=0)
    outcome_counts = {outcome: int(count) for outcome, count in counts.items()}
    row_count = int(len(df))
    base_rates = {
        "base_win_rate": outcome_counts["WIN"] / row_count,
        "base_loss_rate": outcome_counts["LOSS"] / row_count,
        "base_timeout_rate": outcome_counts["TIMEOUT"] / row_count,
    }
    return outcome_counts, base_rates


def _stats_for_subset(
    label: str,
    subset: pd.DataFrame,
    total_win_count: int,
    base_win_rate: float,
    extra: dict,
) -> dict:
    candidate_count = int(len(subset))
    counts = subset["outcome"].value_counts().reindex(["WIN", "LOSS", "TIMEOUT"], fill_value=0)
    win_count = int(counts["WIN"])
    loss_count = int(counts["LOSS"])
    timeout_count = int(counts["TIMEOUT"])

    if candidate_count:
        win_rate = win_count / candidate_count
        loss_rate = loss_count / candidate_count
        timeout_rate = timeout_count / candidate_count
    else:
        win_rate = loss_rate = timeout_rate = 0.0

    precision = win_rate
    recall = win_count / total_win_count if total_win_count else 0.0
    lift = win_rate / base_win_rate if base_win_rate else 0.0
    expectancy = (win_rate * 7.0) - (loss_rate * 3.0)

    return {
        "label": label,
        **extra,
        "candidate_count": candidate_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "timeout_count": timeout_count,
        "win_rate": float(win_rate),
        "loss_rate": float(loss_rate),
        "timeout_rate": float(timeout_rate),
        "precision": float(precision),
        "recall": float(recall),
        "lift_vs_base_win_rate": float(lift),
        "expectancy_win7_loss3_timeout0": float(expectancy),
    }


def _best_by(rows: list[dict], key: str) -> dict:
    return max(
        rows,
        key=lambda row: (
            row[key],
            row["expectancy_win7_loss3_timeout0"],
            row["precision"],
            row["candidate_count"],
        ),
    )


def analyze_kurma2_thresholds(
    predictions_csv: str | Path = DEFAULT_PREDICTIONS_CSV,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    expected_row_count: int = 91797,
    cutoff_date: str = "2025-07-09",
) -> dict:
    predictions_path = Path(predictions_csv)
    output_path = _validate_output_dir(output_dir)

    if not predictions_path.exists():
        raise FileNotFoundError(f"Predictions CSV not found: {predictions_path}")

    print(f"Loading Kurma 2 test predictions: {predictions_path}")
    df = pd.read_csv(predictions_path)
    _validate_required_columns(df.columns)
    outcome_counts, base_rates = _validate_predictions(
        df=df,
        expected_row_count=expected_row_count,
        cutoff_date=cutoff_date,
    )

    df = df.sort_values("win_probability", ascending=False).reset_index(drop=True)
    row_count = int(len(df))
    total_win_count = outcome_counts["WIN"]

    threshold_rows = []
    for threshold in THRESHOLDS:
        subset = df[df["win_probability"] >= threshold]
        threshold_rows.append(
            _stats_for_subset(
                label=f"threshold_{threshold:.2f}",
                subset=subset,
                total_win_count=total_win_count,
                base_win_rate=base_rates["base_win_rate"],
                extra={"threshold": threshold},
            )
        )

    bucket_rows = []
    for label, bucket_type, value in TOP_BUCKETS:
        if bucket_type == "count":
            candidate_count = min(int(value), row_count)
        else:
            candidate_count = max(1, int(math.floor(row_count * (float(value) / 100.0))))
        subset = df.head(candidate_count)
        bucket_rows.append(
            _stats_for_subset(
                label=label,
                subset=subset,
                total_win_count=total_win_count,
                base_win_rate=base_rates["base_win_rate"],
                extra={"bucket_type": bucket_type, "bucket_value": value},
            )
        )

    output_path.mkdir(parents=True, exist_ok=True)
    threshold_csv = output_path / "threshold_analysis.csv"
    threshold_json = output_path / "threshold_analysis.json"
    bucket_csv = output_path / "top_bucket_analysis.csv"
    bucket_json = output_path / "top_bucket_analysis.json"
    summary_path = output_path / "champion_summary.json"

    print(f"Saving threshold analysis to {threshold_csv}")
    pd.DataFrame(threshold_rows).to_csv(threshold_csv, index=False)
    threshold_json.write_text(json.dumps(threshold_rows, indent=2), encoding="utf-8")

    print(f"Saving top-bucket analysis to {bucket_csv}")
    pd.DataFrame(bucket_rows).to_csv(bucket_csv, index=False)
    bucket_json.write_text(json.dumps(bucket_rows, indent=2), encoding="utf-8")

    summary = {
        "model_version": MODEL_VERSION,
        "model_alias": MODEL_ALIAS,
        "analysis_type": ANALYSIS_TYPE,
        "source_predictions_csv": str(predictions_path),
        "output_dir": str(output_path),
        "row_count": row_count,
        **base_rates,
        "outcome_counts": outcome_counts,
        "best_threshold_by_expectancy": _best_by(
            threshold_rows, "expectancy_win7_loss3_timeout0"
        ),
        "best_threshold_by_precision": _best_by(threshold_rows, "precision"),
        "best_bucket_by_expectancy": _best_by(bucket_rows, "expectancy_win7_loss3_timeout0"),
        "best_bucket_by_precision": _best_by(bucket_rows, "precision"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "db_mutation": False,
        "deployed": False,
        "warning": "offline champion threshold analysis only; not deployed for live/demo trading",
    }

    print(f"Saving champion summary to {summary_path}")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Kurma 2 threshold and bucket analysis completed successfully.")
    return summary


if __name__ == "__main__":
    analyze_kurma2_thresholds()
