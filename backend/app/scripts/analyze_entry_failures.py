"""
analyze_entry_failures.py

ML V1.18 Entry Failure Diagnosis.
Read-only script to analyze Day-1 losses by separating gap-down stops,
intraday stop hits, and missing/unclassifiable cases.

Usage:
    python -m app.scripts.analyze_entry_failures
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.shadow_tracking import DEFAULT_DB_PATH

EXPORTS_DIR = "/app/data/exports"
REPORT_JSON_PATH = os.path.join(EXPORTS_DIR, "entry_failure_diagnosis.json")
REPORT_TXT_PATH = os.path.join(EXPORTS_DIR, "entry_failure_diagnosis.txt")

# Stop Mechanisms
GAP_DOWN_STOP = "GAP_DOWN_STOP"
INTRADAY_STOP = "INTRADAY_STOP"
NOT_CLASSIFIED = "NOT_CLASSIFIED"
UNCLASSIFIED_MISSING_ML_SAMPLE = "UNCLASSIFIED_MISSING_ML_SAMPLE"
UNCLASSIFIED_MISSING_NEXT_CANDLE = "UNCLASSIFIED_MISSING_NEXT_CANDLE"
UNCLASSIFIED_STOP_NOT_SEEN_IN_NEXT_CANDLE = "UNCLASSIFIED_STOP_NOT_SEEN_IN_NEXT_CANDLE"


def is_day1_loss(stop_mech: str) -> bool:
    return stop_mech in (
        GAP_DOWN_STOP,
        INTRADAY_STOP,
        UNCLASSIFIED_MISSING_ML_SAMPLE,
        UNCLASSIFIED_MISSING_NEXT_CANDLE,
        UNCLASSIFIED_STOP_NOT_SEEN_IN_NEXT_CANDLE,
    )



def load_resolved_records(shadow_db: str) -> list[dict[str, Any]]:
    if not os.path.exists(shadow_db):
        return []
    conn = sqlite3.connect(shadow_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM shadow_tracking WHERE tracking_status = 'RESOLVED'"
    ).fetchall()
    conn.close()
    
    records = []
    for row in rows:
        r = dict(row)
        try:
            r["_regime"] = json.loads(r.get("regime_context_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            r["_regime"] = {}
        records.append(r)
    return records


def classify_stop_mechanisms(
    records: list[dict[str, Any]],
    dhan_db: str,
) -> list[dict[str, Any]]:
    """
    For each Day-1 loss, classify the stop type using stored values in ml_samples
    and price action in daily_candles.
    """
    if not os.path.exists(dhan_db):
        for r in records:
            if r.get("days_to_outcome") == 1 and r.get("future_observed_outcome") == "LOSS":
                r["stop_mechanism"] = UNCLASSIFIED_MISSING_ML_SAMPLE
            else:
                r["stop_mechanism"] = NOT_CLASSIFIED
        return records

    conn = sqlite3.connect(dhan_db)
    conn.row_factory = sqlite3.Row

    for r in records:
        is_day1_loss = (r.get("days_to_outcome") == 1 and r.get("future_observed_outcome") == "LOSS")
        if not is_day1_loss:
            r["stop_mechanism"] = NOT_CLASSIFIED
            continue

        symbol = r["symbol"]
        scored_date = r["scored_sample_date"]

        # 1. Fetch matching ml_samples row
        sample_row = conn.execute(
            "SELECT entry_close, stop_price, instrument_id FROM ml_samples "
            "WHERE UPPER(symbol) = ? AND sample_date = ?",
            (symbol.upper(), scored_date)
        ).fetchone()

        if not sample_row:
            r["stop_mechanism"] = UNCLASSIFIED_MISSING_ML_SAMPLE
            continue

        entry_close = float(sample_row["entry_close"])
        stop_price = float(sample_row["stop_price"])
        instrument_id = int(sample_row["instrument_id"])

        # 2. Find next trading candle strictly after scored_sample_date
        next_candle = conn.execute(
            "SELECT open, low, high, close FROM daily_candles "
            "WHERE instrument_id = ? AND trading_date > ? "
            "ORDER BY trading_date ASC LIMIT 1",
            (instrument_id, scored_date)
        ).fetchone()

        if not next_candle:
            r["stop_mechanism"] = UNCLASSIFIED_MISSING_NEXT_CANDLE
            continue

        nc_open = float(next_candle["open"])
        nc_low = float(next_candle["low"])

        # 3. Classify Stop Mechanism
        r["entry_close"] = entry_close
        r["stop_price"] = stop_price
        r["next_day_open"] = nc_open
        r["next_day_low"] = nc_low

        if nc_open <= stop_price:
            r["stop_mechanism"] = GAP_DOWN_STOP
        elif nc_low <= stop_price:
            r["stop_mechanism"] = INTRADAY_STOP
        else:
            r["stop_mechanism"] = UNCLASSIFIED_STOP_NOT_SEEN_IN_NEXT_CANDLE

    conn.close()
    return records


# ---------------------------------------------------------------------------
# Report Assembly Helper Functions
# ---------------------------------------------------------------------------

def compute_overall_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    total_resolved = len(records)
    total_losses = sum(1 for r in records if r["future_observed_outcome"] == "LOSS")
    
    day1_losses = [r for r in records if is_day1_loss(r["stop_mechanism"])]
    day1_count = len(day1_losses)

    gap_down_count = sum(1 for r in records if r["stop_mechanism"] == GAP_DOWN_STOP)
    intraday_count = sum(1 for r in records if r["stop_mechanism"] == INTRADAY_STOP)
    missing_sample_count = sum(1 for r in records if r["stop_mechanism"] == UNCLASSIFIED_MISSING_ML_SAMPLE)
    missing_candle_count = sum(1 for r in records if r["stop_mechanism"] == UNCLASSIFIED_MISSING_NEXT_CANDLE)
    not_seen_count = sum(1 for r in records if r["stop_mechanism"] == UNCLASSIFIED_STOP_NOT_SEEN_IN_NEXT_CANDLE)

    return {
        "total_resolved": total_resolved,
        "total_losses": total_losses,
        "day1_loss_count": day1_count,
        "day1_loss_rate_of_losses": round(day1_count / total_losses, 4) if total_losses else 0.0,
        "day1_loss_rate_of_resolved": round(day1_count / total_resolved, 4) if total_resolved else 0.0,
        "gap_down_count": gap_down_count,
        "gap_down_pct_of_day1": round(gap_down_count / day1_count, 4) if day1_count else 0.0,
        "intraday_count": intraday_count,
        "intraday_pct_of_day1": round(intraday_count / day1_count, 4) if day1_count else 0.0,
        "unclassified_missing_sample_count": missing_sample_count,
        "unclassified_missing_candle_count": missing_candle_count,
        "unclassified_stop_not_seen_count": not_seen_count,
    }


def compute_date_concentration(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date = defaultdict(list)
    for r in records:
        by_date[r["scored_sample_date"]].append(r)

    results = []
    for date in sorted(by_date.keys()):
        grp = by_date[date]
        total = len(grp)
        losses = sum(1 for r in grp if r["future_observed_outcome"] == "LOSS")
        day1 = sum(1 for r in grp if is_day1_loss(r["stop_mechanism"]))
        gap_downs = sum(1 for r in grp if r["stop_mechanism"] == GAP_DOWN_STOP)
        intradays = sum(1 for r in grp if r["stop_mechanism"] == INTRADAY_STOP)
        
        results.append({
            "scored_sample_date": date,
            "total_picks": total,
            "total_losses": losses,
            "day1_losses": day1,
            "day1_loss_rate": round(day1 / total, 4) if total else 0.0,
            "gap_downs": gap_downs,
            "intradays": intradays,
        })
    return results


def _rank_band(rank: int) -> str:
    if rank <= 5:
        return "1-5"
    elif rank <= 10:
        return "6-10"
    elif rank <= 15:
        return "11-15"
    elif rank <= 22:
        return "16-22"
    else:
        return "23+"


def compute_rank_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    # 1. Average probabilities
    day1_probs = [r["win_probability"] for r in records if is_day1_loss(r["stop_mechanism"])]
    other_loss_probs = [r["win_probability"] for r in records if r["future_observed_outcome"] == "LOSS" and r["stop_mechanism"] == NOT_CLASSIFIED]
    win_probs = [r["win_probability"] for r in records if r["future_observed_outcome"] == "WIN"]

    avg_day1 = round(sum(day1_probs) / len(day1_probs), 4) if day1_probs else None
    avg_other_loss = round(sum(other_loss_probs) / len(other_loss_probs), 4) if other_loss_probs else None
    avg_win = round(sum(win_probs) / len(win_probs), 4) if win_probs else None

    # 2. Group by rank band
    by_band = defaultdict(list)
    for r in records:
        by_band[_rank_band(r["rank"])].append(r)

    band_results = []
    for band in ["1-5", "6-10", "11-15", "16-22", "23+"]:
        grp = by_band.get(band, [])
        if not grp:
            continue
        total = len(grp)
        day1 = sum(1 for r in grp if is_day1_loss(r["stop_mechanism"]))
        band_results.append({
            "rank_band": band,
            "total_picks": total,
            "day1_losses": day1,
            "day1_loss_rate": round(day1 / total, 4) if total else 0.0,
        })

    return {
        "avg_win_probability_day1_losses": avg_day1,
        "avg_win_probability_other_losses": avg_other_loss,
        "avg_win_probability_wins": avg_win,
        "by_rank_band": band_results,
    }


def compute_bucket_diagnostics(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_bucket = defaultdict(list)
    for r in records:
        by_bucket[r["bucket"]].append(r)

    results = []
    for bucket in sorted(by_bucket.keys()):
        grp = by_bucket[bucket]
        total = len(grp)
        day1 = sum(1 for r in grp if is_day1_loss(r["stop_mechanism"]))
        results.append({
            "bucket": bucket,
            "total_picks": total,
            "day1_losses": day1,
            "day1_loss_rate": round(day1 / total, 4) if total else 0.0,
        })
    return results


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 6) if vals else None


def compute_regime_comparison(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gap_downs = [r for r in records if r["stop_mechanism"] == GAP_DOWN_STOP]
    intradays = [r for r in records if r["stop_mechanism"] == INTRADAY_STOP]
    others = [r for r in records if r["stop_mechanism"] not in (GAP_DOWN_STOP, INTRADAY_STOP)]

    regime_keys = [
        "market_median_20d_return",
        "market_breakout_rate",
        "market_breakdown_rate",
        "market_breadth_delta",
        "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median",
        "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak",
    ]

    gate_table = []
    for key in regime_keys:
        gd_vals = [r["_regime"][key] for r in gap_downs if key in r["_regime"]]
        id_vals = [r["_regime"][key] for r in intradays if key in r["_regime"]]
        other_vals = [r["_regime"][key] for r in others if key in r["_regime"]]

        gate_table.append({
            "feature": key,
            "gap_down_mean": _mean(gd_vals),
            "intraday_mean": _mean(id_vals),
            "other_outcomes_mean": _mean(other_vals),
            "gap_down_count": len(gd_vals),
            "intraday_count": len(id_vals),
            "other_count": len(other_vals),
        })
    return gate_table


def get_high_confidence_failures(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for r in records:
        is_day1 = is_day1_loss(r["stop_mechanism"])
        if is_day1 and r["win_probability"] >= 0.50:
            failures.append({
                "symbol": r["symbol"],
                "rank": r["rank"],
                "win_probability": round(r["win_probability"], 4),
                "scored_sample_date": r["scored_sample_date"],
                "stop_mechanism": r["stop_mechanism"],
            })
    return sorted(failures, key=lambda x: x["win_probability"], reverse=True)


def get_repeat_symbol_offenders(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = defaultdict(int)
    details = defaultdict(list)
    for r in records:
        is_day1 = is_day1_loss(r["stop_mechanism"])
        if is_day1:
            counts[r["symbol"]] += 1
            details[r["symbol"]].append(f"{r['scored_sample_date']}(Rank {r['rank']})")

    results = []
    for sym in sorted(counts.keys(), key=lambda x: counts[x], reverse=True):
        if counts[sym] > 1:
            results.append({
                "symbol": sym,
                "day1_loss_count": counts[sym],
                "occurrences": details[sym],
            })
    return results


def get_diagnostic_notes(overall: dict[str, Any], date_stats: list[dict[str, Any]]) -> list[str]:
    notes = [
        "EARLY SHADOW SAMPLE — only 44 resolved records. No conclusion is statistically stable.",
    ]
    
    # Check for date clustering
    max_day1_date = None
    max_day1_cnt = -1
    for d in date_stats:
        if d["day1_losses"] > max_day1_cnt:
            max_day1_cnt = d["day1_losses"]
            max_day1_date = d["scored_sample_date"]

    if max_day1_cnt >= 10:
        notes.append(
            f"Significant temporal concentration observed: {max_day1_cnt} Day-1 losses occurred "
            f"on scored date {max_day1_date}. This indicates a candidate risk marker for market-wide shocks."
        )

    # Check gap down vs intraday dominance
    gd_pct = overall["gap_down_pct_of_day1"]
    id_pct = overall["intraday_pct_of_day1"]
    if gd_pct > 0.60:
        notes.append(
            f"Gap-down openings dominate Day-1 stop-outs ({gd_pct:.1%}). Intraday execution or stop placement "
            "is not the primary failure mode; trades are opening already breached due to overnight gaps."
        )
    elif id_pct > 0.60:
        notes.append(
            f"Intraday price declines dominate Day-1 stop-outs ({id_pct:.1%}). The strategy is suffering from "
            "immediate session reversal after entry, suggesting poor momentum persistence."
        )
    else:
        notes.append(
            "Day-1 stop-outs are mixed between opening gap-downs and intraday session declines."
        )

    return notes


# ---------------------------------------------------------------------------
# Report Assembly and Printing
# ---------------------------------------------------------------------------

def build_report(
    shadow_db: str = DEFAULT_DB_PATH,
    dhan_db: str | None = None,
) -> dict[str, Any]:
    if dhan_db is None:
        settings = get_settings()
        dhan_db = str(settings.database_path)

    records = load_resolved_records(shadow_db)
    records = classify_stop_mechanisms(records, dhan_db)
    generated_at = datetime.now(timezone.utc).isoformat()

    report: dict[str, Any] = {
        "generated_at": generated_at,
        "shadow_db": shadow_db,
        "dhan_db": dhan_db,
        "resolved_count": len(records),
        "early_sample_warning": "EARLY SHADOW SAMPLE — only 44 resolved records. Not statistically stable.",
    }

    if not records:
        report["status"] = "NO_RESOLVED_RECORDS"
        return report

    report["status"] = "OK"
    report["overall"] = compute_overall_stats(records)
    report["by_date"] = compute_date_concentration(records)
    report["rank_diagnostics"] = compute_rank_diagnostics(records)
    report["bucket_diagnostics"] = compute_bucket_diagnostics(records)
    report["regime_context"] = compute_regime_comparison(records)
    report["high_confidence_failures"] = get_high_confidence_failures(records)
    report["repeat_symbol_offenders"] = get_repeat_symbol_offenders(records)
    report["plain_english_diagnostic_notes"] = get_diagnostic_notes(
        report["overall"], report["by_date"]
    )

    return report


def format_txt_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    sep = "=" * 75

    lines += [
        sep,
        "ML V1.18 ENTRY FAILURE DIAGNOSIS REPORT",
        sep,
        f"Generated at    : {report['generated_at']}",
        f"Resolved records: {report['resolved_count']}",
        "",
        f"WARNING: {report['early_sample_warning']}",
        "",
    ]

    if report.get("status") == "NO_RESOLVED_RECORDS":
        lines.append("No resolved records found. Nothing to analyze.")
        lines.append(sep)
        return "\n".join(lines)

    # 1. Overall
    ov = report["overall"]
    lines += [
        "1. OVERALL DAY-1 LOSS SUMMARY",
        f"   Total resolved picks   : {ov['total_resolved']}",
        f"   Total losses           : {ov['total_losses']}",
        f"   Total Day-1 losses     : {ov['day1_loss_count']} ({ov['day1_loss_rate_of_losses']:.2%} of all losses, {ov['day1_loss_rate_of_resolved']:.2%} of resolved)",
        "",
        "2. STOP MECHANISM CLASSIFICATION",
        f"   GAP_DOWN_STOP          : {ov['gap_down_count']} ({ov['gap_down_pct_of_day1']:.2%} of Day-1 losses)",
        f"   INTRADAY_STOP          : {ov['intraday_count']} ({ov['intraday_pct_of_day1']:.2%} of Day-1 losses)",
        f"   UNCLASSIFIED_MISSING_ML_SAMPLE  : {ov['unclassified_missing_sample_count']}",
        f"   UNCLASSIFIED_MISSING_NEXT_CANDLE: {ov['unclassified_missing_candle_count']}",
        f"   UNCLASSIFIED_STOP_NOT_SEEN_IN_NEXT_CANDLE: {ov['unclassified_stop_not_seen_count']}",
        "",
    ]

    # 3. By Date
    lines += ["3. SCORED-DATE CONCENTRATION"]
    lines.append(f"   {'Date':<12} {'Picks':>5} {'Losses':>6} {'Day-1':>6} {'Day-1%':>8} {'Gaps':>5} {'Intradays':>9}")
    for d in report["by_date"]:
        lines.append(
            f"   {d['scored_sample_date']:<12} {d['total_picks']:>5} {d['total_losses']:>6} "
            f"{d['day1_losses']:>6} {d['day1_loss_rate']:>8.1%} {d['gap_downs']:>5} {d['intradays']:>9}"
        )
    lines.append("")

    # 4. Rank Diagnostics
    rd = report["rank_diagnostics"]
    lines += [
        "4. RANK AND PROBABILITY DIAGNOSTICS",
        f"   Avg probability of Day-1 losses  : {rd['avg_win_probability_day1_losses']}",
        f"   Avg probability of other losses  : {rd['avg_win_probability_other_losses']}",
        f"   Avg probability of wins          : {rd['avg_win_probability_wins']}",
        "   By Rank Band:",
        f"     {'Band':<10} {'Picks':>6} {'Day-1':>6} {'Day-1%':>8}"
    ]
    for b in rd["by_rank_band"]:
        lines.append(
            f"     {b['rank_band']:<10} {b['total_picks']:>6} {b['day1_losses']:>6} {b['day1_loss_rate']:>8.1%}"
        )
    lines.append("")

    # 5. Bucket Diagnostics
    lines += ["5. BUCKET DIAGNOSTICS"]
    lines.append(f"   {'Bucket':<15} {'Picks':>6} {'Day-1':>6} {'Day-1%':>8}")
    for b in report["bucket_diagnostics"]:
        lines.append(
            f"   {b['bucket']:<15} {b['total_picks']:>6} {b['day1_losses']:>6} {b['day1_loss_rate']:>8.1%}"
        )
    lines.append("")

    # 6. Regime context
    lines += ["6. WHAT-IF REGIME CONTEXT COMPARISON (candidate risk markers)"]
    lines.append(
        f"   {'Feature':<45} {'GapDown':>10} {'Intraday':>10} {'Other':>10}"
    )
    for g in report["regime_context"]:
        gd = f"{g['gap_down_mean']:.4f}" if g["gap_down_mean"] is not None else "N/A"
        id_ = f"{g['intraday_mean']:.4f}" if g["intraday_mean"] is not None else "N/A"
        oth = f"{g['other_outcomes_mean']:.4f}" if g["other_outcomes_mean"] is not None else "N/A"
        lines.append(f"   {g['feature']:<45} {gd:>10} {id_:>10} {oth:>10}")
    lines.append("")

    # 7. High-confidence
    lines += ["7. HIGH-CONFIDENCE DAY-1 FAILURES (win_probability >= 0.50)"]
    hc = report["high_confidence_failures"]
    if hc:
        for item in hc:
            lines.append(
                f"   Symbol: {item['symbol']:<10} Rank: {item['rank']:<2} "
                f"Prob: {item['win_probability']:.4f} Date: {item['scored_sample_date']} Type: {item['stop_mechanism']}"
            )
    else:
        lines.append("   None found.")
    lines.append("")

    # 8. Repeat offenders
    lines += ["8. REPEAT SYMBOL OFFENDERS"]
    rep = report["repeat_symbol_offenders"]
    if rep:
        for item in rep:
            lines.append(
                f"   Symbol: {item['symbol']:<10} Day-1 Losses: {item['day1_loss_count']} "
                f"Occurrences: {', '.join(item['occurrences'])}"
            )
    else:
        lines.append("   None found.")
    lines.append("")

    # 9. Plain english
    lines += ["9. PLAIN-ENGLISH DIAGNOSTIC OBSERVATIONS"]
    for note in report["plain_english_diagnostic_notes"]:
        lines.append(f"   * {note}")
    lines.append("")

    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_diagnosis(
    shadow_db: str = DEFAULT_DB_PATH,
    dhan_db: str | None = None,
    exports_dir: str = EXPORTS_DIR,
    report_json_path: str = REPORT_JSON_PATH,
    report_txt_path: str = REPORT_TXT_PATH,
) -> int:
    print("ML V1.18 ENTRY FAILURE DIAGNOSIS")
    print(f"Shadow DB   : {shadow_db}")
    print(f"Dhan DB     : {dhan_db or 'Default'}")
    print(f"Exports dir : {exports_dir}")
    print("")

    report = build_report(shadow_db=shadow_db, dhan_db=dhan_db)

    txt = format_txt_report(report)
    print(txt)

    os.makedirs(os.path.dirname(report_json_path), exist_ok=True)
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    with open(report_txt_path, "w", encoding="utf-8") as f:
        f.write(txt)

    print(f"JSON report : {report_json_path}")
    print(f"Text report : {report_txt_path}")

    return 0  # Always 0 — analysis, not a gate


if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description="Analyze Day-1 entry failure diagnosis")
    parser.add_argument("--shadow-db", type=str, default=DEFAULT_DB_PATH, help="Path to shadow DB")
    parser.add_argument("--dhan-db", type=str, default=None, help="Path to dhan auth DB")
    parser.add_argument("--exports-dir", type=str, default=EXPORTS_DIR, help="Path to exports directory")
    parser.add_argument("--report-json", type=str, default=REPORT_JSON_PATH, help="JSON output path")
    parser.add_argument("--report-txt", type=str, default=REPORT_TXT_PATH, help="TXT output path")
    args = parser.parse_args()

    sys.exit(run_diagnosis(
        shadow_db=args.shadow_db,
        dhan_db=args.dhan_db,
        exports_dir=args.exports_dir,
        report_json_path=args.report_json,
        report_txt_path=args.report_txt
    ))
