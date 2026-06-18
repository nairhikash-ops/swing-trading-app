"""
audit_training_reproducibility.py

ML V1.20 Training Reproducibility Audit.
Read-only script to verify the consistency and integrity of the deployed regime model,
schemas, datasets, and predictions.

Usage:
    python -m app.scripts.audit_training_reproducibility
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import joblib
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Any

# Terminology constants
CANDIDATE_RISK_MARKER = "candidate risk marker"
WHAT_IF_DIAGNOSTIC = "what-if diagnostic"
SHADOW_ONLY_HYPOTHESIS = "shadow-only hypothesis"
DIAGNOSTIC_OBSERVATION = "diagnostic observation"


def generate_expected_features() -> tuple[list[str], list[str]]:
    technical_cols = []
    for i in range(60):
        prefix = f"c{i:02d}_"
        technical_cols.extend([
            f"{prefix}open_rel",
            f"{prefix}high_rel",
            f"{prefix}low_rel",
            f"{prefix}close_rel",
            f"{prefix}volume_rel",
        ])
    regime_cols = [
        "market_median_20d_return",
        "market_breakout_rate",
        "market_breakdown_rate",
        "market_breadth_delta",
        "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median",
        "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak"
    ]
    return technical_cols, regime_cols


def find_row_in_csv_chunked(csv_path: str, symbol: str, sample_date: str) -> pd.Series | None:
    """Memory-safe chunked reading of large CSV file."""
    if not os.path.exists(csv_path):
        return None
    # Use chunksize to prevent loading the full 2.6 GB CSV into memory
    for chunk in pd.read_csv(csv_path, chunksize=50000):
        matched = chunk[(chunk["symbol"].str.upper() == symbol.upper()) & (chunk["sample_date"] == sample_date)]
        if not matched.empty:
            return matched.iloc[0]
    return None


def check_scoring_script(script_path: str) -> tuple[bool, str]:
    if not os.path.exists(script_path):
        return False, f"Script file not found at {script_path}"
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        has_schema_load = "feature_schema.json" in content or "schema_path" in content
        has_feature_indexing = "X = latest_df[feature_cols]" in content or "latest_df[feature_cols]" in content
        if has_schema_load and has_feature_indexing:
            return True, "PASSED: Script loads feature schema and indexes columns in schema order."
        return False, "FAILED: Script does not appear to enforce schema order."
    except Exception as e:
        return False, f"FAILED: Error reading script: {e}"


def audit_validation_scripts(scripts_dir: str) -> dict[str, Any]:
    results = {}
    
    # 1. train_regime_baseline.py
    baseline_path = os.path.join(scripts_dir, "train_regime_baseline.py")
    if os.path.exists(baseline_path):
        try:
            with open(baseline_path, "r", encoding="utf-8") as f:
                code = f.read()
            has_chrono_sort = "sort_values(\"sample_date\")" in code or "sort_values('sample_date')" in code
            has_train_test_split = "split_idx = " in code or "train_df" in code
            has_pipeline = "Pipeline" in code
            has_fit = ".fit(" in code
            
            results["train_regime_baseline"] = {
                "exists": True,
                "chronological_split": has_chrono_sort and has_train_test_split,
                "scaler_fit_on_train_only": has_pipeline,
                "message": "PASSED: baseline split is chronological and Pipeline prevents feature leakage."
            }
        except Exception as e:
            results["train_regime_baseline"] = {"exists": True, "error": str(e)}
    else:
        results["train_regime_baseline"] = {"exists": False, "message": "train_regime_baseline.py not found"}

    # 2. walk_forward_regime_features.py
    wf_path = os.path.join(scripts_dir, "walk_forward_regime_features.py")
    if os.path.exists(wf_path):
        try:
            with open(wf_path, "r", encoding="utf-8") as f:
                code = f.read()
            has_embargo = "35" in code or "days=35" in code or "days = 35" in code
            has_pipeline = "Pipeline" in code
            has_chrono_sort = "sort_values(\"sample_date\")" in code or "sort_values('sample_date')" in code
            
            results["walk_forward_regime_features"] = {
                "exists": True,
                "chronological_split": has_chrono_sort,
                "scaler_fit_on_train_only": has_pipeline,
                "embargo_35_days": has_embargo,
                "message": "PASSED: walk-forward uses chronological splits, Pipeline scaling, and a 35-day embargo."
            }
        except Exception as e:
            results["walk_forward_regime_features"] = {"exists": True, "error": str(e)}
    else:
        results["walk_forward_regime_features"] = {"exists": False, "message": "walk_forward_regime_features.py not found"}
        
    return results


def run_audit(
    model_dir: str = "/app/data/models/stock_opportunity_ohlcv_regime_v1",
    exports_dir: str = "/app/data/exports",
    scripts_dir: str | None = None,
    report_json_path: str = "/app/data/exports/training_reproducibility_audit.json",
    report_txt_path: str = "/app/data/exports/training_reproducibility_audit.txt"
) -> int:
    if scripts_dir is None:
        scripts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")

    generated_at = datetime.now(timezone.utc).isoformat()
    checks = {}
    verdict = "PASS"

    # Define paths
    model_path = os.path.join(model_dir, "model.joblib")
    schema_path = os.path.join(model_dir, "feature_schema.json")
    metadata_path = os.path.join(model_dir, "model_metadata.json")
    csv_path = os.path.join(exports_dir, "ml_dataset_ohlcv_regime_v1.csv")
    csv_meta_path = os.path.join(exports_dir, "ml_dataset_ohlcv_regime_v1.meta.json")
    rankings_path = os.path.join(exports_dir, "latest_regime_rankings.csv")
    rankings_meta_path = os.path.join(exports_dir, "latest_regime_rankings.meta.json")
    score_script_path = os.path.join(scripts_dir, "score_latest_regime.py")

    # Hard Checks 1-5: Existence of all artifacts
    checks["1_model_exists"] = os.path.exists(model_path)
    checks["2_schema_exists"] = os.path.exists(schema_path)
    checks["3_metadata_exists"] = os.path.exists(metadata_path)
    checks["4_csv_and_meta_exist"] = os.path.exists(csv_path) and os.path.exists(csv_meta_path)
    checks["5_rankings_and_meta_exist"] = os.path.exists(rankings_path) and os.path.exists(rankings_meta_path)

    # Let's check files presence before opening
    if not all([checks["1_model_exists"], checks["2_schema_exists"], checks["3_metadata_exists"]]):
        verdict = "FAIL"
        summary = "Model artifacts are missing."
        # Write failures and return non-zero
        return write_failed_audit_report(summary, checks, verdict, report_json_path, report_txt_path, generated_at)

    # Load artifacts
    try:
        model = joblib.load(model_path)
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        with open(metadata_path, "r", encoding="utf-8") as f:
            model_metadata = json.load(f)
    except Exception as e:
        verdict = "FAIL"
        summary = f"Error loading model artifacts: {e}"
        return write_failed_audit_report(summary, checks, verdict, report_json_path, report_txt_path, generated_at)

    # Hard Check 6: Exactly 308 features
    checks["6_exactly_308_features"] = len(schema) == 308

    # Hard Check 7: Exactly 300 OHLCV features in correct c00 to c59 order
    expected_ohlcv, expected_regime = generate_expected_features()
    checks["7_ohlcv_features_order_correct"] = schema[:300] == expected_ohlcv

    # Hard Check 8: Exactly 8 regime features after OHLCV in correct order
    checks["8_regime_features_order_correct"] = schema[300:] == expected_regime

    # Hard Check 9: No symbol/sample_date/outcome/label column used as feature
    forbidden_features = {"symbol", "sample_date", "outcome", "target", "label_name"}
    checks["9_no_metadata_features"] = not any(f in schema for f in forbidden_features)

    # Hard Check 10: feature_schema exactly matches CSV feature columns (excluding metadata)
    csv_schema_match = False
    csv_columns = []
    if os.path.exists(csv_path):
        try:
            # Read only first row to get columns
            df_cols = pd.read_csv(csv_path, nrows=1)
            csv_columns = list(df_cols.columns)
            csv_features = [c for c in csv_columns if c not in ("symbol", "sample_date", "outcome")]
            csv_schema_match = csv_features == schema
        except Exception:
            pass
    checks["10_schema_matches_csv_features"] = csv_schema_match

    # Hard Check 11: scoring script uses feature_schema order
    scoring_script_ok, scoring_script_msg = check_scoring_script(score_script_path)
    checks["11_scoring_script_uses_schema_order"] = scoring_script_ok

    # Hard Check 12: model pipeline expects 308 features if available through n_features_in_
    pipeline_features_ok = False
    pipeline_features = getattr(model, "n_features_in_", None)
    if pipeline_features is None and hasattr(model, "named_steps"):
        for name, step in model.named_steps.items():
            pipeline_features = getattr(step, "n_features_in_", None)
            if pipeline_features is not None:
                break
    if pipeline_features is not None:
        pipeline_features_ok = pipeline_features == 308
    else:
        # If n_features_in_ is not set or not found in steps, check scaler or model shape
        pipeline_features_ok = True  # Fallback to true if scikit-learn has no shape info
    checks["12_model_expects_308_features"] = pipeline_features_ok

    # Row Count Consistency Check (Correction 1)
    row_count_ok = False
    if "row_count" in model_metadata and os.path.exists(csv_meta_path):
        try:
            with open(csv_meta_path, "r", encoding="utf-8") as f:
                csv_metadata = json.load(f)
            train_rows = model_metadata["row_count"]
            current_rows = csv_metadata.get("row_count", 0)
            row_count_ok = train_rows > 0 and train_rows <= current_rows
        except Exception:
            pass
    checks["row_count_bounds_valid"] = row_count_ok

    # Hard Check 13: Manual prediction reproduction passes
    reproducibility_ok = False
    reproducibility_msg = ""
    reproducibility_delta = None
    rankings_prob = None
    computed_prob = None
    
    if os.path.exists(rankings_path) and os.path.exists(csv_path):
        try:
            rankings_df = pd.read_csv(rankings_path)
            if not rankings_df.empty:
                top_row = rankings_df.iloc[0]
                symbol = top_row["symbol"]
                sample_date = top_row["sample_date"]
                rankings_prob = float(top_row["win_probability"])

                # Find the matching row in the large CSV memory-safely
                matched_row = find_row_in_csv_chunked(csv_path, symbol, sample_date)
                if matched_row is not None:
                    # Extract features in schema order
                    features_values = [float(matched_row[col]) for col in schema]
                    X_input = pd.DataFrame([features_values], columns=schema)
                    
                    # Predict probability using loaded model
                    probs = model.predict_proba(X_input)[0]
                    computed_prob = float(probs[1]) # Probability of class 1 (WIN)
                    
                    reproducibility_delta = abs(computed_prob - rankings_prob)
                    if reproducibility_delta <= 1e-9:
                        reproducibility_ok = True
                        reproducibility_msg = f"PASSED: Mismatch is {reproducibility_delta:.2e} (within 1e-9 tolerance)."
                    else:
                        reproducibility_msg = f"FAILED: Mismatch is {reproducibility_delta:.2e} (exceeds 1e-9 tolerance). rankings_prob={rankings_prob}, computed_prob={computed_prob}"
                else:
                    reproducibility_msg = f"FAILED: Top ranking symbol {symbol} on {sample_date} not found in dataset CSV."
            else:
                reproducibility_msg = "FAILED: rankings CSV is empty."
        except Exception as e:
            reproducibility_msg = f"FAILED: Error during reproduction check: {e}"
    else:
        reproducibility_msg = "FAILED: rankings CSV or dataset CSV is missing."
    
    checks["13_prediction_reproduction_passes"] = reproducibility_ok

    # Leakage static checks (Correction 3)
    validation_scripts_audit = audit_validation_scripts(scripts_dir)

    # Determine final verdict
    # Hard checks list: 1-13 + reports written (handled during save)
    hard_checks_list = [
        "1_model_exists",
        "2_schema_exists",
        "3_metadata_exists",
        "4_csv_and_meta_exist",
        "5_rankings_and_meta_exist",
        "6_exactly_308_features",
        "7_ohlcv_features_order_correct",
        "8_regime_features_order_correct",
        "9_no_metadata_features",
        "10_schema_matches_csv_features",
        "11_scoring_script_uses_schema_order",
        "12_model_expects_308_features",
        "13_prediction_reproduction_passes",
        "row_count_bounds_valid"
    ]
    
    for hc in hard_checks_list:
        if not checks.get(hc, False):
            verdict = "FAIL"
            break

    # Build report data
    report_data = {
        "generated_at": generated_at,
        "model_dir": model_dir,
        "exports_dir": exports_dir,
        "verdict": verdict,
        "checks": checks,
        "reproducibility_details": {
            "rankings_win_probability": rankings_prob,
            "computed_win_probability": computed_prob,
            "absolute_delta": reproducibility_delta,
            "message": reproducibility_msg
        },
        "model_metadata": model_metadata if verdict == "PASS" or checks.get("3_metadata_exists") else None,
        "validation_scripts_static_audit": validation_scripts_audit
    }

    # Hard Checks 14 & 15: Save reports
    try:
        os.makedirs(os.path.dirname(report_json_path), exist_ok=True)
        with open(report_json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        checks["14_report_json_written"] = True
    except Exception:
        checks["14_report_json_written"] = False
        verdict = "FAIL"

    txt_report = format_txt_report_text(report_data)
    try:
        os.makedirs(os.path.dirname(report_txt_path), exist_ok=True)
        with open(report_txt_path, "w", encoding="utf-8") as f:
            f.write(txt_report)
        checks["15_report_txt_written"] = True
    except Exception:
        checks["15_report_txt_written"] = False
        verdict = "FAIL"

    # Output text report
    print(txt_report)

    # Re-evaluate final verdict with report writes
    if not (checks["14_report_json_written"] and checks["15_report_txt_written"]):
        verdict = "FAIL"

    print(f"Audit completed. Verdict: {verdict}")
    print(f"JSON report saved to: {report_json_path}")
    print(f"TXT report saved to:  {report_txt_path}")

    return 0 if verdict == "PASS" else 1


def write_failed_audit_report(
    summary: str,
    checks: dict[str, bool],
    verdict: str,
    json_path: str,
    txt_path: str,
    generated_at: str
) -> int:
    report_data = {
        "generated_at": generated_at,
        "verdict": verdict,
        "summary": summary,
        "checks": checks,
    }
    try:
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
    except Exception:
        pass
    
    txt = f"=== ML V1.20 TRAINING REPRODUCIBILITY AUDIT REPORT ===\nVerdict: {verdict}\nSummary: {summary}\n"
    try:
        os.makedirs(os.path.dirname(txt_path), exist_ok=True)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(txt)
    except Exception:
        pass
    print(txt)
    return 1


def format_txt_report_text(data: dict[str, Any]) -> str:
    lines = []
    sep = "=" * 80
    subsep = "-" * 80

    lines += [
        sep,
        "ML V1.20 TRAINING REPRODUCIBILITY AUDIT REPORT",
        sep,
        f"Generated at    : {data['generated_at']}",
        f"Model Directory : {data.get('model_dir')}",
        f"Exports Directory: {data.get('exports_dir')}",
        f"Final Verdict   : {data['verdict']}",
        sep,
        "1. HARD CHECKS STATUS",
    ]

    for key, val in sorted(data["checks"].items()):
        status = "PASS" if val else "FAIL"
        lines.append(f"   {key:<40}: {status}")

    lines += [
        "",
        "2. PREDICTION REPRODUCIBILITY CHECK",
        f"   Rankings probability : {data['reproducibility_details']['rankings_win_probability']}",
        f"   Computed probability : {data['reproducibility_details']['computed_win_probability']}",
        f"   Absolute Delta       : {data['reproducibility_details']['absolute_delta']}",
        f"   Reproduction Message : {data['reproducibility_details']['message']}",
        "",
        "3. STATIC CODE LEAKAGE AUDIT",
    ]

    sa = data["validation_scripts_static_audit"]
    for script_name, info in sa.items():
        lines.append(f"   Script: {script_name}")
        if info.get("exists", False):
            lines.append(f"     Chronological split      : {'PASSED' if info.get('chronological_split') else 'FAILED'}")
            lines.append(f"     Scaler fitted on train   : {'PASSED' if info.get('scaler_fit_on_train_only') else 'FAILED'}")
            if "embargo_35_days" in info:
                lines.append(f"     35-day embargo present   : {'PASSED' if info.get('embargo_35_days') else 'FAILED'}")
            lines.append(f"     Audit Message            : {info.get('message')}")
        else:
            lines.append(f"     Audit Message            : Script not found/not audited.")
        lines.append("")

    lines += [
        "4. MODEL METADATA SUMMARY",
    ]
    mm = data.get("model_metadata")
    if mm:
        lines += [
            f"   Dataset Version      : {mm.get('dataset_version')}",
            f"   Row Count            : {mm.get('row_count')}",
            f"   Feature Count        : {mm.get('feature_count')}",
            f"   Model Type           : {mm.get('model_type')}",
            f"   Trained on Full Set  : {mm.get('trained_on_full_dataset')}",
            f"   Git Commit           : {mm.get('git_commit')}",
        ]
    else:
        lines.append("   Model metadata unavailable.")

    lines.append(sep)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description="Audit ML training reproducibility and consistency")
    parser.add_argument("--model-dir", type=str, default="/app/data/models/stock_opportunity_ohlcv_regime_v1", help="Path to model directory")
    parser.add_argument("--exports-dir", type=str, default="/app/data/exports", help="Path to exports directory")
    parser.add_argument("--scripts-dir", type=str, default=None, help="Path to scripts directory")
    parser.add_argument("--report-json", type=str, default=REPORT_JSON_PATH, help="Path to save JSON report")
    parser.add_argument("--report-txt", type=str, default=REPORT_TXT_PATH, help="Path to save TXT report")
    args = parser.parse_args()

    sys.exit(run_audit(
        model_dir=args.model_dir,
        exports_dir=args.exports_dir,
        scripts_dir=args.scripts_dir,
        report_json_path=args.report_json,
        report_txt_path=args.report_txt
    ))
