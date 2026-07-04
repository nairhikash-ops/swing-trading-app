import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_DB_PATH = Path(
    r"D:\app\data\evaluations\v3_signal_state_backtest_v1\recovered_artifacts\dhan_auth.sqlite3"
)
UPTREND_TRADES_CSV = Path(
    r"D:\app\data\exports\sweep_sideways_expectancy\sideways_uptrend_trades.csv"
)
OUT_DIR = Path(r"D:\app\data\exports\sweep_sideways_expectancy\uptrend_sideways_branch")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024 * 10), b""):
            h.update(chunk)
    return h.hexdigest()


def load_price_history(symbols: pd.Series) -> dict[str, dict[str, np.ndarray]]:
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
            WHERE ic.active = 1
            """,
            conn,
        )
        symbols_df["symbol"] = symbols_df["symbol"].astype(str).str.upper()
        symbols_df = symbols_df.drop_duplicates("symbol")
        ids = (
            symbols_df[symbols_df["symbol"].isin(symbols.astype(str).str.upper().unique())][
                "instrument_id"
            ]
            .astype(int)
            .tolist()
        )
        placeholders = ",".join("?" for _ in ids)
        candles = pd.read_sql_query(
            f"""
            SELECT instrument_id, trading_date, high, low
            FROM daily_candles
            WHERE instrument_id IN ({placeholders})
            ORDER BY instrument_id, trading_date
            """,
            conn,
            params=ids,
        )

    candles = candles.merge(symbols_df[["symbol", "instrument_id"]], on="instrument_id")
    candles["trading_date"] = pd.to_datetime(candles["trading_date"])
    candles["high"] = pd.to_numeric(candles["high"], errors="coerce")
    candles["low"] = pd.to_numeric(candles["low"], errors="coerce")
    out = {}
    for symbol, group in candles.groupby("symbol", sort=False):
        group = group.sort_values("trading_date").reset_index(drop=True)
        out[symbol] = {
            "dates": group["trading_date"].to_numpy(dtype="datetime64[ns]"),
            "highs": group["high"].to_numpy(dtype=float),
            "lows": group["low"].to_numpy(dtype=float),
        }
    return out


def first_range_break(highs: np.ndarray, lows: np.ndarray, base_high: float, base_low: float) -> str:
    for high, low in zip(highs, lows):
        broke_down = low < base_low
        broke_up = high > base_high
        if broke_down and broke_up:
            return "same_day_both"
        if broke_down:
            return "downward_first"
        if broke_up:
            return "upward_first"
    return "no_break"


def main() -> None:
    if not DEFAULT_DB_PATH.exists():
        raise FileNotFoundError(DEFAULT_DB_PATH)
    if not UPTREND_TRADES_CSV.exists():
        raise FileNotFoundError(UPTREND_TRADES_CSV)

    print("--- Uptrend Sideways Branch Analysis ---")
    print(f"DB Path: {DEFAULT_DB_PATH}")
    print(f"DB SHA256: {file_sha256(DEFAULT_DB_PATH)}")
    print(f"Source CSV: {UPTREND_TRADES_CSV}")

    trades = pd.read_csv(UPTREND_TRADES_CSV, parse_dates=["base_end_date"])
    identity_cols = ["symbol", "base_start_date", "base_end_date", "setup_date", "entry_date"]
    unique = trades.drop_duplicates(identity_cols).copy()
    print(f"Unique uptrend-sideways instances: {len(unique)}")

    prices_by_symbol = load_price_history(unique["symbol"])

    branch_rows = []
    for _, row in unique.iterrows():
        symbol = str(row["symbol"]).upper()
        price_data = prices_by_symbol.get(symbol)
        if price_data is None:
            continue

        dates = price_data["dates"]
        highs = price_data["highs"]
        lows = price_data["lows"]
        start = int(np.searchsorted(dates, np.datetime64(row["base_end_date"]), side="right"))
        if start >= len(dates):
            continue
        path_highs = highs[start:]
        path_lows = lows[start:]

        base_high = float(row["base_high"])
        base_low = float(row["base_low"])
        branch = first_range_break(path_highs, path_lows, base_high, base_low)

        max_return_any = (float(np.max(path_highs)) / base_high) - 1
        first_40_highs = path_highs[:40]
        max_return_40 = (float(np.max(first_40_highs)) / base_high) - 1

        branch_rows.append(
            {
                **row.to_dict(),
                "range_break_branch": branch,
                "max_return_from_base_high_any": max_return_any,
                "max_return_from_base_high_40d": max_return_40,
                "reached_10pct_above_base_high_any": bool(max_return_any >= 0.10),
                "reached_10pct_above_base_high_40d": bool(max_return_40 >= 0.10),
            }
        )

    result = pd.DataFrame(branch_rows)

    eventually_up = result[result["exit_price"] > result["entry_price"]].copy()
    branch_a = eventually_up[eventually_up["range_break_branch"] == "upward_first"].copy()
    branch_b = eventually_up[eventually_up["range_break_branch"] == "same_day_both"].copy()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_DIR / "uptrend_sideways_unique_branch_all.csv", index=False)
    eventually_up.to_csv(OUT_DIR / "uptrend_sideways_eventually_up.csv", index=False)
    branch_a.to_csv(OUT_DIR / "branch_a_upward_first.csv", index=False)
    branch_b.to_csv(OUT_DIR / "branch_b_same_day_both.csv", index=False)

    summary = {
        "source": {
            "db_path": str(DEFAULT_DB_PATH),
            "db_sha256": file_sha256(DEFAULT_DB_PATH),
            "uptrend_trades_csv": str(UPTREND_TRADES_CSV),
        },
        "counts": {
            "unique_uptrend_sideways_instances": int(len(unique)),
            "eventually_up_instances": int(len(eventually_up)),
            "branch_a_upward_first": int(len(branch_a)),
            "branch_b_same_day_both": int(len(branch_b)),
            "downward_first_among_eventually_up": int(
                (eventually_up["range_break_branch"] == "downward_first").sum()
            ),
        },
        "branch_a_return_from_base_high": {
            "reached_10pct_40d_count": int(
                branch_a["reached_10pct_above_base_high_40d"].sum()
            ),
            "reached_10pct_40d_pct": float(
                branch_a["reached_10pct_above_base_high_40d"].mean()
            ),
            "reached_10pct_any_count": int(
                branch_a["reached_10pct_above_base_high_any"].sum()
            ),
            "reached_10pct_any_pct": float(
                branch_a["reached_10pct_above_base_high_any"].mean()
            ),
            "highest_return_40d_pct": float(
                branch_a["max_return_from_base_high_40d"].max() * 100
            ),
            "average_return_40d_pct": float(
                branch_a["max_return_from_base_high_40d"].mean() * 100
            ),
            "median_return_40d_pct": float(
                branch_a["max_return_from_base_high_40d"].median() * 100
            ),
            "highest_return_any_pct": float(
                branch_a["max_return_from_base_high_any"].max() * 100
            ),
            "average_return_any_pct": float(
                branch_a["max_return_from_base_high_any"].mean() * 100
            ),
            "median_return_any_pct": float(
                branch_a["max_return_from_base_high_any"].median() * 100
            ),
        },
    }

    with (OUT_DIR / "uptrend_sideways_branch_summary.json").open("w") as f:
        json.dump(summary, f, indent=4)

    print(json.dumps(summary["counts"], indent=4))
    print(json.dumps(summary["branch_a_return_from_base_high"], indent=4))
    print(f"Exports written to: {OUT_DIR}")


if __name__ == "__main__":
    main()
