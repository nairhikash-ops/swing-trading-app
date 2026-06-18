"""compare_shadow_model_versions.py

Read-only comparison of two shadow-tracked model versions on a given
scored_sample_date.

Usage
-----
    python -m app.scripts.compare_shadow_model_versions \\
        --date 2026-05-18 \\
        --model-a stock_opportunity_hgb_regime_v1 \\
        --model-b stock_opportunity_ohlcv_regime_v1

Safety contract
---------------
* This script NEVER writes to shadow_tracking.sqlite3.
* It may only write export/report files to the exports directory.
* It includes OBSERVING (unresolved) rows in the status summary so that
  a premature-comparison warning can be shown.
* It never claims model superiority.
"""

import json
import os
import argparse
from typing import Any, Dict, List, Optional
from collections import defaultdict

from app.shadow_tracking import (
    DEFAULT_DB_PATH,
    get_all_records_by_model,
)
from app.ml_foundation import ML_TARGET_PERCENT, ML_STOP_PERCENT


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "One scored date only. Shadow diagnostic only. "
    "Not enough evidence for model promotion."
)

FULL_DISCLAIMER = f"""\
{'=' * 70}
DISCLAIMER:
{DISCLAIMER}
This comparison is informational only. No model promotion decision
should be made based on a single scored date.
{'=' * 70}"""


# ---------------------------------------------------------------------------
# Metric helpers (read-only, operates on plain list of dicts)
# ---------------------------------------------------------------------------

def calculate_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute performance metrics for a list of RESOLVED shadow records."""
    row_count = len(records)
    if row_count == 0:
        return {
            "row_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "timeout_count": 0,
            "ambiguous_count": 0,
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "avg_win_probability": 0.0,
            "avg_days_to_outcome": 0.0,
            "gross_expectancy": 0.0,
        }

    win_count      = sum(1 for r in records if r["future_observed_outcome"] == "WIN")
    loss_count     = sum(1 for r in records if r["future_observed_outcome"] == "LOSS")
    timeout_count  = sum(1 for r in records if r["future_observed_outcome"] == "TIMEOUT")
    ambiguous_count = sum(1 for r in records if r["future_observed_outcome"] == "AMBIGUOUS")

    total_prob = sum(r["win_probability"] for r in records)
    days_list  = [r["days_to_outcome"] for r in records if r.get("days_to_outcome") is not None]

    avg_prob = total_prob / row_count
    avg_days = sum(days_list) / len(days_list) if days_list else 0.0
    win_rate  = win_count  / row_count
    loss_rate = loss_count / row_count

    valid_expectancy_rows = win_count + loss_count + timeout_count
    if valid_expectancy_rows > 0:
        p_win  = win_count  / valid_expectancy_rows
        p_loss = loss_count / valid_expectancy_rows
        gross_expectancy = (p_win * ML_TARGET_PERCENT) - (p_loss * ML_STOP_PERCENT)
    else:
        gross_expectancy = 0.0

    return {
        "row_count": row_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "timeout_count": timeout_count,
        "ambiguous_count": ambiguous_count,
        "win_rate": round(win_rate, 4),
        "loss_rate": round(loss_rate, 4),
        "avg_win_probability": round(avg_prob, 4),
        "avg_days_to_outcome": round(avg_days, 2),
        "gross_expectancy": round(gross_expectancy, 4),
    }


def get_prob_band(prob: float) -> str:
    if prob >= 0.50:
        return ">= 0.50"
    elif prob >= 0.40:
        return "0.40 to 0.50"
    elif prob >= 0.30:
        return "0.30 to 0.40"
    else:
        return "below 0.30"


# ---------------------------------------------------------------------------
# Status summary (includes OBSERVING rows — never writes)
# ---------------------------------------------------------------------------

def build_model_status(
    all_rows: List[Dict[str, Any]],
    scored_date: str,
) -> Dict[str, Any]:
    """Summarise ALL rows (OBSERVING + RESOLVED) for one model on one date.

    The scored_date filter is applied here so the comparison is limited to
    the same observation window for both models.
    """
    date_rows = [r for r in all_rows if r["scored_sample_date"] == scored_date]

    observing = [r for r in date_rows if r["tracking_status"] == "OBSERVING"]
    resolved  = [r for r in date_rows if r["tracking_status"] == "RESOLVED"]

    bucket_counts: Dict[str, int] = defaultdict(int)
    for r in date_rows:
        bucket_counts[r["bucket"]] += 1

    outcome_counts: Dict[str, int] = defaultdict(int)
    for r in resolved:
        outcome_counts[r["future_observed_outcome"]] += 1

    is_premature = len(observing) > 0

    return {
        "total_rows_on_date": len(date_rows),
        "observing_count": len(observing),
        "resolved_count": len(resolved),
        "is_premature": is_premature,
        "bucket_counts": dict(bucket_counts),
        "outcome_counts": dict(outcome_counts),
        "resolved_records": resolved,
        "symbols_on_date": {r["symbol"] for r in date_rows},
    }


# ---------------------------------------------------------------------------
# Overlap analysis
# ---------------------------------------------------------------------------

def build_overlap(
    status_a: Dict[str, Any],
    status_b: Dict[str, Any],
    model_a: str,
    model_b: str,
    all_rows_a: List[Dict[str, Any]],
    all_rows_b: List[Dict[str, Any]],
    scored_date: str,
) -> List[Dict[str, Any]]:
    """Find symbols present in both models' shortlists on scored_date.

    Returns a list of dicts with symbol, model_a outcome, model_b outcome.
    """
    overlap_syms = status_a["symbols_on_date"] & status_b["symbols_on_date"]

    # Index by symbol for O(1) lookup
    idx_a = {
        r["symbol"]: r
        for r in all_rows_a
        if r["scored_sample_date"] == scored_date
    }
    idx_b = {
        r["symbol"]: r
        for r in all_rows_b
        if r["scored_sample_date"] == scored_date
    }

    overlap = []
    for sym in sorted(overlap_syms):
        row_a = idx_a.get(sym, {})
        row_b = idx_b.get(sym, {})
        overlap.append({
            "symbol": sym,
            f"{model_a}_bucket": row_a.get("bucket"),
            f"{model_a}_outcome": row_a.get("future_observed_outcome"),
            f"{model_a}_status": row_a.get("tracking_status"),
            f"{model_a}_win_probability": row_a.get("win_probability"),
            f"{model_b}_bucket": row_b.get("bucket"),
            f"{model_b}_outcome": row_b.get("future_observed_outcome"),
            f"{model_b}_status": row_b.get("tracking_status"),
            f"{model_b}_win_probability": row_b.get("win_probability"),
        })

    return overlap


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def fmt(label: str, value: Any) -> str:
    return f"  {label:<40}: {value}"


def format_status_block(model: str, status: Dict[str, Any]) -> str:
    lines = [f"--- {model} ---"]
    lines.append(fmt("Total rows on date", status["total_rows_on_date"]))
    lines.append(fmt("OBSERVING (not yet resolved)", status["observing_count"]))
    lines.append(fmt("RESOLVED", status["resolved_count"]))
    if status["is_premature"]:
        lines.append(
            f"  *** WARNING: Comparison is premature — "
            f"{status['observing_count']} row(s) still OBSERVING ***"
        )
    lines.append(fmt("Bucket counts", dict(status["bucket_counts"])))
    lines.append(fmt("Outcome counts (resolved only)", dict(status["outcome_counts"])))
    lines.append("")
    return "\n".join(lines)


def format_metrics_block(label: str, metrics: Dict[str, Any]) -> str:
    lines = [f"  [{label}]"]
    for k, v in metrics.items():
        lines.append(f"    {k}: {v}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main comparison runner
# ---------------------------------------------------------------------------

def run_comparison(
    shadow_db_path: str = DEFAULT_DB_PATH,
    scored_date: str = "",
    model_a: str = "",
    model_b: str = "",
    exports_dir: str = "/app/data/exports",
) -> None:
    """Run a read-only comparison of two model versions on one scored date.

    This function NEVER writes to shadow_tracking.sqlite3.
    """
    os.makedirs(exports_dir, exist_ok=True)

    lines: List[str] = []

    # --- Disclaimer always first --------------------------------------------
    lines.append(FULL_DISCLAIMER)
    lines.append("")
    lines.append(f"Scored date : {scored_date}")
    lines.append(f"Model A     : {model_a}")
    lines.append(f"Model B     : {model_b}")
    lines.append("")

    # --- Fetch all rows for both models (read-only) -------------------------
    all_rows_a = get_all_records_by_model(shadow_db_path, model_a)
    all_rows_b = get_all_records_by_model(shadow_db_path, model_b)

    status_a = build_model_status(all_rows_a, scored_date)
    status_b = build_model_status(all_rows_b, scored_date)

    # --- Section 1: Status summary ------------------------------------------
    lines.append("=" * 70)
    lines.append("1. STATUS SUMMARY (includes OBSERVING rows)")
    lines.append("=" * 70)
    lines.append(format_status_block(model_a, status_a))
    lines.append(format_status_block(model_b, status_b))

    any_premature = status_a["is_premature"] or status_b["is_premature"]
    if any_premature:
        lines.append(
            "*** WARNING: One or both models have unresolved OBSERVING rows. ***\n"
            "*** The performance comparison below is INCOMPLETE.             ***\n"
            "*** Re-run after all outcomes are resolved.                     ***"
        )
        lines.append("")

    # --- Section 2: Per-model resolved performance --------------------------
    lines.append("=" * 70)
    lines.append("2. RESOLVED PERFORMANCE BY BUCKET")
    lines.append("=" * 70)

    for model, status in [(model_a, status_a), (model_b, status_b)]:
        resolved = status["resolved_records"]
        lines.append(f"--- {model} ({status['resolved_count']} resolved rows) ---")

        if not resolved:
            lines.append("  No RESOLVED rows — comparison premature.")
            lines.append("")
            continue

        # Group by bucket
        by_bucket: Dict[str, List] = defaultdict(list)
        for r in resolved:
            by_bucket[r["bucket"]].append(r)

        overall_metrics = calculate_metrics(resolved)
        lines.append(format_metrics_block("OVERALL", overall_metrics))

        for bucket_name in sorted(by_bucket.keys()):
            m = calculate_metrics(by_bucket[bucket_name])
            lines.append(format_metrics_block(bucket_name, m))

    # --- Section 3: Overlap analysis ----------------------------------------
    lines.append("=" * 70)
    lines.append("3. SYMBOL OVERLAP ANALYSIS")
    lines.append("=" * 70)

    overlap = build_overlap(
        status_a, status_b, model_a, model_b, all_rows_a, all_rows_b, scored_date
    )

    if not overlap:
        lines.append("  No symbols appear in both models' shortlists on this date.")
    else:
        lines.append(f"  {len(overlap)} symbol(s) appear in both shortlists:")
        lines.append(
            f"  {'symbol':<12} "
            f"{'A_bucket':<18} {'A_outcome':<14} "
            f"{'B_bucket':<18} {'B_outcome':<14}"
        )
        lines.append("  " + "-" * 80)
        for row in overlap:
            a_bucket  = str(row.get(f"{model_a}_bucket") or "N/A")
            a_outcome = str(row.get(f"{model_a}_outcome") or row.get(f"{model_a}_status") or "N/A")
            b_bucket  = str(row.get(f"{model_b}_bucket") or "N/A")
            b_outcome = str(row.get(f"{model_b}_outcome") or row.get(f"{model_b}_status") or "N/A")
            lines.append(
                f"  {row['symbol']:<12} "
                f"{a_bucket:<18} {a_outcome:<14} "
                f"{b_bucket:<18} {b_outcome:<14}"
            )
    lines.append("")

    # --- Section 4: Caveats -------------------------------------------------
    lines.append("=" * 70)
    lines.append("4. CAVEATS")
    lines.append("=" * 70)
    lines.append(FULL_DISCLAIMER)

    full_report = "\n".join(lines)
    print(full_report)

    # --- Write JSON export (read-only from DB perspective) ------------------
    model_a_slug = model_a.replace("/", "_")
    model_b_slug = model_b.replace("/", "_")
    json_filename = f"compare_shadow_{model_a_slug}_vs_{model_b_slug}_{scored_date}.json"
    json_path = os.path.join(exports_dir, json_filename)

    export = {
        "scored_date": scored_date,
        "model_a": model_a,
        "model_b": model_b,
        "disclaimer": DISCLAIMER,
        "status_a": {
            k: v for k, v in status_a.items() if k != "resolved_records" and k != "symbols_on_date"
        },
        "status_b": {
            k: v for k, v in status_b.items() if k != "resolved_records" and k != "symbols_on_date"
        },
        "metrics_a": {
            "overall": calculate_metrics(status_a["resolved_records"]),
            "by_bucket": {
                bucket: calculate_metrics(recs)
                for bucket, recs in (
                    lambda rows: {
                        b: [r for r in rows if r["bucket"] == b]
                        for b in set(r["bucket"] for r in rows)
                    }
                )(status_a["resolved_records"]).items()
            } if status_a["resolved_records"] else {},
        },
        "metrics_b": {
            "overall": calculate_metrics(status_b["resolved_records"]),
            "by_bucket": {
                bucket: calculate_metrics(recs)
                for bucket, recs in (
                    lambda rows: {
                        b: [r for r in rows if r["bucket"] == b]
                        for b in set(r["bucket"] for r in rows)
                    }
                )(status_b["resolved_records"]).items()
            } if status_b["resolved_records"] else {},
        },
        "overlap": overlap,
    }

    with open(json_path, "w") as f:
        json.dump(export, f, indent=2)

    print(f"\nSaved comparison JSON: {json_path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only comparison of two shadow-tracked model versions.\n\n"
            "This script NEVER writes to shadow_tracking.sqlite3.\n"
            "It may only write export/report files.\n\n"
            "V1.24 safety rule: always inspect the premature-comparison\n"
            "warning before drawing any conclusion."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_DB_PATH,
        help="Path to shadow tracking DB",
    )
    parser.add_argument(
        "--exports-dir",
        type=str,
        default="/app/data/exports",
        help="Directory to save comparison JSON",
    )
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="scored_sample_date to compare (e.g. 2026-05-18)",
    )
    parser.add_argument(
        "--model-a",
        type=str,
        required=True,
        help="First model_version (e.g. stock_opportunity_hgb_regime_v1)",
    )
    parser.add_argument(
        "--model-b",
        type=str,
        required=True,
        help="Second model_version (e.g. stock_opportunity_ohlcv_regime_v1)",
    )
    args = parser.parse_args()

    run_comparison(
        shadow_db_path=args.db_path,
        scored_date=args.date,
        model_a=args.model_a,
        model_b=args.model_b,
        exports_dir=args.exports_dir,
    )


if __name__ == "__main__":
    main()
