import sys
import json
import os
import argparse
from typing import List, Dict, Any, Optional
from collections import defaultdict

from app.shadow_tracking import (
    get_connection,
    DEFAULT_DB_PATH,
    get_resolved_records_by_model,
)
from app.ml_foundation import ML_TARGET_PERCENT, ML_STOP_PERCENT

V124_DISCLAIMER = """\
======================================================================
DISCLAIMER:
One scored date only. Shadow diagnostic only.
Not enough evidence for model promotion.
This is shadow observation only. No real trade. No demo trade.
No capital. No position sizing.
======================================================================"""


def get_resolved_records(db_path: str) -> List[Dict[str, Any]]:
    """Fetch all RESOLVED rows regardless of model_version.

    Preserved for backward compatibility. Prefer get_resolved_records_by_model
    when model_version is known.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shadow_tracking WHERE tracking_status = 'RESOLVED'")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calculate_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
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


def format_metrics(name: str, metrics: Dict[str, Any]) -> str:
    lines = [f"--- {name} ---"]
    for k, v in metrics.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def get_prob_band(prob: float) -> str:
    if prob >= 0.50:
        return ">= 0.50"
    elif prob >= 0.40:
        return "0.40 to 0.50"
    elif prob >= 0.30:
        return "0.30 to 0.40"
    else:
        return "below 0.30"


def run_report(
    shadow_db_path: str = DEFAULT_DB_PATH,
    exports_dir: str = "/app/data/exports",
    model_version: Optional[str] = None,
) -> None:
    """Generate shadow performance report.

    Args:
        shadow_db_path: Path to shadow tracking DB.
        exports_dir:    Directory to write report files.
        model_version:  If provided, report covers only resolved rows for this
                        model_version.  Output filenames will include the
                        model_version slug to prevent overwriting other reports.
                        If None, all RESOLVED rows are included (backward
                        compatible).

    V1.24 note
    ----------
    HGB performance is grouped by bucket (PRIMARY_TOP_1 / WATCH_TOP_5) rather
    than by old LogisticRegression rank bands (1-4, 5-10, etc.).  The bucket
    column already encodes the correct membership; rank bands would be
    misleading for a different shortlist size.
    """
    os.makedirs(exports_dir, exist_ok=True)

    # --- Fetch records -------------------------------------------------------
    if model_version:
        records = get_resolved_records_by_model(shadow_db_path, model_version)
        version_slug = model_version
    else:
        records = get_resolved_records(shadow_db_path)
        version_slug = "all_models"

    # --- Header info ---------------------------------------------------------
    report_header = "\n".join([
        "ML SHADOW PERFORMANCE REPORT (V1.24)",
        V124_DISCLAIMER,
        f"Model version filter : {model_version if model_version else '(none — all models)'}",
        f"Total resolved rows  : {len(records)}",
        "",
    ])

    if not records:
        msg = f"No RESOLVED records found for model_version={model_version!r}."
        print(report_header)
        print(msg)
        return

    # --- Build summary -------------------------------------------------------
    summary: Dict[str, Any] = {
        "model_version": model_version,
        "overall": calculate_metrics(records),
        "by_bucket": {},
        "by_date": {},
        "by_outcome": {},
        "by_days": {},
        "by_prob_band": {},
    }

    groups: Dict[str, Any] = {
        "by_bucket":    defaultdict(list),
        "by_date":      defaultdict(list),
        "by_outcome":   defaultdict(list),
        "by_days":      defaultdict(list),
        "by_prob_band": defaultdict(list),
    }

    for r in records:
        groups["by_bucket"][r["bucket"]].append(r)
        groups["by_date"][r["scored_sample_date"]].append(r)
        groups["by_outcome"][r["future_observed_outcome"]].append(r)
        days = r.get("days_to_outcome")
        groups["by_days"][str(days) if days is not None else "Unknown"].append(r)
        groups["by_prob_band"][get_prob_band(r["win_probability"])].append(r)

    for k, grp in groups.items():
        for group_name, group_records in grp.items():
            summary[k][group_name] = calculate_metrics(group_records)

    # --- Save JSON -----------------------------------------------------------
    json_filename = f"shadow_performance_summary_{version_slug}.json"
    json_path = os.path.join(exports_dir, json_filename)
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    # --- Build text report ---------------------------------------------------
    report_lines = [
        report_header,
        format_metrics("1. OVERALL SHADOW PERFORMANCE", summary["overall"]),
        # NOTE: HGB groups by bucket (PRIMARY_TOP_1 / WATCH_TOP_5), not by
        # hardcoded LR rank bands (1-4, 5-10, 11-22, 23+).
        "2. BY BUCKET (PRIMARY_TOP_1 / WATCH_TOP_5)",
    ]
    for k, v in sorted(summary["by_bucket"].items()):
        report_lines.append(format_metrics(k, v))

    report_lines.append("3. BY SCORED SAMPLE DATE")
    for k, v in sorted(summary["by_date"].items()):
        report_lines.append(format_metrics(k, v))

    report_lines.append("4. BY OUTCOME")
    for k, v in summary["by_outcome"].items():
        report_lines.append(format_metrics(k, v))

    report_lines.append("5. BY DAYS TO OUTCOME")
    for k, v in sorted(
        summary["by_days"].items(),
        key=lambda x: float(x[0]) if x[0] != "Unknown" else 999,
    ):
        report_lines.append(format_metrics(f"{k} days", v))

    report_lines.append("6. BY PROBABILITY BAND")
    for k, v in summary["by_prob_band"].items():
        report_lines.append(format_metrics(k, v))

    report_lines.append(V124_DISCLAIMER)

    full_report = "\n".join(report_lines)

    # --- Save text report with model-version in filename --------------------
    txt_filename = f"shadow_performance_report_{version_slug}.txt"
    txt_path = os.path.join(exports_dir, txt_filename)
    with open(txt_path, "w") as f:
        f.write(full_report)

    print(full_report)
    print(f"\nSaved JSON  : {json_path}")
    print(f"Saved report: {txt_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate shadow performance report.\n\n"
            "Pass --model-version to restrict the report to one model and\n"
            "produce model-version-specific output filenames."
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
        help="Directory to save report artifacts",
    )
    parser.add_argument(
        "--model-version",
        type=str,
        default=None,
        help=(
            "Restrict report to RESOLVED rows for this model_version. "
            "Output filenames will include the model_version slug. "
            "Example: --model-version stock_opportunity_hgb_regime_v1"
        ),
    )
    args = parser.parse_args()

    run_report(
        shadow_db_path=args.db_path,
        exports_dir=args.exports_dir,
        model_version=args.model_version,
    )


if __name__ == "__main__":
    main()
