"""
test_analyze_entry_failures.py

Tests for ML V1.18 Entry Failure Diagnosis.
All tests use tmp_path SQLite databases.
Never touches real shadow DB or live dhan DB.
"""
from __future__ import annotations

import json
import os
import sqlite3
import pytest

from app.scripts.analyze_entry_failures import (
    build_report,
    format_txt_report,
    run_diagnosis,
    GAP_DOWN_STOP,
    INTRADAY_STOP,
    NOT_CLASSIFIED,
    UNCLASSIFIED_MISSING_ML_SAMPLE,
    UNCLASSIFIED_MISSING_NEXT_CANDLE,
)


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
                r.get("regime_context_json", REGIME_JSON),
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


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_empty_db_handled_gracefully(tmp_path):
    s_db = make_shadow_db(tmp_path, [])
    d_db = make_dhan_db(tmp_path, [], [])
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    assert report["status"] == "NO_RESOLVED_RECORDS"
    assert report["resolved_count"] == 0
    
    txt = format_txt_report(report)
    assert "No resolved records" in txt


def test_gap_down_stop_classification(tmp_path):
    # Day-1 Loss: Scored on May 15. Hit Stop on May 18.
    s_row = {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "GAPSYM", "scored_sample_date": "2026-05-15", "barrier_hit_date": "2026-05-18"}
    s_db = make_shadow_db(tmp_path, [s_row])
    
    # ml_samples: Entry = 100, Stop = 97, Inst = 1
    sample = {"symbol": "GAPSYM", "sample_date": "2026-05-15", "entry_close": 100.0, "stop_price": 97.0, "instrument_id": 1}
    # next candle (May 18): Open = 96.0, Low = 95.0 -> Gap down stop (open <= 97.0)
    candle = {"instrument_id": 1, "trading_date": "2026-05-18", "open": 96.0, "high": 99.0, "low": 95.0, "close": 98.0}
    d_db = make_dhan_db(tmp_path, [sample], [candle])
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    assert report["status"] == "OK"
    assert report["overall"]["gap_down_count"] == 1
    assert report["overall"]["intraday_count"] == 0


def test_intraday_stop_classification(tmp_path):
    # Day-1 Loss: Scored on May 15. Hit Stop on May 18.
    s_row = {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "INTRASYM", "scored_sample_date": "2026-05-15", "barrier_hit_date": "2026-05-18"}
    s_db = make_shadow_db(tmp_path, [s_row])
    
    # ml_samples: Entry = 100, Stop = 97, Inst = 2
    sample = {"symbol": "INTRASYM", "sample_date": "2026-05-15", "entry_close": 100.0, "stop_price": 97.0, "instrument_id": 2}
    # next candle (May 18): Open = 98.0, Low = 96.0 -> Intraday stop (open > 97.0 and low <= 97.0)
    candle = {"instrument_id": 2, "trading_date": "2026-05-18", "open": 98.0, "high": 99.0, "low": 96.0, "close": 98.0}
    d_db = make_dhan_db(tmp_path, [sample], [candle])
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    assert report["status"] == "OK"
    assert report["overall"]["gap_down_count"] == 0
    assert report["overall"]["intraday_count"] == 1


def test_missing_ml_sample_classification(tmp_path):
    # Day-1 Loss row
    s_row = {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "MISSSYM", "scored_sample_date": "2026-05-15"}
    s_db = make_shadow_db(tmp_path, [s_row])
    # Empty dhan_db (no matching ml_samples)
    d_db = make_dhan_db(tmp_path, [], [])
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    assert report["status"] == "OK"
    assert report["overall"]["unclassified_missing_sample_count"] == 1
    assert report["overall"]["gap_down_count"] == 0
    assert report["overall"]["intraday_count"] == 0


def test_missing_next_candle_classification(tmp_path):
    # Day-1 Loss row
    s_row = {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "NOCANDLESYM", "scored_sample_date": "2026-05-15"}
    s_db = make_shadow_db(tmp_path, [s_row])
    
    # ml_samples has row, but daily_candles has no entries after 2026-05-15
    sample = {"symbol": "NOCANDLESYM", "sample_date": "2026-05-15", "entry_close": 100.0, "stop_price": 97.0, "instrument_id": 3}
    d_db = make_dhan_db(tmp_path, [sample], [])
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    assert report["status"] == "OK"
    assert report["overall"]["unclassified_missing_candle_count"] == 1
    assert report["overall"]["gap_down_count"] == 0
    assert report["overall"]["intraday_count"] == 0


def test_non_day1_losses_excluded(tmp_path):
    # Case A: Win
    # Case B: Timeout
    # Case C: Loss on Day 2
    s_rows = [
        {"outcome": "WIN", "days_to_outcome": 5, "symbol": "WINSYM", "scored_sample_date": "2026-05-15"},
        {"outcome": "TIMEOUT", "days_to_outcome": 20, "symbol": "TIMEOUTSYM", "scored_sample_date": "2026-05-15"},
        {"outcome": "LOSS", "days_to_outcome": 2, "symbol": "LOSS2SYM", "scored_sample_date": "2026-05-15"},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    
    # Dhan DB
    samples = [
        {"symbol": "WINSYM", "sample_date": "2026-05-15", "entry_close": 100.0, "stop_price": 97.0, "instrument_id": 4},
        {"symbol": "TIMEOUTSYM", "sample_date": "2026-05-15", "entry_close": 100.0, "stop_price": 97.0, "instrument_id": 5},
        {"symbol": "LOSS2SYM", "sample_date": "2026-05-15", "entry_close": 100.0, "stop_price": 97.0, "instrument_id": 6},
    ]
    candles = [
        {"instrument_id": 4, "trading_date": "2026-05-18", "open": 101.0, "high": 107.5, "low": 100.0, "close": 107.0},
        {"instrument_id": 5, "trading_date": "2026-05-18", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"instrument_id": 6, "trading_date": "2026-05-18", "open": 99.0, "high": 100.0, "low": 98.0, "close": 99.0},
        {"instrument_id": 6, "trading_date": "2026-05-19", "open": 98.0, "high": 99.0, "low": 96.0, "close": 97.0},
    ]
    d_db = make_dhan_db(tmp_path, samples, candles)
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    assert report["status"] == "OK"
    assert report["overall"]["day1_loss_count"] == 0
    assert report["overall"]["gap_down_count"] == 0
    assert report["overall"]["intraday_count"] == 0


def test_date_concentration_aggregation(tmp_path):
    s_rows = [
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "A", "scored_sample_date": "2026-05-15"},
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "B", "scored_sample_date": "2026-05-15"},
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "C", "scored_sample_date": "2026-05-18"},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    
    samples = [
        {"symbol": "A", "sample_date": "2026-05-15", "entry_close": 100.0, "stop_price": 97.0, "instrument_id": 1},
        {"symbol": "B", "sample_date": "2026-05-15", "entry_close": 100.0, "stop_price": 97.0, "instrument_id": 2},
        {"symbol": "C", "sample_date": "2026-05-18", "entry_close": 100.0, "stop_price": 97.0, "instrument_id": 3},
    ]
    # All gaps
    candles = [
        {"instrument_id": 1, "trading_date": "2026-05-18", "open": 95.0, "high": 96.0, "low": 94.0, "close": 95.0},
        {"instrument_id": 2, "trading_date": "2026-05-18", "open": 96.0, "high": 97.0, "low": 95.0, "close": 96.0},
        {"instrument_id": 3, "trading_date": "2026-05-19", "open": 94.0, "high": 95.0, "low": 93.0, "close": 94.0},
    ]
    d_db = make_dhan_db(tmp_path, samples, candles)
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    date_map = {d["scored_sample_date"]: d for d in report["by_date"]}
    assert date_map["2026-05-15"]["day1_losses"] == 2
    assert date_map["2026-05-18"]["day1_losses"] == 1


def test_rank_band_aggregation(tmp_path):
    s_rows = [
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "A", "rank": 2},
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "B", "rank": 8},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    d_db = make_dhan_db(tmp_path, [], []) # Missing ml_samples is fine
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    bands = {b["rank_band"]: b for b in report["rank_diagnostics"]["by_rank_band"]}
    assert bands["1-5"]["day1_losses"] == 1
    assert bands["6-10"]["day1_losses"] == 1


def test_bucket_aggregation(tmp_path):
    s_rows = [
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "A", "bucket": "PRIMARY_TOP_1"},
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "B", "bucket": "WATCH_TOP_5"},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    d_db = make_dhan_db(tmp_path, [], [])
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    buckets = {b["bucket"]: b for b in report["bucket_diagnostics"]}
    assert buckets["PRIMARY_TOP_1"]["day1_losses"] == 1
    assert buckets["WATCH_TOP_5"]["day1_losses"] == 1


def test_high_confidence_failures(tmp_path):
    s_rows = [
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "A", "win_probability": 0.55, "rank": 1},
        {"outcome": "LOSS", "days_to_outcome": 1, "symbol": "B", "win_probability": 0.45, "rank": 5},
    ]
    s_db = make_shadow_db(tmp_path, s_rows)
    d_db = make_dhan_db(tmp_path, [], [])
    
    report = build_report(shadow_db=s_db, dhan_db=d_db)
    hc = report["high_confidence_failures"]
    assert len(hc) == 1
    assert hc[0]["symbol"] == "A"


def test_report_json_written(tmp_path):
    s_db = make_shadow_db(tmp_path, [{"outcome": "LOSS", "days_to_outcome": 1, "symbol": "A"}])
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "r.json")
    rt = str(tmp_path / "r.txt")
    
    code = run_diagnosis(shadow_db=s_db, dhan_db=d_db, exports_dir=str(tmp_path), report_json_path=rj, report_txt_path=rt)
    assert code == 0
    assert os.path.exists(rj)
    assert os.path.exists(rt)
    
    with open(rj) as f:
        report = json.load(f)
    assert "overall" in report
    assert "by_date" in report
    assert "rank_diagnostics" in report
    assert "bucket_diagnostics" in report
    assert "regime_context" in report
    assert "high_confidence_failures" in report
    assert "repeat_symbol_offenders" in report
    assert "plain_english_diagnostic_notes" in report


def test_report_txt_written(tmp_path):
    s_db = make_shadow_db(tmp_path, [{"outcome": "LOSS", "days_to_outcome": 1, "symbol": "A"}])
    d_db = make_dhan_db(tmp_path, [], [])
    
    rj = str(tmp_path / "r.json")
    rt = str(tmp_path / "r.txt")
    
    run_diagnosis(shadow_db=s_db, dhan_db=d_db, exports_dir=str(tmp_path), report_json_path=rj, report_txt_path=rt)
    with open(rt) as f:
        content = f.read()
        
    assert "ENTRY FAILURE DIAGNOSIS REPORT" in content
    assert "1. OVERALL DAY-1 LOSS SUMMARY" in content
    assert "2. STOP MECHANISM CLASSIFICATION" in content
    assert "3. SCORED-DATE CONCENTRATION" in content
    assert "4. RANK AND PROBABILITY DIAGNOSTICS" in content
    assert "5. BUCKET DIAGNOSTICS" in content
    assert "6. WHAT-IF REGIME CONTEXT COMPARISON" in content
    assert "7. HIGH-CONFIDENCE DAY-1 FAILURES" in content
    assert "8. REPEAT SYMBOL OFFENDERS" in content
    assert "9. PLAIN-ENGLISH DIAGNOSTIC OBSERVATIONS" in content
