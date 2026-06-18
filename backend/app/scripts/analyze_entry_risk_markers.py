"""
analyze_entry_risk_markers.py

ML V1.19 Shadow Entry Risk Marker What-If Analysis.
Read-only script to test candidate risk markers against resolved shadow tracking records.
Uses entry_failure_diagnosis.json as the primary source for stop mechanism classification,
and falls back to dhan_auth.sqlite3 only if needed.

Usage:
    python -m app.scripts.analyze_entry_risk_markers
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
DIAGNOSIS_JSON_PATH = os.path.join(EXPORTS_DIR, "entry_failure_diagnosis.json")
REPORT_JSON_PATH = os.path.join(EXPORTS_DIR, "entry_risk_marker_report.json")
REPORT_TXT_PATH = os.path.join(EXPORTS_DIR, "entry_risk_marker_report.txt")

# Stop Mechanisms constants
GAP_DOWN_STOP = "GAP_DOWN_STOP"
INTRADAY_STOP = "INTRADAY_STOP"
UNCLASSIFIED_STOP_NOT_SEEN_IN_NEXT_CANDLE = "UNCLASSIFIED_STOP_NOT_SEEN_IN_NEXT_CANDLE"
UNCLASSIFIED_MISSING_ML_SAMPLE = "UNCLASSIFIED_MISSING_ML_SAMPLE"
UNCLASSIFIED_MISSING_NEXT_CANDLE = "UNCLASSIFIED_MISSING_NEXT_CANDLE"
NOT_CLASSIFIED = "NOT_CLASSIFIED"

# Payoff targets
ML_TARGET_PERCENT = 7.0
ML_STOP_PERCENT = 3.0


def is_day1_loss(outcome: str, days: int | None) -> bool:
    return outcome == "LOSS" and days == 1


def compute_expectancy(win_count: int, loss_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    win_rate = win_count / total_count
    loss_rate = loss_count / total_count
    return round((win_rate * ML_TARGET_PERCENT) - (loss_rate * ML_STOP_PERCENT), 4)


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


def load_diagnosis_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def classify_stop_mechanisms(
    records: list[dict[str, Any]],
    diagnosis_json: dict[str, Any],
    dhan_db: str,
) -> list[dict[str, Any]]:
    """
    For each resolved record, identify if it's a Day-1 loss and classify the stop mechanism.
    First checks diagnosis_json, and falls back to Dhan DB only if not found.
    """
    # Build a lookup from diagnosis_json if possible
    json_lookup = {}
    if diagnosis_json and "high_confidence_failures" in diagnosis_json:
        for f in diagnosis_json["high_confidence_failures"]:
            key = (f["symbol"].upper(), f["scored_sample_date"])
            json_lookup[key] = f.get("stop_mechanism")

    # If the diagnosis_json has a direct 'records' list (future-proofing)
    if diagnosis_json and "records" in diagnosis_json:
        for r in diagnosis_json["records"]:
            key = (r["symbol"].upper(), r["scored_sample_date"])
            json_lookup[key] = r.get("stop_mechanism")

    dhan_conn = None
    if os.path.exists(dhan_db):
        dhan_conn = sqlite3.connect(dhan_db)
        dhan_conn.row_factory = sqlite3.Row

    for r in records:
        symbol = r["symbol"]
        scored_date = r["scored_sample_date"]
        outcome = r["future_observed_outcome"]
        days = r.get("days_to_outcome")

        if not is_day1_loss(outcome, days):
            r["stop_mechanism"] = NOT_CLASSIFIED
            continue

        lookup_key = (symbol.upper(), scored_date)
        if lookup_key in json_lookup:
            r["stop_mechanism"] = json_lookup[lookup_key]
            continue

        # Fallback to Dhan DB to compute classification
        if dhan_conn is None:
            r["stop_mechanism"] = UNCLASSIFIED_MISSING_ML_SAMPLE
            continue

        # 1. Fetch matching ml_samples row
        sample_row = dhan_conn.execute(
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
        next_candle = dhan_conn.execute(
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

        if nc_open <= stop_price:
            r["stop_mechanism"] = GAP_DOWN_STOP
        elif nc_low <= stop_price:
            r["stop_mechanism"] = INTRADAY_STOP
        else:
            r["stop_mechanism"] = UNCLASSIFIED_STOP_NOT_SEEN_IN_NEXT_CANDLE

    if dhan_conn:
        dhan_conn.close()

    return records


def count_picks_by_date(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = defaultdict(int)
    for r in records:
        counts[r["scored_sample_date"]] += 1
    return dict(counts)


def run_marker_evaluation(
    records: list[dict[str, Any]],
    picks_by_date: dict[str, int]
) -> list[dict[str, Any]]:
    """
    Simulates the impact of the 10 candidate risk markers.
    """
    # Baseline stats
    baseline_win = sum(1 for r in records if r["future_observed_outcome"] == "WIN")
    baseline_loss = sum(1 for r in records if r["future_observed_outcome"] == "LOSS")
    baseline_timeout = sum(1 for r in records if r["future_observed_outcome"] == "TIMEOUT")
    baseline_total = len(records)
    baseline_exp = compute_expectancy(baseline_win, baseline_loss, baseline_total)

    # Segments
    prim_baseline_total = sum(1 for r in records if r["bucket"] == "PRIMARY_TOP_1")
    prim_baseline_win = sum(1 for r in records if r["bucket"] == "PRIMARY_TOP_1" and r["future_observed_outcome"] == "WIN")
    prim_baseline_loss = sum(1 for r in records if r["bucket"] == "PRIMARY_TOP_1" and r["future_observed_outcome"] == "LOSS")
    prim_baseline_exp = compute_expectancy(prim_baseline_win, prim_baseline_loss, prim_baseline_total)

    watch_baseline_total = sum(1 for r in records if r["bucket"] == "WATCH_TOP_5")
    watch_baseline_win = sum(1 for r in records if r["bucket"] == "WATCH_TOP_5" and r["future_observed_outcome"] == "WIN")
    watch_baseline_loss = sum(1 for r in records if r["bucket"] == "WATCH_TOP_5" and r["future_observed_outcome"] == "LOSS")
    watch_baseline_exp = compute_expectancy(watch_baseline_win, watch_baseline_loss, watch_baseline_total)

    # Definitions of markers
    markers_def = [
        {
            "id": "market_breadth_delta_05",
            "name": "market_breadth_delta < -0.05",
            "check": lambda r: r["_regime"].get("market_breadth_delta", 0.0) < -0.05
        },
        {
            "id": "market_breadth_delta_10",
            "name": "market_breadth_delta < -0.10",
            "check": lambda r: r["_regime"].get("market_breadth_delta", 0.0) < -0.10
        },
        {
            "id": "market_breakdown_rate_08",
            "name": "market_breakdown_rate > 0.08",
            "check": lambda r: r["_regime"].get("market_breakdown_rate", 0.0) > 0.08
        },
        {
            "id": "market_breakdown_rate_10",
            "name": "market_breakdown_rate > 0.10",
            "check": lambda r: r["_regime"].get("market_breakdown_rate", 0.0) > 0.10
        },
        {
            "id": "market_median_20d_return_01",
            "name": "market_median_20d_return < -0.01",
            "check": lambda r: r["_regime"].get("market_median_20d_return", 0.0) < -0.01
        },
        {
            "id": "market_median_20d_return_02",
            "name": "market_median_20d_return < -0.02",
            "check": lambda r: r["_regime"].get("market_median_20d_return", 0.0) < -0.02
        },
        {
            "id": "stock_is_stronger_than_market_false",
            "name": "stock_is_stronger_than_market == 0",
            "check": lambda r: r["_regime"].get("stock_is_stronger_than_market", 0.0) == 0
        },
        {
            "id": "stock_20d_return_minus_market_median_weak",
            "name": "stock_20d_return_minus_market_median < 0",
            "check": lambda r: r["_regime"].get("stock_20d_return_minus_market_median", 0.0) < 0
        },
        {
            "id": "high_prob_hostile_market",
            "name": "win_probability >= 0.50 AND market_breadth_delta < -0.05",
            "check": lambda r: r["win_probability"] >= 0.50 and r["_regime"].get("market_breadth_delta", 0.0) < -0.05
        },
        {
            "id": "shock_concentration",
            "name": "scored date has more than 10 picks AND negative market_breadth_delta",
            "check": lambda r: picks_by_date.get(r["scored_sample_date"], 0) > 10 and r["_regime"].get("market_breadth_delta", 0.0) < 0.0
        }
    ]

    results = []
    for m in markers_def:
        excluded = [r for r in records if m["check"](r)]
        remaining = [r for r in records if not m["check"](r)]

        # Counts
        total_excl = len(excluded)
        wins_removed = sum(1 for r in excluded if r["future_observed_outcome"] == "WIN")
        losses_removed = sum(1 for r in excluded if r["future_observed_outcome"] == "LOSS")
        timeouts_removed = sum(1 for r in excluded if r["future_observed_outcome"] == "TIMEOUT")

        day1_losses_avoided = sum(1 for r in excluded if is_day1_loss(r["future_observed_outcome"], r.get("days_to_outcome")))
        intraday_stops_avoided = sum(1 for r in excluded if r.get("stop_mechanism") == INTRADAY_STOP)
        gap_down_stops_avoided = sum(1 for r in excluded if r.get("stop_mechanism") == GAP_DOWN_STOP)

        rem_win = sum(1 for r in remaining if r["future_observed_outcome"] == "WIN")
        rem_loss = sum(1 for r in remaining if r["future_observed_outcome"] == "LOSS")
        rem_total = len(remaining)
        post_exp = compute_expectancy(rem_win, rem_loss, rem_total)

        # PRIMARY_TOP_1 segment
        prim_excluded = [r for r in excluded if r["bucket"] == "PRIMARY_TOP_1"]
        prim_wins_removed = sum(1 for r in prim_excluded if r["future_observed_outcome"] == "WIN")
        prim_losses_removed = sum(1 for r in prim_excluded if r["future_observed_outcome"] == "LOSS")
        prim_rem_win = prim_baseline_win - prim_wins_removed
        prim_rem_loss = prim_baseline_loss - prim_losses_removed
        prim_rem_total = prim_baseline_total - len(prim_excluded)
        prim_post_exp = compute_expectancy(prim_rem_win, prim_rem_loss, prim_rem_total)

        # WATCH_TOP_5 segment
        watch_excluded = [r for r in excluded if r["bucket"] == "WATCH_TOP_5"]
        watch_wins_removed = sum(1 for r in watch_excluded if r["future_observed_outcome"] == "WIN")
        watch_losses_removed = sum(1 for r in watch_excluded if r["future_observed_outcome"] == "LOSS")
        watch_rem_win = watch_baseline_win - watch_wins_removed
        watch_rem_loss = watch_baseline_loss - watch_losses_removed
        watch_rem_total = watch_baseline_total - len(watch_excluded)
        watch_post_exp = compute_expectancy(watch_rem_win, watch_rem_loss, watch_rem_total)

        # Date-stability
        dates_excl = defaultdict(list)
        for r in excluded:
            dates_excl[r["scored_sample_date"]].append(r)

        date_impacts = {}
        for dt in ["2026-05-15", "2026-05-18"]:
            dt_excl = dates_excl.get(dt, [])
            dt_wins = sum(1 for r in dt_excl if r["future_observed_outcome"] == "WIN")
            dt_losses = sum(1 for r in dt_excl if r["future_observed_outcome"] == "LOSS")
            dt_day1 = sum(1 for r in dt_excl if is_day1_loss(r["future_observed_outcome"], r.get("days_to_outcome")))
            date_impacts[dt] = {
                "excluded": len(dt_excl),
                "wins_removed": dt_wins,
                "losses_removed": dt_losses,
                "day1_losses_avoided": dt_day1
            }

        # Check if it only explains one toxic date
        excl_15 = date_impacts["2026-05-15"]["day1_losses_avoided"]
        excl_18 = date_impacts["2026-05-18"]["day1_losses_avoided"]
        only_explains_one_date = (excl_15 > 0 and excl_18 == 0) or (excl_18 > 0 and excl_15 == 0)

        # High-confidence failures impact
        hc_excl = [r for r in excluded if r["win_probability"] >= 0.50]
        hc_losses_avoided = sum(1 for r in hc_excl if r["future_observed_outcome"] == "LOSS")

        # Flag dangerous (removing > 50% of wins)
        is_dangerous = wins_removed > (baseline_win * 0.50)

        results.append({
            "id": m["id"],
            "name": m["name"],
            "records_excluded": total_excl,
            "day1_losses_avoided": day1_losses_avoided,
            "intraday_stops_avoided": intraday_stops_avoided,
            "gap_down_stops_avoided": gap_down_stops_avoided,
            "wins_removed": wins_removed,
            "losses_removed": losses_removed,
            "timeouts_removed": timeouts_removed,
            "expectancy_before": baseline_exp,
            "expectancy_after": post_exp,
            "is_dangerous": is_dangerous,
            "primary_top_1_impact": {
                "total_excluded": len(prim_excluded),
                "wins_removed": prim_wins_removed,
                "losses_removed": prim_losses_removed,
                "expectancy_before": prim_baseline_exp,
                "expectancy_after": prim_post_exp
            },
            "watch_top_5_impact": {
                "total_excluded": len(watch_excluded),
                "wins_removed": watch_wins_removed,
                "losses_removed": watch_losses_removed,
                "expectancy_before": watch_baseline_exp,
                "expectancy_after": watch_post_exp
            },
            "date_stability": date_impacts,
            "only_explains_one_date": only_explains_one_date,
            "high_confidence_failure_impact": {
                "hc_picks_excluded": len(hc_excl),
                "hc_losses_avoided": hc_losses_avoided
            }
        })

    return results


def get_plain_english_observations(results: list[dict[str, Any]], baseline_count: int) -> list[str]:
    observations = [
        "Small sample size warning: Only 44 resolved records were analyzed. Any findings should be treated as shadow-only hypotheses, not validated trading rules."
    ]

    # Find the best performing marker that is not dangerous
    valid_markers = [m for m in results if not m["is_dangerous"]]
    best_marker = None
    best_improvement = -999.0

    for m in valid_markers:
        imp = m["expectancy_after"] - m["expectancy_before"]
        if imp > best_improvement:
            best_improvement = imp
            best_marker = m

    if best_marker and best_improvement > 0.0:
        observations.append(
            f"Candidate risk marker '{best_marker['name']}' showed the best diagnostic potential, "
            f"improving gross expectancy from {best_marker['expectancy_before']}% to {best_marker['expectancy_after']}% "
            f"by avoiding {best_marker['day1_losses_avoided']} Day-1 losses (including {best_marker['intraday_stops_avoided']} intraday stop-outs) "
            f"while removing only {best_marker['wins_removed']} wins."
        )

    # Identify toxic date concentration
    date_concentrated = [m for m in results if m["only_explains_one_date"] and m["day1_losses_avoided"] > 0]
    if date_concentrated:
        marker_names = ", ".join([f"'{m['name']}'" for m in date_concentrated[:3]])
        observations.append(
            f"Markers like {marker_names} only explained the toxic shock of a single scored date "
            f"and did not demonstrate stability across both 2026-05-15 and 2026-05-18."
        )

    # Dangerous markers warning
    dangerous = [m for m in results if m["is_dangerous"]]
    if dangerous:
        names = ", ".join([f"'{m['name']}'" for m in dangerous[:3]])
        observations.append(
            f"Over-filtering hazard: Markers {names} removed too many wins (> 50% of baseline wins) "
            f"and are flagged as dangerous hypotheses."
        )

    return observations


def format_txt_report(report: dict[str, Any]) -> str:
    lines = []
    sep = "=" * 80
    subsep = "-" * 80

    lines += [
        sep,
        "ML V1.19 SHADOW ENTRY RISK MARKER WHAT-IF ANALYSIS REPORT",
        sep,
        f"Generated at    : {report['generated_at']}",
        f"Shadow DB path  : {report['shadow_db']}",
        f"Resolved count  : {report['resolved_count']}",
        "",
        f"WARNING: {report['overfit_warning']}",
        "",
        "1. BASELINE SHADOW PERFORMANCE SUMMARY",
        f"   Total resolved picks   : {report['baseline']['total_resolved']}",
        f"   Wins / Losses / TOs    : {report['baseline']['wins']} / {report['baseline']['losses']} / {report['baseline']['timeouts']}",
        f"   Win rate (overall)     : {report['baseline']['win_rate']:.2%}",
        f"   Gross Expectancy       : {report['baseline']['gross_expectancy']:.4f}%",
        "",
        f"   PRIMARY_TOP_1 (Rank 1-5):",
        f"     Total picks          : {report['baseline']['primary_top_1']['total']}",
        f"     Win / Loss / TO      : {report['baseline']['primary_top_1']['wins']} / {report['baseline']['primary_top_1']['losses']} / {report['baseline']['primary_top_1']['timeouts']}",
        f"     Expectancy           : {report['baseline']['primary_top_1']['expectancy']:.4f}%",
        "",
        f"   WATCH_TOP_5 (Rank 6-22):",
        f"     Total picks          : {report['baseline']['watch_top_5']['total']}",
        f"     Win / Loss / TO      : {report['baseline']['watch_top_5']['wins']} / {report['baseline']['watch_top_5']['losses']} / {report['baseline']['watch_top_5']['timeouts']}",
        f"     Expectancy           : {report['baseline']['watch_top_5']['expectancy']:.4f}%",
        "",
        "2. WHAT-IF EXCLUSION RESULTS PER CANDIDATE MARKER",
    ]

    for m in report["markers"]:
        lines += [
            subsep,
            f"Marker: {m['name']}",
            f"   Excluded records       : {m['records_excluded']}",
            f"   Day-1 losses avoided   : {m['day1_losses_avoided']} (Intraday: {m['intraday_stops_avoided']}, GapDown: {m['gap_down_stops_avoided']})",
            f"   Wins / Losses / TOs rem: {m['wins_removed']} / {m['losses_removed']} / {m['timeouts_removed']}",
            f"   Gross Expectancy       : {m['expectancy_before']:.4f}% -> {m['expectancy_after']:.4f}%",
            f"   Status                 : {'DANGEROUS (Kills >50% wins)' if m['is_dangerous'] else 'OK'}",
            "",
            "   Segment Impact:",
            f"     PRIMARY_TOP_1        : Excl: {m['primary_top_1_impact']['total_excluded']} | Wins rem: {m['primary_top_1_impact']['wins_removed']} | Losses rem: {m['primary_top_1_impact']['losses_removed']} | Exp: {m['primary_top_1_impact']['expectancy_before']:.4f}% -> {m['primary_top_1_impact']['expectancy_after']:.4f}%",
            f"     WATCH_TOP_5          : Excl: {m['watch_top_5_impact']['total_excluded']} | Wins rem: {m['watch_top_5_impact']['wins_removed']} | Losses rem: {m['watch_top_5_impact']['losses_removed']} | Exp: {m['watch_top_5_impact']['expectancy_before']:.4f}% -> {m['watch_top_5_impact']['expectancy_after']:.4f}%",
            "",
            "   Date Stability:",
            f"     2026-05-15           : Excl: {m['date_stability']['2026-05-15']['excluded']} | Wins rem: {m['date_stability']['2026-05-15']['wins_removed']} | Day-1 avoided: {m['date_stability']['2026-05-15']['day1_losses_avoided']}",
            f"     2026-05-18           : Excl: {m['date_stability']['2026-05-18']['excluded']} | Wins rem: {m['date_stability']['2026-05-18']['wins_removed']} | Day-1 avoided: {m['date_stability']['2026-05-18']['day1_losses_avoided']}",
            f"     Stability Check      : {'Toxic-date concentrated' if m['only_explains_one_date'] else 'Stable across dates'}",
            "",
            "   High-Confidence Pick Impact (win_prob >= 0.50):",
            f"     Picks excluded       : {m['high_confidence_failure_impact']['hc_picks_excluded']}",
            f"     Losses avoided       : {m['high_confidence_failure_impact']['hc_losses_avoided']}",
        ]

    lines += [
        subsep,
        "3. PLAIN-ENGLISH DIAGNOSTIC OBSERVATIONS",
    ]
    for obs in report["plain_english_diagnostic_notes"]:
        lines.append(f"   * {obs}")

    lines.append(sep)
    return "\n".join(lines)


def run_analysis(
    shadow_db: str = DEFAULT_DB_PATH,
    dhan_db: str | None = None,
    diagnosis_json_path: str = DIAGNOSIS_JSON_PATH,
    report_json_path: str = REPORT_JSON_PATH,
    report_txt_path: str = REPORT_TXT_PATH,
) -> int:
    print("ML V1.19 SHADOW ENTRY RISK MARKER WHAT-IF ANALYSIS")
    print(f"Shadow DB      : {shadow_db}")
    print(f"Dhan DB        : {dhan_db or 'Default'}")
    print(f"Diagnosis JSON : {diagnosis_json_path}")
    print("")

    if dhan_db is None:
        settings = get_settings()
        dhan_db = str(settings.database_path)

    records = load_resolved_records(shadow_db)
    if not records:
        print("No resolved shadow tracking records found. Exiting.")
        return 0

    diagnosis_json = load_diagnosis_json(diagnosis_json_path)

    # Classify stop mechanisms using JSON as primary and Dhan DB as fallback
    records = classify_stop_mechanisms(records, diagnosis_json, dhan_db)

    picks_by_date = count_picks_by_date(records)
    results = run_marker_evaluation(records, picks_by_date)

    baseline_win = sum(1 for r in records if r["future_observed_outcome"] == "WIN")
    baseline_loss = sum(1 for r in records if r["future_observed_outcome"] == "LOSS")
    baseline_timeout = sum(1 for r in records if r["future_observed_outcome"] == "TIMEOUT")
    baseline_total = len(records)
    baseline_exp = compute_expectancy(baseline_win, baseline_loss, baseline_total)

    prim_baseline_total = sum(1 for r in records if r["bucket"] == "PRIMARY_TOP_1")
    prim_baseline_win = sum(1 for r in records if r["bucket"] == "PRIMARY_TOP_1" and r["future_observed_outcome"] == "WIN")
    prim_baseline_loss = sum(1 for r in records if r["bucket"] == "PRIMARY_TOP_1" and r["future_observed_outcome"] == "LOSS")
    prim_baseline_timeout = sum(1 for r in records if r["bucket"] == "PRIMARY_TOP_1" and r["future_observed_outcome"] == "TIMEOUT")
    prim_baseline_exp = compute_expectancy(prim_baseline_win, prim_baseline_loss, prim_baseline_total)

    watch_baseline_total = sum(1 for r in records if r["bucket"] == "WATCH_TOP_5")
    watch_baseline_win = sum(1 for r in records if r["bucket"] == "WATCH_TOP_5" and r["future_observed_outcome"] == "WIN")
    watch_baseline_loss = sum(1 for r in records if r["bucket"] == "WATCH_TOP_5" and r["future_observed_outcome"] == "LOSS")
    watch_baseline_timeout = sum(1 for r in records if r["bucket"] == "WATCH_TOP_5" and r["future_observed_outcome"] == "TIMEOUT")
    watch_baseline_exp = compute_expectancy(watch_baseline_win, watch_baseline_loss, watch_baseline_total)

    generated_at = datetime.now(timezone.utc).isoformat()
    overfit_warning = "EARLY SHADOW SAMPLE — only 44 resolved records. High risk of overfitting. Findings represent shadow-only hypotheses."

    report = {
        "generated_at": generated_at,
        "shadow_db": shadow_db,
        "resolved_count": len(records),
        "overfit_warning": overfit_warning,
        "baseline": {
            "total_resolved": baseline_total,
            "wins": baseline_win,
            "losses": baseline_loss,
            "timeouts": baseline_timeout,
            "win_rate": round(baseline_win / baseline_total, 4) if baseline_total else 0.0,
            "gross_expectancy": baseline_exp,
            "primary_top_1": {
                "total": prim_baseline_total,
                "wins": prim_baseline_win,
                "losses": prim_baseline_loss,
                "timeouts": prim_baseline_timeout,
                "expectancy": prim_baseline_exp
            },
            "watch_top_5": {
                "total": watch_baseline_total,
                "wins": watch_baseline_win,
                "losses": watch_baseline_loss,
                "timeouts": watch_baseline_timeout,
                "expectancy": watch_baseline_exp
            }
        },
        "markers": results,
        "plain_english_diagnostic_notes": get_plain_english_observations(results, baseline_total)
    }

    txt_report = format_txt_report(report)
    print(txt_report)

    os.makedirs(os.path.dirname(report_json_path), exist_ok=True)
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    with open(report_txt_path, "w", encoding="utf-8") as f:
        f.write(txt_report)

    print(f"JSON Report written to: {report_json_path}")
    print(f"TXT Report written to:  {report_txt_path}")

    return 0


if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description="Analyze entry risk markers what-if backtest")
    parser.add_argument("--shadow-db", type=str, default=DEFAULT_DB_PATH, help="Path to shadow DB")
    parser.add_argument("--dhan-db", type=str, default=None, help="Path to dhan auth DB")
    parser.add_argument("--diagnosis-json", type=str, default=DIAGNOSIS_JSON_PATH, help="Path to entry failure diagnosis JSON")
    parser.add_argument("--report-json", type=str, default=REPORT_JSON_PATH, help="Path to write JSON report")
    parser.add_argument("--report-txt", type=str, default=REPORT_TXT_PATH, help="Path to write TXT report")
    args = parser.parse_args()

    sys.exit(run_analysis(
        shadow_db=args.shadow_db,
        dhan_db=args.dhan_db,
        diagnosis_json_path=args.diagnosis_json,
        report_json_path=args.report_json,
        report_txt_path=args.report_txt
    ))
