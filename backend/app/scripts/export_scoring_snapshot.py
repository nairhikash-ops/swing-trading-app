# backend/app/scripts/export_scoring_snapshot.py
"""V1.26 — Export a feature-only scoring CSV for one clean post-training sample_date.

Purpose
-------
Build a feature CSV for a given sample_date using rows that exist in ml_samples
as INSUFFICIENT_FUTURE_DATA (i.e. dates after the HGB training cutoff whose outcome
labels are not yet available).  The resulting CSV is formatted identically to
ml_dataset_ohlcv_regime_v1.csv so that score_latest_hgb_regime.py can consume it
via --dataset-csv without any changes.

Safety rules (all enforced, abort on violation)
----------------------------------------------
1. sample_date must be strictly AFTER --training-cutoff-date (default 2026-05-18).
2. Zero trainable=1 rows may exist in ml_samples for that date.
3. At least one INSUFFICIENT_FUTURE_DATA row must exist for that date.
4. Archive output files must not already exist.
5. ml_samples is never modified.
6. Training CSV files are never modified.
7. Model files are never touched.
8. shadow_tracking is never touched.

Output files
------------
  /app/data/exports/ml_scoring_ohlcv_regime_YYYY-MM-DD.csv
  /app/data/exports/ml_scoring_ohlcv_regime_YYYY-MM-DD.meta.json

CLI
---
  python -m app.scripts.export_scoring_snapshot --sample-date 2026-05-19
  python -m app.scripts.export_scoring_snapshot --sample-date 2026-05-21 \\
      --output-dir /app/data/exports --training-cutoff-date 2026-05-18
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_TRAINING_CUTOFF   = "2026-05-18"
DEFAULT_OUTPUT_DIR        = Path("/app/data/exports")
DEFAULT_DB_PATH           = "/app/data/dhan_auth.sqlite3"
DEFAULT_MODEL_ROOT        = Path("/app/data/models/stock_opportunity_hgb_regime_v1")

# Feature layout — must match export_ml_dataset.py exactly
OHLCV_KEYS   = ["open_rel", "high_rel", "low_rel", "close_rel", "volume_rel"]
N_CANDLES    = 60
REGIME_COLS  = [
    "market_median_20d_return",
    "market_breakout_rate",
    "market_breakdown_rate",
    "market_breadth_delta",
    "market_cross_sectional_volatility",
    "stock_20d_return_minus_market_median",
    "stock_is_stronger_than_market",
    "stock_breakout_while_market_weak",
]


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


# ---------------------------------------------------------------------------
# Feature column helpers — match export_ml_dataset.py layout
# ---------------------------------------------------------------------------

def _load_feature_schema(schema_path: Path) -> list[str]:
    """Load feature names from a schema file.

    The HGB model writes a bare JSON list:   ["c00_open_rel", "c00_high_rel", ...]
    Test fixtures and the LR model write:     {"features": [...]}
    Both formats are handled transparently.
    """
    with schema_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        features = raw
    elif isinstance(raw, dict):
        # Try common keys in priority order
        features = (
            raw.get("features")
            or raw.get("feature_order")
            or raw.get("feature_names")
            or []
        )
    else:
        raise ValueError(
            f"Unexpected schema format in {schema_path}: "
            f"expected list or dict, got {type(raw).__name__}."
        )

    if not features:
        raise ValueError(
            f"feature_schema.json at {schema_path} contains no feature names."
        )
    return list(features)


def _ohlcv_col_names() -> list[str]:
    """Return the 300 OHLCV feature column names (c00_open_rel … c59_volume_rel)."""
    cols = []
    for i in range(N_CANDLES):
        prefix = f"c{i:02d}_"
        for k in OHLCV_KEYS:
            cols.append(f"{prefix}{k}")
    return cols


def _flatten_feature_json(feature_json_str: str, symbol: str, date: str) -> dict[str, float]:
    """Parse a feature_json blob and return a flat dict of the 300 OHLCV columns."""
    try:
        feature = json.loads(feature_json_str)
    except Exception as e:
        raise ValueError(f"Invalid feature_json for {symbol} {date}: {e}")

    candles: list[dict[str, Any]] = feature.get("candles", [])
    if len(candles) != N_CANDLES:
        raise ValueError(
            f"Expected {N_CANDLES} candles, got {len(candles)} for {symbol} {date}."
        )

    flat: dict[str, float] = {}
    for i, candle in enumerate(candles):
        prefix = f"c{i:02d}_"
        for k in OHLCV_KEYS:
            v = candle.get(k)
            if v is None:
                raise ValueError(f"Null value for {k} in candle {i} for {symbol} {date}.")
            flat[f"{prefix}{k}"] = float(v)
    return flat


# ---------------------------------------------------------------------------
# Regime feature computation — identical logic to export_ml_dataset_regime.py
# ---------------------------------------------------------------------------

def _compute_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add 8 regime columns in-place.  Logic is identical to export_ml_dataset_regime.py."""
    df = df.copy()

    df["current_close_ratio"] = (1.0 + df["c59_close_rel"]).astype(np.float32)
    df["past_close_ratio"]    = (1.0 + df["c39_close_rel"]).astype(np.float32)
    df["_stock_20d_return"]   = (df["current_close_ratio"] / df["past_close_ratio"] - 1.0).astype(np.float32)

    prev_20_high_cols = [f"c{i:02d}_high_rel" for i in range(39, 59)]
    prev_20_low_cols  = [f"c{i:02d}_low_rel"  for i in range(39, 59)]

    max_prev_20_high = df[prev_20_high_cols].max(axis=1) + 1.0
    min_prev_20_low  = df[prev_20_low_cols].min(axis=1)  + 1.0

    df["_stock_is_breakout"]  = (df["current_close_ratio"] > max_prev_20_high).astype(np.float32)
    df["_stock_is_breakdown"] = (df["current_close_ratio"] < min_prev_20_low).astype(np.float32)

    market_agg = df.groupby("sample_date").agg(
        market_median_20d_return         = ("_stock_20d_return", "median"),
        market_cross_sectional_volatility= ("_stock_20d_return", "std"),
        market_breakout_rate             = ("_stock_is_breakout", "mean"),
        market_breakdown_rate            = ("_stock_is_breakdown", "mean"),
    ).reset_index()

    market_agg["market_breadth_delta"] = (
        market_agg["market_breakout_rate"] - market_agg["market_breakdown_rate"]
    ).astype(np.float32)
    market_agg["market_cross_sectional_volatility"] = (
        market_agg["market_cross_sectional_volatility"].fillna(0.0).astype(np.float32)
    )
    market_agg["market_median_20d_return"]  = market_agg["market_median_20d_return"].astype(np.float32)
    market_agg["market_breakout_rate"]      = market_agg["market_breakout_rate"].astype(np.float32)
    market_agg["market_breakdown_rate"]     = market_agg["market_breakdown_rate"].astype(np.float32)

    df = df.merge(market_agg, on="sample_date", how="left")

    df["stock_20d_return_minus_market_median"] = (
        df["_stock_20d_return"] - df["market_median_20d_return"]
    ).astype(np.float32)
    df["stock_is_stronger_than_market"] = (
        df["_stock_20d_return"] > df["market_median_20d_return"]
    ).astype(np.float32)
    df["stock_breakout_while_market_weak"] = (
        (df["_stock_is_breakout"] == 1.0) & (df["market_breadth_delta"] < 0)
    ).astype(np.float32)

    # Drop intermediate columns
    df.drop(columns=[
        "current_close_ratio", "past_close_ratio",
        "_stock_20d_return", "_stock_is_breakout", "_stock_is_breakdown",
    ], inplace=True)

    return df


# ---------------------------------------------------------------------------
# Safety gate helpers
# ---------------------------------------------------------------------------

def _check_leakage_safety(
    conn: sqlite3.Connection,
    sample_date: str,
    training_cutoff_date: str,
) -> None:
    """Enforce all leakage safety rules.  Aborts (raises) on any violation."""

    # Rule 1: sample_date must be strictly after training cutoff
    if sample_date <= training_cutoff_date:
        raise ValueError(
            f"LEAKAGE SAFETY: sample_date={sample_date!r} is not strictly after "
            f"training_cutoff_date={training_cutoff_date!r}. "
            "Scoring in-sample dates is forbidden. "
            "Only dates strictly after the training cutoff may be scored."
        )

    # Rule 2: No trainable rows for this date
    trainable_count: int = conn.execute(
        "SELECT COUNT(1) FROM ml_samples WHERE sample_date = ? AND trainable = 1",
        (sample_date,),
    ).fetchone()[0]
    if trainable_count > 0:
        raise ValueError(
            f"LEAKAGE SAFETY: {trainable_count} trainable row(s) found in ml_samples for "
            f"sample_date={sample_date!r}. "
            "This date has known outcome labels and must NOT be used as a clean future date."
        )

    # Rule 3: INSUFFICIENT_FUTURE_DATA rows must exist
    insuf_count: int = conn.execute(
        """
        SELECT COUNT(1) FROM ml_samples
        WHERE sample_date = ? AND outcome = 'INSUFFICIENT_FUTURE_DATA'
        """,
        (sample_date,),
    ).fetchone()[0]
    if insuf_count == 0:
        raise ValueError(
            f"LEAKAGE SAFETY: No INSUFFICIENT_FUTURE_DATA rows found in ml_samples "
            f"for sample_date={sample_date!r}. "
            "The date must be present in ml_samples as INSUFFICIENT_FUTURE_DATA to be scored."
        )

    logging.info(
        "Leakage safety PASSED: date=%s, cutoff=%s, trainable=0, insuf_rows=%d",
        sample_date,
        training_cutoff_date,
        insuf_count,
    )


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def export_scoring_snapshot(
    sample_date: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    training_cutoff_date: str = DEFAULT_TRAINING_CUTOFF,
    db_path: str = DEFAULT_DB_PATH,
    model_root: Path = DEFAULT_MODEL_ROOT,
) -> dict:
    """Export a feature-only scoring CSV for one clean post-training date.

    Args:
        sample_date:           YYYY-MM-DD date to export.  Must be > training_cutoff_date.
        output_dir:            Directory to write output files.
        training_cutoff_date:  Training cutoff date (exclusive lower bound). Default 2026-05-18.
        db_path:               Path to dhan_auth.sqlite3 (contains ml_samples).
        model_root:            Directory containing the HGB model's feature_schema.json.

    Returns:
        dict with row_count, feature_count, output_csv, output_meta.

    Safety:
        - Aborts if sample_date <= training_cutoff_date.
        - Aborts if any trainable=1 rows exist for the date.
        - Aborts if no INSUFFICIENT_FUTURE_DATA rows exist.
        - Aborts if output archive files already exist.
        - Never modifies ml_samples, training CSVs, model files, or shadow_tracking.
    """
    _setup_logging()
    logging.info("=== export_scoring_snapshot START ===")
    logging.info("sample_date          : %s", sample_date)
    logging.info("training_cutoff_date : %s", training_cutoff_date)
    logging.info("output_dir           : %s", output_dir)
    logging.info("db_path              : %s", db_path)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    out_csv  = output_dir / f"ml_scoring_ohlcv_regime_{sample_date}.csv"
    out_meta = output_dir / f"ml_scoring_ohlcv_regime_{sample_date}.meta.json"

    # Rule 4: Abort if archive files already exist
    if out_csv.exists():
        raise FileExistsError(
            f"Archive file already exists: {out_csv}. "
            "Refusing to overwrite. Remove the file manually if this is intentional."
        )
    if out_meta.exists():
        raise FileExistsError(
            f"Archive meta already exists: {out_meta}. "
            "Refusing to overwrite. Remove the file manually if this is intentional."
        )

    # Load feature schema — handles both bare list and {"features": [...]} formats
    schema_path = model_root / "feature_schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Feature schema not found: {schema_path}")
    expected_features: list[str] = _load_feature_schema(schema_path)
    logging.info("Feature schema loaded: %d features from %s", len(expected_features), schema_path)

    # Connect and run leakage safety checks
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        _check_leakage_safety(conn, sample_date, training_cutoff_date)

        # Query INSUFFICIENT_FUTURE_DATA rows for this date
        rows = conn.execute(
            """
            SELECT symbol, sample_date, feature_json
            FROM ml_samples
            WHERE sample_date = ?
              AND outcome = 'INSUFFICIENT_FUTURE_DATA'
              AND trainable = 0
            ORDER BY symbol ASC
            """,
            (sample_date,),
        ).fetchall()
    finally:
        conn.close()

    logging.info("INSUFFICIENT_FUTURE_DATA rows fetched: %d", len(rows))

    if not rows:
        raise ValueError(
            f"No rows fetched for sample_date={sample_date!r} after applying all filters. "
            "This should not happen after the safety checks passed."
        )

    # Build flat OHLCV dataframe
    ohlcv_cols = _ohlcv_col_names()   # 300 columns
    records: list[dict] = []
    for row in rows:
        symbol      = row["symbol"]
        date_str    = row["sample_date"]
        flat_ohlcv  = _flatten_feature_json(row["feature_json"], symbol, date_str)
        record = {
            "symbol":      symbol,
            "sample_date": date_str,
            "outcome":     "INSUFFICIENT_FUTURE_DATA",   # passthrough label — scorer ignores it
        }
        record.update(flat_ohlcv)
        records.append(record)

    df = pd.DataFrame(records)
    logging.info("DataFrame built: %d rows, %d columns before regime", len(df), len(df.columns))

    # Compute regime features (identical to export_ml_dataset_regime.py)
    df = _compute_regime_features(df)
    logging.info("Regime features computed.")

    # Validate expected features all present
    missing_features = [f for f in expected_features if f not in df.columns]
    if missing_features:
        raise ValueError(
            f"Missing expected feature columns in output: {missing_features}. "
            "The scoring CSV would not be compatible with the HGB model."
        )

    # Validate NaN / inf
    feature_df = df[expected_features]
    if feature_df.isna().any().any():
        raise ValueError("NaN values found in feature columns — aborting.")
    if np.isinf(feature_df.select_dtypes(include=np.number).values).any():
        raise ValueError("Infinite values found in feature columns — aborting.")

    # Assemble final column order: symbol, sample_date, outcome, <features>
    metadata_cols   = ["symbol", "sample_date", "outcome"]
    ohlcv_feature_cols  = [c for c in expected_features if c not in REGIME_COLS]
    final_cols = metadata_cols + ohlcv_feature_cols + REGIME_COLS
    # Only include columns that exist in df
    final_cols = [c for c in final_cols if c in df.columns]
    df_out = df[final_cols].reset_index(drop=True)

    # Write CSV
    df_out.to_csv(out_csv, index=False)
    logging.info("Scoring CSV written to %s (%d rows)", out_csv, len(df_out))

    # Metadata
    meta = {
        "sample_date":             sample_date,
        "row_count":               int(len(df_out)),
        "model_version":           "stock_opportunity_hgb_regime_v1",
        "training_cutoff_date":    training_cutoff_date,
        "source_table":            "ml_samples",
        "source_outcome":          "INSUFFICIENT_FUTURE_DATA",
        "trainable_rows_for_date": 0,
        "feature_count":           len(expected_features),
        "created_at":              datetime.now(timezone.utc).isoformat(),
        "leakage_safe":            True,
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    logging.info("Scoring meta written to %s", out_meta)

    logging.info("=== export_scoring_snapshot COMPLETE ===")
    return {
        "row_count":    int(len(df_out)),
        "feature_count": len(expected_features),
        "output_csv":   str(out_csv),
        "output_meta":  str(out_meta),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export a feature-only scoring CSV for one clean post-training sample_date.\n\n"
            "Safety rules:\n"
            "  - sample_date must be strictly after --training-cutoff-date.\n"
            "  - Zero trainable=1 rows may exist in ml_samples for that date.\n"
            "  - At least one INSUFFICIENT_FUTURE_DATA row must exist for that date.\n"
            "  - Archive output files must not already exist.\n\n"
            "No DB writes. No model modifications. No shadow_tracking changes.\n\n"
            "Example:\n"
            "  python -m app.scripts.export_scoring_snapshot --sample-date 2026-05-19"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sample-date",
        type=str,
        required=True,
        help="YYYY-MM-DD date to export (must be after training cutoff).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory for output files (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--training-cutoff-date",
        type=str,
        default=DEFAULT_TRAINING_CUTOFF,
        help=(
            f"Training cutoff date (exclusive). sample_date must be strictly after this. "
            f"Default: {DEFAULT_TRAINING_CUTOFF}."
        ),
    )
    args = parser.parse_args()

    result = export_scoring_snapshot(
        sample_date=args.sample_date,
        output_dir=Path(args.output_dir),
        training_cutoff_date=args.training_cutoff_date,
    )
    print("=== export_scoring_snapshot RESULT ===")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
