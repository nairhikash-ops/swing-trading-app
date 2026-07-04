import pandas as pd
import numpy as np
from pathlib import Path
import sys
import json

def main():
    csv_path = Path(r"D:\app\data\exports\sweep_sideways_expectancy\sweep_robustness_trades.csv")
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
        
    # Convert dates
    slice_df["entry_date"] = pd.to_datetime(slice_df["entry_date"])
    slice_df["year"] = slice_df["entry_date"].dt.year
    slice_df["month_str"] = slice_df["entry_date"].dt.strftime("%Y-%m")
    
    total_trades = len(slice_df)
    total_pnl = slice_df["realized_pnl"].sum()
    total_expectancy = slice_df["realized_pnl"].mean()
    total_wins = (slice_df["outcome"] == "WIN").sum()
    total_win_rate = total_wins / total_trades if total_trades > 0 else 0
    
    print("\n--- BASELINE METRICS ---")
    print(f"Target Slice: 30-session, 8% range, max 8% stop, 0.50% friction")
    print(f"Total Trades: {total_trades}")
    print(f"Total PnL: {total_pnl:.4f}")
    print(f"Total Expectancy: {total_expectancy:.4f}")
    print(f"Total Win Rate: {total_win_rate:.2%}")
    
    # 1. Yearly Stats
    print("\n--- YEARLY STATS ---")
    yearly = slice_df.groupby("year").agg(
        trades=("symbol", "count"),
        wins=("outcome", lambda x: (x == "WIN").sum()),
        expectancy=("realized_pnl", "mean")
    )
    yearly["win_rate"] = yearly["wins"] / yearly["trades"]
    print(yearly[["trades", "win_rate", "expectancy"]].round({"win_rate": 4, "expectancy": 4}).to_string())
    
    # 2. Monthly Stats
    print("\n--- MONTHLY STATS ---")
    monthly = slice_df.groupby("month_str").agg(
        trades=("symbol", "count"),
        wins=("outcome", lambda x: (x == "WIN").sum()),
        expectancy=("realized_pnl", "mean"),
        total_pnl=("realized_pnl", "sum")
    )
    monthly["win_rate"] = monthly["wins"] / monthly["trades"]
    print(monthly[["trades", "win_rate", "expectancy", "total_pnl"]].sort_index().round({"win_rate": 4, "expectancy": 4, "total_pnl": 4}).to_string())
    
    # 3. Symbol Stats
    sym_stats = slice_df.groupby("symbol").agg(
        trades=("symbol", "count"),
        total_pnl=("realized_pnl", "sum")
    )
    
    print("\n--- TOP SYMBOLS BY TRADE COUNT ---")
    print(sym_stats.sort_values("trades", ascending=False).head(5).to_string())
    
    print("\n--- TOP SYMBOLS BY TOTAL PNL ---")
    sym_by_pnl = sym_stats.sort_values("total_pnl", ascending=False)
    print(sym_by_pnl.head(5).to_string())
    
    print("\n--- FRAGILITY & REMOVAL ANALYSIS ---")
    
    # Best month removal
    monthly_pnl = monthly.sort_values("total_pnl", ascending=False)
    best_month = monthly_pnl.index[0]
    best_2_months = monthly_pnl.index[:2].tolist()
    worst_month = monthly_pnl.sort_values("total_pnl", ascending=True).index[0]
    
    no_best_month = slice_df[slice_df["month_str"] != best_month]
    no_best_2_months = slice_df[~slice_df["month_str"].isin(best_2_months)]
    
    print(f"Expectancy after removing best month ({best_month}): {no_best_month['realized_pnl'].mean():.4f}")
    print(f"Expectancy after removing best 2 months ({best_2_months}): {no_best_2_months['realized_pnl'].mean():.4f}")
    
    # Best symbol removal
    best_sym = sym_by_pnl.index[0]
    best_3_sym = sym_by_pnl.index[:3].tolist()
    worst_sym = sym_stats.sort_values("total_pnl", ascending=True).index[0]
    
    no_best_sym = slice_df[slice_df["symbol"] != best_sym]
    no_best_3_sym = slice_df[~slice_df["symbol"].isin(best_3_sym)]
    
    print(f"Expectancy after removing best symbol ({best_sym}): {no_best_sym['realized_pnl'].mean():.4f}")
    print(f"Expectancy after removing best 3 symbols ({best_3_sym}): {no_best_3_sym['realized_pnl'].mean():.4f}")
    
    print(f"Worst month: {worst_month} (PnL: {monthly.loc[worst_month, 'total_pnl']:.4f})")
    print(f"Worst symbol: {worst_sym} (PnL: {sym_stats.loc[worst_sym, 'total_pnl']:.4f})")
    
    # Broadness
    unique_syms = len(sym_stats)
    profitable_syms = len(sym_stats[sym_stats["total_pnl"] > 0])
    top_5_sym_pnl = sym_by_pnl.head(5)["total_pnl"].sum()
    top_5_contrib_pct = top_5_sym_pnl / total_pnl if total_pnl > 0 else 0
    
    print(f"\nUnique symbols traded: {unique_syms}")
    print(f"Profitable symbols: {profitable_syms} ({(profitable_syms/unique_syms if unique_syms>0 else 0):.1%})")
    print(f"Top 5 symbols total PnL contribution: {top_5_contrib_pct:.2%}")
    
    # Final Verdict logic
    print("\n--- VERDICT RULES ---")
    median_monthly_expectancy = monthly["expectancy"].median()
    print(f"Median monthly expectancy: {median_monthly_expectancy:.4f}")
    
    promotable = True
    reject_reason = []
    
    best_month_pct = monthly.loc[best_month, "total_pnl"] / total_pnl if total_pnl > 0 else 0
    best_sym_pct = sym_stats.loc[best_sym, "total_pnl"] / total_pnl if total_pnl > 0 else 0
    
    if best_month_pct > 0.5:
        promotable = False
        reject_reason.append(f"One month explains {best_month_pct:.1%} of total PnL (>50%).")
    
    if best_sym_pct > 0.5:
        promotable = False
        reject_reason.append(f"One symbol explains {best_sym_pct:.1%} of total PnL (>50%).")
        
    if no_best_month['realized_pnl'].mean() <= 0:
        promotable = False
        reject_reason.append("Expectancy is negative after removing best month.")
        
    if no_best_3_sym['realized_pnl'].mean() <= 0:
        promotable = False
        reject_reason.append("Expectancy is negative after removing best 3 symbols.")
        
    caution_flags = []
    if median_monthly_expectancy <= 0:
        caution_flags.append("Median monthly expectancy is negative (edge is unevenly distributed).")
        
    # Chronological Caution Flags
    # 1. 2023 dominance
    if 2023 in yearly.index:
        y23_pnl = slice_df[slice_df["year"] == 2023]["realized_pnl"].sum()
        if total_pnl > 0 and (y23_pnl / total_pnl) > 0.5:
            caution_flags.append(f"2023 contributes the vast majority of net PnL ({y23_pnl:.3f} out of {total_pnl:.3f}).")
            
    # 2. Negative years
    neg_years = yearly[yearly["expectancy"] < 0].index.tolist()
    if neg_years:
        caution_flags.append(f"Negative expectancy years detected: {neg_years}.")
        
    # 3. Profitable months fraction
    total_active_months = len(monthly)
    profitable_months = len(monthly[monthly["total_pnl"] > 0])
    if total_active_months > 0 and (profitable_months / total_active_months) < 0.6:
        caution_flags.append(f"Only {profitable_months} out of {total_active_months} active months were profitable.")
        
    if promotable:
        print(">>> STATUS: PROMOTABLE. Edge survived fragility audits.")
        if caution_flags:
            print(">>> CAUTION FLAGS:")
            for c in caution_flags:
                print(f"  - {c}")
    else:
        print(">>> STATUS: REJECTED due to fragility.")
        for r in reject_reason:
            print(f"  - {r}")
            
    # Export summary to JSON
    summary_data = {
        "target_slice": {
            "base_duration": dur,
            "base_range": rng,
            "stop_variant": stp,
            "round_trip_friction": fric
        },
        "baseline": {
            "total_trades": int(total_trades),
            "total_pnl": float(total_pnl),
            "total_expectancy": float(total_expectancy),
            "total_win_rate": float(total_win_rate)
        },
        "fragility": {
            "expectancy_no_best_month": float(no_best_month['realized_pnl'].mean()),
            "expectancy_no_best_2_months": float(no_best_2_months['realized_pnl'].mean()),
            "expectancy_no_best_symbol": float(no_best_sym['realized_pnl'].mean()),
            "expectancy_no_best_3_symbols": float(no_best_3_sym['realized_pnl'].mean()),
            "median_monthly_expectancy": float(median_monthly_expectancy)
        },
        "broadness": {
            "unique_symbols": int(unique_syms),
            "profitable_symbols": int(profitable_syms),
            "top_5_sym_pnl_contribution_pct": float(top_5_contrib_pct)
        },
        "verdict": {
            "promotable": bool(promotable),
            "reject_reasons": reject_reason,
            "caution_flags": caution_flags
        }
    }
    
    out_dir = csv_path.parent
    out_file = out_dir / "audit_concentration_summary.json"
    with open(out_file, "w") as f:
        json.dump(summary_data, f, indent=4)
        
    print(f"\nExported audit summary to: {out_file}")

if __name__ == "__main__":
    main()
