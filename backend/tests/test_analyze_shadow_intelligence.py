"""
test_analyze_shadow_intelligence.py

Tests for ML V1.17 Shadow Performance Intelligence.

All tests use tmp_path SQLite databases.
Never touches /app/data/shadow_tracking.sqlite3.
"""
from __future__ import annotations

import json
import os
import sqlite3
import pytest

from app.scripts.analyze_shadow_intelligence import (
    build_report,
    compute_expectancy,
    format_txt_report,
    load_resolved_records,
    run_analysis,
    section_calibration,
    section_by_date,
    section_rank_effectiveness,
    section_regime_gates,
    section_speed_of_failure,
    ML_TARGET_PERCENT,
    ML_STOP_PERCENT,
)


# ---------------------------------------------------------------------------
# Shadow DB builder
# ---------------------------------------------------------------------------

REGIME_JSON = json.dumps({
    "market_median_20d_return": -0.01,
    "market_breakout_rate": 0.02,
    "market_breakdown_rate": 0.10,
    "market_breadth_delta": -0.05,
    "market_cross_sectional_volatility": 0.03,
    "stock_20d_return_minus_market_median": 0.04,
    "stock_is_stronger_than_market": 1.0,
    "stock_breakout_while_market_weak": 0.0,
})


def make_shadow_db(tmp_path, rows: list[dict]) -> str:
    """
    rows: list of dicts with keys:
        symbol, scored_sample_date, outcome, rank, bucket,
        win_probability, days_to_outcome
    """
    db_path = str(tmp_path / "shadow.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE shadow_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_scored TEXT,
            scored_sample_date TEXT NOT NULL,
            model_version TEXT NOT NULL DEFAULT 'test_model_v1',
            model_commit TEXT DEFAULT 'abc123',
            rank INTEGER NOT NULL,
            bucket TEXT NOT NULL,
            symbol TEXT NOT NULL,
            win_probability REAL NOT NULL,
            regime_context_json TEXT,
            tracking_status TEXT NOT NULL,
            future_observed_outcome TEXT,
            days_to_outcome INTEGER,
            barrier_hit_type TEXT,
            barrier_hit_date TEXT,
            resolved_at TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT '2026-01-01',
            updated_at TEXT NOT NULL DEFAULT '2026-01-01'
        );
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO shadow_tracking "
            "(scored_sample_date, rank, bucket, symbol, win_probability, "
            " regime_context_json, tracking_status, future_observed_outcome, days_to_outcome)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r.get("scored_sample_date", "2026-05-15"),
                r.get("rank", 1),
                r.get("bucket", "PRIMARY_TOP_1"),
                r.get("symbol", "SYM"),
                r.get("win_probability", 0.45),
                r.get("regime_context_json", REGIME_JSON),
                r.get("tracking_status", "RESOLVED"),
                r.get("outcome"),
                r.get("days_to_outcome"),
            ),
        )
    conn.commit()
    conn.close()
    return db_path


def win_row(**kwargs) -> dict:
    return {"outcome": "WIN", "days_to_outcome": 5, **kwargs}


def loss_row(**kwargs) -> dict:
    return {"outcome": "LOSS", "days_to_outcome": 1, **kwargs}


def timeout_row(**kwargs) -> dict:
    return {"outcome": "TIMEOUT", "days_to_outcome": 20, **kwargs}


def observing_row(**kwargs) -> dict:
    return {"outcome": None, "days_to_outcome": None, "tracking_status": "OBSERVING", **kwargs}


# ---------------------------------------------------------------------------
# compute_expectancy: formula correctness
# ---------------------------------------------------------------------------

def test_expectancy_all_zero():
    e = compute_expectancy(0, 0, 0)
    assert e["gross_expectancy_all_resolved"] is None
    assert e["gross_expectancy_excluding_timeout"] is None


def test_expectancy_consistent_denominator_all_resolved():
    e = compute_expectancy(14, 29, 1)
    # denom = 44, P_win = 14/44, P_loss = 29/44
    expected = round((14 / 44) * ML_TARGET_PERCENT - (29 / 44) * ML_STOP_PERCENT, 4)
    assert e["gross_expectancy_all_resolved"] == expected
    assert e["denominator_all_resolved"] == 44


def test_expectancy_consistent_denominator_excl_timeout():
    e = compute_expectancy(14, 29, 1)
    # denom = 43
    expected = round((14 / 43) * ML_TARGET_PERCENT - (29 / 43) * ML_STOP_PERCENT, 4)
    assert e["gross_expectancy_excluding_timeout"] == expected
    assert e["denominator_excluding_timeout"] == 43


def test_expectancy_all_wins():
    e = compute_expectancy(10, 0, 0)
    assert e["gross_expectancy_all_resolved"] == round(ML_TARGET_PERCENT, 4)
    assert e["gross_expectancy_excluding_timeout"] == round(ML_TARGET_PERCENT, 4)


def test_expectancy_all_losses():
    e = compute_expectancy(0, 10, 0)
    assert e["gross_expectancy_all_resolved"] == round(-ML_STOP_PERCENT, 4)
    assert e["gross_expectancy_excluding_timeout"] == round(-ML_STOP_PERCENT, 4)


def test_expectancy_timeout_only():
    e = compute_expectancy(0, 0, 5)
    # all resolved = 5, expectancy = 0
    assert e["gross_expectancy_all_resolved"] == 0.0
    # no W+L → excl timeout is None
    assert e["gross_expectancy_excluding_timeout"] is None


# ---------------------------------------------------------------------------
# Empty DB handled gracefully
# ---------------------------------------------------------------------------

def test_empty_db_no_resolved(tmp_path):
    db = make_shadow_db(tmp_path, [])
    report = build_report(shadow_db=db)
    assert report["status"] == "NO_RESOLVED_RECORDS"
    assert report["resolved_count"] == 0
    txt = format_txt_report(report)
    assert "No resolved records" in txt


def test_empty_db_run_analysis_exits_0(tmp_path):
    db = make_shadow_db(tmp_path, [])
    exp_dir = str(tmp_path / "exports")
    code = run_analysis(
        shadow_db=db,
        exports_dir=exp_dir,
        report_json_path=str(tmp_path / "r.json"),
        report_txt_path=str(tmp_path / "r.txt"),
    )
    assert code == 0


# ---------------------------------------------------------------------------
# All-loss scenario
# ---------------------------------------------------------------------------

def test_all_loss_expectancy_negative(tmp_path):
    db = make_shadow_db(tmp_path, [loss_row(symbol=f"L{i}") for i in range(5)])
    report = build_report(shadow_db=db)
    assert report["overall"]["win_count"] == 0
    assert report["overall"]["loss_count"] == 5
    ge = report["overall"]["expectancy"]["gross_expectancy_all_resolved"]
    assert ge == round(-ML_STOP_PERCENT, 4)


# ---------------------------------------------------------------------------
# All-win scenario
# ---------------------------------------------------------------------------

def test_all_win_expectancy_positive(tmp_path):
    db = make_shadow_db(tmp_path, [win_row(symbol=f"W{i}") for i in range(5)])
    report = build_report(shadow_db=db)
    assert report["overall"]["win_count"] == 5
    ge = report["overall"]["expectancy"]["gross_expectancy_all_resolved"]
    assert ge == round(ML_TARGET_PERCENT, 4)


# ---------------------------------------------------------------------------
# Mixed win/loss/timeout
# ---------------------------------------------------------------------------

def test_mixed_all_sections_present(tmp_path):
    rows = (
        [win_row(symbol=f"W{i}", rank=i + 1) for i in range(5)]
        + [loss_row(symbol=f"L{i}", rank=i + 6) for i in range(5)]
        + [timeout_row(symbol="T1", rank=11)]
    )
    db = make_shadow_db(tmp_path, rows)
    report = build_report(shadow_db=db)
    assert report["status"] == "OK"
    for section in ("overall", "calibration", "speed_of_failure",
                    "rank_effectiveness", "by_date", "regime_gates"):
        assert section in report, f"Missing section: {section}"


# ---------------------------------------------------------------------------
# Calibration bins
# ---------------------------------------------------------------------------

def test_calibration_bins_count(tmp_path):
    rows = [
        {"outcome": "WIN", "days_to_outcome": 5, "win_probability": 0.1, "rank": 1, "symbol": "A"},
        {"outcome": "LOSS", "days_to_outcome": 1, "win_probability": 0.3, "rank": 2, "symbol": "B"},
        {"outcome": "WIN", "days_to_outcome": 3, "win_probability": 0.5, "rank": 3, "symbol": "C"},
        {"outcome": "LOSS", "days_to_outcome": 2, "win_probability": 0.7, "rank": 4, "symbol": "D"},
        {"outcome": "WIN", "days_to_outcome": 4, "win_probability": 0.9, "rank": 5, "symbol": "E"},
    ]
    db = make_shadow_db(tmp_path, rows)
    records = load_resolved_records(db)
    result = section_calibration(records, n_bins=5)
    assert len(result["bins"]) == 5
    assert result["ece"] is not None
    assert result["ece"] >= 0.0


def test_calibration_ece_perfect_model(tmp_path):
    """If all high-prob predictions are wins and low-prob are losses, ECE should be low."""
    rows = [
        {"outcome": "WIN", "win_probability": 0.95, "days_to_outcome": 5, "rank": 1, "symbol": "H1"},
        {"outcome": "WIN", "win_probability": 0.90, "days_to_outcome": 4, "rank": 2, "symbol": "H2"},
        {"outcome": "LOSS", "win_probability": 0.05, "days_to_outcome": 1, "rank": 3, "symbol": "L1"},
        {"outcome": "LOSS", "win_probability": 0.10, "days_to_outcome": 1, "rank": 4, "symbol": "L2"},
    ]
    db = make_shadow_db(tmp_path, rows)
    records = load_resolved_records(db)
    result = section_calibration(records, n_bins=5)
    assert result["ece"] < 0.5  # ECE should be lower than a random model


# ---------------------------------------------------------------------------
# Rank effectiveness
# ---------------------------------------------------------------------------

def test_rank_bands_grouping(tmp_path):
    rows = [
        win_row(rank=1, symbol="R1"),
        loss_row(rank=3, symbol="R2"),
        win_row(rank=6, symbol="R3"),
        loss_row(rank=10, symbol="R4"),
        loss_row(rank=12, symbol="R5"),
        win_row(rank=20, symbol="R6"),
    ]
    db = make_shadow_db(tmp_path, rows)
    records = load_resolved_records(db)
    result = section_rank_effectiveness(records)
    bands = [b["rank_band"] for b in result["by_rank_band"]]
    # rank 1,3 -> "1-5"; rank 6,10 -> "6-10"; rank 12 -> "11-15"; rank 20 -> "16-22"
    assert "1-5" in bands
    assert "6-10" in bands
    assert "11-15" in bands
    assert "16-22" in bands


def test_rank_band_win_rates(tmp_path):
    # Band 1-5: 2 wins, 0 losses -> 100%
    # Band 6-10: 0 wins, 2 losses -> 0%
    rows = [
        win_row(rank=1, symbol="W1"), win_row(rank=2, symbol="W2"),
        loss_row(rank=6, symbol="L1"), loss_row(rank=7, symbol="L2"),
    ]
    db = make_shadow_db(tmp_path, rows)
    records = load_resolved_records(db)
    result = section_rank_effectiveness(records)
    band_map = {b["rank_band"]: b for b in result["by_rank_band"]}
    assert band_map["1-5"]["win_rate_excl_timeout"] == 1.0
    assert band_map["6-10"]["win_rate_excl_timeout"] == 0.0


# ---------------------------------------------------------------------------
# Days to outcome / speed of failure
# ---------------------------------------------------------------------------

def test_days_to_outcome_analysis(tmp_path):
    rows = [
        win_row(days_to_outcome=5, symbol="W1"),
        win_row(days_to_outcome=10, symbol="W2"),
        loss_row(days_to_outcome=1, symbol="L1"),
        loss_row(days_to_outcome=1, symbol="L2"),
        loss_row(days_to_outcome=3, symbol="L3"),
    ]
    db = make_shadow_db(tmp_path, rows)
    records = load_resolved_records(db)
    result = section_speed_of_failure(records)
    assert result["wins"]["avg"] == 7.5
    assert result["wins"]["min"] == 5
    assert result["wins"]["max"] == 10
    assert result["losses"]["avg"] == pytest.approx(5 / 3, abs=0.01)
    assert result["day1_loss_count"] == 2
    assert result["day1_loss_rate"] == pytest.approx(2 / 3, abs=0.01)


def test_day_histogram_correct(tmp_path):
    rows = [
        loss_row(days_to_outcome=1, symbol="L1"),
        loss_row(days_to_outcome=1, symbol="L2"),
        loss_row(days_to_outcome=2, symbol="L3"),
    ]
    db = make_shadow_db(tmp_path, rows)
    records = load_resolved_records(db)
    result = section_speed_of_failure(records)
    hist = result["losses"]["day_histogram"]
    assert hist["1"] == 2
    assert hist["2"] == 1


# ---------------------------------------------------------------------------
# Regime gate analysis
# ---------------------------------------------------------------------------

def test_regime_gate_delta_computed(tmp_path):
    win_regime = json.dumps({
        "market_median_20d_return": -0.02,
        "market_breakout_rate": 0.03,
        "market_breakdown_rate": 0.12,
        "market_breadth_delta": -0.10,
        "market_cross_sectional_volatility": 0.03,
        "stock_20d_return_minus_market_median": 0.02,
        "stock_is_stronger_than_market": 1.0,
        "stock_breakout_while_market_weak": 0.0,
    })
    loss_regime = json.dumps({
        "market_median_20d_return": -0.005,
        "market_breakout_rate": 0.02,
        "market_breakdown_rate": 0.07,
        "market_breadth_delta": -0.04,
        "market_cross_sectional_volatility": 0.03,
        "stock_20d_return_minus_market_median": 0.04,
        "stock_is_stronger_than_market": 0.5,
        "stock_breakout_while_market_weak": 0.0,
    })
    rows = [
        win_row(symbol="W1", regime_context_json=win_regime),
        win_row(symbol="W2", regime_context_json=win_regime),
        loss_row(symbol="L1", regime_context_json=loss_regime),
        loss_row(symbol="L2", regime_context_json=loss_regime),
    ]
    db = make_shadow_db(tmp_path, rows)
    records = load_resolved_records(db)
    result = section_regime_gates(records)
    gate_map = {g["feature"]: g for g in result["gate_table"]}
    # WIN median_20d_return is more negative than LOSS → delta should be negative
    assert gate_map["market_median_20d_return"]["delta_win_minus_loss"] < 0
    # Sorted by abs(delta) descending
    deltas = [abs(g["delta_win_minus_loss"]) for g in result["gate_table"] if g["delta_win_minus_loss"] is not None]
    assert deltas == sorted(deltas, reverse=True)


def test_regime_gate_missing_context(tmp_path):
    """If regime_context_json is empty, function should not crash."""
    rows = [
        {"outcome": "WIN", "days_to_outcome": 5, "rank": 1, "symbol": "W1",
         "regime_context_json": "{}"},
        {"outcome": "LOSS", "days_to_outcome": 1, "rank": 2, "symbol": "L1",
         "regime_context_json": "{}"},
    ]
    db = make_shadow_db(tmp_path, rows)
    records = load_resolved_records(db)
    result = section_regime_gates(records)
    assert "gate_table" in result
    for g in result["gate_table"]:
        assert g["win_mean"] is None
        assert g["loss_mean"] is None
        assert g["delta_win_minus_loss"] is None


# ---------------------------------------------------------------------------
# Per-date breakdown
# ---------------------------------------------------------------------------

def test_by_date_groups_correctly(tmp_path):
    rows = [
        win_row(symbol="W1", scored_sample_date="2026-05-15"),
        loss_row(symbol="L1", scored_sample_date="2026-05-15"),
        loss_row(symbol="L2", scored_sample_date="2026-05-18"),
        win_row(symbol="W2", scored_sample_date="2026-05-18"),
        win_row(symbol="W3", scored_sample_date="2026-05-18"),
    ]
    db = make_shadow_db(tmp_path, rows)
    records = load_resolved_records(db)
    result = section_by_date(records)
    date_map = {d["scored_sample_date"]: d for d in result["by_date"]}
    assert "2026-05-15" in date_map
    assert "2026-05-18" in date_map
    assert date_map["2026-05-15"]["win_count"] == 1
    assert date_map["2026-05-15"]["loss_count"] == 1
    assert date_map["2026-05-18"]["win_count"] == 2
    assert date_map["2026-05-18"]["loss_count"] == 1


# ---------------------------------------------------------------------------
# JSON and TXT reports written
# ---------------------------------------------------------------------------

def test_json_report_written_with_required_keys(tmp_path):
    rows = (
        [win_row(symbol=f"W{i}", rank=i + 1) for i in range(3)]
        + [loss_row(symbol=f"L{i}", rank=i + 4) for i in range(3)]
        + [timeout_row(symbol="T1", rank=7)]
    )
    db = make_shadow_db(tmp_path, rows)
    exp_dir = str(tmp_path / "exports")
    rj = str(tmp_path / "report.json")
    rt = str(tmp_path / "report.txt")

    code = run_analysis(shadow_db=db, exports_dir=exp_dir, report_json_path=rj, report_txt_path=rt)
    assert code == 0
    assert os.path.exists(rj)
    assert os.path.exists(rt)

    with open(rj) as f:
        report = json.load(f)

    required_keys = [
        "generated_at", "resolved_count", "observing_count", "sample_warning",
        "overall", "calibration", "speed_of_failure",
        "rank_effectiveness", "by_date", "regime_gates",
    ]
    for key in required_keys:
        assert key in report, f"Missing key in report: {key}"


def test_txt_report_non_empty_and_contains_sections(tmp_path):
    rows = [win_row(symbol="W1"), loss_row(symbol="L1")]
    db = make_shadow_db(tmp_path, rows)
    rj = str(tmp_path / "report.json")
    rt = str(tmp_path / "report.txt")

    run_analysis(shadow_db=db, exports_dir=str(tmp_path / "exports"), report_json_path=rj, report_txt_path=rt)
    with open(rt) as f:
        content = f.read()

    for section in ["OVERALL SUMMARY", "CALIBRATION", "SPEED OF FAILURE",
                    "RANK EFFECTIVENESS", "BY SCORED SAMPLE DATE", "REGIME GATE"]:
        assert section in content, f"Missing section in TXT: {section}"


def test_run_analysis_always_exits_0_on_db_error(tmp_path):
    """Even if the shadow DB does not exist, run_analysis must exit 0."""
    code = run_analysis(
        shadow_db=str(tmp_path / "nonexistent.sqlite3"),
        exports_dir=str(tmp_path / "exports"),
        report_json_path=str(tmp_path / "r.json"),
        report_txt_path=str(tmp_path / "r.txt"),
    )
    assert code == 0
