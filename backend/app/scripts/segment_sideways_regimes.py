import pandas as pd
import sqlite3
from pathlib import Path
import sys
import numpy as np
import time

DEFAULT_DB_PATH = Path(r"D:\app\data\evaluations\v3_signal_state_backtest_v1\recovered_artifacts\dhan_auth.sqlite3")
TRADES_CSV = Path(r"D:\app\data\exports\sweep_sideways_expectancy\sweep_robustness_trades.csv")

def main():
    print("--- Sideways Breakout Regime Segmentation (ALL INSTANCES) ---")
    
    start_t = time.time()
    # 1. Load the raw trades (all rows, no filtering)
    print(f"Loading ALL trades from {TRADES_CSV}...")
    df_trades = pd.read_csv(TRADES_CSV)
    print(f"Loaded {len(df_trades)} total rows.")
    
    # 2. Extract unique (symbol, base_start_date) to minimize DB lookups
    unique_bases = df_trades[["symbol", "base_start_date"]].drop_duplicates().copy()
    print(f"Found {len(unique_bases)} unique sideways base instances.")
    
    # 3. Load historical DB to fetch pre-base returns
    print(f"Loading price history from {DEFAULT_DB_PATH}...")
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    
    symbols = unique_bases["symbol"].unique()
    symbols_str = "','".join(symbols)
    
    symbols_query = f"""
        SELECT ic.symbol, i.id AS instrument_id
        FROM index_constituents ic
        JOIN instruments i ON i.isin = ic.isin
        WHERE ic.symbol IN ('{symbols_str}')
    """
    df_symbols = pd.read_sql(symbols_query, conn)
    instrument_ids = df_symbols["instrument_id"].unique().tolist()
    
    placeholders = ",".join("?" for _ in instrument_ids)
    candles_query = f"""
        SELECT instrument_id, trading_date, close
        FROM daily_candles
        WHERE instrument_id IN ({placeholders})
        ORDER BY instrument_id, trading_date
    """
    df_candles = pd.read_sql(candles_query, conn, params=instrument_ids)
    conn.close()
    
    df_symbols["symbol"] = df_symbols["symbol"].astype(str).str.upper()
    df_candles = df_candles.merge(df_symbols[["symbol", "instrument_id"]], on="instrument_id")
    df_candles["trading_date"] = pd.to_datetime(df_candles["trading_date"]).astype(str)
    df_candles = df_candles.sort_values(["symbol", "trading_date"]).reset_index(drop=True)
    
    # 4. Compute pre_structure_return_60d for each UNIQUE base
    print("Calculating pre-structure returns...")
    
    pre_returns = []
    buckets = []
    
    # Pre-group candles by symbol for faster lookup
    candles_by_sym = {sym: group for sym, group in df_candles.groupby("symbol")}
    
    for _, row in unique_bases.iterrows():
        sym = row["symbol"]
        base_start = str(row["base_start_date"])
        
        if sym in candles_by_sym:
            sym_cands = candles_by_sym[sym]
            dates = sym_cands["trading_date"].values
            closes = sym_cands["close"].values
            
            try:
                # Find index of base_start
                base_start_idx = np.where(dates == base_start)[0][0]
                
                pre_end = base_start_idx - 1
                pre_start = base_start_idx - 61
                
                if pre_start >= 0:
                    ret = (closes[pre_end] / closes[pre_start]) - 1
                else:
                    ret = 0.0
                    
            except IndexError:
                ret = 0.0
        else:
            ret = 0.0
            
        pre_returns.append(ret)
        
        if ret >= 0.10:
            buckets.append("uptrend")
        elif ret <= -0.10:
            buckets.append("downtrend")
        else:
            buckets.append("neutral")
            
    unique_bases["pre_structure_return_60d"] = pre_returns
    unique_bases["regime_bucket"] = buckets
    
    # 5. Join back to the full 600k+ trades dataframe
    print("Merging regimes back to full trades dataset...")
    df_trades = df_trades.merge(unique_bases, on=["symbol", "base_start_date"], how="left")
    
    # 6. Export to three separate files
    out_dir = Path(r"D:\app\data\exports\sweep_sideways_expectancy")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print("Exporting separate files...")
    uptrend = df_trades[df_trades["regime_bucket"] == "uptrend"]
    neutral = df_trades[df_trades["regime_bucket"] == "neutral"]
    downtrend = df_trades[df_trades["regime_bucket"] == "downtrend"]
    
    uptrend.to_csv(out_dir / "sideways_uptrend_trades.csv", index=False)
    print(f"-> sideways_uptrend_trades.csv ({len(uptrend)} rows)")
    
    neutral.to_csv(out_dir / "sideways_neutral_trades.csv", index=False)
    print(f"-> sideways_neutral_trades.csv ({len(neutral)} rows)")
    
    downtrend.to_csv(out_dir / "sideways_downtrend_trades.csv", index=False)
    print(f"-> sideways_downtrend_trades.csv ({len(downtrend)} rows)")
    
    print(f"Done in {time.time() - start_t:.1f}s.")

if __name__ == "__main__":
    main()
