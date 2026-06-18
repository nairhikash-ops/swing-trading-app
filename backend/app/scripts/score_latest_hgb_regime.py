# backend/app/scripts/score_latest_hgb_regime.py
"""Scoring script for the HistGradientBoosting shadow-candidate model (V1.22+).

- Loads the feature export CSV.
- Optionally filters to a specific sample_date via --sample-date (V1.25).
  If omitted, uses the latest date in the dataset.
- Uses the HGB model trained by `train_hgb_regime_candidate.py`.
- Produces:
    latest_hgb_regime_rankings.csv              (always updated)
    latest_hgb_regime_rankings.meta.json        (always updated)
    hgb_regime_rankings_YYYY-MM-DD.csv          (date-stamped archive, never overwritten)
    hgb_regime_rankings_YYYY-MM-DD.meta.json    (date-stamped archive, never overwritten)
- Logs key information at INFO level.

V1.25 safety rules
------------------
- If the date-stamped archive files already exist, the script aborts with a
  clear error. Silent overwrite is forbidden.
- `is_live_today` is written to meta so the tracker can enforce its guard.
- Column name is `win_probability` (not `win_prob`).
- Meta key is `scored_sample_date` (not `scored_date`).
"""

import argparse
import logging
import json
from datetime import date as _date
from pathlib import Path

import pandas as pd
import numpy as np
from joblib import load

DEFAULT_DATASET_CSV  = Path("/app/data/exports/ml_dataset_ohlcv_regime_v1.csv")
DEFAULT_MODEL_ROOT   = Path("/app/data/models/stock_opportunity_hgb_regime_v1")
DEFAULT_EXPORTS_DIR  = Path("/app/data/exports")
DEFAULT_RANKING_CSV  = DEFAULT_EXPORTS_DIR / "latest_hgb_regime_rankings.csv"
DEFAULT_RANKING_META = DEFAULT_EXPORTS_DIR / "latest_hgb_regime_rankings.meta.json"


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _load_schema(schema_path: Path) -> list:
    """Load feature names from a schema file.

    Handles two formats:
      - Bare JSON list:  ["c00_open_rel", "c00_high_rel", ...]  (real HGB model)
      - Dict format:     {"features": [...]}  (test fixtures / LR model)
    """
    with schema_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        return raw
    elif isinstance(raw, dict):
        return (
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


def _resolve_sample_date(df: pd.DataFrame, requested: str | None) -> str:
    """Return the scoring date as a YYYY-MM-DD string.

    If ``requested`` is None, returns the latest date in the dataset.
    If ``requested`` is supplied but not in the dataset, raises ValueError.
    """
    available = set(pd.to_datetime(df["sample_date"]).dt.strftime("%Y-%m-%d").unique())
    if requested is None:
        latest = pd.to_datetime(df["sample_date"]).max()
        return latest.strftime("%Y-%m-%d")
    if requested not in available:
        raise ValueError(
            f"Requested --sample-date '{requested}' is not present in the dataset. "
            f"Available range: {min(available)} to {max(available)}."
        )
    return requested


def score(
    dataset_csv: Path = DEFAULT_DATASET_CSV,
    model_root: Path = DEFAULT_MODEL_ROOT,
    ranking_csv: Path = DEFAULT_RANKING_CSV,
    ranking_meta: Path = DEFAULT_RANKING_META,
    exports_dir: Path = DEFAULT_EXPORTS_DIR,
    sample_date: str | None = None,
) -> None:
    """Score the HGB model for a given (or latest) sample_date.

    Args:
        dataset_csv:   Path to the feature CSV (all dates).
        model_root:    Directory containing model.joblib and feature_schema.json.
        ranking_csv:   Path for latest_hgb_regime_rankings.csv (always updated).
        ranking_meta:  Path for latest_hgb_regime_rankings.meta.json (always updated).
        exports_dir:   Base exports directory used to write date-stamped archives.
        sample_date:   YYYY-MM-DD string to score. If None, uses latest date in CSV.

    V1.25: Writes date-stamped archive files in addition to latest files.
           Aborts if archive files already exist (never silently overwrites).
    """
    _setup_logging()
    logging.info("Scoring using dataset: %s", dataset_csv)
    logging.info("Model directory: %s", model_root)

    # Load model and schema
    model_path  = model_root / "model.joblib"
    schema_path = model_root / "feature_schema.json"
    clf = load(model_path)
    feature_order = _load_schema(schema_path)
    logging.info("Feature count (from schema): %d", len(feature_order))

    # Load only required columns
    usecols = feature_order + ["symbol", "sample_date"]
    df = pd.read_csv(dataset_csv, usecols=usecols)
    logging.info("Rows loaded for scoring: %d", len(df))

    # Resolve scoring date
    target_date_str = _resolve_sample_date(df, sample_date)
    logging.info("Scoring date: %s", target_date_str)

    # Filter to that date only
    df_scored = df[pd.to_datetime(df["sample_date"]).dt.strftime("%Y-%m-%d") == target_date_str].copy()
    logging.info("Rows for scoring date %s: %d", target_date_str, len(df_scored))

    if df_scored.empty:
        raise ValueError(f"No rows found for sample_date={target_date_str!r} after filtering.")

    # Predict
    X = df_scored[feature_order].astype(np.float32)
    probs = clf.predict_proba(X)[:, 1]   # probability of WIN (class 1)
    df_scored["win_probability"] = probs  # V1.25: column is win_probability

    # Rank descending by probability
    df_scored.sort_values("win_probability", ascending=False, inplace=True)
    df_scored["rank"] = np.arange(1, len(df_scored) + 1)

    # Determine is_live_today
    today_str = _date.today().strftime("%Y-%m-%d")
    is_live_today: bool = target_date_str == today_str

    # --- Check archive paths before writing anything -------------------------
    exports_dir = Path(exports_dir)
    exports_dir.mkdir(parents=True, exist_ok=True)

    archive_csv  = exports_dir / f"hgb_regime_rankings_{target_date_str}.csv"
    archive_meta = exports_dir / f"hgb_regime_rankings_{target_date_str}.meta.json"

    if archive_csv.exists():
        raise FileExistsError(
            f"Archive file already exists: {archive_csv}. "
            "Refusing to overwrite. If this was intentional, remove the file manually "
            "and re-run. An explicit --overwrite flag is not supported."
        )
    if archive_meta.exists():
        raise FileExistsError(
            f"Archive meta already exists: {archive_meta}. "
            "Refusing to overwrite. Remove the file manually and re-run."
        )

    # --- Build output dataframe ----------------------------------------------
    ranking_cols = ["symbol", "sample_date", "win_probability", "rank"]
    df_out = df_scored[ranking_cols].reset_index(drop=True)

    # --- Write archive CSV + meta (date-stamped, never overwritten) ----------
    df_out.to_csv(archive_csv, index=False)
    logging.info("Archive ranking CSV written to %s", archive_csv)

    meta = {
        "model_version": "stock_opportunity_hgb_regime_v1",
        "source_csv": str(dataset_csv.name),
        "scored_sample_date": target_date_str,            # V1.25: correct key
        "row_count": int(len(df_scored)),
        "ranking_count": int(len(df_out)),
        "feature_schema_match": True,
        "is_live_today": is_live_today,                   # V1.25: guard key
        "purpose": "offline candidate scoring verification",
        "warning": "candidate only, not deployed for live trading",
    }
    archive_meta.write_text(json.dumps(meta, indent=2))
    logging.info("Archive ranking meta written to %s", archive_meta)

    # --- Write / update latest files -----------------------------------------
    ranking_csv = Path(ranking_csv)
    ranking_meta = Path(ranking_meta)
    df_out.to_csv(ranking_csv, index=False)
    logging.info("Latest ranking CSV written to %s", ranking_csv)
    ranking_meta.write_text(json.dumps(meta, indent=2))
    logging.info("Latest ranking meta written to %s", ranking_meta)

    logging.info("INFO – HGB scoring completed successfully for date=%s", target_date_str)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Score the HGB candidate model for a given sample date.\n\n"
            "V1.25: Writes date-stamped archive files in addition to the latest files.\n"
            "Archive files are never overwritten — the script aborts if they exist.\n\n"
            "Safety rule: This script does NOT write to shadow_tracking.sqlite3."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dataset-csv",
        type=str,
        default=str(DEFAULT_DATASET_CSV),
        help="Path to the ML dataset CSV (default: %(default)s)",
    )
    parser.add_argument(
        "--model-root",
        type=str,
        default=str(DEFAULT_MODEL_ROOT),
        help="Directory containing model.joblib and feature_schema.json",
    )
    parser.add_argument(
        "--exports-dir",
        type=str,
        default=str(DEFAULT_EXPORTS_DIR),
        help="Directory for all output files (default: %(default)s)",
    )
    parser.add_argument(
        "--sample-date",
        type=str,
        default=None,
        help=(
            "YYYY-MM-DD date to score. If omitted, uses the latest date in the dataset. "
            "If the date is not in the dataset, the script fails loudly. "
            "Example: --sample-date 2026-05-21"
        ),
    )
    args = parser.parse_args()

    exports_dir = Path(args.exports_dir)
    score(
        dataset_csv=Path(args.dataset_csv),
        model_root=Path(args.model_root),
        ranking_csv=exports_dir / "latest_hgb_regime_rankings.csv",
        ranking_meta=exports_dir / "latest_hgb_regime_rankings.meta.json",
        exports_dir=exports_dir,
        sample_date=args.sample_date,
    )


if __name__ == "__main__":
    main()
