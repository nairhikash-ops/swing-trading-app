"""
test_analyze_entry_risk_markers.py

Tests for ML V1.19 Shadow Entry Risk Marker What-If Analysis.
All tests use tmp_path SQLite databases.
Never touches real shadow DB or live dhan DB.
"""
from __future__ import annotations

import json
import os
import sqlite3
import pytest

from app.scripts.analyze_entry_risk_markers import (
    format_txt_report,
    run_analysis,
    GAP_DOWN_STOP,
    INTRADAY_STOP,
    NOT_CLASSIFIED,
)


def make_shadow_db(tmp_path, rows: list[dict]) -> str:
    db_path = str(tmp_path / "shadow_tracking.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE shadow_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_scored TEXT NOT NULL,
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
            barrier_hit_date TEXT,
            barrier_hit_type TEXT,
            days_to_outcome INTEGER,
            created_at TEXT NOT NULL DEFAULT '2026-01-01',
            updated_at TEXT NOT NULL DEFAULT '2026-01-01',
            notes TEXT,
            resolved_at TEXT
        );
    """)
    for r in rows:
        regime = r.get("regime", {
            "market_median_20d_return": 0.01,
            "market_breakout_rate": 0.05,
            "market_breakdown_rate": 0.05,
            "market_breadth_delta": 0.0,
            "market_cross_sectional_volatility": 0.05,
            "stock_20d_return_minus_market_median": 0.05,
            "stock_is_stronger_than_market": 1.0,
            "stock_breakout_while_market_weak": 0.0,
        })
        conn.execute(
            "INSERT INTO shadow_tracking "
            "(scored_sample_date, date_scored, rank, bucket, symbol, win_probability, "
            " regime_context_json, tracking_status, future_observed_outcome, days_to_outcome, barrier_hit_date)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r.get("scored_sample_date", "2026-05-15"),
                r.get("date_scored", "2026-05-15"),
                r.get("rank", 1),
                r.get("bucket", "PRIMARY_TOP_1"),
                r.get("symbol", "SYM"),
                r.get("win_probability", 0.45),
                json.dumps(regime),
                r.get("tracking_status", "RESOLVED"),
                r.get("outcome"),
                r.get("days_to_outcome"),
                r.get("barrier_hit_date"),
            ),
        )
    conn.commit()
    conn.close()
    return db_path


def make_dhan_db(tmp_path, samples: list[dict], candles: list[dict]) -> str:
    db_path = str(tmp_path / "dhan_auth.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE ml_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            sample_date TEXT NOT NULL,
            entry_close REAL NOT NULL,
            stop_price REAL NOT NULL,
            instrument_id INTEGER NOT NULL
        );
        CREATE TABLE daily_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_id INTEGER NOT NULL,
            trading_date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL DEFAULT 1000
        );
    """)
    for s in samples:
        conn.execute(
            "INSERT INTO ml_samples (symbol, sample_date, entry_close, stop_price, instrument_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (s["symbol"], s["sample_date"], s["entry_close"], s["stop_price"], s["instrument_id"])
        )
    for c in candles:
        conn.execute(
            "INSERT INTO daily_candles (instrument_id, trading_date, open, high, low, close) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (c["instrument_id"], c["trading_date"], c["open"], c["high"], c["low"], c["close"])
        )
    conn.commit()
    conn.close()
    return db_path


def make_diagnosis_json(tmp_path, data: dict) -> str:
    path = str(tmp_path / "entry_failure_diagnosis.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_empty_shadow_input_handled_gracefully(tmp_path):
    s_db = make_shadow_db(tmp_path, [])
    d_db = make_dhan_db(tmp_path, [], [])
    diag = make_diagnosis_json(tmp_path, {})
    
    # Exits with 0 / handled gracefully
    code = run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                        report_json_path=str(tmp_path / "out.json"),
                        report_txt_path=str(tmp_path / "out.txt"))
    assert code == 0


def test_marker_removes_day_1_losses(tmp_path):
    # Setup one Day-1 loss under high stress
    regime = {
        "market_breadth_delta": -0.08,
        "market_breakdown_rate": 0.09,
        "market_median_20d_return": -0.015,
        "stock_is_stronger_than_market": 1.0,
        "stock_20d_return_minus_market_median": 0.05
    }
    s_rows = [
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "STRESS_LOSS", "regime": regime}
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    
    # Diagnose file maps STRESS_LOSS to INTRADAY_STOP
    diag_data = {
        "high_confidence_failures": [
            {"symbol": "STRESS_LOSS", "scored_sample_date": "2026-05-15", "stop_mechanism": INTRADAY_STOP}
        ]
    }
    diag = make_diagnosis_json(tmp_path, diag_data)
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    with open(rj) as f:
        report = json.load(f)
    
    # market_breadth_delta_05 marker should exclude this record
    marker_05 = [m for m in report["markers"] if m["id"] == "market_breadth_delta_05"][0]
    assert marker_05["records_excluded"] == 1
    assert marker_05["day1_losses_avoided"] == 1
    assert marker_05["intraday_stops_avoided"] == 1


def test_marker_removes_too_many_wins_and_is_flagged_dangerous(tmp_path):
    # Setup 3 wins, 1 loss.
    # Exclude two wins. This is 2/3 = 66% of wins, which is > 50% threshold.
    regime_stress = {"market_breadth_delta": -0.06}
    regime_normal = {"market_breadth_delta": 0.05}
    s_rows = [
        {"outcome": "WIN", "symbol": "W1", "regime": regime_stress},
        {"outcome": "WIN", "symbol": "W2", "regime": regime_stress},
        {"outcome": "WIN", "symbol": "W3", "regime": regime_normal},
        {"outcome": "LOSS", "symbol": "L1", "regime": regime_normal},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    diag = make_diagnosis_json(tmp_path, {})
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    with open(rj) as f:
        report = json.load(f)
        
    marker_05 = [m for m in report["markers"] if m["id"] == "market_breadth_delta_05"][0]
    assert marker_05["is_dangerous"] is True


def test_expectancy_improves_after_exclusion(tmp_path):
    # Before: 1 win, 2 losses -> Exp: (1/3)*7 - (2/3)*3 = 2.333 - 2 = 0.333
    # Exclude 1 loss -> Remaining: 1 win, 1 loss -> Exp: (1/2)*7 - (1/2)*3 = 2.0
    # Exp improves!
    regime_stress = {"market_breadth_delta": -0.06}
    regime_normal = {"market_breadth_delta": 0.05}
    s_rows = [
        {"outcome": "WIN", "symbol": "W1", "regime": regime_normal},
        {"outcome": "LOSS", "symbol": "L1", "regime": regime_normal},
        {"outcome": "LOSS", "symbol": "L2", "regime": regime_stress},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    diag = make_diagnosis_json(tmp_path, {})
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    with open(rj) as f:
        report = json.load(f)
        
    marker_05 = [m for m in report["markers"] if m["id"] == "market_breadth_delta_05"][0]
    assert marker_05["expectancy_after"] > marker_05["expectancy_before"]


def test_expectancy_worsens_after_exclusion(tmp_path):
    # Before: 2 wins, 1 loss -> Exp: (2/3)*7 - (1/3)*3 = 4.667 - 1 = 3.667
    # Exclude 1 win -> Remaining: 1 win, 1 loss -> Exp: 2.0
    # Exp worsens!
    regime_stress = {"market_breadth_delta": -0.06}
    regime_normal = {"market_breadth_delta": 0.05}
    s_rows = [
        {"outcome": "WIN", "symbol": "W1", "regime": regime_normal},
        {"outcome": "WIN", "symbol": "W2", "regime": regime_stress},
        {"outcome": "LOSS", "symbol": "L1", "regime": regime_normal},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    diag = make_diagnosis_json(tmp_path, {})
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    with open(rj) as f:
        report = json.load(f)
        
    marker_05 = [m for m in report["markers"] if m["id"] == "market_breadth_delta_05"][0]
    assert marker_05["expectancy_after"] < marker_05["expectancy_before"]


def test_primary_top1_and_watch_top5_analyzed_separately(tmp_path):
    s_rows = [
        {"outcome": "WIN", "symbol": "W1", "bucket": "PRIMARY_TOP_1"},
        {"outcome": "LOSS", "symbol": "L1", "bucket": "WATCH_TOP_5"},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    diag = make_diagnosis_json(tmp_path, {})
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    with open(rj) as f:
        report = json.load(f)
        
    assert "primary_top_1" in report["baseline"]
    assert "watch_top_5" in report["baseline"]
    
    marker = report["markers"][0]
    assert "primary_top_1_impact" in marker
    assert "watch_top_5_impact" in marker


def test_scored_date_stability_computed(tmp_path):
    s_rows = [
        {"outcome": "WIN", "symbol": "W1", "scored_sample_date": "2026-05-15"},
        {"outcome": "LOSS", "symbol": "L1", "scored_sample_date": "2026-05-18"},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    diag = make_diagnosis_json(tmp_path, {})
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    with open(rj) as f:
        report = json.load(f)
        
    marker = report["markers"][0]
    assert "2026-05-15" in marker["date_stability"]
    assert "2026-05-18" in marker["date_stability"]


def test_marker_flagged_if_it_only_works_on_one_scored_date(tmp_path):
    # Marker avoids Day-1 loss on 2026-05-15, but has no avoided losses on 2026-05-18
    # Triggering breadth delta only on May 15
    regime_stress = {"market_breadth_delta": -0.06}
    regime_normal = {"market_breadth_delta": 0.05}
    s_rows = [
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "L15", "scored_sample_date": "2026-05-15", "regime": regime_stress},
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "L18", "scored_sample_date": "2026-05-18", "regime": regime_normal},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    diag = make_diagnosis_json(tmp_path, {})
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    with open(rj) as f:
        report = json.load(f)
        
    marker_05 = [m for m in report["markers"] if m["id"] == "market_breadth_delta_05"][0]
    assert marker_05["only_explains_one_date"] is True


def test_overfit_warning_appears_for_small_sample(tmp_path):
    s_rows = [{"outcome": "WIN", "symbol": "W1"}]
    s_db = make_shadow_db(tmp_path, s_rows)
    diag = make_diagnosis_json(tmp_path, {})
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    with open(rj) as f:
        report = json.load(f)
        
    assert "EARLY SHADOW SAMPLE" in report["overfit_warning"]


def test_json_report_written(tmp_path):
    s_db = make_shadow_db(tmp_path, [{"outcome": "WIN", "symbol": "W1"}])
    diag = make_diagnosis_json(tmp_path, {})
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    assert os.path.exists(rj)
    with open(rj) as f:
        data = json.load(f)
    assert "baseline" in data
    assert "markers" in data
    assert "plain_english_diagnostic_notes" in data


def test_txt_report_written(tmp_path):
    s_db = make_shadow_db(tmp_path, [{"outcome": "WIN", "symbol": "W1"}])
    diag = make_diagnosis_json(tmp_path, {})
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "out.json")
    rt = str(tmp_path / "out.txt")
    run_analysis(shadow_db=s_db, dhan_db=d_db, diagnosis_json_path=diag,
                 report_json_path=rj, report_txt_path=rt)
    
    assert os.path.exists(rt)
    with open(rt) as f:
        txt = f.read()
    assert "SHADOW ENTRY RISK MARKER WHAT-IF ANALYSIS REPORT" in txt
    assert "1. BASELINE SHADOW PERFORMANCE SUMMARY" in txt
    assert "2. WHAT-IF EXCLUSION RESULTS PER CANDIDATE MARKER" in txt
    assert "3. PLAIN-ENGLISH DIAGNOSTIC OBSERVATIONS" in txt
