"""
test_hgb_regime_candidate.py

Unit tests for ML V1.22 HistGradientBoosting Shadow Candidate Build.
Uses isolated tmp_path fixtures.
No production DB/dataset CSV access.
"""
from __future__ import annotations

import json
import os
import sqlite3
import joblib
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from app.scripts.model_capacity_reality_check import generate_default_schema
from app.scripts.train_hgb_regime_candidate import run_train_hgb_candidate
from app.scripts.score_latest_hgb_regime import run_score_latest_hgb_regime
from app.scripts.track_shadow_hgb_shortlist import run_track_shadow_hgb_shortlist


def make_mock_dataset(path: str, schema: list[str], row_count: int = 100) -> pd.DataFrame:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    metadata_cols = ["symbol", "sample_date", "outcome"]
    all_cols = metadata_cols + schema
    
    dates = pd.date_range(start="2026-05-01", periods=row_count, freq="D")
    
    data = []
    for i in range(row_count):
        outcome_val = "WIN"
        if i % 3 == 1:
            outcome_val = "LOSS"
        elif i % 3 == 2:
            outcome_val = "TIMEOUT"
            
        # Add some AMBIGUOUS/INSUFFICIENT rows
        if i == 0:
            outcome_val = "AMBIGUOUS"
        elif i == 1:
            outcome_val = "INSUFFICIENT_FUTURE_DATA"
            
        row = {
            "symbol": f"SYM{i}",
            "sample_date": dates[i].strftime("%Y-%m-%d"),
            "outcome": outcome_val
        }
        for col in schema:
            # Add values != 0 to verify standard scaler check
            row[col] = float(50.0 + (i % 3) * 5.0)
        data.append(row)
        
    df = pd.DataFrame(data, columns=all_cols)
    df.to_csv(path, index=False)
    return df


def setup_env(tmp_path):
    schema_list = generate_default_schema()
    
    # Old LogisticRegression model dir (mocked)
    lr_model_dir = tmp_path / "models" / "stock_opportunity_ohlcv_regime_v1"
    os.makedirs(lr_model_dir, exist_ok=True)
    with open(lr_model_dir / "feature_schema.json", "w", encoding="utf-8") as f:
        json.dump(schema_list, f, indent=2)
        
    # Write a mock model and metadata for LR
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression()
    clf.fit([[0] * 308, [1] * 308], [0, 1])
    joblib.dump(clf, lr_model_dir / "model.joblib")
    with open(lr_model_dir / "model_metadata.json", "w", encoding="utf-8") as f:
        json.dump({"model_type": "LogisticRegression"}, f, indent=2)
        
    # Old LogisticRegression rankings files (mocked)
    exports_dir = tmp_path / "exports"
    os.makedirs(exports_dir, exist_ok=True)
    pd.DataFrame([{"symbol": "LR_SYM", "rank": 1, "win_probability": 0.5}]).to_csv(
        exports_dir / "latest_regime_rankings.csv", index=False
    )
    with open(exports_dir / "latest_regime_rankings.meta.json", "w", encoding="utf-8") as f:
        json.dump({"model_version": "stock_opportunity_ohlcv_regime_v1"}, f, indent=2)
        
    # Dataset CSV
    csv_path = exports_dir / "ml_dataset_ohlcv_regime_v1.csv"
    make_mock_dataset(str(csv_path), schema_list)
    
    # HGB model candidate output dir
    hgb_model_dir = tmp_path / "models" / "stock_opportunity_hgb_regime_v1"
    
    # Shadow tracking DB
    shadow_db = tmp_path / "shadow_tracking.sqlite3"
    
    return {
        "csv": str(csv_path),
        "lr_model_dir": str(lr_model_dir),
        "hgb_model_dir": str(hgb_model_dir),
        "exports_dir": str(exports_dir),
        "shadow_db": str(shadow_db)
    }


def test_hgb_training_uses_exactly_308_features(tmp_path):
    env = setup_env(tmp_path)
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    
    # Load HGB metadata and schema
    with open(os.path.join(env["hgb_model_dir"], "feature_schema.json"), "r") as f:
        schema = json.load(f)
    with open(os.path.join(env["hgb_model_dir"], "model_metadata.json"), "r") as f:
        meta = json.load(f)
        
    assert len(schema) == 308
    assert meta["feature_count"] == 308


def test_metadata_columns_are_excluded(tmp_path, monkeypatch):
    env = setup_env(tmp_path)
    
    from app.scripts.train_hgb_regime_candidate import encode_label
    # Verify no metadata columns are treated as features
    with open(os.path.join(env["lr_model_dir"], "feature_schema.json"), "r") as f:
        schema = json.load(f)
    assert "symbol" not in schema
    assert "sample_date" not in schema
    assert "outcome" not in schema


def test_feature_schema_order_is_preserved(tmp_path):
    env = setup_env(tmp_path)
    
    # Re-order the schema in LR dir
    schema_list = generate_default_schema()
    custom_order = list(reversed(schema_list))
    with open(os.path.join(env["lr_model_dir"], "feature_schema.json"), "w") as f:
        json.dump(custom_order, f, indent=2)
        
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    
    # Assert that HGB saved schema order matches reversed custom order
    with open(os.path.join(env["hgb_model_dir"], "feature_schema.json"), "r") as f:
        saved_schema = json.load(f)
    assert saved_schema == custom_order


def test_ambiguous_insufficient_rows_excluded(tmp_path, monkeypatch):
    env = setup_env(tmp_path)
    
    # Capture encoded label calls to assert AMBIGUOUS/INSUFFICIENT are skipped
    from app.scripts.train_hgb_regime_candidate import encode_label
    encoded_vals = []
    
    def mock_encode(val):
        encoded_vals.append(val)
        return encode_label(val)
        
    monkeypatch.setattr("app.scripts.train_hgb_regime_candidate.encode_label", mock_encode)
    
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    
    assert "WIN" in encoded_vals
    assert "LOSS" in encoded_vals
    assert "TIMEOUT" in encoded_vals
    assert "AMBIGUOUS" not in encoded_vals
    assert "INSUFFICIENT_FUTURE_DATA" not in encoded_vals


def test_model_metadata_written_to_separate_hgb_directory(tmp_path):
    env = setup_env(tmp_path)
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    
    # HGB metadata path exists
    assert os.path.exists(os.path.join(env["hgb_model_dir"], "model_metadata.json"))


def test_old_logistic_regression_model_directory_not_touched(tmp_path):
    env = setup_env(tmp_path)
    
    # Capture initial metadata state and schema modification time
    with open(os.path.join(env["lr_model_dir"], "model_metadata.json"), "r") as f:
        initial_meta = json.load(f)
        
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    
    # Verify LR metadata remains exactly the same
    with open(os.path.join(env["lr_model_dir"], "model_metadata.json"), "r") as f:
        current_meta = json.load(f)
        
    assert current_meta == initial_meta


def test_scoring_writes_separate_hgb_rankings_file(tmp_path):
    env = setup_env(tmp_path)
    
    # Train first
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    
    # Score
    run_score_latest_hgb_regime(
        input_csv_path=env["csv"],
        model_dir=env["hgb_model_dir"],
        output_dir=env["exports_dir"]
    )
    
    # Assert rankings file exist
    assert os.path.exists(os.path.join(env["exports_dir"], "latest_hgb_regime_rankings.csv"))
    assert os.path.exists(os.path.join(env["exports_dir"], "latest_hgb_regime_rankings.meta.json"))


def test_scoring_does_not_overwrite_logistic_regression_rankings(tmp_path):
    env = setup_env(tmp_path)
    
    # Train and Score HGB
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    
    # Read LR rankings before HGB scoring
    lr_rankings_before = pd.read_csv(os.path.join(env["exports_dir"], "latest_regime_rankings.csv"))
    
    run_score_latest_hgb_regime(
        input_csv_path=env["csv"],
        model_dir=env["hgb_model_dir"],
        output_dir=env["exports_dir"]
    )
    
    # Assert LR rankings still match
    lr_rankings_after = pd.read_csv(os.path.join(env["exports_dir"], "latest_regime_rankings.csv"))
    pd.testing.assert_frame_equal(lr_rankings_before, lr_rankings_after)


def test_prediction_reproduction_works_from_hgb_artifact_and_rankings(tmp_path):
    env = setup_env(tmp_path)
    
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    
    run_score_latest_hgb_regime(
        input_csv_path=env["csv"],
        model_dir=env["hgb_model_dir"],
        output_dir=env["exports_dir"]
    )
    
    # Load HGB model and schema
    clf = joblib.load(os.path.join(env["hgb_model_dir"], "model.joblib"))
    with open(os.path.join(env["hgb_model_dir"], "feature_schema.json"), "r") as f:
        schema = json.load(f)
        
    # Read top HGB ranking row
    rankings_df = pd.read_csv(os.path.join(env["exports_dir"], "latest_hgb_regime_rankings.csv"))
    top_row = rankings_df.iloc[0]
    symbol = top_row["symbol"]
    sample_date = top_row["sample_date"]
    rankings_prob = float(top_row["win_probability"])
    
    # Find matching row in dataset
    dataset_df = pd.read_csv(env["csv"])
    matched = dataset_df[(dataset_df["symbol"] == symbol) & (dataset_df["sample_date"] == sample_date)].iloc[0]
    
    # Extract features in schema order
    features_values = [float(matched[col]) for col in schema]
    X_input = pd.DataFrame([features_values], columns=schema)
    
    # Run prediction
    computed_prob = float(clf.predict_proba(X_input)[0][1])
    
    # Assert difference is within 1e-9 tolerance
    assert abs(computed_prob - rankings_prob) <= 1e-9


def test_hgb_shadow_records_use_separate_model_version_and_coexist(tmp_path):
    env = setup_env(tmp_path)
    
    # Train, score, and track HGB
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    run_score_latest_hgb_regime(
        input_csv_path=env["csv"],
        model_dir=env["hgb_model_dir"],
        output_dir=env["exports_dir"]
    )
    
    # Add dummy observing record for LR in db
    conn = sqlite3.connect(env["shadow_db"])
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shadow_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_scored TEXT, scored_sample_date TEXT, model_version TEXT, model_commit TEXT,
            rank INTEGER, bucket TEXT, symbol TEXT, win_probability REAL, regime_context_json TEXT,
            tracking_status TEXT, future_observed_outcome TEXT, created_at TEXT, updated_at TEXT, notes TEXT,
            UNIQUE(model_version, scored_sample_date, symbol)
        )
    ''')
    cursor.execute('''
        INSERT INTO shadow_tracking (scored_sample_date, model_version, model_commit, rank, bucket, symbol, win_probability, regime_context_json, tracking_status, created_at, updated_at)
        VALUES ("2026-05-10", "stock_opportunity_ohlcv_regime_v1", "head", 1, "PRIMARY_TOP_1", "SYM5", 0.6, "{}", "OBSERVING", "now", "now")
    ''')
    conn.commit()
    conn.close()
    
    run_track_shadow_hgb_shortlist(
        exports_dir=env["exports_dir"],
        db_path=env["shadow_db"]
    )
    
    # Read all shadow records
    conn = sqlite3.connect(env["shadow_db"])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    rows = [dict(r) for r in cursor.execute("SELECT * FROM shadow_tracking").fetchall()]
    conn.close()
    
    # Verify that HGB model records were added and co-exist safely alongside the LR record
    hgb_records = [r for r in rows if r["model_version"] == "stock_opportunity_hgb_regime_v1"]
    lr_records = [r for r in rows if r["model_version"] == "stock_opportunity_ohlcv_regime_v1"]
    
    assert len(lr_records) == 1
    assert len(hgb_records) > 0
    assert lr_records[0]["symbol"] == "SYM5"


def test_no_production_artifact_is_mutated(tmp_path):
    env = setup_env(tmp_path)
    
    # Capture initial file modified times
    lr_model_time = os.path.getmtime(os.path.join(env["lr_model_dir"], "model.joblib"))
    lr_schema_time = os.path.getmtime(os.path.join(env["lr_model_dir"], "feature_schema.json"))
    lr_metadata_time = os.path.getmtime(os.path.join(env["lr_model_dir"], "model_metadata.json"))
    lr_rankings_time = os.path.getmtime(os.path.join(env["exports_dir"], "latest_regime_rankings.csv"))
    
    # Run full HGB pipeline
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    run_score_latest_hgb_regime(
        input_csv_path=env["csv"],
        model_dir=env["hgb_model_dir"],
        output_dir=env["exports_dir"]
    )
    
    # Assert unmodified times
    assert os.path.getmtime(os.path.join(env["lr_model_dir"], "model.joblib")) == lr_model_time
    assert os.path.getmtime(os.path.join(env["lr_model_dir"], "feature_schema.json")) == lr_schema_time
    assert os.path.getmtime(os.path.join(env["lr_model_dir"], "model_metadata.json")) == lr_metadata_time
    assert os.path.getmtime(os.path.join(env["exports_dir"], "latest_regime_rankings.csv")) == lr_rankings_time


def test_metadata_files_contain_diagnostic_warning(tmp_path):
    env = setup_env(tmp_path)
    
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    run_score_latest_hgb_regime(
        input_csv_path=env["csv"],
        model_dir=env["hgb_model_dir"],
        output_dir=env["exports_dir"]
    )
    
    # Load HGB model metadata and rankings metadata
    with open(os.path.join(env["hgb_model_dir"], "model_metadata.json"), "r") as f:
        model_meta = json.load(f)
    with open(os.path.join(env["exports_dir"], "latest_hgb_regime_rankings.meta.json"), "r") as f:
        rankings_meta = json.load(f)
        
    warning_str = "candidate only, not deployed for live trading"
    assert model_meta["warning"] == warning_str
    assert rankings_meta["warning"] == warning_str


def test_tree_models_are_not_scaled_or_wrapped(tmp_path, monkeypatch):
    """Verify HGBClassifier fits directly on raw (unscaled) features."""
    env = setup_env(tmp_path)
    
    from sklearn.ensemble import HistGradientBoostingClassifier
    original_fit = HistGradientBoostingClassifier.fit
    
    hgb_fit_X_stats = []
    
    def mock_fit(self, X, y):
        # Captures statistics of X to prove it was not standardized (mean=0, std=1)
        # In mock data, feature values are shifted to 50.0+.
        hgb_fit_X_stats.append((float(X.mean().mean()), float(X.std().mean())))
        return original_fit(self, X, y)
        
    monkeypatch.setattr(HistGradientBoostingClassifier, "fit", mock_fit)
    
    run_train_hgb_candidate(
        input_csv_path=env["csv"],
        old_schema_path=env["lr_model_dir"] + "/feature_schema.json",
        output_dir=env["hgb_model_dir"]
    )
    
    assert len(hgb_fit_X_stats) > 0
    # StandardScaler standardized mean is 0. Raw mean is > 40.
    for mean_val, std_val in hgb_fit_X_stats:
        assert mean_val > 40.0
