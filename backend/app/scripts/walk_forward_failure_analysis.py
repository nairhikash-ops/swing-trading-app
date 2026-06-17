import os
import datetime

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def encode_label(outcome: str) -> int:
    if outcome == "WIN":
        return 1
    elif outcome in ("LOSS", "TIMEOUT"):
        return 0
    raise ValueError(f"Unknown outcome: {outcome}")

def calculate_top_n_exp(df_sorted, percent):
    idx = max(1, int(len(df_sorted) * (percent / 100.0)))
    subset = df_sorted.iloc[:idx]
    row_count = len(subset)
    win_count = len(subset[subset["outcome"] == "WIN"])
    loss_count = len(subset[subset["outcome"] == "LOSS"])
    
    win_rate = win_count / row_count if row_count > 0 else 0.0
    loss_rate = loss_count / row_count if row_count > 0 else 0.0
    return (win_rate * 7.0) - (loss_rate * 3.0)

def analyze_top_1_slice(df_sorted, overall_win_rate):
    percent = 1
    idx = max(1, int(len(df_sorted) * (percent / 100.0)))
    subset = df_sorted.iloc[:idx].copy()
    
    row_count = len(subset)
    win_count = len(subset[subset["outcome"] == "WIN"])
    loss_count = len(subset[subset["outcome"] == "LOSS"])
    timeout_count = len(subset[subset["outcome"] == "TIMEOUT"])
    
    win_rate = win_count / row_count if row_count > 0 else 0.0
    loss_rate = loss_count / row_count if row_count > 0 else 0.0
    
    expectancy = (win_rate * 7.0) - (loss_rate * 3.0)
    
    unique_symbols = subset["symbol"].nunique() if row_count > 0 else 0
    if row_count > 0:
        symbol_counts = subset["symbol"].value_counts()
        top_symbol = symbol_counts.index[0]
        max_share = (symbol_counts.iloc[0] / row_count) * 100
        
        # Best/Worst symbols
        win_mask = subset["outcome"] == "WIN"
        loss_mask = subset["outcome"] == "LOSS"
        
        best_syms = subset[win_mask]["symbol"].value_counts().head(5).to_dict()
        worst_syms = subset[loss_mask]["symbol"].value_counts().head(5).to_dict()
    else:
        top_symbol = "None"
        max_share = 0.0
        best_syms = {}
        worst_syms = {}

    return {
        "rows": row_count,
        "win": win_count,
        "loss": loss_count,
        "to": timeout_count,
        "expectancy": expectancy,
        "unique_symbols": unique_symbols,
        "max_symbol_share": max_share,
        "top_symbol_by_rows": top_symbol,
        "best_symbols": best_syms,
        "worst_symbols": worst_syms
    }

def run_failure_analysis_experiment(
    input_csv_path: str = "/app/data/exports/ml_dataset_ohlcv_v1.csv",
    report_path: str = "/app/data/exports/walk_forward_failure_analysis_report.txt"
):
    if not os.path.exists(input_csv_path):
        raise FileNotFoundError(f"Dataset not found at {input_csv_path}")

    print(f"Loading dataset from {input_csv_path}...")
    df = pd.read_csv(input_csv_path)

    df["sample_date"] = pd.to_datetime(df["sample_date"])
    df = df.sort_values("sample_date").reset_index(drop=True)
    df["target"] = df["outcome"].apply(encode_label)

    feature_cols = []
    for i in range(60):
        prefix = f"c{i:02d}_"
        feature_cols.extend([
            f"{prefix}open_rel",
            f"{prefix}high_rel",
            f"{prefix}low_rel",
            f"{prefix}close_rel",
            f"{prefix}volume_rel",
        ])
        
    actual_feature_cols = [c for c in df.columns if c in feature_cols]

    start_date = df["sample_date"].min()
    end_date = df["sample_date"].max()
    validation_start = start_date + pd.DateOffset(years=2)
    
    aggregate_stats = {
        "number_of_periods": 0,
        "positive_top_1_periods": 0,
        "negative_top_1_periods": 0,
        "top_1_expectancies": [],
        "worst_top_1_period": None,
        "best_top_1_period": None,
        "worst_top_1_val": 999.0,
        "best_top_1_val": -999.0,
    }

    report_lines = [
        "=== WALK-FORWARD FAILURE ANALYSIS EXPERIMENT ===",
        "Artifact status: EXPERIMENTAL ONLY - not for live trading or production scoring",
        f"Input CSV:            {input_csv_path}",
        f"Dataset Date Range:   {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
        "Sector Concentration: unavailable in current exported dataset.",
        "Training Window:      Expanding (from earliest sample)",
        "Validation Step:      3 Months (full blocks only)",
        "Embargo Period:       35 calendar days before validation start",
        ""
    ]

    while True:
        validation_end = validation_start + pd.DateOffset(months=3)
        if validation_end > end_date:
            break

        embargo_end = validation_start - pd.Timedelta(days=35)
        
        train_df = df[df["sample_date"] <= embargo_end]
        test_df = df[(df["sample_date"] >= validation_start) & (df["sample_date"] < validation_end)]

        period_name = f"{validation_start.strftime('%Y-%m-%d')} to {validation_end.strftime('%Y-%m-%d')}"
        
        if len(train_df) == 0 or len(test_df) == 0:
            validation_start = validation_start + pd.DateOffset(months=3)
            continue

        X_train = train_df[actual_feature_cols]
        y_train = train_df["target"]
        X_test = test_df[actual_feature_cols]
        y_test = test_df["target"]

        if len(y_train.unique()) < 2:
            validation_start = validation_start + pd.DateOffset(months=3)
            continue

        lr = Pipeline([
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(max_iter=1000, random_state=42))
        ])
        lr.fit(X_train, y_train)

        y_prob = lr.predict_proba(X_test)[:, 1]
        
        test_df = test_df.copy()
        test_df["prob"] = y_prob
        test_df_sorted = test_df.sort_values("prob", ascending=False)
        overall_win_rate = test_df["target"].mean()

        top_1_stats = analyze_top_1_slice(test_df_sorted, overall_win_rate)
        top_5_exp = calculate_top_n_exp(test_df_sorted, 5)

        exp_1 = top_1_stats["expectancy"]
        is_negative = exp_1 <= 0
        
        report_lines.append(f"--- PERIOD: {period_name} ---")
        if is_negative:
            report_lines.append(f"** NEGATIVE PERIOD DETECTED **")
            
        report_lines.append(f"Training end (post-embargo): {embargo_end.strftime('%Y-%m-%d')}")
        report_lines.append(f"Train rows: {len(train_df)} | Test rows: {len(test_df)}")
        report_lines.append(f"Top 1% rows: {top_1_stats['rows']} | WIN: {top_1_stats['win']} | LOSS: {top_1_stats['loss']} | TO: {top_1_stats['to']}")
        report_lines.append(f"Top 1% Expectancy: {exp_1:+.4f}")
        report_lines.append(f"Top 5% Expectancy: {top_5_exp:+.4f}")
        report_lines.append(f"Top 1% Unique Symbols: {top_1_stats['unique_symbols']}")
        report_lines.append(f"Top 1% Max Symbol Share: {top_1_stats['max_symbol_share']:.2f}% (Symbol: {top_1_stats['top_symbol_by_rows']})")
        
        best_syms_str = ", ".join([f"{k}:{v}" for k, v in top_1_stats['best_symbols'].items()])
        worst_syms_str = ", ".join([f"{k}:{v}" for k, v in top_1_stats['worst_symbols'].items()])
        
        report_lines.append(f"Top 1% Best Symbols (WINs): {best_syms_str}")
        report_lines.append(f"Top 1% Worst Symbols (LOSSes): {worst_syms_str}")
        report_lines.append("")

        aggregate_stats["number_of_periods"] += 1
        aggregate_stats["top_1_expectancies"].append(exp_1)
        
        if exp_1 > 0:
            aggregate_stats["positive_top_1_periods"] += 1
        else:
            aggregate_stats["negative_top_1_periods"] += 1

        if exp_1 > aggregate_stats["best_top_1_val"]:
            aggregate_stats["best_top_1_val"] = exp_1
            aggregate_stats["best_top_1_period"] = period_name
            
        if exp_1 < aggregate_stats["worst_top_1_val"]:
            aggregate_stats["worst_top_1_val"] = exp_1
            aggregate_stats["worst_top_1_period"] = period_name

        validation_start = validation_start + pd.DateOffset(months=3)

    if aggregate_stats["number_of_periods"] > 0:
        report_lines.extend([
            "=== AGGREGATE RESULTS ===",
            f"Total completed periods:       {aggregate_stats['number_of_periods']}",
            f"Positive Top 1% periods:       {aggregate_stats['positive_top_1_periods']}",
            f"Negative Top 1% periods:       {aggregate_stats['negative_top_1_periods']}",
            "",
            f"Best Top 1% period:            {aggregate_stats['best_top_1_period']} (Exp: {aggregate_stats['best_top_1_val']:+.4f})",
            f"Worst Top 1% period:           {aggregate_stats['worst_top_1_period']} (Exp: {aggregate_stats['worst_top_1_val']:+.4f})",
        ])

    report_text = "\n".join(report_lines) + "\n"
    print(report_text)

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"Failure Analysis report saved to: {report_path}")

if __name__ == "__main__":
    run_failure_analysis_experiment()
