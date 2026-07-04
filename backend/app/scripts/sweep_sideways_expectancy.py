import sqlite3
import pandas as pd
import numpy as np
import hashlib
from pathlib import Path
import argparse
import sys
import time

DEFAULT_DB_PATH = Path(r"D:\app\data\evaluations\v3_signal_state_backtest_v1\recovered_artifacts\dhan_auth.sqlite3")

def reject_nonlocal_path(path_text: str, label: str) -> None:
    normalized = path_text.replace("/", "\\").lower()
    forbidden_fragments = [
        "100.76.",
        "http://",
        "https://",
        "\\home\\hacker\\",
        "/home/hacker/",
        "matsya-postgres",
        "postgresql://",
        "ssh ",
    ]
    if any(fragment in normalized for fragment in forbidden_fragments):
        print(f"ERROR: {label} must be local-only, got forbidden path/value: {path_text}", flush=True)
        sys.exit(1)

def get_file_hash(path: Path) -> str:
    if not path.exists():
        return "FILE_NOT_FOUND"
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024 * 10), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def load_local_candles(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(f"Local SQLite DB not found: {db_path}")

    symbols_query = """
        SELECT
            ic.symbol AS symbol,
            i.id AS instrument_id
        FROM index_constituents ic
        JOIN instruments i
          ON i.isin = ic.isin
         AND i.active = 1
         AND i.exchange_id = 'NSE'
         AND i.segment = 'E'
         AND i.instrument = 'EQUITY'
        WHERE ic.index_name = 'NIFTY_500'
          AND ic.active = 1
        ORDER BY ic.symbol
    """
    with sqlite3.connect(db_path) as conn:
        symbols_df = pd.read_sql_query(symbols_query, conn)
        if symbols_df.empty:
            raise ValueError("No active NIFTY_500 instruments found in local DB.")

        instrument_ids = [int(value) for value in symbols_df["instrument_id"].dropna().unique()]
        placeholders = ",".join("?" for _ in instrument_ids)
        candles_query = f"""
            SELECT
                instrument_id,
                trading_date,
                open,
                high,
                low,
                close,
                volume
            FROM daily_candles
            WHERE instrument_id IN ({placeholders})
            ORDER BY instrument_id, trading_date
        """
        candles_df = pd.read_sql_query(candles_query, conn, params=instrument_ids)

    if candles_df.empty:
        raise ValueError("No active NIFTY_500 candle rows found in local DB.")

    symbols_df["symbol"] = symbols_df["symbol"].astype(str).str.upper()
    symbols_df = symbols_df.drop_duplicates(subset=["instrument_id"])
    df = candles_df.merge(
        symbols_df[["symbol", "instrument_id"]],
        on=["instrument_id"],
        how="inner",
    )
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    
    df["daily_value"] = df["volume"] * df["close"]
    
    df = df.sort_values(["symbol", "trading_date"]).reset_index(drop=True)
    df["vol20_pre"] = df.groupby("symbol")["volume"].transform(lambda x: x.rolling(20).mean().shift(1))
    df["adtv20_pre"] = df.groupby("symbol")["daily_value"].transform(lambda x: x.rolling(20).mean().shift(1))
    df["sma100_pre"] = df.groupby("symbol")["close"].transform(lambda x: x.rolling(100).mean().shift(1))

    return df

def find_candidates(symbol: str, df: pd.DataFrame, base_durations: list[int], base_ranges: list[float], trend_filter: str) -> dict:
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    volumes = df["volume"].values
    vol20_pre = df["vol20_pre"].values
    adtv20_pre = df["adtv20_pre"].values
    sma100_pre = df["sma100_pre"].values
    dates = df["trading_date"].values
    n = len(df)
    
    rolling_highs = {}
    rolling_lows = {}
    for dur in base_durations:
        rolling_highs[dur] = df["high"].rolling(dur).max().shift(1).values
        rolling_lows[dur] = df["low"].rolling(dur).min().shift(1).values
        
    all_candidates = { (dur, rng): [] for dur in base_durations for rng in base_ranges }
    
    for dur in base_durations:
        rh = rolling_highs[dur]
        rl = rolling_lows[dur]
        
        for rng in base_ranges:
            last_setup_idx = -9999
            
            for i in range(dur, n - 1):
                if i - last_setup_idx < 15:
                    continue
                    
                if n - i - 1 < 40:
                    continue
                    
                base_high = rh[i]
                base_low = rl[i]
                
                if np.isnan(base_high) or np.isnan(base_low) or base_low <= 0:
                    continue
                    
                actual_range = (base_high - base_low) / base_low
                
                if actual_range > rng:
                    continue
                    
                if trend_filter == "breakout_above_sma100":
                    if closes[i] <= sma100_pre[i]:
                        continue
                elif trend_filter in ["prebase_60d_return_10", "prebase_60d_return_15", "prebase_60d_return_20", "sma100_and_prebase_60d_return_10", "sma100_and_prebase_60d_return_15"]:
                    base_start_idx = i - dur
                    if base_start_idx < 60:
                        continue
                        
                    prior_end_idx = base_start_idx - 1
                    prior_start_idx = base_start_idx - 60
                    prebase_return = (closes[prior_end_idx] / closes[prior_start_idx]) - 1
                    
                    if trend_filter == "prebase_60d_return_10":
                        if prebase_return < 0.10:
                            continue
                    elif trend_filter == "prebase_60d_return_15":
                        if prebase_return < 0.15:
                            continue
                    elif trend_filter == "prebase_60d_return_20":
                        if prebase_return < 0.20:
                            continue
                    elif trend_filter == "sma100_and_prebase_60d_return_10":
                        if closes[i] <= sma100_pre[i] or prebase_return < 0.10:
                            continue
                    elif trend_filter == "sma100_and_prebase_60d_return_15":
                        if closes[i] <= sma100_pre[i] or prebase_return < 0.15:
                            continue
                    
                if closes[i] < base_high * 1.005:
                    continue
                    
                vol_avg = vol20_pre[i]
                if np.isnan(vol_avg) or vol_avg <= 0:
                    continue
                    
                if volumes[i] < 1.5 * vol_avg:
                    continue
                    
                adtv = adtv20_pre[i]
                if np.isnan(adtv) or adtv < 10000000:
                    continue
                    
                entry_idx = i + 1
                entry_price = opens[entry_idx]
                
                end_idx = min(entry_idx + 40, n)
                fw_highs = highs[entry_idx : end_idx]
                fw_lows = lows[entry_idx : end_idx]
                fw_closes = closes[entry_idx : end_idx]
                
                all_candidates[(dur, rng)].append({
                    "symbol": symbol,
                    "setup_date": dates[i],
                    "base_start_date": dates[i - dur],
                    "base_end_date": dates[i - 1],
                    "base_high": base_high,
                    "base_low": base_low,
                    "breakout_date": dates[i],
                    "breakout_close": closes[i],
                    "entry_date": dates[entry_idx],
                    "entry_price": entry_price,
                    "fw_dates": dates[entry_idx : end_idx],
                    "fw_highs": fw_highs,
                    "fw_lows": fw_lows,
                    "fw_closes": fw_closes
                })
                last_setup_idx = i
                
    return all_candidates

def evaluate_trade(entry_price, fw_highs, fw_lows, fw_closes, base_low, stop_variant, friction):
    if stop_variant == "base_low_stop":
        stop_price = base_low
    elif stop_variant == "max_8pct_stop":
        stop_price = max(base_low, entry_price * 0.92)
    elif stop_variant == "max_10pct_stop":
        stop_price = max(base_low, entry_price * 0.90)
        
    target_price = entry_price * 1.10
    stop_pct = (entry_price - stop_price) / entry_price
    
    for i in range(len(fw_highs)):
        touched_target = fw_highs[i] >= target_price
        touched_stop = fw_lows[i] <= stop_price
        
        if touched_target and touched_stop:
            return "LOSS", (stop_price - entry_price) / entry_price - friction, i + 1, stop_pct, stop_price, target_price, stop_price
        elif touched_stop:
            return "LOSS", (stop_price - entry_price) / entry_price - friction, i + 1, stop_pct, stop_price, target_price, stop_price
        elif touched_target:
            return "WIN", 0.10 - friction, i + 1, stop_pct, stop_price, target_price, target_price
            
    day_40_close = fw_closes[-1]
    return "TIMEOUT", (day_40_close - entry_price) / entry_price - friction, 40, stop_pct, stop_price, target_price, day_40_close

def main():
    parser = argparse.ArgumentParser(description="Sweep sideways breakouts expectancies.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Local SQLite DB path.")
    parser.add_argument("--export-trades", action="store_true", help="Also export all evaluated trades to CSV")
    parser.add_argument("--trend-filter", type=str, default="none", choices=["none", "breakout_above_sma100", "prebase_60d_return_10", "prebase_60d_return_15", "prebase_60d_return_20", "sma100_and_prebase_60d_return_10", "sma100_and_prebase_60d_return_15"], help="Trend filter to apply")
    args = parser.parse_args()

    reject_nonlocal_path(str(args.db_path), "db-path")

    print("\n--- Historical Scan Proof ---", flush=True)
    print("WARNING: This is a CURRENT-UNIVERSE HISTORICAL SCAN (Discovery tool).", flush=True)
    print("Survivorship bias exists as delisted/removed symbols are excluded.", flush=True)
    print(f"DB Path: {args.db_path}", flush=True)
    print(f"DB Hash: {get_file_hash(args.db_path)}", flush=True)

    candles = load_local_candles(args.db_path)
    
    # Let's fix the groupby issue by making sure "symbol" isn't dropped if we used include_groups=False.
    # Actually, the simplest fix is to just do it via map instead of groupby.apply to avoid warnings entirely.
    print(f"Loaded candle rows: {len(candles)}", flush=True)
    
    symbols = candles["symbol"].unique()
    print(f"Symbols: {len(symbols)}", flush=True)
    print(f"Date range: {candles['trading_date'].min().strftime('%Y-%m-%d')} to {candles['trading_date'].max().strftime('%Y-%m-%d')}", flush=True)
    print("-----------------------------\n", flush=True)

    base_durations = [10, 15, 20, 30]
    base_ranges = [0.06, 0.08, 0.10, 0.12, 0.15]
    stop_variants = ["base_low_stop", "max_8pct_stop", "max_10pct_stop"]
    round_trip_frictions = [0.0015, 0.0030, 0.0050]

    grid_results = {}
    for dur in base_durations:
        for rng in base_ranges:
            for stp in stop_variants:
                for fric in round_trip_frictions:
                    grid_results[(dur, rng, stp, fric)] = {
                        "candidate_count": 0,
                        "win_count": 0,
                        "win_pnl_sum": 0.0,
                        "loss_count": 0,
                        "loss_pnl_sum": 0.0,
                        "timeout_count": 0,
                        "timeout_pnl_sum": 0.0,
                        "days_in_trade_sum": 0,
                        "returns": [],
                        "stop_pcts": []
                    }

    t0 = time.time()
    all_trades = []
    
    grouped = candles.groupby("symbol", sort=True)
    for i, symbol in enumerate(symbols, 1):
        df = grouped.get_group(symbol).sort_values("trading_date").reset_index(drop=True)
        
        all_cands = find_candidates(symbol, df, base_durations, base_ranges, args.trend_filter)
        
        for dur in base_durations:
            for rng in base_ranges:
                cands = all_cands[(dur, rng)]
                if not cands:
                    continue
                    
                for cand in cands:
                    for stp in stop_variants:
                        for fric in round_trip_frictions:
                            outcome, pnl, days, stop_pct, stop_price, target_price, exit_price = evaluate_trade(
                                cand["entry_price"], 
                                cand["fw_highs"],
                                cand["fw_lows"],
                                cand["fw_closes"],
                                cand["base_low"], 
                                stp, 
                                fric
                            )
                            
                            key = (dur, rng, stp, fric)
                            res = grid_results[key]
                            res["candidate_count"] += 1
                            res["returns"].append(pnl)
                            res["stop_pcts"].append(stop_pct)
                            res["days_in_trade_sum"] += days
                            
                            if outcome == "WIN":
                                res["win_count"] += 1
                                res["win_pnl_sum"] += pnl
                            elif outcome == "LOSS":
                                res["loss_count"] += 1
                                res["loss_pnl_sum"] += pnl
                            if outcome == "TIMEOUT":
                                res["timeout_count"] += 1
                                res["timeout_pnl_sum"] += pnl
                            
                            if args.export_trades:
                                all_trades.append({
                                    "trend_filter": args.trend_filter,
                                    "base_duration": dur,
                                    "base_range": rng,
                                    "stop_variant": stp,
                                    "round_trip_friction": fric,
                                    "symbol": cand["symbol"],
                                    "setup_date": cand["setup_date"],
                                    "base_start_date": cand["base_start_date"],
                                    "base_end_date": cand["base_end_date"],
                                    "base_high": round(cand["base_high"], 2),
                                    "base_low": round(cand["base_low"], 2),
                                    "breakout_date": cand["breakout_date"],
                                    "breakout_close": round(cand["breakout_close"], 2),
                                    "entry_date": cand["entry_date"],
                                    "entry_price": round(cand["entry_price"], 2),
                                    "stop_price": round(stop_price, 2),
                                    "target_price": round(target_price, 2),
                                    "exit_date": cand["fw_dates"][days - 1],
                                    "exit_price": round(exit_price, 2),
                                    "outcome": outcome,
                                    "realized_pnl": round(pnl, 4),
                                    "days_in_trade": days,
                                    "stop_pct": round(stop_pct, 4)
                                })

        if i % 50 == 0 or i == len(symbols):
            elapsed = time.time() - t0
            print(f"Processed {i}/{len(symbols)} symbols in {elapsed:.1f}s...", flush=True)
            
    # Baseline check
    baseline = grid_results.get((30, 0.06, "base_low_stop", 0.0015))
    if baseline:
        print(f"\n[Baseline Verification] duration=30, range=0.06: Candidate Count = {baseline['candidate_count']} (Expected: 40)", flush=True)
        
    rows = []
    for (dur, rng, stp, fric), res in grid_results.items():
        count = res["candidate_count"]
        if count == 0:
            continue
            
        win_rate = res["win_count"] / count
        avg_win = res["win_pnl_sum"] / res["win_count"] if res["win_count"] > 0 else 0.0
        avg_loss = res["loss_pnl_sum"] / res["loss_count"] if res["loss_count"] > 0 else 0.0
        avg_timeout_return = res["timeout_pnl_sum"] / res["timeout_count"] if res["timeout_count"] > 0 else 0.0
        expectancy = np.mean(res["returns"])
        median_return = np.median(res["returns"])
        
        gross_profit = sum(p for p in res["returns"] if p > 0)
        gross_loss = abs(sum(p for p in res["returns"] if p < 0))
        
        if gross_loss == 0 and gross_profit > 0:
            profit_factor = float('inf')
        elif gross_loss == 0 and gross_profit == 0:
            profit_factor = 0.0
        else:
            profit_factor = gross_profit / gross_loss
            
        worst_realized_pnl = min(res["returns"])
        avg_stop_pct = np.mean(res["stop_pcts"])
        median_stop_pct = np.median(res["stop_pcts"])
        p25_stop_pct = np.percentile(res["stop_pcts"], 25)
        p75_stop_pct = np.percentile(res["stop_pcts"], 75)
        avg_days_in_trade = res["days_in_trade_sum"] / count
        timeouts_pct = res["timeout_count"] / count
        
        rows.append({
            "trend_filter": args.trend_filter,
            "base_duration": dur,
            "base_range": rng,
            "stop_variant": stp,
            "round_trip_friction": fric,
            "candidate_count": count,
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "avg_timeout_return": round(avg_timeout_return, 4),
            "expectancy": round(expectancy, 4),
            "median_return": round(median_return, 4),
            "profit_factor": round(profit_factor, 4),
            "worst_realized_pnl": round(worst_realized_pnl, 4),
            "avg_stop_pct": round(avg_stop_pct, 4),
            "median_stop_pct": round(median_stop_pct, 4),
            "p25_stop_pct": round(p25_stop_pct, 4),
            "p75_stop_pct": round(p75_stop_pct, 4),
            "avg_days_in_trade": round(avg_days_in_trade, 2),
            "timeouts_pct": round(timeouts_pct, 4)
        })

    out_df = pd.DataFrame(rows)
    out_dir = Path(r"D:\app\data\exports\sweep_sideways_expectancy")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if args.trend_filter == "none":
        matrix_filename = "sweep_robustness_matrix.csv"
        trades_filename = "sweep_robustness_trades.csv"
    else:
        matrix_filename = f"sweep_robustness_matrix_trend_{args.trend_filter}.csv"
        trades_filename = f"sweep_robustness_trades_trend_{args.trend_filter}.csv"
        
    out_path = out_dir / matrix_filename
    
    out_df.to_csv(out_path, index=False)
    print(f"Exported {len(rows)} matrix rows to: {out_path}", flush=True)

    if args.export_trades and all_trades:
        trades_df = pd.DataFrame(all_trades)
        trades_path = out_dir / trades_filename
        trades_df.to_csv(trades_path, index=False)
        print(f"Exported {len(trades_df)} individual trade rows to: {trades_path}", flush=True)

if __name__ == "__main__":
    main()
