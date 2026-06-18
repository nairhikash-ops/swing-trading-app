import sys
import json
import os
import argparse
from typing import List, Dict, Any
from collections import defaultdict

from app.shadow_tracking import get_connection, DEFAULT_DB_PATH
from app.ml_foundation import ML_TARGET_PERCENT, ML_STOP_PERCENT

REPORT_DISCLAIMER = """
======================================================================
DISCLAIMER: 
This is shadow observation only.
No real trade.
No demo trade.
No capital.
No position sizing.
One scored date only.
Not enough sample size for final model judgment.
======================================================================
"""

def get_resolved_records(db_path: str) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM shadow_tracking 
        WHERE tracking_status = 'RESOLVED'
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_rank_band(rank: int) -> str:
    if 1 <= rank <= 4:
        return "1-4"
    elif 5 <= rank <= 10:
        return "5-10"
    elif 11 <= rank <= 22:
        return "11-22"
    else:
        return "23+"

def get_prob_band(prob: float) -> str:
    if prob >= 0.50:
        return ">= 0.50"
    elif prob >= 0.40:
        return "0.40 to 0.50"
    elif prob >= 0.30:
        return "0.30 to 0.40"
    else:
        return "below 0.30"

def calculate_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    row_count = len(records)
    if row_count == 0:
        return {
            "row_count": 0, "win_count": 0, "loss_count": 0, "timeout_count": 0, "ambiguous_count": 0,
            "win_rate": 0.0, "loss_rate": 0.0, "avg_win_probability": 0.0, "avg_days_to_outcome": 0.0,
            "gross_expectancy": 0.0
        }
    
    win_count = sum(1 for r in records if r["future_observed_outcome"] == "WIN")
    loss_count = sum(1 for r in records if r["future_observed_outcome"] == "LOSS")
    timeout_count = sum(1 for r in records if r["future_observed_outcome"] == "TIMEOUT")
    ambiguous_count = sum(1 for r in records if r["future_observed_outcome"] == "AMBIGUOUS")
    
    total_prob = sum(r["win_probability"] for r in records)
    # days_to_outcome can be None or not present for TIMEOUTs depending on the resolver logic, but TIMEOUT sets it to 20
    days_list = [r["days_to_outcome"] for r in records if r.get("days_to_outcome") is not None]
    
    avg_prob = total_prob / row_count if row_count > 0 else 0.0
    avg_days = sum(days_list) / len(days_list) if len(days_list) > 0 else 0.0
    
    # Win rate and loss rate: usually calculated as a percentage of all non-ambiguous outcomes or all rows?
    # Usually relative to all rows or WIN+LOSS+TIMEOUT
    win_rate = win_count / row_count
    loss_rate = loss_count / row_count
    
    # Expectancy calculation (AMBIGUOUS excluded)
    valid_expectancy_rows = win_count + loss_count + timeout_count
    if valid_expectancy_rows > 0:
        # P(WIN) * TARGET + P(LOSS) * STOP + P(TIMEOUT) * 0
        # Wait, the user formula: Gross expectancy = (W/Total * 7) - (L/Total * 3)
        # Using the exact formula provided by user where Total = valid_expectancy_rows
        p_win = win_count / valid_expectancy_rows
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
        "gross_expectancy": round(gross_expectancy, 4)
    }

def format_metrics(name: str, metrics: Dict[str, Any]) -> str:
    lines = [f"--- {name} ---"]
    for k, v in metrics.items():
        lines.append(f"{k}: {v}")
    lines.append("")
    return "\n".join(lines)

def run_report(
    shadow_db_path: str = DEFAULT_DB_PATH,
    exports_dir: str = "/app/data/exports"
):
    os.makedirs(exports_dir, exist_ok=True)
    records = get_resolved_records(shadow_db_path)
    
    if not records:
        print("No RESOLVED records found to report on.")
        return
        
    summary = {
        "overall": calculate_metrics(records),
        "by_bucket": {},
        "by_date": {},
        "by_outcome": {},
        "by_days": {},
        "by_rank_band": {},
        "by_prob_band": {}
    }
    
    # Grouping aggregators
    groups = {
        "by_bucket": defaultdict(list),
        "by_date": defaultdict(list),
        "by_outcome": defaultdict(list),
        "by_days": defaultdict(list),
        "by_rank_band": defaultdict(list),
        "by_prob_band": defaultdict(list)
    }
    
    for r in records:
        groups["by_bucket"][r["bucket"]].append(r)
        groups["by_date"][r["scored_sample_date"]].append(r)
        groups["by_outcome"][r["future_observed_outcome"]].append(r)
        days = r.get("days_to_outcome")
        groups["by_days"][str(days) if days is not None else "Unknown"].append(r)
        groups["by_rank_band"][get_rank_band(r["rank"])].append(r)
        groups["by_prob_band"][get_prob_band(r["win_probability"])].append(r)
        
    for k, grp in groups.items():
        for group_name, group_records in grp.items():
            summary[k][group_name] = calculate_metrics(group_records)
            
    # Output JSON
    json_path = os.path.join(exports_dir, "shadow_performance_summary.json")
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
        
    # Output Text
    report_lines = [
        "ML V1.11 SHADOW PERFORMANCE REPORT",
        REPORT_DISCLAIMER,
        format_metrics("1. OVERALL SHADOW PERFORMANCE", summary["overall"]),
        "2. BY BUCKET"
    ]
    for k, v in summary["by_bucket"].items():
        report_lines.append(format_metrics(k, v))
        
    report_lines.append("3. BY SCORED SAMPLE DATE")
    for k, v in summary["by_date"].items():
        report_lines.append(format_metrics(k, v))
        
    report_lines.append("4. BY OUTCOME")
    for k, v in summary["by_outcome"].items():
        report_lines.append(format_metrics(k, v))
        
    report_lines.append("5. BY DAYS TO OUTCOME")
    for k, v in sorted(summary["by_days"].items(), key=lambda x: float(x[0]) if x[0] != "Unknown" else 999):
        report_lines.append(format_metrics(f"{k} days", v))
        
    report_lines.append("6. BY RANK BAND")
    for k, v in summary["by_rank_band"].items():
        report_lines.append(format_metrics(k, v))
        
    report_lines.append("7. BY PROBABILITY BAND")
    for k, v in summary["by_prob_band"].items():
        report_lines.append(format_metrics(k, v))
        
    full_report = "\n".join(report_lines)
    
    txt_path = os.path.join(exports_dir, "shadow_performance_report.txt")
    with open(txt_path, "w") as f:
        f.write(full_report)
        
    v1_path = os.path.join(exports_dir, "shadow_performance_report_v1.txt")
    with open(v1_path, "w") as f:
        f.write(full_report)
        
    print(full_report)
    print(f"\nSaved report artifacts to: {exports_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate V1.11 Shadow Performance Report")
    parser.add_argument("--db-path", type=str, default=DEFAULT_DB_PATH, help="Path to shadow tracking DB")
    parser.add_argument("--exports-dir", type=str, default="/app/data/exports", help="Directory to save report artifacts")
    args = parser.parse_args()
    
    run_report(shadow_db_path=args.db_path, exports_dir=args.exports_dir)

if __name__ == "__main__":
    main()
