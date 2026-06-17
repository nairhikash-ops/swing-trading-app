import os
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

def derive_regime_metrics(test_df: pd.DataFrame) -> dict:
    # 20d window comprises c39 to c58
    prev_20_cols = [f"c{i}_close_rel" for i in range(39, 59)]
    
    # 20d return: c59_close_rel relative to c39_close_rel
    # c39_close_rel = (c39 / c59) - 1.0 => c39 = c59 * (c39_rel + 1)
    # 20d_return = (c59 - c39) / c39 = (c59 / c39) - 1 = 1 / (c39_rel + 1) - 1
    ret_20d = (1.0 / (test_df["c39_close_rel"] + 1.0)) - 1.0
    
    median_20d = ret_20d.median()
    mean_20d = ret_20d.mean()
    std_20d = ret_20d.std()
    
    # Breakout: current close (c59) > max(previous 20 closes)
    # Since relative closes are calculated as (prev / c59) - 1, 
    # if max(prev_rels) < 0, then all previous closes are < c59.
    max_prev_20 = test_df[prev_20_cols].max(axis=1)
    breakouts = (max_prev_20 < 0.0).sum()
    breakout_rate = breakouts / len(test_df)
    
    # Breakdown: current close (c59) < min(previous 20 closes)
    # if min(prev_rels) > 0, then all previous closes are > c59.
    min_prev_20 = test_df[prev_20_cols].min(axis=1)
    breakdowns = (min_prev_20 > 0.0).sum()
    breakdown_rate = breakdowns / len(test_df)
    
    hostile_regime = bool((median_20d < 0) or (breakdown_rate > breakout_rate))
    
    return {
        "median_20d_return": median_20d,
        "mean_20d_return": mean_20d,
        "breakout_rate": breakout_rate,
        "breakdown_rate": breakdown_rate,
        "breakout_minus_breakdown": breakout_rate - breakdown_rate,
        "cross_sectional_20d_return_std": std_20d,
        "sample_count_used_for_regime": len(test_df),
        "hostile_regime_flag": hostile_regime
    }

def run_regime_diagnostics_experiment(
    input_csv_path: str = "/app/data/exports/ml_dataset_ohlcv_v1.csv",
    report_path: str = "/app/data/exports/walk_forward_regime_diagnostics_report.txt"
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

    known_failed_periods = [
        "2024-06-13 to 2024-09-13",
        "2025-06-13 to 2025-09-13",
        "2025-09-13 to 2025-12-13",
        "2025-12-13 to 2026-03-13"
    ]
    
    failed_snapshots = []

    report_lines = [
        "=== WALK-FORWARD REGIME DIAGNOSTICS EXPERIMENT ===",
        "Artifact status: EXPERIMENTAL ONLY - not for live trading or production scoring",
        f"Input CSV:            {input_csv_path}",
        f"Dataset Date Range:   {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
        "Sector/Index Info:    unavailable in current exported dataset. Relying on aggregate universe breadth.",
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

        top_1_exp = calculate_top_n_exp(test_df_sorted, 1)
        top_5_exp = calculate_top_n_exp(test_df_sorted, 5)

        regime = derive_regime_metrics(test_df_copy)
        
        report_lines.append(f"--- PERIOD: {period_name} ---")
        report_lines.append(f"period_start: {validation_start.strftime('%Y-%m-%d')}")
        report_lines.append(f"period_end: {validation_end.strftime('%Y-%m-%d')}")
        report_lines.append(f"training_end_after_embargo: {embargo_end.strftime('%Y-%m-%d')}")
        report_lines.append(f"train_rows: {len(train_df)} | test_rows: {len(test_df)}")
        report_lines.append(f"top_1_expectancy: {top_1_exp:+.4f}")
        report_lines.append(f"top_5_expectancy: {top_5_exp:+.4f}")
        report_lines.append(f"median_20d_return: {regime['median_20d_return'] * 100:+.2f}%")
        report_lines.append(f"mean_20d_return: {regime['mean_20d_return'] * 100:+.2f}%")
        report_lines.append(f"breakout_rate: {regime['breakout_rate'] * 100:.2f}%")
        report_lines.append(f"breakdown_rate: {regime['breakdown_rate'] * 100:.2f}%")
        report_lines.append(f"breakout_minus_breakdown: {regime['breakout_minus_breakdown'] * 100:+.2f}%")
        report_lines.append(f"cross_sectional_20d_return_std: {regime['cross_sectional_20d_return_std'] * 100:.2f}%")
        report_lines.append(f"sample_count_used_for_regime: {regime['sample_count_used_for_regime']}")
        report_lines.append(f"hostile_regime_flag: {regime['hostile_regime_flag']}")
        report_lines.append("")

        if period_name in known_failed_periods:
            failed_snapshots.append((period_name, top_1_exp, regime))

        validation_start = validation_start + pd.DateOffset(months=3)

    if failed_snapshots:
        report_lines.append("=== FAILED TOP 1% PERIOD REGIME SNAPSHOT ===")
        for period, exp, reg in failed_snapshots:
            report_lines.append(f"Period: {period}")
            report_lines.append(f"Top 1% Exp: {exp:+.4f}")
            report_lines.append(f"Hostile Flag: {reg['hostile_regime_flag']}")
            report_lines.append(f"Median 20d Ret: {reg['median_20d_return']*100:+.2f}% | Breadth Delta: {reg['breakout_minus_breakdown']*100:+.2f}%")
            report_lines.append("")

    report_text = "\n".join(report_lines) + "\n"
    print(report_text)

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"Regime Diagnostics report saved to: {report_path}")

if __name__ == "__main__":
    run_regime_diagnostics_experiment()
