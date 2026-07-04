import pandas as pd
import numpy as np
from pathlib import Path
import json
import sys

import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trend-filter", type=str, default="none", help="Which trend filter trades file to load")
    args = parser.parse_args()
    
    base_dir = Path(r"D:\app\data\exports\sweep_sideways_expectancy")
    
    if args.trend_filter == "none":
        csv_path = base_dir / "sweep_robustness_trades.csv"
        out_csv = base_dir / "blind_grid_survival_summary.csv"
        out_json = base_dir / "blind_grid_survival_summary.json"
    else:
        csv_path = base_dir / f"sweep_robustness_trades_trend_{args.trend_filter}.csv"
        out_csv = base_dir / f"blind_grid_survival_summary_trend_{args.trend_filter}.csv"
        out_json = base_dir / f"blind_grid_survival_summary_trend_{args.trend_filter}.json"
        
    if not csv_path.exists():
        print(f"ERROR: Cannot find trades CSV at {csv_path}")
        sys.exit(1)
        
    df = pd.read_csv(csv_path)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    
    # Filter blind period
    blind_df = df[df["entry_date"] >= "2024-01-01"].copy()
    blind_df["month_str"] = blind_df["entry_date"].dt.strftime("%Y-%m")
    
    groups = blind_df.groupby(["base_duration", "base_range", "stop_variant", "round_trip_friction"])
    
    results = []
    
    for name, group in groups:
        dur, rng, stp, fric = name
        
        trade_count = len(group)
        if trade_count == 0:
            continue
            
        win_mask = group["outcome"] == "WIN"
        wins = win_mask.sum()
        win_rate = float(wins / trade_count)
        
        total_pnl = float(group["realized_pnl"].sum())
        expectancy = float(total_pnl / trade_count)
        median_return = float(group["realized_pnl"].median())
        
        gross_profit = float(group.loc[group["realized_pnl"] > 0, "realized_pnl"].sum())
        gross_loss = float(group.loc[group["realized_pnl"] < 0, "realized_pnl"].sum())
        
        profit_factor = float(gross_profit / abs(gross_loss)) if gross_loss != 0 else float('inf')
        
        sym_pnl = group.groupby("symbol")["realized_pnl"].sum()
        unique_symbols = len(sym_pnl)
        profitable_symbols = int((sym_pnl > 0).sum())
        
        monthly_pnl = group.groupby("month_str")["realized_pnl"].sum()
        active_months = len(monthly_pnl)
        profitable_months = int((monthly_pnl > 0).sum())
        profitable_month_ratio = float(profitable_months / active_months) if active_months > 0 else 0.0
        
        survived = bool(
            trade_count >= 100 and
            expectancy > 0 and
            profit_factor > 1 and
            profitable_month_ratio >= 0.50 and
            unique_symbols >= 30
        )
        
        results.append({
            "base_duration": int(dur),
            "base_range": float(rng),
            "stop_variant": str(stp),
            "round_trip_friction": float(fric),
            "trade_count": int(trade_count),
            "win_rate": float(win_rate),
            "total_pnl": float(total_pnl),
            "expectancy": float(expectancy),
            "median_return": float(median_return),
            "profit_factor": float(profit_factor),
            "unique_symbols": int(unique_symbols),
            "profitable_symbols": int(profitable_symbols),
            "active_months": int(active_months),
            "profitable_months": int(profitable_months),
            "profitable_month_ratio": float(profitable_month_ratio),
            "survived_blind_diagnostic": survived
        })
        
    res_df = pd.DataFrame(results)
    
    res_df.to_csv(out_csv, index=False)
    
    survivors = res_df[res_df["survived_blind_diagnostic"] == True]
    
    print(f"Total combinations evaluated in blind period: {len(res_df)}")
    print(f"Combinations surviving diagnostic criteria: {len(survivors)}")
    
    json_data = {
        "verdict_summary": f"Fixed 30/8 failed, but {len(survivors)}/{len(res_df)} grid rows remained positive and survived diagnostics in the blind period.",
        "total_combinations": len(res_df),
        "surviving_combinations_count": len(survivors),
        "survivors": survivors.sort_values("expectancy", ascending=False).to_dict(orient="records")
    }
    
    with open(out_json, "w") as f:
        json.dump(json_data, f, indent=4)
        
    print(f"\n{json_data['verdict_summary']}")
    if len(survivors) > 0:
        print("\nTop Survivors by Expectancy:")
        top_survivors = survivors.sort_values("expectancy", ascending=False).head(5)
        print(top_survivors[["base_duration", "base_range", "stop_variant", "round_trip_friction", "trade_count", "expectancy", "profit_factor"]].to_string())
    
    # Check fixed 30/8 specifically:
    target = res_df[
        (res_df["base_duration"] == 30) & 
        (np.isclose(res_df["base_range"], 0.08)) & 
        (res_df["stop_variant"] == "max_8pct_stop") & 
        (np.isclose(res_df["round_trip_friction"], 0.005))
    ]
    if not target.empty:
        t = target.iloc[0]
        print(f"\n--- ORIGINAL FIXED 30/8 SETUP (BLIND) ---")
        print(f"Trades: {t['trade_count']}")
        print(f"Expectancy: {t['expectancy']:.4f}")
        print(f"Profit Factor: {t['profit_factor']:.2f}")
        print(f"Profitable Month Ratio: {t['profitable_month_ratio']:.2%}")
        print(f"Survived Diagnostic: {t['survived_blind_diagnostic']}")
        
    print(f"\nExported artifacts:\n - {out_csv}\n - {out_json}")

if __name__ == "__main__":
    main()
