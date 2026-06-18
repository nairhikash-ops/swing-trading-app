"""
model_capacity_reality_check.py

ML V1.21 Model Capacity Reality Check.
Read-only script to compare multiple model architectures on the same regime dataset.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
except ImportError:
    LGB_AVAILABLE = False


def generate_default_schema() -> list[str]:
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
    return technical_cols + regime_cols


def load_feature_schema(schema_path: str) -> list[str]:
    if os.path.exists(schema_path):
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
                if isinstance(schema, list) and len(schema) == 308:
                    return schema
        except Exception as e:
            print(f"Warning: failed to load schema from {schema_path}: {e}")
    return generate_default_schema()


def encode_label(outcome: str) -> int:
    if outcome == "WIN":
        return 1
    elif outcome in ("LOSS", "TIMEOUT"):
        return 0
    raise ValueError(f"Unknown outcome: {outcome}")


def run_model_comparison(
    csv_path: str = "/app/data/exports/ml_dataset_ohlcv_regime_v1.csv",
    schema_path: str = "/app/data/models/stock_opportunity_ohlcv_regime_v1/feature_schema.json",
    report_json_path: str = "/app/data/exports/model_capacity_reality_check.json",
    report_txt_path: str = "/app/data/exports/model_capacity_reality_check.txt"
) -> int:
    generated_at = datetime.now(timezone.utc).isoformat()
    
    if not os.path.exists(csv_path):
        print(f"Error: Dataset CSV not found at {csv_path}")
        return 1
        
    print(f"Loading feature schema from {schema_path}...")
    feature_schema = load_feature_schema(schema_path)
    
    print(f"Loading dataset from {csv_path} memory-safely...")
    # Load only required columns and use float32 to reduce memory usage by 50%
    req_cols = ["symbol", "sample_date", "outcome"] + feature_schema
    dtype_dict = {col: np.float32 for col in feature_schema}
    dtype_dict.update({"symbol": "category"})
    
    try:
        df = pd.read_csv(csv_path, usecols=req_cols, dtype=dtype_dict)
    except Exception as e:
        print(f"Error loading dataset: {e}")
        return 1
        
    df["sample_date"] = pd.to_datetime(df["sample_date"])
    
    # Filter outcome labels and map WIN -> 1, LOSS/TIMEOUT -> 0
    # Exclude AMBIGUOUS and INSUFFICIENT_FUTURE_DATA
    df = df[df["outcome"].isin(["WIN", "LOSS", "TIMEOUT"])].copy()
    df["target"] = df["outcome"].apply(encode_label)
    
    # Sort chronologically
    df = df.sort_values("sample_date").reset_index(drop=True)
    
    start_date = df["sample_date"].min()
    end_date = df["sample_date"].max()
    
    # Build periods list
    validation_start = start_date + pd.DateOffset(years=2)
    periods = []
    current_val_start = validation_start
    while True:
        current_val_end = current_val_start + pd.DateOffset(months=3)
        if current_val_end > end_date:
            break
        
        embargo_end = current_val_start - pd.Timedelta(days=35)
        train_df = df[df["sample_date"] <= embargo_end]
        test_df = df[(df["sample_date"] >= current_val_start) & (df["sample_date"] < current_val_end)]
        
        if len(train_df) > 0 and len(test_df) > 0 and len(train_df["target"].unique()) >= 2:
            periods.append({
                "start": current_val_start,
                "end": current_val_end,
                "embargo_end": embargo_end,
                "period_name": f"{current_val_start.strftime('%Y-%m-%d')} to {current_val_end.strftime('%Y-%m-%d')}"
            })
        current_val_start = current_val_start + pd.DateOffset(months=3)
        
    if not periods:
        print("Error: No validation periods found.")
        return 1
        
    # Setup candidate models
    models_dict = {
        "LogisticRegression": {
            "name": "StandardScaler + LogisticRegression",
            "use_scaler": True,
            "model_obj": LogisticRegression(max_iter=1000, random_state=42)
        },
        "HistGradientBoosting": {
            "name": "HistGradientBoostingClassifier (Raw Features)",
            "use_scaler": False,
            "model_obj": HistGradientBoostingClassifier(random_state=42)
        },
        "RandomForest": {
            "name": "RandomForestClassifier (Raw Features)",
            "use_scaler": False,
            "model_obj": RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
        }
    }
    
    if XGB_AVAILABLE:
        models_dict["XGBoost"] = {
            "name": "XGBClassifier (Raw Features)",
            "use_scaler": False,
            "model_obj": xgb.XGBClassifier(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1, eval_metric="logloss")
        }
    else:
        print("XGBoost is not installed. Skipping XGBoost model.")
        
    if LGB_AVAILABLE:
        models_dict["LightGBM"] = {
            "name": "LGBMClassifier (Raw Features)",
            "use_scaler": False,
            "model_obj": lgb.LGBMClassifier(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1, verbosity=-1)
        }
    else:
        print("LightGBM is not installed. Skipping LightGBM model.")
        
    # Setup statistics tracking
    model_stats = {}
    for key, info in models_dict.items():
        model_stats[key] = {
            "name": info["name"],
            "completed_periods": 0,
            "runtime_limited": False,
            "total_elapsed": 0.0,
            "top_1_expectancies": [],
            "top_5_expectancies": [],
            "top_10_expectancies": [],
            "top_20_expectancies": [],
            "positive_top_1_periods": 0,
            "negative_top_1_periods": 0,
            "positive_top_5_periods": 0,
            "negative_top_5_periods": 0,
            "worst_top_1_period": None,
            "worst_top_1_val": 999.0,
            "worst_top_5_period": None,
            "worst_top_5_val": 999.0,
            "best_top_1_period": None,
            "best_top_1_val": -999.0,
            "best_top_5_period": None,
            "best_top_5_val": -999.0,
        }

    print(f"Starting walk-forward validation comparison across {len(periods)} periods...")
    for idx, period in enumerate(periods, 1):
        print(f"\nPeriod {idx}/{len(periods)}: {period['period_name']}")
        
        train_df = df[df["sample_date"] <= period["embargo_end"]]
        test_df = df[(df["sample_date"] >= period["start"]) & (df["sample_date"] < period["end"])]
        
        X_train = train_df[feature_schema]
        y_train = train_df["target"]
        X_test = test_df[feature_schema]
        y_test = test_df["target"]
        
        print(f"  Train samples: {len(train_df)} | Test samples: {len(test_df)}")
        
        for key, info in models_dict.items():
            stats = model_stats[key]
            if stats["runtime_limited"]:
                print(f"  - {info['name']}: SKIPPED (Runtime limited)")
                continue
                
            t0 = time.perf_counter()
            try:
                model_obj = info["model_obj"]
                if info["use_scaler"]:
                    # Scaler only fitted on train data inside a Pipeline
                    pipe = Pipeline([
                        ("scaler", StandardScaler()),
                        ("clf", model_obj)
                    ])
                    pipe.fit(X_train, y_train)
                    probs = pipe.predict_proba(X_test)[:, 1]
                else:
                    # Trees/boosting models fitted directly on raw features
                    model_obj.fit(X_train, y_train)
                    probs = model_obj.predict_proba(X_test)[:, 1]
                    
                elapsed = time.perf_counter() - t0
                stats["total_elapsed"] += elapsed
                stats["completed_periods"] += 1
                
                # Check runtime safety guard (Correction 3)
                if elapsed > 120.0:
                    print(f"  - WARNING: {info['name']} fit took {elapsed:.2f}s, exceeding 120s limit. Marking as runtime limited.")
                    stats["runtime_limited"] = True
                
                # Slicing and expectancy
                test_df_copy = test_df.copy()
                test_df_copy["prob"] = probs
                test_df_sorted = test_df_copy.sort_values("prob", ascending=False)
                overall_win_rate = test_df_copy["target"].mean()
                
                pct_results = {}
                for pct in [1, 5, 10, 20]:
                    n_rows = max(1, int(len(test_df_sorted) * (pct / 100.0)))
                    subset = test_df_sorted.iloc[:n_rows]
                    
                    win_count = int(len(subset[subset["outcome"] == "WIN"]))
                    loss_count = int(len(subset[subset["outcome"] == "LOSS"]))
                    
                    win_rate = win_count / n_rows
                    loss_rate = loss_count / n_rows
                    
                    expectancy = (win_rate * 7.0) - (loss_rate * 3.0)
                    pct_results[pct] = expectancy
                    
                    # Accumulate into lists
                    if pct == 1:
                        stats["top_1_expectancies"].append(expectancy)
                        if expectancy > 0:
                            stats["positive_top_1_periods"] += 1
                        else:
                            stats["negative_top_1_periods"] += 1
                            
                        if expectancy < stats["worst_top_1_val"]:
                            stats["worst_top_1_val"] = expectancy
                            stats["worst_top_1_period"] = period["period_name"]
                        if expectancy > stats["best_top_1_val"]:
                            stats["best_top_1_val"] = expectancy
                            stats["best_top_1_period"] = period["period_name"]
                            
                    elif pct == 5:
                        stats["top_5_expectancies"].append(expectancy)
                        if expectancy > 0:
                            stats["positive_top_5_periods"] += 1
                        else:
                            stats["negative_top_5_periods"] += 1
                            
                        if expectancy < stats["worst_top_5_val"]:
                            stats["worst_top_5_val"] = expectancy
                            stats["worst_top_5_period"] = period["period_name"]
                        if expectancy > stats["best_top_5_val"]:
                            stats["best_top_5_val"] = expectancy
                            stats["best_top_5_period"] = period["period_name"]
                            
                    elif pct == 10:
                        stats["top_10_expectancies"].append(expectancy)
                    elif pct == 20:
                        stats["top_20_expectancies"].append(expectancy)
                        
                print(f"  - {info['name']}: Top 1% Exp: {pct_results[1]:+.4f} | Top 5% Exp: {pct_results[5]:+.4f} | Time: {elapsed:.2f}s")
                
            except Exception as e:
                print(f"  - Error running {info['name']}: {e}")
                # We do not crash the script, mark model as runtime/execution limited
                stats["runtime_limited"] = True
                
    # Calculate averages and verify improvements
    aggregate_results = []
    best_top_1_model = None
    best_top_1_val = -999.0
    best_top_5_model = None
    best_top_5_val = -999.0
    
    for key, stats in model_stats.items():
        if stats["completed_periods"] > 0:
            avg_1 = float(np.mean(stats["top_1_expectancies"]))
            avg_5 = float(np.mean(stats["top_5_expectancies"]))
            avg_10 = float(np.mean(stats["top_10_expectancies"]))
            avg_20 = float(np.mean(stats["top_20_expectancies"]))
            
            stats["avg_top_1_expectancy"] = avg_1
            stats["avg_top_5_expectancy"] = avg_5
            stats["avg_top_10_expectancy"] = avg_10
            stats["avg_top_20_expectancy"] = avg_20
            
            if avg_1 > best_top_1_val:
                best_top_1_val = avg_1
                best_top_1_model = stats["name"]
            if avg_5 > best_top_5_val:
                best_top_5_val = avg_5
                best_top_5_model = stats["name"]
        else:
            stats["avg_top_1_expectancy"] = None
            stats["avg_top_5_expectancy"] = None
            stats["avg_top_10_expectancy"] = None
            stats["avg_top_20_expectancy"] = None
            
    # Determine verdict
    # Check if a non-linear model beats LogisticRegression by >= 0.05 average expectancy
    lr_stats = model_stats.get("LogisticRegression")
    lr_top_1_avg = lr_stats["avg_top_1_expectancy"] if lr_stats else None
    lr_top_5_avg = lr_stats["avg_top_5_expectancy"] if lr_stats else None
    
    verdict = "No non-linear model materially beats LogisticRegression."
    material_improvement = False
    
    for key, stats in model_stats.items():
        if key == "LogisticRegression" or stats["completed_periods"] == 0:
            continue
        avg_1 = stats["avg_top_1_expectancy"]
        avg_5 = stats["avg_top_5_expectancy"]
        
        # Check Top 1% and Top 5% material improvements
        t1_improved = (lr_top_1_avg is not None and avg_1 is not None and (avg_1 - lr_top_1_avg) >= 0.05)
        t5_improved = (lr_top_5_avg is not None and avg_5 is not None and (avg_5 - lr_top_5_avg) >= 0.05)
        
        if t1_improved or t5_improved:
            material_improvement = True
            verdict = f"{stats['name']} materially beats LogisticRegression."
            break
            
    report_data = {
        "generated_at": generated_at,
        "csv_path": csv_path,
        "schema_path": schema_path,
        "disclaimer": "Diagnostic comparison report only. No models were deployed. No production artifacts were modified.",
        "best_model_by_top_1_expectancy": best_top_1_model,
        "best_model_by_top_5_expectancy": best_top_5_model,
        "material_nonlinear_improvement": material_improvement,
        "verdict": verdict,
        "model_statistics": model_stats
    }
    
    # Save JSON Report
    try:
        os.makedirs(os.path.dirname(report_json_path), exist_ok=True)
        with open(report_json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
    except Exception as e:
        print(f"Error writing JSON report: {e}")
        return 1
        
    # Format Text Report
    txt_lines = [
        "=" * 80,
        "ML V1.21 MODEL CAPACITY REALITY CHECK REPORT",
        "=" * 80,
        f"Generated at    : {generated_at}",
        f"Dataset CSV     : {csv_path}",
        f"Disclaimer      : {report_data['disclaimer']}",
        "-" * 80,
        "SUMMARY VERDICT:",
        f"  Best Model (Top 1% average expectancy): {best_top_1_model} ({best_top_1_val:+.4f})",
        f"  Best Model (Top 5% average expectancy): {best_top_5_model} ({best_top_5_val:+.4f})",
        f"  Verdict: {verdict}",
        "-" * 80,
        "MODEL STATISTICS COMPARISON:",
        ""
    ]
    
    for key, stats in model_stats.items():
        txt_lines.append(f"Model: {stats['name']}")
        if stats["runtime_limited"]:
            txt_lines.append("  * Runtime/Execution Limited: True (partially completed or skipped)")
        txt_lines.append(f"  Completed Periods : {stats['completed_periods']}")
        txt_lines.append(f"  Total Runtime     : {stats['total_elapsed']:.2f}s")
        
        if stats["completed_periods"] > 0:
            txt_lines.append(f"  Average Expectancies:")
            txt_lines.append(f"    Top 01% band    : {stats['avg_top_1_expectancy']:+.4f}")
            txt_lines.append(f"    Top 05% band    : {stats['avg_top_5_expectancy']:+.4f}")
            txt_lines.append(f"    Top 10% band    : {stats['avg_top_10_expectancy']:+.4f}")
            txt_lines.append(f"    Top 20% band    : {stats['avg_top_20_expectancy']:+.4f}")
            txt_lines.append(f"  Period Split Success Ratio:")
            txt_lines.append(f"    Top 01% positive: {stats['positive_top_1_periods']} / negative: {stats['negative_top_1_periods']}")
            txt_lines.append(f"    Top 05% positive: {stats['positive_top_5_periods']} / negative: {stats['negative_top_5_periods']}")
            txt_lines.append(f"  Boundaries:")
            txt_lines.append(f"    Worst Top 1% Period: {stats['worst_top_1_period']} ({stats['worst_top_1_val']:+.4f})")
            txt_lines.append(f"    Best Top 1% Period : {stats['best_top_1_period']} ({stats['best_top_1_val']:+.4f})")
            txt_lines.append(f"    Worst Top 5% Period: {stats['worst_top_5_period']} ({stats['worst_top_5_val']:+.4f})")
            txt_lines.append(f"    Best Top 5% Period : {stats['best_top_5_period']} ({stats['best_top_5_val']:+.4f})")
        else:
            txt_lines.append("  No validation metrics available.")
        txt_lines.append("-" * 40)
        
    txt_report = "\n".join(txt_lines) + "\n"
    print("\n" + txt_report)
    
    # Save Text Report
    try:
        with open(report_txt_path, "w", encoding="utf-8") as f:
            f.write(txt_report)
    except Exception as e:
        print(f"Error writing Text report: {e}")
        return 1
        
    print(f"JSON Report written to: {report_json_path}")
    print(f"TXT Report written to:  {report_txt_path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ML V1.21 Model Capacity Reality Check")
    parser.add_argument("--csv", type=str, default="/app/data/exports/ml_dataset_ohlcv_regime_v1.csv", help="Path to dataset CSV")
    parser.add_argument("--schema", type=str, default="/app/data/models/stock_opportunity_ohlcv_regime_v1/feature_schema.json", help="Path to schema JSON")
    parser.add_argument("--report-json", type=str, default="/app/data/exports/model_capacity_reality_check.json", help="Path to JSON report")
    parser.add_argument("--report-txt", type=str, default="/app/data/exports/model_capacity_reality_check.txt", help="Path to TXT report")
    args = parser.parse_args()
    
    import sys
    sys.exit(run_model_comparison(
        csv_path=args.csv,
        schema_path=args.schema,
        report_json_path=args.report_json,
        report_txt_path=args.report_txt
    ))
