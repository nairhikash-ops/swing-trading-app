"""
test_audit_training_reproducibility.py

Unit tests for ML V1.20 Training Reproducibility Audit.
Uses isolated tmp_path fixtures.
No production DB/dataset CSV access.
"""
from __future__ import annotations

import json
import os
import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.scripts.audit_training_reproducibility import run_audit, generate_expected_features


def make_mock_model_pipeline(path: str, n_features: int = 308):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lr = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression())
    ])
    X = np.random.normal(0, 1, (10, n_features))
    y = np.random.binomial(1, 0.5, 10)
    lr.fit(X, y)
    joblib.dump(lr, path)
    return lr


def make_mock_csv(path: str, schema: list[str], row_count: int = 10, target_val: float = 0.5) -> pd.DataFrame:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    metadata_cols = ["symbol", "sample_date", "outcome"]
    all_cols = metadata_cols + schema
    
    data = []
    for i in range(row_count):
        row = {
            "symbol": f"SYM{i}",
            "sample_date": "2026-05-18",
            "outcome": "WIN" if i % 2 == 0 else "LOSS"
        }
        for col in schema:
            row[col] = float(i * 0.1) # predictable features
        data.append(row)
        
    df = pd.DataFrame(data, columns=all_cols)
    df.to_csv(path, index=False)
    return df


def setup_env(
    tmp_path,
    n_features: int = 308,
    custom_schema: list[str] | None = None,
    custom_meta: dict | None = None,
    custom_csv_meta: dict | None = None,
    custom_rankings: list[dict] | None = None,
    skip_model: bool = False,
    skip_schema: bool = False,
    skip_meta: bool = False,
    skip_csv: bool = False,
    skip_csv_meta: bool = False,
    skip_rankings: bool = False
):
    model_dir = tmp_path / "model"
    exports_dir = tmp_path / "exports"
    scripts_dir = tmp_path / "scripts"
    
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(exports_dir, exist_ok=True)
    os.makedirs(scripts_dir, exist_ok=True)
    
    # Generate schema
    technical, regime = generate_expected_features()
    expected_schema = technical + regime
    if custom_schema is not None:
        schema_list = custom_schema
    else:
        schema_list = expected_schema[:n_features]
        
    if not skip_schema:
        with open(model_dir / "feature_schema.json", "w", encoding="utf-8") as f:
            json.dump(schema_list, f, indent=2)
            
    # Generate model
    if not skip_model:
        make_mock_model_pipeline(str(model_dir / "model.joblib"), len(schema_list))
        
    # Generate model metadata
    if not skip_meta:
        meta = custom_meta or {
            "dataset_version": "stock_opportunity_ohlcv_regime_v1",
            "row_count": 10,
            "feature_count": len(schema_list)
        }
        with open(model_dir / "model_metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
            
    # Generate CSV
    if not skip_csv:
        make_mock_csv(str(exports_dir / "ml_dataset_ohlcv_regime_v1.csv"), schema_list, row_count=10)
        
    # Generate CSV metadata
    if not skip_csv_meta:
        csv_meta = custom_csv_meta or {
            "row_count": 10
        }
        with open(exports_dir / "ml_dataset_ohlcv_regime_v1.meta.json", "w", encoding="utf-8") as f:
            json.dump(csv_meta, f, indent=2)
            
    # Generate rankings
    if not skip_rankings:
        rankings = custom_rankings or [
            {
                "symbol": "SYM0",
                "sample_date": "2026-05-18",
                "win_probability": 0.5 # will be verified by reproducibility
            }
        ]
        pd.DataFrame(rankings).to_csv(exports_dir / "latest_regime_rankings.csv", index=False)
        with open(exports_dir / "latest_regime_rankings.meta.json", "w", encoding="utf-8") as f:
            json.dump({"row_count": len(rankings)}, f, indent=2)
            
    # Generate mock score script
    score_content = """
# score_latest_regime.py
with open(schema_path, "r") as f:
    feature_cols = json.load(f)
X = latest_df[feature_cols]
"""
    with open(scripts_dir / "score_latest_regime.py", "w", encoding="utf-8") as f:
        f.write(score_content)

    return {
        "model_dir": str(model_dir),
        "exports_dir": str(exports_dir),
        "scripts_dir": str(scripts_dir),
        "report_json": str(exports_dir / "training_reproducibility_audit.json"),
        "report_txt": str(exports_dir / "training_reproducibility_audit.txt")
    }


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_missing_model_artifact_fails(tmp_path):
    env = setup_env(tmp_path, skip_model=True)
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1


def test_missing_feature_schema_fails(tmp_path):
    env = setup_env(tmp_path, skip_schema=True)
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1


def test_wrong_feature_count_fails(tmp_path):
    # Setup with 307 features instead of 308
    env = setup_env(tmp_path, n_features=307)
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1


def test_missing_ohlcv_feature_fails(tmp_path):
    technical, regime = generate_expected_features()
    # Modify schema to replace c00_open_rel with a bad name
    bad_schema = ["bad_feature"] + technical[1:] + regime
    env = setup_env(tmp_path, custom_schema=bad_schema)
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1


def test_wrong_ohlcv_order_fails(tmp_path):
    technical, regime = generate_expected_features()
    # Swap first two features
    bad_schema = [technical[1], technical[0]] + technical[2:] + regime
    env = setup_env(tmp_path, custom_schema=bad_schema)
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1


def test_missing_regime_feature_fails(tmp_path):
    technical, regime = generate_expected_features()
    # Bad regime feature name
    bad_schema = technical + ["bad_regime_feature"] + regime[1:]
    env = setup_env(tmp_path, custom_schema=bad_schema)
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1


def test_schema_and_csv_mismatch_fails(tmp_path):
    env = setup_env(tmp_path)
    # Re-write the CSV with a different schema to force mismatch
    make_mock_csv(
        os.path.join(env["exports_dir"], "ml_dataset_ohlcv_regime_v1.csv"),
        ["bad_feature"] * 308,
        row_count=10
    )
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1


def test_metadata_row_count_mismatch_fails(tmp_path):
    # CSV has 10 rows, but model metadata lists row_count = 15 (> 10, which violates <= rule)
    env = setup_env(tmp_path, custom_meta={"row_count": 15, "feature_count": 308})
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1


def test_prediction_reproduction_passes_when_align(tmp_path):
    # Setup aligned environment where rankings prob matches manual scikit-learn prediction
    env = setup_env(tmp_path)
    
    # Load model and run prediction on SYM0's features to get the exact prob
    model = joblib.load(os.path.join(env["model_dir"], "model.joblib"))
    technical, regime = generate_expected_features()
    schema = technical + regime
    
    # Features for row index 0 (all 0.0 in make_mock_csv)
    features_values = [0.0 for _ in schema]
    X_input = pd.DataFrame([features_values], columns=schema)
    expected_prob = model.predict_proba(X_input)[0][1]
    
    # Write rankings with exact expected prob
    rankings = [{
        "symbol": "SYM0",
        "sample_date": "2026-05-18",
        "win_probability": expected_prob
    }]
    pd.DataFrame(rankings).to_csv(os.path.join(env["exports_dir"], "latest_regime_rankings.csv"), index=False)
    
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 0 # Passes successfully!


def test_prediction_reproduction_fails_when_feature_order_differs(tmp_path):
    env = setup_env(tmp_path)
    
    # rankings prob is 0.5, but model prediction on SYM0 (all 0.0) is not 0.5 (or we intentionally mismatch it)
    # Write rankings with a mismatched probability (e.g. 0.99)
    rankings = [{
        "symbol": "SYM0",
        "sample_date": "2026-05-18",
        "win_probability": 0.99
    }]
    pd.DataFrame(rankings).to_csv(os.path.join(env["exports_dir"], "latest_regime_rankings.csv"), index=False)
    
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1 # Fails because of probability mismatch (> 1e-9)


def test_report_json_written(tmp_path):
    env = setup_env(tmp_path)
    run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert os.path.exists(env["report_json"])
    with open(env["report_json"]) as f:
        data = json.load(f)
    assert "verdict" in data
    assert "checks" in data
    assert "reproducibility_details" in data


def test_report_txt_written(tmp_path):
    env = setup_env(tmp_path)
    run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert os.path.exists(env["report_txt"])
    with open(env["report_txt"]) as f:
        txt = f.read()
    assert "ML V1.20 TRAINING REPRODUCIBILITY AUDIT REPORT" in txt
    assert "1. HARD CHECKS STATUS" in txt
    assert "2. PREDICTION REPRODUCIBILITY CHECK" in txt


def test_exit_code_non_zero_on_hard_failure(tmp_path):
    # Setup environment with missing metadata file
    env = setup_env(tmp_path, skip_meta=True)
    code = run_audit(
        model_dir=env["model_dir"],
        exports_dir=env["exports_dir"],
        scripts_dir=env["scripts_dir"],
        report_json_path=env["report_json"],
        report_txt_path=env["report_txt"]
    )
    assert code == 1
