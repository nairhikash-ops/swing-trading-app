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

def calculate_top_n_stats(df_sorted, percent, overall_win_rate):
    idx = max(1, int(len(df_sorted) * (percent / 100.0)))
    subset = df_sorted.iloc[:idx]
    row_count = len(subset)
    win_count = len(subset[subset["outcome"] == "WIN"])
    loss_count = len(subset[subset["outcome"] == "LOSS"])
    timeout_count = len(subset[subset["outcome"] == "TIMEOUT"])
    
    win_rate = win_count / row_count if row_count > 0 else 0.0
    loss_rate = loss_count / row_count if row_count > 0 else 0.0
    timeout_rate = timeout_count / row_count if row_count > 0 else 0.0
    
    expectancy = (win_rate * 7.0) - (loss_rate * 3.0)
    lift = win_rate / overall_win_rate if overall_win_rate else 0.0
    
    return {
        "percent": percent,
        "row_count": row_count,
        "win": win_count,
        "loss": loss_count,
        "to": timeout_count,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "to_rate": timeout_rate,
        "expectancy": expectancy,
        "lift": lift
    }

def format_top_n_stats(stats):
    return (
        f"Top {stats['percent']:02d}% | Rows: {stats['row_count']:<5} | "
        f"WIN: {stats['win']:<5} | LOSS: {stats['loss']:<5} | TO: {stats['to']:<4} | "
        f"WIN%: {stats['win_rate']:.4f} (Lift: {stats['lift']:.2f}x) | "
        f"LOSS%: {stats['loss_rate']:.4f} | TO%: {stats['to_rate']:.4f} | Exp: {stats['expectancy']:+.4f}"
    )

def run_walk_forward_experiment(
    input_csv_path: str = "/app/data/exports/ml_dataset_ohlcv_v1.csv",
    report_path: str = "/app/data/exports/walk_forward_baseline_report.txt"
):
    if not os.path.exists(input_csv_path):
        raise FileNotFoundError(f"Dataset not found at {input_csv_path}")

    print(f"Loading dataset from {input_csv_path}...")
    df = pd.read_csv(input_csv_path)

    # Convert to datetime and sort
    df["sample_date"] = pd.to_datetime(df["sample_date"])
    df = df.sort_values("sample_date").reset_index(drop=True)
    df["target"] = df["outcome"].apply(encode_label)

    # Feature columns
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
        "positive_top_5_periods": 0,
        "negative_top_1_periods": 0,
        "negative_top_5_periods": 0,
        "top_1_expectancies": [],
        "top_5_expectancies": [],
        "top_10_expectancies": [],
        "top_20_expectancies": [],
        "best_top_5_period": None,
        "worst_top_5_period": None,
        "best_top_5_val": -999.0,
        "worst_top_5_val": 999.0,
    }

    report_lines = [
        "=== WALK-FORWARD VALIDATION EXPERIMENT ===",
        "Artifact status: EXPERIMENTAL ONLY - not for live trading or production scoring",
        f"Input CSV:            {input_csv_path}",
        f"Dataset Date Range:   {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
        "Training Window:      Expanding (from earliest sample)",
        "Minimum Train Time:   2 Years",
        "Validation Step:      3 Months (full blocks only)",
        "Embargo Period:       35 calendar days before validation start",
        ""
    ]

    while True:
        validation_end = validation_start + pd.DateOffset(months=3)
        if validation_end > end_date:
            report_lines.append(f"Skipping final partial period starting {validation_start.strftime('%Y-%m-%d')} (less than 3 months of data).")
            break

        embargo_end = validation_start - pd.Timedelta(days=35)
        
        train_df = df[df["sample_date"] <= embargo_end]
        test_df = df[(df["sample_date"] >= validation_start) & (df["sample_date"] < validation_end)]

        period_name = f"{validation_start.strftime('%Y-%m-%d')} to {validation_end.strftime('%Y-%m-%d')}"
        
        # If no train data or test data, skip
        if len(train_df) == 0 or len(test_df) == 0:
            validation_start = validation_start + pd.DateOffset(months=3)
            continue

        X_train = train_df[actual_feature_cols]
        y_train = train_df["target"]
        X_test = test_df[actual_feature_cols]
        y_test = test_df["target"]

        # Only train if there are at least two classes in training set
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

        top_1 = calculate_top_n_stats(test_df_sorted, 1, overall_win_rate)
        top_5 = calculate_top_n_stats(test_df_sorted, 5, overall_win_rate)
        top_10 = calculate_top_n_stats(test_df_sorted, 10, overall_win_rate)
        top_20 = calculate_top_n_stats(test_df_sorted, 20, overall_win_rate)

        report_lines.append(f"--- PERIOD: {period_name} ---")
        report_lines.append(f"Training end (post-embargo): {embargo_end.strftime('%Y-%m-%d')}")
        report_lines.append(f"Train rows: {len(train_df)} | Test rows: {len(test_df)} | Overall WIN%: {overall_win_rate:.4f}")
        report_lines.append(format_top_n_stats(top_1))
        report_lines.append(format_top_n_stats(top_5))
        report_lines.append(format_top_n_stats(top_10))
        report_lines.append(format_top_n_stats(top_20))
        report_lines.append("")

        # Aggregates
        aggregate_stats["number_of_periods"] += 1
        
        exp_1 = top_1["expectancy"]
        exp_5 = top_5["expectancy"]
        
        aggregate_stats["top_1_expectancies"].append(exp_1)
        aggregate_stats["top_5_expectancies"].append(exp_5)
        aggregate_stats["top_10_expectancies"].append(top_10["expectancy"])
        aggregate_stats["top_20_expectancies"].append(top_20["expectancy"])
        
        if exp_1 > 0:
            aggregate_stats["positive_top_1_periods"] += 1
        else:
            aggregate_stats["negative_top_1_periods"] += 1
            
        if exp_5 > 0:
            aggregate_stats["positive_top_5_periods"] += 1
        else:
            aggregate_stats["negative_top_5_periods"] += 1

        if exp_5 > aggregate_stats["best_top_5_val"]:
            aggregate_stats["best_top_5_val"] = exp_5
            aggregate_stats["best_top_5_period"] = period_name
            
        if exp_5 < aggregate_stats["worst_top_5_val"]:
            aggregate_stats["worst_top_5_val"] = exp_5
            aggregate_stats["worst_top_5_period"] = period_name

        # Advance step
        validation_start = validation_start + pd.DateOffset(months=3)

    # Final Aggregation Report
    if aggregate_stats["number_of_periods"] > 0:
        avg_exp_1 = np.mean(aggregate_stats["top_1_expectancies"])
        avg_exp_5 = np.mean(aggregate_stats["top_5_expectancies"])
        avg_exp_10 = np.mean(aggregate_stats["top_10_expectancies"])
        avg_exp_20 = np.mean(aggregate_stats["top_20_expectancies"])
        
        report_lines.extend([
            "=== AGGREGATE RESULTS ===",
            f"Total completed periods:       {aggregate_stats['number_of_periods']}",
            f"Positive Top 1% periods:       {aggregate_stats['positive_top_1_periods']}",
            f"Negative Top 1% periods:       {aggregate_stats['negative_top_1_periods']}",
            f"Positive Top 5% periods:       {aggregate_stats['positive_top_5_periods']}",
            f"Negative Top 5% periods:       {aggregate_stats['negative_top_5_periods']}",
            "",
            f"Best Top 5% period:            {aggregate_stats['best_top_5_period']} (Exp: {aggregate_stats['best_top_5_val']:+.4f})",
            f"Worst Top 5% period:           {aggregate_stats['worst_top_5_period']} (Exp: {aggregate_stats['worst_top_5_val']:+.4f})",
            "",
            f"Average Top 1% expectancy:     {avg_exp_1:+.4f}",
            f"Average Top 5% expectancy:     {avg_exp_5:+.4f}",
            f"Average Top 10% expectancy:    {avg_exp_10:+.4f}",
            f"Average Top 20% expectancy:    {avg_exp_20:+.4f}",
        ])
    else:
        report_lines.append("=== AGGREGATE RESULTS ===")
        report_lines.append("No full validation periods were completed.")

    report_text = "\n".join(report_lines) + "\n"
    print(report_text)

    # Save report
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"Walk-forward report saved to: {report_path}")

if __name__ == "__main__":
    run_walk_forward_experiment()
