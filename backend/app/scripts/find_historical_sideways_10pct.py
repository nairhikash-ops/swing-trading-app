import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_DB_PATH = Path(
    r"D:\app\data\evaluations\v3_signal_state_backtest_v1\recovered_artifacts\dhan_auth.sqlite3"
)
OUTPUT_CSV = Path(r"D:\app\data\exports\find_historical_sideways_10pct\sideways_breakouts_10pct.csv")


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
        raise ValueError(f"{label} must be local-only, got forbidden path/value: {path_text}")


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
    return df


def process_symbol(symbol: str, df: pd.DataFrame, dedup_days: int) -> list[dict]:
    df = df.sort_values("trading_date").reset_index(drop=True)
    if len(df) < 80:
        return []

    # Calculate ADTV20 and VolAvg20
    df["turnover"] = df["close"] * df["volume"]
    
    # We use shift(1) so that at index i, the rolling features are from [i-20 : i-1]
    df["adtv20_pre"] = df["turnover"].rolling(20).mean().shift(1)
    df["vol20_pre"] = df["volume"].rolling(20).mean().shift(1)

    candidates = []
    last_setup_idx = -9999
    
    # Needs at least 30 days for base, 1 day for breakout, plus 40 days forward.
    for i in range(30, len(df) - 1):
        if i - last_setup_idx < dedup_days:
            continue
            
        if len(df) - i - 1 < 40:
            continue
        # Base is i-30 to i-1
        base_window = df.iloc[i-30 : i]
        
        base_high = base_window["high"].max()
        base_low = base_window["low"].min()
        
        if base_low <= 0:
            continue
            
        base_range_pct = (base_high - base_low) / base_low
        
        if base_range_pct > 0.06:
            continue
            
        breakout_row = df.iloc[i]
        close_i = breakout_row["close"]
        vol_i = breakout_row["volume"]
        adtv20 = breakout_row["adtv20_pre"]
        vol20 = breakout_row["vol20_pre"]
        
        if pd.isna(adtv20) or pd.isna(vol20) or adtv20 < 10_000_000:
            continue
            
        # Breakout criteria
        if close_i < base_high * 1.005:
            continue
            
        if vol_i < vol20 * 1.5:
            continue
            
        # Valid candidate!
        entry_idx = i + 1
        entry_row = df.iloc[entry_idx]
        entry_price = entry_row["open"]
        
        if entry_price <= 0:
            continue
            
        stop_price = base_low
        stop_pct = (entry_price - stop_price) / entry_price
        target_price = entry_price * 1.10
        
        # Determine outcome over max 40 days
        forward_window = df.iloc[entry_idx : entry_idx + 40]
        
        touched_10pct = False
        outcome = "TIMEOUT"
        exit_date = forward_window.iloc[-1]["trading_date"] if not forward_window.empty else entry_row["trading_date"]
        
        max_high = forward_window["high"].max()
        min_low = forward_window["low"].min()
        max_return = (max_high - entry_price) / entry_price
        max_drawdown = (min_low - entry_price) / entry_price
        
        target_hit_date = None
        days_to_target = None
        
        # MFE check
        if max_high >= target_price:
            touched_10pct = True
            hit_row = forward_window[forward_window["high"] >= target_price].iloc[0]
            target_hit_date = hit_row["trading_date"].strftime("%Y-%m-%d")
            days_to_target = int(hit_row.name - entry_idx) + 1
            
        # Strategy outcome (Pessimistic)
        for _, day_row in forward_window.iterrows():
            d_low = day_row["low"]
            d_high = day_row["high"]
            d_date = day_row["trading_date"]
            
            hit_stop = d_low <= stop_price
            hit_target = d_high >= target_price
            
            if hit_stop and hit_target:
                # Same day ambiguity -> Pessimistic handling
                outcome = "STOPPED_BEFORE_TARGET"
                exit_date = d_date
                break
            elif hit_stop:
                outcome = "STOPPED_BEFORE_TARGET"
                exit_date = d_date
                break
            elif hit_target:
                outcome = "WIN_10PCT"
                exit_date = d_date
                break

        candidates.append({
            "symbol": symbol,
            "setup_date": breakout_row["trading_date"].strftime("%Y-%m-%d"),
            "entry_date": entry_row["trading_date"].strftime("%Y-%m-%d"),
            "entry_price": round(entry_price, 2),
            "stop_price": round(stop_price, 2),
            "stop_pct": round(stop_pct, 4),
            "target_price": round(target_price, 2),
            "breakout_close": round(close_i, 2),
            "breakout_volume": float(vol_i),
            "adtv20": round(float(adtv20), 2),
            "base_start_date": base_window.iloc[0]["trading_date"].strftime("%Y-%m-%d"),
            "base_end_date": base_window.iloc[-1]["trading_date"].strftime("%Y-%m-%d"),
            "base_high": round(base_high, 2),
            "base_low": round(base_low, 2),
            "base_range_pct": round(base_range_pct, 4),
            "max_return": round(max_return, 4),
            "max_drawdown": round(max_drawdown, 4),
            "touched_10pct_within_40d": touched_10pct,
            "target_hit_date": target_hit_date,
            "days_to_target": days_to_target,
            "trade_outcome_with_base_low_stop": outcome,
            "first_exit_reason": outcome,
            "first_exit_date": exit_date.strftime("%Y-%m-%d"),
        })
        last_setup_idx = i
        
    return candidates


def main():
    parser = argparse.ArgumentParser(description="Find historical sideways breakouts reaching +10%.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Local SQLite DB path.")
    parser.add_argument("--dedup-days", type=int, default=15, help="Minimum days between setups for the same symbol.")
    args = parser.parse_args()

    reject_nonlocal_path(str(args.db_path), "db-path")

    print("--- Historical Scan Proof ---", flush=True)
    print("WARNING: This is a CURRENT-UNIVERSE HISTORICAL SCAN (Discovery tool).", flush=True)
    print("Survivorship bias exists as delisted/removed symbols are excluded.", flush=True)
    print(f"DB Path: {args.db_path}", flush=True)
    print(f"DB Hash: {get_file_hash(args.db_path)}", flush=True)
    
    candles = load_local_candles(args.db_path)
    symbols = sorted(candles["symbol"].unique())
    print(f"Loaded candle rows: {len(candles)}", flush=True)
    print(f"Symbols: {len(symbols)}", flush=True)
    print(f"Date range: {candles['trading_date'].min().date()} to {candles['trading_date'].max().date()}", flush=True)
    print("-----------------------------\n", flush=True)

    all_candidates = []
    grouped = candles.groupby("symbol", sort=True)
    for i, symbol in enumerate(symbols, 1):
        cands = process_symbol(symbol, grouped.get_group(symbol), args.dedup_days)
        all_candidates.extend(cands)
        if i % 100 == 0 or i == len(symbols):
            print(f"Processed {i}/{len(symbols)} symbols...", flush=True)

    df = pd.DataFrame(all_candidates)
    print(f"\nTotal Candidates Found: {len(df)}", flush=True)
    
    if len(df) > 0:
        win_count = len(df[df["trade_outcome_with_base_low_stop"] == "WIN_10PCT"])
        stop_count = len(df[df["trade_outcome_with_base_low_stop"] == "STOPPED_BEFORE_TARGET"])
        timeout_count = len(df[df["trade_outcome_with_base_low_stop"] == "TIMEOUT"])
        touched_count = df["touched_10pct_within_40d"].sum()
        
        print("\n--- Outcome Summary ---")
        print(f"WIN_10PCT: {win_count}")
        print(f"STOPPED_BEFORE_TARGET: {stop_count}")
        print(f"TIMEOUT: {timeout_count}")
        print(f"Touched 10% (Pure MFE): {touched_count}")
        print("-----------------------")

        print("\n--- 5 Example Trades (Mixed Outcomes) ---")
        sample_df = df.sample(min(5, len(df)), random_state=42)
        cols_to_print = ["symbol", "setup_date", "stop_pct", "trade_outcome_with_base_low_stop", "touched_10pct_within_40d"]
        print(sample_df[cols_to_print].to_string(index=False))

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nExported {len(df)} rows to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
