"""
test_audit_ml_data_integrity.py

Tests for ML V1.16 Data Integrity Audit Layer.

All tests use in-memory or tmp_path SQLite databases.
No test touches /app/data/dhan_auth.sqlite3 or any production path.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import math
import pytest

from app.ml_data_integrity import (
    CheckResult,
    check_testsym_contamination,
    check_ml_samples_duplicates,
    check_ml_sample_validity,
    check_feature_json_validity,
    check_candle_linkage,
    check_export_artifacts,
    check_ranking_artifacts,
    check_shadow_tracking,
    run_all_checks,
    EXPECTED_BASE_CSV_COLUMNS,
    EXPECTED_REGIME_CSV_COLUMNS,
)
from app.scripts.audit_ml_data_integrity import run_audit


# ---------------------------------------------------------------------------
# Feature JSON builders — nested candle format (matching the real DB schema)
# ---------------------------------------------------------------------------

def make_candle(open_rel=0.01, high_rel=0.02, low_rel=-0.01, close_rel=0.015,
                volume_rel=0.005, trading_date="2026-01-01") -> dict:
    return {
        "open_rel": open_rel,
        "high_rel": high_rel,
        "low_rel": low_rel,
        "close_rel": close_rel,
        "volume_rel": volume_rel,
        "trading_date": trading_date,
    }


def make_valid_feature_json(symbol="REALSYM", instrument_id=1,
                             sample_date="2026-03-01") -> str:
    """Build a valid nested feature_json matching real DB schema."""
    candles = [make_candle(trading_date=f"2026-{(i // 30 + 1):02d}-{(i % 28 + 1):02d}")
               for i in range(60)]
    feature = {
        "candles": candles,
        "symbol": symbol,
        "sample_date": sample_date,
        "instrument_id": instrument_id,
        "input_window_sessions": 60,
        "future_window_sessions": 20,
        "target_percent": 7.0,
        "stop_percent": 3.0,
        "entry_close": 1234.5,
    }
    return json.dumps(feature)


# ---------------------------------------------------------------------------
# Helpers for building minimal test databases
# ---------------------------------------------------------------------------

def make_main_db(tmp_path, symbol="REALSYM", outcome="WIN", trainable=1,
                 feature_override=None, inject_testsym=False) -> str:
    """Create a minimal main DB with one instrument, candle, and ml_sample."""
    db_path = str(tmp_path / "test_main.sqlite3")
    conn = sqlite3.connect(db_path)

    conn.executescript("""
        CREATE TABLE instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            underlying_symbol TEXT NOT NULL,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE daily_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_id INTEGER,
            trading_date TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER
        );
        CREATE TABLE ml_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            label_name TEXT NOT NULL,
            instrument_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            sample_date TEXT NOT NULL,
            outcome TEXT NOT NULL,
            trainable INTEGER NOT NULL DEFAULT 0,
            exclude_reason TEXT NOT NULL DEFAULT '',
            feature_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT '2026-01-01',
            updated_at TEXT NOT NULL DEFAULT '2026-01-01'
        );
    """)

    # Insert real instrument + candle + sample
    conn.execute("INSERT INTO instruments (id, underlying_symbol) VALUES (1, ?)", (symbol,))
    conn.execute(
        "INSERT INTO daily_candles (instrument_id, trading_date, open, high, low, close, volume)"
        " VALUES (1, '2026-03-01', 100, 105, 95, 102, 1000)"
    )

    feature_str = feature_override if feature_override is not None else make_valid_feature_json(symbol)
    conn.execute(
        "INSERT INTO ml_samples (model_name, label_name, instrument_id, symbol, sample_date,"
        " outcome, trainable, feature_json)"
        " VALUES ('stock_opportunity_ohlcv_v1','hit_7pct',1,?,'2026-03-01',?,?,?)",
        (symbol, outcome, trainable, feature_str)
    )

    if inject_testsym:
        conn.execute("INSERT INTO instruments (id, underlying_symbol) VALUES (99, 'TESTSYM')")
        conn.execute(
            "INSERT INTO daily_candles (instrument_id, trading_date, open, high, low, close, volume)"
            " VALUES (99, '2026-03-01', 10, 11, 9, 10, 500)"
        )
        conn.execute(
            "INSERT INTO ml_samples (model_name, label_name, instrument_id, symbol, sample_date,"
            " outcome, trainable, feature_json)"
            " VALUES ('stock_opportunity_ohlcv_v1','hit_7pct',99,'TESTSYM','2026-03-01','WIN',1,'{}')"
        )

    conn.commit()
    conn.close()
    return db_path


def make_shadow_db(tmp_path, inject_bad=False) -> str:
    """Create a minimal shadow DB."""
    db_path = str(tmp_path / "test_shadow.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE shadow_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_scored TEXT,
            scored_sample_date TEXT NOT NULL,
            model_version TEXT NOT NULL,
            model_commit TEXT,
            rank INTEGER NOT NULL,
            bucket TEXT NOT NULL,
            symbol TEXT NOT NULL,
            win_probability REAL NOT NULL,
            regime_context_json TEXT,
            tracking_status TEXT NOT NULL,
            future_observed_outcome TEXT,
            created_at TEXT NOT NULL DEFAULT '2026-01-01',
            updated_at TEXT NOT NULL DEFAULT '2026-01-01',
            UNIQUE(model_version, scored_sample_date, symbol)
        );
    """)
    conn.execute(
        "INSERT INTO shadow_tracking (scored_sample_date, model_version, model_commit, rank,"
        " bucket, symbol, win_probability, tracking_status)"
        " VALUES ('2026-03-01','stock_opportunity_ohlcv_regime_v1','abc123',1,"
        " 'PRIMARY_TOP_1','REALSYM',0.55,'OBSERVING')"
    )
    if inject_bad:
        # Invalid bucket and status
        conn.execute(
            "INSERT INTO shadow_tracking (scored_sample_date, model_version, model_commit, rank,"
            " bucket, symbol, win_probability, tracking_status)"
            " VALUES ('2026-03-01','stock_opportunity_ohlcv_regime_v1','abc123',2,"
            " 'INVALID_BUCKET','BADSYM',0.3,'INVALID_STATUS')"
        )
    conn.commit()
    conn.close()
    return db_path


def make_exports_dir(tmp_path, base_cols=EXPECTED_BASE_CSV_COLUMNS,
                     regime_cols=EXPECTED_REGIME_CSV_COLUMNS,
                     ranking_count=5, include_meta=True) -> str:
    """Create minimal export artifacts in a temp directory."""
    exp_dir = str(tmp_path / "exports")
    os.makedirs(exp_dir, exist_ok=True)

    # Base CSV
    base_header = ["symbol", "sample_date", "outcome"] + [f"c{i:02d}_close_rel" for i in range(base_cols - 3)]
    with open(os.path.join(exp_dir, "ml_dataset_ohlcv_v1.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(base_header)
        writer.writerow(["REALSYM", "2026-03-01", "WIN"] + [0.01] * (base_cols - 3))

    # Regime CSV
    regime_header = ["symbol", "sample_date", "outcome"] + [f"feat_{i}" for i in range(regime_cols - 3)]
    with open(os.path.join(exp_dir, "ml_dataset_ohlcv_regime_v1.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(regime_header)
        writer.writerow(["REALSYM", "2026-03-01", "WIN"] + [0.01] * (regime_cols - 3))

    # Regime meta
    regime_meta = {
        "technical_feature_count": 300,
        "regime_feature_count": 8,
        "total_feature_count": 308,
        "duplicate_count": 0,
        "null_count": 0,
    }
    with open(os.path.join(exp_dir, "ml_dataset_ohlcv_regime_v1.meta.json"), "w") as f:
        json.dump(regime_meta, f)

    # Ranking CSV
    ranking_header = ["rank", "symbol", "win_probability", "sample_date"]
    rows = [[i + 1, f"SYM{i}", 0.5 - i * 0.01, "2026-03-01"] for i in range(ranking_count)]
    with open(os.path.join(exp_dir, "latest_regime_rankings.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(ranking_header)
        writer.writerows(rows)

    # Ranking meta
    if include_meta:
        meta = {
            "scored_sample_date": "2026-03-01",
            "ranking_count": ranking_count,
            "model_version": "stock_opportunity_ohlcv_regime_v1",
        }
        with open(os.path.join(exp_dir, "latest_regime_rankings.meta.json"), "w") as f:
            json.dump(meta, f)

    # Shadow performance summary (just needs to exist)
    with open(os.path.join(exp_dir, "shadow_performance_summary.json"), "w") as f:
        json.dump({"overall": {}}, f)

    return exp_dir


# ---------------------------------------------------------------------------
# Check 1: TESTSYM contamination
# ---------------------------------------------------------------------------

def test_testsym_check_passes_clean_db(tmp_path):
    db = make_main_db(tmp_path)
    result = check_testsym_contamination(db)
    assert result.status == "PASS"
    assert not result.errors


def test_testsym_check_fails_when_contaminated(tmp_path):
    db = make_main_db(tmp_path, inject_testsym=True)
    result = check_testsym_contamination(db)
    assert result.status == "FAIL"
    assert any("TESTSYM" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Check 2: Duplicate samples
# ---------------------------------------------------------------------------

def test_duplicates_check_passes_clean(tmp_path):
    db = make_main_db(tmp_path)
    result = check_ml_samples_duplicates(db)
    assert result.status == "PASS"


def test_duplicates_check_fails_with_duplicate(tmp_path):
    db = make_main_db(tmp_path)
    conn = sqlite3.connect(db)
    # Insert a second row with same model_name, label_name, instrument_id, sample_date
    conn.execute(
        "INSERT INTO ml_samples (model_name, label_name, instrument_id, symbol, sample_date,"
        " outcome, trainable, feature_json)"
        " VALUES ('stock_opportunity_ohlcv_v1','hit_7pct',1,'REALSYM','2026-03-01','LOSS',1,'{}')"
    )
    conn.commit()
    conn.close()
    result = check_ml_samples_duplicates(db)
    assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# Check 3: Sample field validity
# ---------------------------------------------------------------------------

def test_sample_validity_passes_good_row(tmp_path):
    db = make_main_db(tmp_path, outcome="WIN", trainable=1)
    result = check_ml_sample_validity(db)
    assert result.status == "PASS"


def test_sample_validity_fails_invalid_outcome(tmp_path):
    db = make_main_db(tmp_path, outcome="UNKNOWN_OUTCOME", trainable=1)
    result = check_ml_sample_validity(db)
    assert result.status == "FAIL"
    assert any("invalid outcome" in e for e in result.errors)


def test_sample_validity_fails_trainable_mismatch(tmp_path):
    # WIN should be trainable=1, but we set trainable=0
    db = make_main_db(tmp_path, outcome="WIN", trainable=0)
    result = check_ml_sample_validity(db)
    assert result.status == "FAIL"
    assert any("trainable" in e for e in result.errors)


def test_sample_validity_passes_insufficient_future(tmp_path):
    # INSUFFICIENT_FUTURE_DATA => trainable=0
    db = make_main_db(tmp_path, outcome="INSUFFICIENT_FUTURE_DATA", trainable=0)
    result = check_ml_sample_validity(db)
    assert result.status == "PASS"


# ---------------------------------------------------------------------------
# Check 4: Feature JSON validity (nested candle format)
# ---------------------------------------------------------------------------

def test_feature_json_passes_valid_nested_format(tmp_path):
    """Valid nested feature_json with 60 candles x 5 fields must PASS."""
    db = make_main_db(tmp_path, outcome="WIN", trainable=1)
    result = check_feature_json_validity(db)
    assert result.status == "PASS", f"Expected PASS but got errors: {result.errors}"


def test_feature_json_fails_wrong_candle_count(tmp_path):
    """candles array with != 60 entries must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["candles"] = feature["candles"][:30]  # only 30 candles
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("candles length" in e for e in result.errors)


def test_feature_json_fails_missing_candle_field(tmp_path):
    """Candle missing open_rel must FAIL."""
    feature = json.loads(make_valid_feature_json())
    del feature["candles"][0]["open_rel"]
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("missing numeric field" in e for e in result.errors)


def test_feature_json_fails_null_candle_value(tmp_path):
    """Null in a numeric candle field must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["candles"][5]["close_rel"] = None
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("null value" in e for e in result.errors)


def test_feature_json_fails_nan_candle_value(tmp_path):
    """NaN in a numeric candle field must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["candles"][0]["volume_rel"] = float("nan")
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("NaN/Inf" in e for e in result.errors)


def test_feature_json_fails_inf_candle_value(tmp_path):
    """Inf in a numeric candle field must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["candles"][10]["high_rel"] = float("inf")
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("NaN/Inf" in e for e in result.errors)


def test_feature_json_fails_forbidden_key_in_candle(tmp_path):
    """Forbidden key (e.g. RSI) in candle dict must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["candles"][0]["RSI_14"] = 50.0
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("forbidden" in e for e in result.errors)


def test_feature_json_fails_wrong_input_window_sessions(tmp_path):
    """input_window_sessions != 60 must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["input_window_sessions"] = 30
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("metadata" in e for e in result.errors)


def test_feature_json_fails_wrong_future_window_sessions(tmp_path):
    """future_window_sessions != 20 must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["future_window_sessions"] = 10
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("metadata" in e for e in result.errors)


def test_feature_json_fails_wrong_target_percent(tmp_path):
    """target_percent != 7.0 must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["target_percent"] = 5.0
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("metadata" in e for e in result.errors)


def test_feature_json_fails_wrong_stop_percent(tmp_path):
    """stop_percent != 3.0 must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["stop_percent"] = 5.0
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("metadata" in e for e in result.errors)


def test_feature_json_fails_entry_close_zero(tmp_path):
    """entry_close <= 0 must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["entry_close"] = 0
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("metadata" in e for e in result.errors)


def test_feature_json_fails_entry_close_negative(tmp_path):
    """entry_close < 0 must FAIL."""
    feature = json.loads(make_valid_feature_json())
    feature["entry_close"] = -100.0
    db = make_main_db(tmp_path, outcome="WIN", trainable=1, feature_override=json.dumps(feature))
    result = check_feature_json_validity(db)
    assert result.status == "FAIL"
    assert any("metadata" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Check 5: Candle linkage
# ---------------------------------------------------------------------------

def test_candle_linkage_passes_clean(tmp_path):
    db = make_main_db(tmp_path)
    result = check_candle_linkage(db)
    assert result.status == "PASS"


def test_candle_linkage_fails_orphaned_instrument(tmp_path):
    db = make_main_db(tmp_path)
    conn = sqlite3.connect(db)
    # Insert sample with a non-existent instrument_id
    conn.execute(
        "INSERT INTO ml_samples (model_name, label_name, instrument_id, symbol, sample_date,"
        " outcome, trainable, feature_json)"
        " VALUES ('stock_opportunity_ohlcv_v1','hit_7pct',999,'ORPHAN','2026-03-01','WIN',1,'{}')"
    )
    conn.commit()
    conn.close()
    result = check_candle_linkage(db)
    assert result.status == "FAIL"
    assert any("instrument_id" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Check 6: Export artifacts
# ---------------------------------------------------------------------------

def test_export_artifacts_passes_clean(tmp_path):
    exp_dir = make_exports_dir(tmp_path)
    result = check_export_artifacts(exp_dir)
    assert result.status == "PASS"


def test_export_artifacts_fails_missing_file(tmp_path):
    exp_dir = make_exports_dir(tmp_path)
    os.remove(os.path.join(exp_dir, "shadow_performance_summary.json"))
    result = check_export_artifacts(exp_dir)
    assert result.status == "FAIL"
    assert any("shadow_performance_summary.json" in e for e in result.errors)


def test_export_artifacts_fails_wrong_column_count(tmp_path):
    exp_dir = make_exports_dir(tmp_path, base_cols=200)  # wrong
    result = check_export_artifacts(exp_dir)
    assert result.status == "FAIL"
    assert any("columns" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Check 7: Ranking artifacts
# ---------------------------------------------------------------------------

def test_ranking_artifacts_passes_clean(tmp_path):
    exp_dir = make_exports_dir(tmp_path, ranking_count=5)
    result = check_ranking_artifacts(exp_dir)
    assert result.status == "PASS"


def test_ranking_artifacts_fails_missing_meta(tmp_path):
    exp_dir = make_exports_dir(tmp_path, include_meta=False)
    result = check_ranking_artifacts(exp_dir)
    assert result.status == "FAIL"


def test_ranking_artifacts_fails_count_mismatch(tmp_path):
    exp_dir = make_exports_dir(tmp_path, ranking_count=5)
    # Overwrite meta with wrong count
    meta = {"scored_sample_date": "2026-03-01", "ranking_count": 99}
    with open(os.path.join(exp_dir, "latest_regime_rankings.meta.json"), "w") as f:
        json.dump(meta, f)
    result = check_ranking_artifacts(exp_dir)
    assert result.status == "FAIL"
    assert any("data rows" in e for e in result.errors)


def test_ranking_artifacts_fails_duplicate_symbols(tmp_path):
    exp_dir = make_exports_dir(tmp_path, ranking_count=3)
    # Overwrite ranking CSV with duplicate symbol
    ranking_header = ["rank", "symbol", "win_probability", "sample_date"]
    with open(os.path.join(exp_dir, "latest_regime_rankings.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(ranking_header)
        writer.writerow([1, "DUPSYM", 0.55, "2026-03-01"])
        writer.writerow([2, "DUPSYM", 0.50, "2026-03-01"])  # duplicate
        writer.writerow([3, "UNIQSYM", 0.45, "2026-03-01"])
    result = check_ranking_artifacts(exp_dir)
    assert result.status == "FAIL"
    assert any("Duplicate symbol" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Check 8: Shadow tracking
# ---------------------------------------------------------------------------

def test_shadow_tracking_passes_clean(tmp_path):
    db = make_shadow_db(tmp_path)
    result = check_shadow_tracking(db)
    assert result.status == "PASS"


def test_shadow_tracking_fails_missing_db(tmp_path):
    result = check_shadow_tracking(str(tmp_path / "nonexistent.sqlite3"))
    assert result.status == "FAIL"
    assert any("Not found" in e for e in result.errors)


def test_shadow_tracking_fails_invalid_bucket_status(tmp_path):
    db = make_shadow_db(tmp_path, inject_bad=True)
    result = check_shadow_tracking(db)
    assert result.status == "FAIL"
    assert any("bucket" in e or "tracking_status" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Integration: run_all_checks
# ---------------------------------------------------------------------------

def test_run_all_checks_passes_clean(tmp_path):
    main_db = make_main_db(tmp_path)
    shadow_db = make_shadow_db(tmp_path)
    exp_dir = make_exports_dir(tmp_path)
    overall, checks = run_all_checks(main_db=main_db, shadow_db=shadow_db, exports_dir=exp_dir)
    assert overall == "PASS"
    for chk in checks:
        assert chk.status == "PASS", f"Expected PASS on {chk.name}, got FAIL: {chk.errors}"


def test_run_all_checks_fails_on_contamination(tmp_path):
    main_db = make_main_db(tmp_path, inject_testsym=True)
    shadow_db = make_shadow_db(tmp_path)
    exp_dir = make_exports_dir(tmp_path)
    overall, checks = run_all_checks(main_db=main_db, shadow_db=shadow_db, exports_dir=exp_dir)
    assert overall == "FAIL"
    contamination = next(c for c in checks if c.name == "testsym_contamination")
    assert contamination.status == "FAIL"


# ---------------------------------------------------------------------------
# Integration: run_audit (full script entry point)
# ---------------------------------------------------------------------------

def test_run_audit_exits_0_on_clean(tmp_path):
    main_db = make_main_db(tmp_path)
    shadow_db = make_shadow_db(tmp_path)
    exp_dir = make_exports_dir(tmp_path)
    report_json = str(tmp_path / "report.json")
    report_txt = str(tmp_path / "report.txt")

    code = run_audit(
        main_db=main_db,
        shadow_db=shadow_db,
        exports_dir=exp_dir,
        report_json_path=report_json,
        report_txt_path=report_txt,
        feature_sample_limit=100,
    )
    assert code == 0
    assert os.path.exists(report_json)
    assert os.path.exists(report_txt)

    with open(report_json) as f:
        report = json.load(f)
    assert report["overall_status"] == "PASS"
    assert "generated_at" in report
    assert len(report["checks"]) == 8


def test_run_audit_exits_1_on_failure(tmp_path):
    main_db = make_main_db(tmp_path, inject_testsym=True)
    shadow_db = make_shadow_db(tmp_path)
    exp_dir = make_exports_dir(tmp_path)
    report_json = str(tmp_path / "report.json")
    report_txt = str(tmp_path / "report.txt")

    code = run_audit(
        main_db=main_db,
        shadow_db=shadow_db,
        exports_dir=exp_dir,
        report_json_path=report_json,
        report_txt_path=report_txt,
        feature_sample_limit=100,
    )
    assert code == 1

    with open(report_json) as f:
        report = json.load(f)
    assert report["overall_status"] == "FAIL"
