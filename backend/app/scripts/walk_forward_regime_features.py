import os
import pandas as pd
import numpy as np
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

def compute_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["current_close_ratio"] = (1.0 + df["c59_close_rel"]).astype(np.float32)
    df["past_close_ratio"] = (1.0 + df["c39_close_rel"]).astype(np.float32)
    df["stock_20d_return"] = (df["current_close_ratio"] / df["past_close_ratio"] - 1.0).astype(np.float32)

    prev_20_high_cols = [f"c{i:02d}_high_rel" for i in range(39, 59)]
    prev_20_low_cols = [f"c{i:02d}_low_rel" for i in range(39, 59)]

    max_prev_20_high = df[prev_20_high_cols].max(axis=1) + 1.0
    min_prev_20_low = df[prev_20_low_cols].min(axis=1) + 1.0

    df["stock_is_breakout"] = (df["current_close_ratio"] > max_prev_20_high).astype(np.float32)
    df["stock_is_breakdown"] = (df["current_close_ratio"] < min_prev_20_low).astype(np.float32)

    market_df = df.groupby("sample_date").agg(
        market_median_20d_return=("stock_20d_return", "median"),
        market_cross_sectional_volatility=("stock_20d_return", "std"),
        market_breakout_rate=("stock_is_breakout", "mean"),
        market_breakdown_rate=("stock_is_breakdown", "mean")
    ).reset_index()

    market_df["market_breadth_delta"] = (market_df["market_breakout_rate"] - market_df["market_breakdown_rate"]).astype(np.float32)
    market_df["market_cross_sectional_volatility"] = market_df["market_cross_sectional_volatility"].fillna(0.0).astype(np.float32)
    market_df["market_median_20d_return"] = market_df["market_median_20d_return"].astype(np.float32)
    market_df["market_breakout_rate"] = market_df["market_breakout_rate"].astype(np.float32)
    market_df["market_breakdown_rate"] = market_df["market_breakdown_rate"].astype(np.float32)

    df = df.merge(market_df, on="sample_date", how="left")

    df["stock_20d_return_minus_market_median"] = (df["stock_20d_return"] - df["market_median_20d_return"]).astype(np.float32)
    df["stock_is_stronger_than_market"] = (df["stock_20d_return"] > df["market_median_20d_return"]).astype(np.float32)
    df["stock_breakout_while_market_weak"] = ((df["stock_is_breakout"] == 1.0) & (df["market_breadth_delta"] < 0)).astype(np.float32)

    df.drop(columns=["current_close_ratio", "past_close_ratio", "stock_20d_return", "stock_is_breakout", "stock_is_breakdown"], inplace=True)
    return df

def run_regime_features_experiment(
    input_csv_path: str = "/app/data/exports/ml_dataset_ohlcv_v1.csv",
    report_path: str = "/app/data/exports/walk_forward_regime_features_report.txt"
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
    
    # Enrich with regime features
    print("Computing aggregate regime features...")
    df = compute_regime_features(df)
    
    regime_feature_cols = [
        "market_median_20d_return",
        "market_breakout_rate",
        "market_breakdown_rate",
        "market_breadth_delta",
        "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median",
        "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak"
    ]
    actual_feature_cols.extend(regime_feature_cols)

    start_date = df["sample_date"].min()
    end_date = df["sample_date"].max()
    validation_start = start_date + pd.DateOffset(years=2)

    aggregate_stats = {
        "number_of_periods": 0,
        "positive_top_1_periods": 0,
        "negative_top_1_periods": 0,
        "positive_top_5_periods": 0,
        "negative_top_5_periods": 0,
        "top_1_expectancies": [],
        "top_5_expectancies": [],
        "top_10_expectancies": [],
        "top_20_expectancies": [],
    }

    report_lines = [
        "=== WALK-FORWARD REGIME FEATURES EXPERIMENT ===",
        "Artifact status: EXPERIMENTAL ONLY - not for live trading or production scoring",
        f"Input CSV:            {input_csv_path}",
        f"Dataset Date Range:   {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
        "Regime Integration:   8 aggregated macro features injected directly into X_train.",
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
        
        test_df_copy = test_df.copy()
        test_df_copy["prob"] = y_prob
        test_df_sorted = test_df_copy.sort_values("prob", ascending=False)
        overall_win_rate = test_df_copy["target"].mean()

        exp_1 = calculate_top_n_exp(test_df_sorted, 1)
        exp_5 = calculate_top_n_exp(test_df_sorted, 5)
        exp_10 = calculate_top_n_exp(test_df_sorted, 10)
        exp_20 = calculate_top_n_exp(test_df_sorted, 20)
        
        idx_1 = max(1, int(len(test_df_sorted) * 0.01))
        top_1_subset = test_df_sorted.iloc[:idx_1]
        top_1_win = len(top_1_subset[top_1_subset["outcome"] == "WIN"])
        top_1_loss = len(top_1_subset[top_1_subset["outcome"] == "LOSS"])
        top_1_to = len(top_1_subset[top_1_subset["outcome"] == "TIMEOUT"])

        report_lines.append(f"--- PERIOD: {period_name} ---")
        report_lines.append(f"Training end (post-embargo): {embargo_end.strftime('%Y-%m-%d')}")
        report_lines.append(f"Train rows: {len(train_df)} | Test rows: {len(test_df)} | Overall WIN%: {overall_win_rate:.4f}")
        report_lines.append(f"Top 01% | Rows: {len(top_1_subset):<5} | WIN: {top_1_win:<5} | LOSS: {top_1_loss:<5} | TO: {top_1_to:<4} | Exp: {exp_1:+.4f}")
        report_lines.append(f"Top 05% | Exp: {exp_5:+.4f}")
        report_lines.append(f"Top 10% | Exp: {exp_10:+.4f}")
        report_lines.append(f"Top 20% | Exp: {exp_20:+.4f}")
        report_lines.append("")

        aggregate_stats["number_of_periods"] += 1
        aggregate_stats["top_1_expectancies"].append(exp_1)
        aggregate_stats["top_5_expectancies"].append(exp_5)
        aggregate_stats["top_10_expectancies"].append(exp_10)
        aggregate_stats["top_20_expectancies"].append(exp_20)
        
        if exp_1 > 0:
            aggregate_stats["positive_top_1_periods"] += 1
        else:
            aggregate_stats["negative_top_1_periods"] += 1
            
        if exp_5 > 0:
            aggregate_stats["positive_top_5_periods"] += 1
        else:
            aggregate_stats["negative_top_5_periods"] += 1

        validation_start = validation_start + pd.DateOffset(months=3)

    if aggregate_stats["number_of_periods"] > 0:
        avg_exp_1 = sum(aggregate_stats["top_1_expectancies"]) / len(aggregate_stats["top_1_expectancies"])
        avg_exp_5 = sum(aggregate_stats["top_5_expectancies"]) / len(aggregate_stats["top_5_expectancies"])
        avg_exp_10 = sum(aggregate_stats["top_10_expectancies"]) / len(aggregate_stats["top_10_expectancies"])
        avg_exp_20 = sum(aggregate_stats["top_20_expectancies"]) / len(aggregate_stats["top_20_expectancies"])

        report_lines.extend([
            "=== AGGREGATE RESULTS ===",
            f"Total completed periods:       {aggregate_stats['number_of_periods']}",
            f"Positive Top 1% periods:       {aggregate_stats['positive_top_1_periods']}",
            f"Negative Top 1% periods:       {aggregate_stats['negative_top_1_periods']}",
            f"Positive Top 5% periods:       {aggregate_stats['positive_top_5_periods']}",
            f"Negative Top 5% periods:       {aggregate_stats['negative_top_5_periods']}",
            "",
            f"Average Top 1% expectancy:     {avg_exp_1:+.4f}",
            f"Average Top 5% expectancy:     {avg_exp_5:+.4f}",
            f"Average Top 10% expectancy:    {avg_exp_10:+.4f}",
            f"Average Top 20% expectancy:    {avg_exp_20:+.4f}",
        ])

    report_text = "\n".join(report_lines) + "\n"
    print(report_text)

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"Regime Features report saved to: {report_path}")

if __name__ == "__main__":
    run_regime_features_experiment()
