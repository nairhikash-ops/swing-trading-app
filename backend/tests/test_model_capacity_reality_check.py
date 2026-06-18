"""
test_model_capacity_reality_check.py

Unit tests for ML V1.21 Model Capacity Reality Check.
Uses isolated tmp_path fixtures.
No production DB/dataset CSV access.
"""
from __future__ import annotations

import json
import os
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from app.scripts.model_capacity_reality_check import run_model_comparison, generate_default_schema


def make_mock_csv(path: str, schema: list[str], row_count: int = 1000) -> pd.DataFrame:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    metadata_cols = ["symbol", "sample_date", "outcome"]
    all_cols = metadata_cols + schema
    
    # Generate dates spanning ~2.7 years to satisfy the expanding 2-year min lookback
    dates = pd.date_range(start="2021-01-01", periods=row_count, freq="D")
    
    data = []
    for i in range(row_count):
        outcome_val = "WIN"
        if i % 3 == 1:
            outcome_val = "LOSS"
        elif i % 3 == 2:
            outcome_val = "TIMEOUT"
            
        # Add some AMBIGUOUS/INSUFFICIENT rows to test exclusions
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
            # Shift features away from mean=0, std=1 to verify scaling vs raw features
            row[col] = float(100.0 + (i % 5) * 10.0)
        data.append(row)
        
    df = pd.DataFrame(data, columns=all_cols)
    df.to_csv(path, index=False)
    return df


def setup_env(tmp_path, row_count: int = 1000):
    schema_list = generate_default_schema()
    csv_path = tmp_path / "ml_dataset_ohlcv_regime_v1.csv"
    schema_path = tmp_path / "feature_schema.json"
    report_json = tmp_path / "model_capacity_reality_check.json"
    report_txt = tmp_path / "model_capacity_reality_check.txt"
    
    make_mock_csv(str(csv_path), schema_list, row_count=row_count)
    
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema_list, f, indent=2)
        
    return {
        "csv": str(csv_path),
        "schema": str(schema_path),
        "report_json": str(report_json),
        "report_txt": str(report_txt)
    }


def test_small_fake_dataset_works(tmp_path):
    env = setup_env(tmp_path, row_count=1000)
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0
    assert os.path.exists(env["report_json"])
    assert os.path.exists(env["report_txt"])


def test_metadata_columns_are_excluded_from_features(tmp_path, monkeypatch):
    env = setup_env(tmp_path, row_count=1000)
    
    # Intercept feature loading and assert no metadata columns exist
    from app.scripts.model_capacity_reality_check import load_feature_schema
    original_load = load_feature_schema
    
    def mock_load(path):
        schema = original_load(path)
        assert "symbol" not in schema
        assert "sample_date" not in schema
        assert "outcome" not in schema
        return schema
        
    monkeypatch.setattr("app.scripts.model_capacity_reality_check.load_feature_schema", mock_load)
    
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0


def test_feature_columns_enforced_in_exact_schema_order(tmp_path, monkeypatch):
    env = setup_env(tmp_path, row_count=1000)
    
    # We alter the schema file to reverse feature order
    schema_list = generate_default_schema()
    reversed_schema = list(reversed(schema_list))
    
    with open(env["schema"], "w", encoding="utf-8") as f:
        json.dump(reversed_schema, f, indent=2)
        
    # Capture inputs passed to fit to verify ordering matchesreversed schema
    from sklearn.ensemble import HistGradientBoostingClassifier
    original_fit = HistGradientBoostingClassifier.fit
    
    called_with_reversed_cols = []
    
    def mock_fit(self, X, y):
        # Check if column order in DataFrame X matches reversed_schema
        if list(X.columns) == reversed_schema:
            called_with_reversed_cols.append(True)
        return original_fit(self, X, y)
        
    monkeypatch.setattr(HistGradientBoostingClassifier, "fit", mock_fit)
    
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0
    assert len(called_with_reversed_cols) > 0


def test_win_loss_timeout_labels_mapped_correctly(tmp_path, monkeypatch):
    env = setup_env(tmp_path, row_count=1000)
    
    # Mock encoding check
    from app.scripts.model_capacity_reality_check import encode_label
    encoded_vals = []
    
    def mock_encode(val):
        res = encode_label(val)
        encoded_vals.append((val, res))
        return res
        
    monkeypatch.setattr("app.scripts.model_capacity_reality_check.encode_label", mock_encode)
    
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0
    
    # WIN -> 1, LOSS -> 0, TIMEOUT -> 0
    assert ("WIN", 1) in encoded_vals
    assert ("LOSS", 0) in encoded_vals
    assert ("TIMEOUT", 0) in encoded_vals


def test_ambiguous_insufficient_rows_excluded(tmp_path, monkeypatch):
    env = setup_env(tmp_path, row_count=1000)
    
    from app.scripts.model_capacity_reality_check import encode_label
    called_with_ambiguous = []
    
    def mock_encode(val):
        if val in ("AMBIGUOUS", "INSUFFICIENT_FUTURE_DATA"):
            called_with_ambiguous.append(val)
        return encode_label(val)
        
    monkeypatch.setattr("app.scripts.model_capacity_reality_check.encode_label", mock_encode)
    
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0
    # Verify these values were never processed by encode_label (because they were excluded)
    assert len(called_with_ambiguous) == 0


def test_top_percentile_metrics_and_expectancy_math(tmp_path):
    env = setup_env(tmp_path, row_count=1000)
    
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0
    
    with open(env["report_json"], "r") as f:
        data = json.load(f)
        
    # Check that expectancy math values are computed and present
    lr_stats = data["model_statistics"]["LogisticRegression"]
    assert "avg_top_1_expectancy" in lr_stats
    assert len(lr_stats["top_1_expectancies"]) > 0
    
    # Payoff formula check: (win_rate * 7.0) - (loss_rate * 3.0)
    # Since our mock repeats outcome cyclically, check that values are bounds-valid
    for exp in lr_stats["top_1_expectancies"]:
        assert -3.0 <= exp <= 7.0


def test_chronological_split_is_not_shuffled(tmp_path, monkeypatch):
    env = setup_env(tmp_path, row_count=1000)
    
    from sklearn.ensemble import HistGradientBoostingClassifier
    original_fit = HistGradientBoostingClassifier.fit
    
    fit_dates = []
    
    def mock_fit(self, X, y):
        # Capture the sample index or verify chronological sorting
        # X is DataFrame from test setup, we check if indices are sorted
        assert list(X.index) == sorted(list(X.index))
        fit_dates.append(True)
        return original_fit(self, X, y)
        
    monkeypatch.setattr(HistGradientBoostingClassifier, "fit", mock_fit)
    
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0
    assert len(fit_dates) > 0


def test_scaler_is_not_applied_incorrectly_to_tree_models(tmp_path, monkeypatch):
    """Verify tree models are NOT wrapped in StandardScaler / fitted with scaled features."""
    env = setup_env(tmp_path, row_count=1000)
    
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    
    hgb_fit_X_stats = []
    rf_fit_X_stats = []
    
    original_hgb_fit = HistGradientBoostingClassifier.fit
    original_rf_fit = RandomForestClassifier.fit
    
    def mock_hgb_fit(self, X, y):
        # In mock data, feature values are shifted to 100.0+.
        # Standardized features would have mean close to 0 and std close to 1.
        # We assert that the features passed to HGBClassifier fit are raw (mean > 50).
        hgb_fit_X_stats.append((float(X.mean().mean()), float(X.std().mean())))
        return original_hgb_fit(self, X, y)
        
    def mock_rf_fit(self, X, y):
        rf_fit_X_stats.append((float(X.mean().mean()), float(X.std().mean())))
        return original_rf_fit(self, X, y)
        
    monkeypatch.setattr(HistGradientBoostingClassifier, "fit", mock_hgb_fit)
    monkeypatch.setattr(RandomForestClassifier, "fit", mock_rf_fit)
    
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0
    assert len(hgb_fit_X_stats) > 0
    assert len(rf_fit_X_stats) > 0
    
    # Assert features are raw (mean around ~120, definitely not scaled to mean=0)
    for mean_val, std_val in hgb_fit_X_stats:
        assert mean_val > 50.0
    for mean_val, std_val in rf_fit_X_stats:
        assert mean_val > 50.0


def test_model_comparison_report_files_written(tmp_path):
    env = setup_env(tmp_path, row_count=1000)
    run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    
    assert os.path.exists(env["report_json"])
    assert os.path.exists(env["report_txt"])
    
    with open(env["report_json"], "r") as f:
        data = json.load(f)
    assert "disclaimer" in data
    assert "best_model_by_top_1_expectancy" in data
    assert "best_model_by_top_5_expectancy" in data
    assert "verdict" in data
    
    with open(env["report_txt"], "r") as f:
        text = f.read()
    assert "ML V1.21 MODEL CAPACITY REALITY CHECK REPORT" in text
    assert "SUMMARY VERDICT:" in text
    assert "MODEL STATISTICS COMPARISON:" in text


def test_script_handles_missing_optional_model_gracefully(tmp_path, monkeypatch):
    env = setup_env(tmp_path, row_count=1000)
    
    # Simulate missing optional models by turning flags off
    monkeypatch.setattr("app.scripts.model_capacity_reality_check.XGB_AVAILABLE", False)
    monkeypatch.setattr("app.scripts.model_capacity_reality_check.LGB_AVAILABLE", False)
    
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0
    
    with open(env["report_json"], "r") as f:
        data = json.load(f)
    # Confirms XGBoost/LightGBM were skipped and are not in results
    assert "XGBoost" not in data["model_statistics"]
    assert "LightGBM" not in data["model_statistics"]


def test_no_production_artifact_is_written_or_modified(tmp_path):
    env = setup_env(tmp_path, row_count=1000)
    
    # Capture initial timestamps/states
    initial_schema_time = os.path.getmtime(env["schema"])
    
    code = run_model_comparison(
        csv_path=env["csv"],
        schema_path=env["schema"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0
    
    # Verify input feature schema wasn't modified
    assert os.path.getmtime(env["schema"]) == initial_schema_time
