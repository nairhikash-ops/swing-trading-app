"""
analyze_shadow_intelligence.py

ML V1.17 Shadow Performance Intelligence.

Read-only analysis of resolved shadow picks.
Produces a structured intelligence report in JSON and TXT.

Usage:
    python -m app.scripts.analyze_shadow_intelligence

Exit code: always 0 (analysis, not a gate).
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.shadow_tracking import DEFAULT_DB_PATH

ML_TARGET_PERCENT = 7.0
ML_STOP_PERCENT = 3.0

EXPORTS_DIR = "/app/data/exports"
REPORT_JSON_PATH = os.path.join(EXPORTS_DIR, "shadow_intelligence_report.json")
REPORT_TXT_PATH = os.path.join(EXPORTS_DIR, "shadow_intelligence_report.txt")

SAMPLE_WARNING = (
    "EARLY SHADOW SAMPLE — only {} resolved records. "
    "No conclusion here is statistically stable."
)

REGIME_KEYS = [
    "market_median_20d_return",
    "market_breakout_rate",
    "market_breakdown_rate",
    "market_breadth_delta",
    "market_cross_sectional_volatility",
    "stock_20d_return_minus_market_median",
    "stock_is_stronger_than_market",
    "stock_breakout_while_market_weak",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

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


def load_observing_count(shadow_db: str) -> int:
    if not os.path.exists(shadow_db):
        return 0
    conn = sqlite3.connect(shadow_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM shadow_tracking WHERE tracking_status = 'OBSERVING'"
    ).fetchone()[0]
    conn.close()
    return count


# ---------------------------------------------------------------------------
# Expectancy (consistent denominators)
# ---------------------------------------------------------------------------

def compute_expectancy(
    win_count: int,
    loss_count: int,
    timeout_count: int,
) -> dict[str, Any]:
    """
    gross_expectancy_all_resolved:
        (WIN/resolved)*TARGET - (LOSS/resolved)*STOP + (TIMEOUT/resolved)*0

    gross_expectancy_excluding_timeout:
        (WIN/(WIN+LOSS))*TARGET - (LOSS/(WIN+LOSS))*STOP

    Both use consistent denominators. Never mix them.
    """
    resolved_count = win_count + loss_count + timeout_count
    win_loss_count = win_count + loss_count

    if resolved_count == 0:
        ge_all = None
    else:
        ge_all = round(
            (win_count / resolved_count) * ML_TARGET_PERCENT
            - (loss_count / resolved_count) * ML_STOP_PERCENT,
            4,
        )

    if win_loss_count == 0:
        ge_excl = None
    else:
        ge_excl = round(
            (win_count / win_loss_count) * ML_TARGET_PERCENT
            - (loss_count / win_loss_count) * ML_STOP_PERCENT,
            4,
        )

    return {
        "gross_expectancy_all_resolved": ge_all,
        "gross_expectancy_excluding_timeout": ge_excl,
        "denominator_all_resolved": resolved_count,
        "denominator_excluding_timeout": win_loss_count,
    }


# ---------------------------------------------------------------------------
# Section 1: Overall summary
# ---------------------------------------------------------------------------

def section_overall(records: list[dict]) -> dict[str, Any]:
    total = len(records)
    wins = [r for r in records if r["future_observed_outcome"] == "WIN"]
    losses = [r for r in records if r["future_observed_outcome"] == "LOSS"]
    timeouts = [r for r in records if r["future_observed_outcome"] == "TIMEOUT"]
    ambiguous = [r for r in records if r["future_observed_outcome"] == "AMBIGUOUS"]

    win_n, loss_n, timeout_n = len(wins), len(losses), len(timeouts)
    wl = win_n + loss_n

    avg_prob = sum(r["win_probability"] for r in records) / total if total else None
    avg_prob_win = sum(r["win_probability"] for r in wins) / win_n if win_n else None
    avg_prob_loss = sum(r["win_probability"] for r in losses) / loss_n if loss_n else None

    return {
        "total_resolved": total,
        "win_count": win_n,
        "loss_count": loss_n,
        "timeout_count": timeout_n,
        "ambiguous_count": len(ambiguous),
        "win_rate_all": round(win_n / total, 4) if total else None,
        "win_rate_excl_timeout": round(win_n / wl, 4) if wl else None,
        "avg_win_probability_all": round(avg_prob, 4) if avg_prob is not None else None,
        "avg_win_probability_wins": round(avg_prob_win, 4) if avg_prob_win is not None else None,
        "avg_win_probability_losses": round(avg_prob_loss, 4) if avg_prob_loss is not None else None,
        "expectancy": compute_expectancy(win_n, loss_n, timeout_n),
        "sample_warning": SAMPLE_WARNING.format(total),
    }


# ---------------------------------------------------------------------------
# Section 2: Probability calibration
# ---------------------------------------------------------------------------

def section_calibration(records: list[dict], n_bins: int = 5) -> dict[str, Any]:
    """
    Split into n_bins equal-width probability bands.
    For each band: record count, predicted mean prob, actual win rate.
    Compute Expected Calibration Error (ECE).
    """
    if not records:
        return {"bins": [], "ece": None, "note": "No records"}

    bin_width = 1.0 / n_bins
    bins: dict[int, list] = defaultdict(list)

    for r in records:
        b = min(int(r["win_probability"] / bin_width), n_bins - 1)
        bins[b].append(r)

    bin_results = []
    total = len(records)
    ece = 0.0

    for i in range(n_bins):
        lo = round(i * bin_width, 2)
        hi = round((i + 1) * bin_width, 2)
        grp = bins.get(i, [])
        count = len(grp)
        if count == 0:
            bin_results.append({
                "prob_range": f"{lo:.2f}–{hi:.2f}",
                "count": 0,
                "predicted_mean_prob": None,
                "actual_win_rate": None,
            })
            continue
        pred_mean = sum(r["win_probability"] for r in grp) / count
        actual_wr = sum(1 for r in grp if r["future_observed_outcome"] == "WIN") / count
        ece += (count / total) * abs(actual_wr - pred_mean)
        bin_results.append({
            "prob_range": f"{lo:.2f}–{hi:.2f}",
            "count": count,
            "predicted_mean_prob": round(pred_mean, 4),
            "actual_win_rate": round(actual_wr, 4),
            "calibration_error": round(abs(actual_wr - pred_mean), 4),
        })

    return {
        "bins": bin_results,
        "ece": round(ece, 4),
        "note": "ECE = expected calibration error (lower is better, 0 is perfect)",
    }


# ---------------------------------------------------------------------------
# Section 3: Speed of failure (days_to_outcome)
# ---------------------------------------------------------------------------

def section_speed_of_failure(records: list[dict]) -> dict[str, Any]:
    wins = [r for r in records if r["future_observed_outcome"] == "WIN"]
    losses = [r for r in records if r["future_observed_outcome"] == "LOSS"]
    timeouts = [r for r in records if r["future_observed_outcome"] == "TIMEOUT"]

    def stats(group: list[dict]) -> dict | None:
        days = [r["days_to_outcome"] for r in group if r.get("days_to_outcome") is not None]
        if not days:
            return None
        hist: dict[str, int] = defaultdict(int)
        for d in days:
            hist[str(d)] += 1
        return {
            "count": len(days),
            "min": min(days),
            "max": max(days),
            "avg": round(sum(days) / len(days), 2),
            "day_histogram": dict(sorted(hist.items(), key=lambda x: int(x[0]))),
        }

    day1_losses = sum(
        1 for r in losses if r.get("days_to_outcome") == 1
    )
    loss_n = len(losses)

    return {
        "wins": stats(wins),
        "losses": stats(losses),
        "timeouts": stats(timeouts),
        "day1_loss_count": day1_losses,
        "day1_loss_rate": round(day1_losses / loss_n, 4) if loss_n else None,
        "note": (
            "High day1_loss_rate means the entry signal is the failure point, "
            "not the hold period."
        ),
    }


# ---------------------------------------------------------------------------
# Section 4: Rank effectiveness
# ---------------------------------------------------------------------------

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


def section_rank_effectiveness(records: list[dict]) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for r in records:
        groups[_rank_band(r["rank"])].append(r)

    band_order = ["1-5", "6-10", "11-15", "16-22", "23+"]
    results = []

    for band in band_order:
        grp = groups.get(band, [])
        if not grp:
            continue
        win_n = sum(1 for r in grp if r["future_observed_outcome"] == "WIN")
        loss_n = sum(1 for r in grp if r["future_observed_outcome"] == "LOSS")
        timeout_n = sum(1 for r in grp if r["future_observed_outcome"] == "TIMEOUT")
        wl = win_n + loss_n
        wr_excl = round(win_n / wl, 4) if wl else None
        results.append({
            "rank_band": band,
            "count": len(grp),
            "win_count": win_n,
            "loss_count": loss_n,
            "timeout_count": timeout_n,
            "win_rate_excl_timeout": wr_excl,
            "expectancy": compute_expectancy(win_n, loss_n, timeout_n),
        })

    return {
        "by_rank_band": results,
        "note": (
            "With only 2 scored dates (22 records each), rank bands have very small samples. "
            "Do not draw hard conclusions."
        ),
    }


# ---------------------------------------------------------------------------
# Section 5: Per scored-date breakdown
# ---------------------------------------------------------------------------

def section_by_date(records: list[dict]) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for r in records:
        groups[r["scored_sample_date"]].append(r)

    results = []
    for date in sorted(groups.keys()):
        grp = groups[date]
        win_n = sum(1 for r in grp if r["future_observed_outcome"] == "WIN")
        loss_n = sum(1 for r in grp if r["future_observed_outcome"] == "LOSS")
        timeout_n = sum(1 for r in grp if r["future_observed_outcome"] == "TIMEOUT")
        wl = win_n + loss_n
        results.append({
            "scored_sample_date": date,
            "count": len(grp),
            "win_count": win_n,
            "loss_count": loss_n,
            "timeout_count": timeout_n,
            "win_rate_excl_timeout": round(win_n / wl, 4) if wl else None,
            "expectancy": compute_expectancy(win_n, loss_n, timeout_n),
        })

    return {"by_date": results}


# ---------------------------------------------------------------------------
# Section 6: Regime gate analysis
# ---------------------------------------------------------------------------

def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 6) if vals else None


def section_regime_gates(records: list[dict]) -> dict[str, Any]:
    wins = [r for r in records if r["future_observed_outcome"] == "WIN"]
    losses = [r for r in records if r["future_observed_outcome"] == "LOSS"]

    gate_table = []
    for key in REGIME_KEYS:
        win_vals = [r["_regime"][key] for r in wins if key in r["_regime"]]
        loss_vals = [r["_regime"][key] for r in losses if key in r["_regime"]]
        win_mean = _mean(win_vals)
        loss_mean = _mean(loss_vals)
        delta = None
        if win_mean is not None and loss_mean is not None:
            delta = round(win_mean - loss_mean, 6)
        gate_table.append({
            "feature": key,
            "win_mean": win_mean,
            "loss_mean": loss_mean,
            "delta_win_minus_loss": delta,
            "win_sample_n": len(win_vals),
            "loss_sample_n": len(loss_vals),
        })

    # Sort by abs(delta) descending
    gate_table.sort(
        key=lambda x: abs(x["delta_win_minus_loss"]) if x["delta_win_minus_loss"] is not None else 0,
        reverse=True,
    )

    return {
        "gate_table": gate_table,
        "note": (
            "Large |delta| means the feature differs meaningfully between wins and losses. "
            "This is informational only — not a trading signal with this sample size."
        ),
    }


# ---------------------------------------------------------------------------
# Report assembly and formatting
# ---------------------------------------------------------------------------

def build_report(
    shadow_db: str = DEFAULT_DB_PATH,
    exports_dir: str = EXPORTS_DIR,
) -> dict[str, Any]:
    records = load_resolved_records(shadow_db)
    observing_count = load_observing_count(shadow_db)
    generated_at = datetime.now(timezone.utc).isoformat()

    report: dict[str, Any] = {
        "generated_at": generated_at,
        "shadow_db": shadow_db,
        "observing_count": observing_count,
        "resolved_count": len(records),
        "sample_warning": SAMPLE_WARNING.format(len(records)),
    }

    if not records:
        report["status"] = "NO_RESOLVED_RECORDS"
        return report

    report["status"] = "OK"
    report["overall"] = section_overall(records)
    report["calibration"] = section_calibration(records)
    report["speed_of_failure"] = section_speed_of_failure(records)
    report["rank_effectiveness"] = section_rank_effectiveness(records)
    report["by_date"] = section_by_date(records)
    report["regime_gates"] = section_regime_gates(records)

    return report


def format_txt_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    sep = "=" * 70

    lines += [
        sep,
        "ML V1.17 SHADOW PERFORMANCE INTELLIGENCE REPORT",
        sep,
        f"Generated at    : {report['generated_at']}",
        f"Resolved records: {report['resolved_count']}",
        f"Observing now   : {report['observing_count']}",
        "",
        f"WARNING: {report['sample_warning']}",
        "",
    ]

    if report.get("status") == "NO_RESOLVED_RECORDS":
        lines.append("No resolved records found. Nothing to analyze.")
        lines.append(sep)
        return "\n".join(lines)

    # Overall
    ov = report["overall"]
    ex = ov["expectancy"]
    lines += [
        "1. OVERALL SUMMARY",
        f"   Wins          : {ov['win_count']}",
        f"   Losses        : {ov['loss_count']}",
        f"   Timeouts      : {ov['timeout_count']}",
        f"   Win rate (all): {ov['win_rate_all']:.2%}" if ov["win_rate_all"] is not None else "   Win rate: N/A",
        f"   Win rate (excl timeout): {ov['win_rate_excl_timeout']:.2%}" if ov["win_rate_excl_timeout"] is not None else "   Win rate (excl timeout): N/A",
        f"   Avg prob all  : {ov['avg_win_probability_all']}",
        f"   Avg prob WINS : {ov['avg_win_probability_wins']}",
        f"   Avg prob LOSS : {ov['avg_win_probability_losses']}",
        f"   Expectancy (all resolved, denom={ex['denominator_all_resolved']}): {ex['gross_expectancy_all_resolved']}%",
        f"   Expectancy (excl timeout, denom={ex['denominator_excluding_timeout']}): {ex['gross_expectancy_excluding_timeout']}%",
        "",
    ]

    # Calibration
    cal = report["calibration"]
    lines += ["2. PROBABILITY CALIBRATION", f"   ECE = {cal['ece']}  ({cal['note']})"]
    lines.append(f"   {'Range':<12} {'Count':>6} {'Pred%':>8} {'Actual%':>8} {'Error':>8}")
    for b in cal["bins"]:
        if b["count"] == 0:
            lines.append(f"   {b['prob_range']:<12} {'0':>6} {'—':>8} {'—':>8} {'—':>8}")
        else:
            lines.append(
                f"   {b['prob_range']:<12} {b['count']:>6} "
                f"{b['predicted_mean_prob']:>8.4f} {b['actual_win_rate']:>8.4f} "
                f"{b['calibration_error']:>8.4f}"
            )
    lines.append("")

    # Speed of failure
    sf = report["speed_of_failure"]
    lines.append("3. SPEED OF FAILURE")
    for outcome_key in ("wins", "losses", "timeouts"):
        s = sf.get(outcome_key)
        if s:
            lines.append(f"   {outcome_key.upper()}: count={s['count']} min={s['min']} max={s['max']} avg={s['avg']}")
            lines.append(f"     day histogram: {s['day_histogram']}")
    lines.append(f"   Day-1 losses: {sf['day1_loss_count']} ({sf['day1_loss_rate']:.1%} of all losses)")
    lines.append(f"   Note: {sf['note']}")
    lines.append("")

    # Rank effectiveness
    re_ = report["rank_effectiveness"]
    lines.append("4. RANK EFFECTIVENESS")
    lines.append(f"   {'Band':<8} {'N':>4} {'W':>4} {'L':>4} {'WR(excl)':>9} {'E(all)':>8}")
    for b in re_["by_rank_band"]:
        wr = f"{b['win_rate_excl_timeout']:.1%}" if b["win_rate_excl_timeout"] is not None else "N/A"
        ge_all = b["expectancy"]["gross_expectancy_all_resolved"]
        ge_str = f"{ge_all:.2f}%" if ge_all is not None else "N/A"
        lines.append(
            f"   {b['rank_band']:<8} {b['count']:>4} {b['win_count']:>4} "
            f"{b['loss_count']:>4} {wr:>9} {ge_str:>8}"
        )
    lines.append(f"   Note: {re_['note']}")
    lines.append("")

    # By date
    bd = report["by_date"]
    lines.append("5. BY SCORED SAMPLE DATE")
    for d in bd["by_date"]:
        wr = f"{d['win_rate_excl_timeout']:.1%}" if d["win_rate_excl_timeout"] is not None else "N/A"
        ge_all = d["expectancy"]["gross_expectancy_all_resolved"]
        lines.append(
            f"   {d['scored_sample_date']}  N={d['count']}  "
            f"W={d['win_count']} L={d['loss_count']} T={d['timeout_count']}  "
            f"WR={wr}  E={ge_all}%"
        )
    lines.append("")

    # Regime gates
    rg = report["regime_gates"]
    lines.append("6. REGIME GATE ANALYSIS (WIN vs LOSS means, sorted by |delta|)")
    lines.append(f"   {'Feature':<45} {'WIN_mean':>10} {'LOSS_mean':>10} {'delta':>10}")
    for g in rg["gate_table"]:
        wm = f"{g['win_mean']:.4f}" if g["win_mean"] is not None else "N/A"
        lm = f"{g['loss_mean']:.4f}" if g["loss_mean"] is not None else "N/A"
        dm = f"{g['delta_win_minus_loss']:+.4f}" if g["delta_win_minus_loss"] is not None else "N/A"
        lines.append(f"   {g['feature']:<45} {wm:>10} {lm:>10} {dm:>10}")
    lines.append(f"   Note: {rg['note']}")
    lines.append("")

    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_analysis(
    shadow_db: str = DEFAULT_DB_PATH,
    exports_dir: str = EXPORTS_DIR,
    report_json_path: str = REPORT_JSON_PATH,
    report_txt_path: str = REPORT_TXT_PATH,
) -> int:
    print("ML V1.17 SHADOW PERFORMANCE INTELLIGENCE")
    print(f"Shadow DB   : {shadow_db}")
    print(f"Exports dir : {exports_dir}")
    print("")

    report = build_report(shadow_db=shadow_db, exports_dir=exports_dir)

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
    sys.exit(run_analysis())
