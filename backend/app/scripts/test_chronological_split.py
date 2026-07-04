import pandas as pd
import numpy as np
from pathlib import Path
import sys
import json

import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trend-filter", type=str, default="none", help="Which trend filter trades file to load")
    args = parser.parse_args()
    
    base_dir = Path(r"D:\app\data\exports\sweep_sideways_expectancy")
    
    if args.trend_filter == "none":
        csv_path = base_dir / "sweep_robustness_trades.csv"
        out_file = base_dir / "chronological_split_summary.json"
    else:
        csv_path = base_dir / f"sweep_robustness_trades_trend_{args.trend_filter}.csv"
        out_file = base_dir / f"chronological_split_summary_trend_{args.trend_filter}.json"
        
    if not csv_path.exists():
        print(f"ERROR: Cannot find trades CSV at {csv_path}")
        sys.exit(1)
        
    df = pd.read_csv(csv_path)
    
    # Target slice
    dur = 30
    rng = 0.08
    stp = "max_8pct_stop"
    fric = 0.005
    
    mask = (
        (df["base_duration"] == dur) & 
        (np.isclose(df["base_range"], rng)) & 
        (df["stop_variant"] == stp) & 
        (np.isclose(df["round_trip_friction"], fric))
    )
    slice_df = df[mask].copy()
    
    if slice_df.empty:
        print("ERROR: No trades found for the target slice.")
        sys.exit(1)
        
    slice_df["entry_date"] = pd.to_datetime(slice_df["entry_date"])
    
    # Define splits
    split_date = pd.to_datetime("2024-01-01")
    
    train_mask = slice_df["entry_date"] < split_date
    test_mask = slice_df["entry_date"] >= split_date
    
    train_df = slice_df[train_mask]
    test_df = slice_df[test_mask]
    
    def print_stats(name, subset):
        trades = len(subset)
        wins = (subset["outcome"] == "WIN").sum()
        wr = wins / trades if trades > 0 else 0
        pnl = subset["realized_pnl"].sum()
        exp = pnl / trades if trades > 0 else 0
        
        print(f"--- {name.upper()} ---")
        print(f"Trades: {trades}")
        print(f"Win Rate: {wr:.2%}")
        print(f"Total PnL: {pnl:.4f}")
        print(f"Expectancy: {exp:.4f}")
        print()
        
    print("\n[CHRONOLOGICAL SPLIT VALIDATION]")
    print(f"Parameters: Base {dur}, Range {rng}, Stop {stp}, Friction {fric}\n")
    
    print_stats("Train/Discovery (2021-06-17 to 2023-12-31)", train_df)
    print_stats("Blind Test (2024-01-01 to 2026-06-17)", test_df)
    
    test_exp = test_df["realized_pnl"].mean()
    if test_exp > 0:
        print(">>> VERDICT: SURVIVED. The blind test shows positive expectancy out-of-sample.")
        verdict = "SURVIVED"
    else:
        print(">>> VERDICT: FAILED. The blind test yielded negative expectancy. The discovery is likely a 2023 artifact.")
        verdict = "FAILED"
        
    summary_data = {
        "parameters": {
            "base_duration": dur,
            "base_range": rng,
            "stop_variant": stp,
            "round_trip_friction": fric
        },
        "train_discovery": {
            "window": "2021-06-17 to 2023-12-31",
            "trades": int(len(train_df)),
            "win_rate": float(((train_df["outcome"] == "WIN").sum() / len(train_df)) if len(train_df) > 0 else 0),
            "total_pnl": float(train_df["realized_pnl"].sum()),
            "expectancy": float(train_df["realized_pnl"].mean())
        },
        "blind_test": {
            "window": "2024-01-01 to 2026-06-17",
            "trades": int(len(test_df)),
            "win_rate": float(((test_df["outcome"] == "WIN").sum() / len(test_df)) if len(test_df) > 0 else 0),
            "total_pnl": float(test_df["realized_pnl"].sum()),
            "expectancy": float(test_df["realized_pnl"].mean())
        },
        "verdict": verdict
    }
    
    with open(out_file, "w") as f:
        json.dump(summary_data, f, indent=4)
    print(f"\nExported summary to: {out_file}")

if __name__ == "__main__":
    main()
