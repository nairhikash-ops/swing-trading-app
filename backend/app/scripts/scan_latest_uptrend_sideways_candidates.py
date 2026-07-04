import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd


DEFAULT_DB_PATH = Path(
    r"D:\app\data\evaluations\v3_signal_state_backtest_v1\recovered_artifacts\dhan_auth.sqlite3"
)
OUT_DIR = Path(r"D:\app\data\exports\uptrend_sideways_latest")

BASE_DAYS = 30
BASE_RANGE_MAX = 0.08
PRE_RETURN_DAYS = 60
PRE_RETURN_MIN = 0.10
BREAKOUT_BUFFER = 1.005


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024 * 10), b""):
            h.update(chunk)
    return h.hexdigest()


def load_candles() -> pd.DataFrame:
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        symbols_df = pd.read_sql_query(
            """
            SELECT ic.symbol AS symbol, i.id AS instrument_id
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
            """,
            conn,
        )
        ids = symbols_df["instrument_id"].dropna().astype(int).unique().tolist()
        placeholders = ",".join("?" for _ in ids)
        candles = pd.read_sql_query(
            f"""
            SELECT instrument_id, trading_date, open, high, low, close, volume
            FROM daily_candles
            WHERE instrument_id IN ({placeholders})
            ORDER BY instrument_id, trading_date
            """,
            conn,
            params=ids,
        )

    symbols_df["symbol"] = symbols_df["symbol"].astype(str).str.upper()
    symbols_df = symbols_df.drop_duplicates("instrument_id")
    candles = candles.merge(symbols_df[["instrument_id", "symbol"]], on="instrument_id")
    candles["trading_date"] = pd.to_datetime(candles["trading_date"])
    for col in ["open", "high", "low", "close", "volume"]:
        candles[col] = pd.to_numeric(candles[col], errors="coerce")
    return candles.dropna(subset=["open", "high", "low", "close"]).sort_values(
        ["symbol", "trading_date"]
    )


def scan_symbol(symbol: str, df: pd.DataFrame) -> dict | None:
    df = df.sort_values("trading_date").reset_index(drop=True)
    if len(df) < BASE_DAYS + PRE_RETURN_DAYS + 2:
        return None

    latest_idx = len(df) - 1
    base_start_idx = latest_idx - BASE_DAYS
    base_end_idx = latest_idx - 1
    pre_start_idx = base_start_idx - PRE_RETURN_DAYS
    pre_end_idx = base_start_idx - 1
    if pre_start_idx < 0:
        return None

    base = df.iloc[base_start_idx:latest_idx]
    latest = df.iloc[latest_idx]
    base_high = float(base["high"].max())
    base_low = float(base["low"].min())
    if base_low <= 0:
        return None
    base_range_pct = (base_high - base_low) / base_low
    if base_range_pct > BASE_RANGE_MAX:
        return None

    pre_start_close = float(df.iloc[pre_start_idx]["close"])
    pre_end_close = float(df.iloc[pre_end_idx]["close"])
    if pre_start_close <= 0:
        return None
    pre_return = (pre_end_close / pre_start_close) - 1
    if pre_return < PRE_RETURN_MIN:
        return None

    latest_close = float(latest["close"])
    latest_high = float(latest["high"])
    latest_low = float(latest["low"])

    broke_up_today = latest_close >= base_high * BREAKOUT_BUFFER
    broke_down_today = latest_low < base_low
    still_in_base = latest_close <= base_high and latest_low >= base_low
    near_breakout = latest_close >= base_high * 0.98 and latest_low >= base_low

    if not (broke_up_today or still_in_base or near_breakout):
        return None

    if broke_up_today and broke_down_today:
        status = "same_day_both"
    elif broke_up_today:
        status = "breakout_today"
    elif near_breakout:
        status = "near_breakout_watch"
    else:
        status = "in_base_watch"

    return {
        "symbol": symbol,
        "latest_date": latest["trading_date"].strftime("%Y-%m-%d"),
        "status": status,
        "base_start_date": df.iloc[base_start_idx]["trading_date"].strftime("%Y-%m-%d"),
        "base_end_date": df.iloc[base_end_idx]["trading_date"].strftime("%Y-%m-%d"),
        "base_high": round(base_high, 2),
        "base_low": round(base_low, 2),
        "base_range_pct": round(base_range_pct, 4),
        "pre_structure_return_60d": round(pre_return, 4),
        "latest_close": round(latest_close, 2),
        "latest_high": round(latest_high, 2),
        "latest_low": round(latest_low, 2),
        "breakout_trigger_close": round(base_high * BREAKOUT_BUFFER, 2),
        "distance_to_base_high_pct": round((base_high - latest_close) / latest_close, 4),
        "target_10pct_from_base_high": round(base_high * 1.10, 2),
    }


def main() -> None:
    if not DEFAULT_DB_PATH.exists():
        raise FileNotFoundError(DEFAULT_DB_PATH)

    print("--- Latest Uptrend Sideways Candidate Scan ---")
    print(f"DB Path: {DEFAULT_DB_PATH}")
    print(f"DB SHA256: {file_sha256(DEFAULT_DB_PATH)}")
    candles = load_candles()
    latest_date = candles["trading_date"].max().strftime("%Y-%m-%d")
    print(f"Loaded rows: {len(candles)}")
    print(f"Symbols: {candles['symbol'].nunique()}")
    print(f"Latest candle date: {latest_date}")

    rows = []
    for symbol, group in candles.groupby("symbol", sort=True):
        row = scan_symbol(symbol, group)
        if row is not None:
            rows.append(row)

    columns = [
        "symbol",
        "latest_date",
        "status",
        "base_start_date",
        "base_end_date",
        "base_high",
        "base_low",
        "base_range_pct",
        "pre_structure_return_60d",
        "latest_close",
        "latest_high",
        "latest_low",
        "breakout_trigger_close",
        "distance_to_base_high_pct",
        "target_10pct_from_base_high",
    ]
    out = pd.DataFrame(rows, columns=columns)
    if len(out):
        out = out.sort_values(["status", "distance_to_base_high_pct", "symbol"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / "latest_uptrend_sideways_candidates.csv"
    out_json = OUT_DIR / "latest_uptrend_sideways_scan_summary.json"
    out.to_csv(out_csv, index=False)

    summary = {
        "db_path": str(DEFAULT_DB_PATH),
        "db_sha256": file_sha256(DEFAULT_DB_PATH),
        "latest_candle_date": latest_date,
        "rule": {
            "base_days": BASE_DAYS,
            "base_range_max": BASE_RANGE_MAX,
            "pre_return_days": PRE_RETURN_DAYS,
            "pre_return_min": PRE_RETURN_MIN,
            "breakout_buffer": BREAKOUT_BUFFER,
        },
        "total_candidates": int(len(out)),
        "status_counts": out["status"].value_counts().to_dict() if len(out) else {},
        "output_csv": str(out_csv),
    }
    with out_json.open("w") as f:
        json.dump(summary, f, indent=4)

    print(json.dumps(summary, indent=4))


if __name__ == "__main__":
    main()
