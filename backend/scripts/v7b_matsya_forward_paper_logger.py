from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


DEFAULT_BASE_URL = "http://100.76.218.124:8020"
EXPORT_DIR = Path(r"D:\app\data\exports\forward_paper_log_matsya")
PORTFOLIO_FILE = EXPORT_DIR / "forward_paper_portfolio.json"
LEDGER_FILE = EXPORT_DIR / "forward_paper_trade_ledger.csv"
DAILY_LOG_FILE = EXPORT_DIR / "forward_paper_daily_log.csv"
SIGNALS_FILE = EXPORT_DIR / "forward_paper_signals.csv"
FETCH_FAILURES_FILE = EXPORT_DIR / "forward_paper_fetch_failures.json"

MAX_SLOTS = 5
FRICTION_BASE = 0.0025
FRICTION_HARSH = 0.0050
MIN_AVG_TRADED_VALUE_20D = 10_000_000
LOOKBACK_DAYS = 420
RANK_LOOKBACK = 60


def round_money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def set_output_dir(log_dir: str) -> None:
    global EXPORT_DIR, PORTFOLIO_FILE, LEDGER_FILE, DAILY_LOG_FILE, SIGNALS_FILE, FETCH_FAILURES_FILE
    EXPORT_DIR = Path(log_dir)
    PORTFOLIO_FILE = EXPORT_DIR / "forward_paper_portfolio.json"
    LEDGER_FILE = EXPORT_DIR / "forward_paper_trade_ledger.csv"
    DAILY_LOG_FILE = EXPORT_DIR / "forward_paper_daily_log.csv"
    SIGNALS_FILE = EXPORT_DIR / "forward_paper_signals.csv"
    FETCH_FAILURES_FILE = EXPORT_DIR / "forward_paper_fetch_failures.json"


def request_json(base_url: str, path: str, params: dict[str, object] | None = None, timeout: float = 30.0) -> dict:
    query = f"?{urlencode(params)}" if params else ""
    url = f"{base_url.rstrip('/')}{path}{query}"
    request = Request(url, method="GET", headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class MatsyaClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def status(self) -> dict:
        return request_json(self.base_url, "/api/matsya/market-data/status", timeout=self.timeout)

    def symbols(self) -> list[dict]:
        payload = request_json(
            self.base_url,
            "/api/matsya/market-data/symbols",
            {"universe": "NIFTY_500", "limit": 5000, "offset": 0},
            timeout=self.timeout,
        )
        return payload.get("symbols", [])

    def latest_ohlcv(self, symbol: str, days: int, security_id: str | None = None) -> list[dict]:
        params = {"days": days}
        if security_id:
            params["security_id"] = security_id
        else:
            params["symbol"] = symbol
        payload = request_json(
            self.base_url,
            "/api/matsya/market-data/ohlcv/latest",
            params,
            timeout=self.timeout,
        )
        return payload.get("candles", [])


def load_state(starting_equity: float) -> dict:
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    return {
        "last_run_date": None,
        "cash": float(starting_equity),
        "pending_orders": [],
        "open_positions": [],
    }


def save_state(state: dict) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    PORTFOLIO_FILE.write_text(json.dumps(state, indent=4), encoding="utf-8")


def append_csv(file_path: Path, row_dict: dict) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([row_dict])
    if file_path.exists():
        row.to_csv(file_path, mode="a", header=False, index=False)
    else:
        row.to_csv(file_path, index=False)


def candles_to_frame(symbol: str, candles: list[dict]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df["symbol"] = symbol
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["trading_date", "open", "high", "low", "close", "volume"])
    return df.sort_values("trading_date").reset_index(drop=True)


def fetch_universe_candles(client: MatsyaClient, days: int, max_workers: int) -> tuple[dict[str, pd.DataFrame], dict]:
    symbols = client.symbols()
    symbol_rows = [
        {"symbol": row["symbol"], "security_id": row.get("security_id")}
        for row in symbols
        if row.get("symbol")
    ]
    candles_by_symbol: dict[str, pd.DataFrame] = {}
    failures: dict[str, str] = {}

    def fetch(row: dict) -> tuple[str, pd.DataFrame]:
        symbol = row["symbol"]
        security_id = row.get("security_id")
        return symbol, candles_to_frame(symbol, client.latest_ohlcv(symbol, days, security_id=security_id))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch, row): row["symbol"] for row in symbol_rows}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                sym, df = future.result()
                if not df.empty:
                    candles_by_symbol[sym] = df
                else:
                    failures[sym] = "empty_candles"
            except Exception as exc:
                failures[symbol] = str(exc)

    return candles_by_symbol, {"symbols_requested": len(symbol_rows), "fetch_failures": failures}


def build_market_returns(candles_by_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for symbol, df in candles_by_symbol.items():
        temp = df[["trading_date", "close"]].copy()
        temp["symbol"] = symbol
        temp["daily_return"] = temp["close"].pct_change()
        rows.append(temp[["symbol", "trading_date", "daily_return"]])
    if not rows:
        return pd.DataFrame(columns=["trading_date", "market_return"]).set_index("trading_date")
    all_returns = pd.concat(rows, ignore_index=True)
    market = all_returns.groupby("trading_date")["daily_return"].mean().to_frame("market_return")
    return market.sort_index()


def compute_base_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if len(df) < 250:
        return df
    df["sma50"] = df["close"].rolling(50).mean()
    df["high_20"] = df["high"].rolling(20).max()
    df["low_250"] = df["low"].shift(1).rolling(250).min()
    df["vol_20"] = df["volume"].rolling(20).mean()
    df["value"] = df["close"] * df["volume"]
    df["avg_traded_value_20d"] = df["value"].rolling(20).mean()
    df["range"] = df["high"] - df["low"]
    df["lower_wick"] = np.minimum(df["open"], df["close"]) - df["low"]
    df["close_pct"] = (df["close"] - df["low"]) / df["range"].replace(0, 1e-5)
    df["drop_from_high"] = (df["high_20"] - df["low"]) / df["high_20"]
    df["is_5d_low"] = df["low"] == df["low"].rolling(5).min()
    df["is_crash"] = (df["drop_from_high"] >= 0.15) & df["is_5d_low"] & (df["close"] < df["sma50"])
    return df


def down_market_capture_60d(df: pd.DataFrame, market_df: pd.DataFrame, conf_idx: int) -> tuple[float | None, bool]:
    if conf_idx < RANK_LOOKBACK:
        return None, False
    window = df.iloc[conf_idx - RANK_LOOKBACK + 1 : conf_idx + 1].copy()
    if len(window) != RANK_LOOKBACK:
        return None, False
    market_slice = market_df.reindex(window["trading_date"])
    if market_slice["market_return"].isna().any():
        return None, False
    stock_rets = window["daily_return"].to_numpy()
    market_rets = market_slice["market_return"].to_numpy()
    down_mask = market_rets < 0
    if down_mask.sum() == 0:
        return None, False
    stock_down = float(np.prod(1 + stock_rets[down_mask]) - 1)
    market_down = float(np.prod(1 + market_rets[down_mask]) - 1)
    if market_down == 0 or math.isnan(stock_down) or math.isnan(market_down):
        return None, False
    return stock_down / market_down, True


def find_confirmed_higher_low_signal(
    symbol: str,
    df_raw: pd.DataFrame,
    market_df: pd.DataFrame,
    as_of_date: str,
) -> dict | None:
    df = compute_base_features(df_raw)
    if "is_crash" not in df.columns:
        return None
    df["daily_return"] = df["close"].pct_change()
    crash_indices = df.index[df["is_crash"]].tolist()
    last_entry = -999
    as_of_ts = pd.to_datetime(as_of_date)

    for idx in crash_indices:
        if idx < last_entry + 15:
            continue
        if idx + 1 >= len(df):
            continue

        crash_date = df.at[idx, "trading_date"]
        reaction_high_price = df.at[idx, "high"]
        reaction_high_date = crash_date
        crash_low_price = df.at[idx, "low"]
        higher_low_price = None
        higher_low_date = None
        higher_low_formed = False
        breakout_idx = -1

        for i in range(1, 15):
            curr = idx + i
            if curr >= len(df):
                break
            if df.at[curr, "low"] < crash_low_price:
                break
            if df.at[curr, "high"] > reaction_high_price and higher_low_formed:
                breakout_idx = curr
                break
            if df.at[curr, "low"] > crash_low_price and df.at[curr, "low"] < df.at[curr - 1, "low"]:
                higher_low_formed = True
                higher_low_price = df.at[curr, "low"]
                higher_low_date = df.at[curr, "trading_date"]
            if df.at[curr, "high"] > reaction_high_price:
                reaction_high_price = df.at[curr, "high"]
                reaction_high_date = df.at[curr, "trading_date"]

        if breakout_idx == -1:
            last_entry = idx + 1
            continue

        confirmation_date = df.at[breakout_idx, "trading_date"]
        entry_idx = breakout_idx + 1
        last_entry = entry_idx
        if confirmation_date != as_of_ts:
            continue

        avg_tv = df.at[breakout_idx, "avg_traded_value_20d"]
        liquidity_pass = pd.notna(avg_tv) and avg_tv > MIN_AVG_TRADED_VALUE_20D
        capture, capture_available = down_market_capture_60d(df, market_df, breakout_idx)
        if not liquidity_pass or not capture_available:
            return None

        return {
            "symbol": symbol,
            "crash_date": crash_date.strftime("%Y-%m-%d"),
            "confirmation_date": confirmation_date.strftime("%Y-%m-%d"),
            "reaction_high_date": reaction_high_date.strftime("%Y-%m-%d"),
            "reaction_high_price": float(reaction_high_price),
            "higher_low_date": higher_low_date.strftime("%Y-%m-%d") if higher_low_date is not None else None,
            "higher_low_price": float(higher_low_price) if higher_low_price is not None else None,
            "avg_traded_value_20d": float(avg_tv),
            "liquidity_cap": float(avg_tv) * 0.01,
            "down_market_capture_60d": float(capture),
            "down_market_capture_60d_available": bool(capture_available),
            "entry_known": entry_idx < len(df),
            "entry_date_if_known": df.at[entry_idx, "trading_date"].strftime("%Y-%m-%d") if entry_idx < len(df) else None,
        }

    return None


def latest_candle_for_date(candles_by_symbol: dict[str, pd.DataFrame], symbol: str, date_str: str) -> dict | None:
    df = candles_by_symbol.get(symbol)
    if df is None or df.empty:
        return None
    rows = df[df["trading_date"] == pd.to_datetime(date_str)]
    if rows.empty:
        return None
    return rows.iloc[-1].to_dict()


def process_pending_orders(state: dict, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> list[str]:
    filled = []
    remaining = []
    for order in state["pending_orders"]:
        candle = latest_candle_for_date(candles_by_symbol, order["symbol"], as_of_date)
        if not candle or pd.isna(candle["open"]):
            remaining.append(order)
            continue

        raw_open = float(candle["open"])
        effective_entry = raw_open * (1 + FRICTION_BASE)
        harsh_entry = raw_open * (1 + FRICTION_HARSH)
        raw_stop_price = round_money(raw_open * 0.95)
        raw_target_price = round_money(raw_open * 1.10)
        position_value = min(float(order["target_allocation"]), float(order["liquidity_cap"]))
        shares = int(position_value / effective_entry)

        if shares > 0 and shares * effective_entry <= state["cash"]:
            invested = shares * effective_entry
            state["cash"] -= invested
            state["open_positions"].append(
                {
                    "symbol": order["symbol"],
                    "entry_date": as_of_date,
                    "signal_date": order["signal_date"],
                    "shares": shares,
                    "raw_entry_price": raw_open,
                    "entry_price": effective_entry,
                    "harsh_entry_price": harsh_entry,
                    "raw_target_price": raw_target_price,
                    "raw_stop_price": raw_stop_price,
                    "target_price": raw_target_price,
                    "stop_price": raw_stop_price,
                    "bars_held": 0,
                    "invested_value": invested,
                    "source": "matsya_api",
                }
            )
            filled.append(order["symbol"])
        else:
            remaining.append(order)

    state["pending_orders"] = remaining
    return filled


def process_open_positions(state: dict, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> list[dict]:
    closed = []
    remaining = []
    for pos in state["open_positions"]:
        candle = latest_candle_for_date(candles_by_symbol, pos["symbol"], as_of_date)
        if not candle:
            remaining.append(pos)
            continue
        pos["bars_held"] += 1
        hit_target = float(candle["high"]) >= float(pos["target_price"])
        hit_stop = float(candle["low"]) <= float(pos["stop_price"])
        exit_triggered = False
        raw_exit_price = 0.0
        reason = ""
        if hit_stop and hit_target:
            exit_triggered = True
            raw_exit_price = float(pos["stop_price"])
            reason = "Stop (Ambiguous Day)"
        elif hit_stop:
            exit_triggered = True
            raw_exit_price = float(pos["stop_price"])
            reason = "Stop Loss"
        elif hit_target:
            exit_triggered = True
            raw_exit_price = float(pos["target_price"])
            reason = "Target Hit"
        elif pos["bars_held"] >= 20:
            exit_triggered = True
            raw_exit_price = float(candle["close"])
            reason = "Time Stop"

        if not exit_triggered:
            remaining.append(pos)
            continue

        effective_exit = raw_exit_price * (1 - FRICTION_BASE)
        harsh_eff_exit = raw_exit_price * (1 - FRICTION_HARSH)
        pnl_val = (effective_exit - float(pos["entry_price"])) * int(pos["shares"])
        harsh_pnl_val = (harsh_eff_exit - float(pos["harsh_entry_price"])) * int(pos["shares"])
        state["cash"] += int(pos["shares"]) * effective_exit
        closed.append(
            {
                "symbol": pos["symbol"],
                "entry_date": pos["entry_date"],
                "exit_date": as_of_date,
                "reason": reason,
                "bars_held": pos["bars_held"],
                "shares": pos["shares"],
                "entry_price": pos["entry_price"],
                "exit_price": effective_exit,
                "pnl_value": pnl_val,
                "pnl_pct": (effective_exit / float(pos["entry_price"])) - 1,
                "harsh_pnl_value": harsh_pnl_val,
                "harsh_pnl_pct": (harsh_eff_exit / float(pos["harsh_entry_price"])) - 1,
                "source": "matsya_api",
            }
        )

    state["open_positions"] = remaining
    return closed


def current_open_value(state: dict, candles_by_symbol: dict[str, pd.DataFrame], as_of_date: str) -> float:
    total = 0.0
    for pos in state["open_positions"]:
        candle = latest_candle_for_date(candles_by_symbol, pos["symbol"], as_of_date)
        if candle:
            total += int(pos["shares"]) * float(candle["close"]) * (1 - FRICTION_BASE)
        else:
            total += float(pos.get("invested_value", 0.0))
    return total


def generate_signals(
    candles_by_symbol: dict[str, pd.DataFrame],
    market_df: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    signals = []
    for symbol, df in candles_by_symbol.items():
        signal = find_confirmed_higher_low_signal(symbol, df, market_df, as_of_date)
        if signal:
            signals.append(signal)
    if not signals:
        return pd.DataFrame()
    return pd.DataFrame(signals).sort_values("down_market_capture_60d", ascending=True)


def process_day(args: argparse.Namespace) -> None:
    set_output_dir(args.log_dir)
    client = MatsyaClient(args.base_url, args.timeout)
    status = client.status()
    as_of_date = args.as_of_date or status.get("latest_candle_date")
    if not as_of_date:
        raise ValueError("No as-of date supplied and Matsya status did not return latest_candle_date.")

    state = load_state(args.starting_equity)
    if state["last_run_date"] == as_of_date and not args.force:
        print(f"Skipping {as_of_date}, already run.")
        return
    if state["last_run_date"] == as_of_date and args.force:
        state["pending_orders"] = [
            order
            for order in state["pending_orders"]
            if not (order.get("signal_date") == as_of_date and order.get("source") == "matsya_api")
        ]

    candles_by_symbol, fetch_meta = fetch_universe_candles(client, args.lookback_days, args.max_workers)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    FETCH_FAILURES_FILE.write_text(
        json.dumps(
            {
                "as_of_date": as_of_date,
                "base_url": args.base_url,
                "symbols_requested": fetch_meta["symbols_requested"],
                "symbols_loaded_raw": len(candles_by_symbol),
                "fetch_failures": fetch_meta["fetch_failures"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    as_of_ts = pd.to_datetime(as_of_date)
    candles_by_symbol = {
        symbol: df[df["trading_date"] <= as_of_ts].copy().reset_index(drop=True)
        for symbol, df in candles_by_symbol.items()
    }
    candles_by_symbol = {symbol: df for symbol, df in candles_by_symbol.items() if not df.empty}
    market_df = build_market_returns(candles_by_symbol)
    filled = process_pending_orders(state, candles_by_symbol, as_of_date)
    closed = process_open_positions(state, candles_by_symbol, as_of_date)
    open_value = current_open_value(state, candles_by_symbol, as_of_date)
    equity = float(state["cash"]) + open_value

    signals = generate_signals(candles_by_symbol, market_df, as_of_date)
    newly_pending = []
    slots_used = len(state["open_positions"]) + len(state["pending_orders"])
    slots_available = MAX_SLOTS - slots_used
    if slots_available > 0 and not signals.empty:
        active_or_pending = {p["symbol"] for p in state["open_positions"]} | {p["symbol"] for p in state["pending_orders"]}
        selected = signals[~signals["symbol"].isin(active_or_pending)].head(slots_available)
        target_allocation = equity / MAX_SLOTS
        for _, row in selected.iterrows():
            order = {
                "symbol": row["symbol"],
                "signal_date": as_of_date,
                "target_allocation": target_allocation,
                "liquidity_cap": row["liquidity_cap"],
                "down_market_capture_60d": row["down_market_capture_60d"],
                "source": "matsya_api",
            }
            state["pending_orders"].append(order)
            newly_pending.append(row["symbol"])

    state["last_run_date"] = as_of_date
    save_state(state)

    for trade in closed:
        append_csv(LEDGER_FILE, trade)
    if not signals.empty:
        signals_out = signals.copy()
        signals_out["as_of_date"] = as_of_date
        signals_out.to_csv(SIGNALS_FILE, mode="a", header=not SIGNALS_FILE.exists(), index=False)

    daily_log = {
        "date": as_of_date,
        "equity": round(equity, 2),
        "cash": round(float(state["cash"]), 2),
        "open_value": round(open_value, 2),
        "open_positions_count": len(state["open_positions"]),
        "pending_orders_count": len(state["pending_orders"]),
        "filled_today": len(filled),
        "closed_today": len(closed),
        "eligible_signals": 0 if signals.empty else len(signals),
        "new_signals": len(newly_pending),
        "matsya_latest_candle_date": status.get("latest_candle_date"),
        "matsya_token_state": status.get("token_state"),
        "symbols_requested": fetch_meta["symbols_requested"],
        "symbols_loaded": len(candles_by_symbol),
        "fetch_failures": len(fetch_meta["fetch_failures"]),
    }
    append_csv(DAILY_LOG_FILE, daily_log)

    print(
        f"[{as_of_date}] Equity: {equity:.2f} | Open: {len(state['open_positions'])} | "
        f"Pending: {len(state['pending_orders'])} | Closed: {len(closed)} | "
        f"Eligible Signals: {0 if signals.empty else len(signals)} | New Pending: {newly_pending}"
    )
    if fetch_meta["fetch_failures"]:
        print(f"WARNING: failed to fetch {len(fetch_meta['fetch_failures'])} symbols.")


def main() -> int:
    parser = argparse.ArgumentParser(description="V7b Matsya-backed forward paper logger.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--as-of-date", default=None, help="YYYY-MM-DD; defaults to Matsya latest_candle_date")
    parser.add_argument("--starting-equity", default=100000.0, type=float)
    parser.add_argument("--log-dir", default=str(EXPORT_DIR))
    parser.add_argument("--lookback-days", default=LOOKBACK_DAYS, type=int)
    parser.add_argument("--max-workers", default=12, type=int)
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--force", action="store_true", help="Rerun an already logged as-of date and replace same-date Matsya pending orders.")
    args = parser.parse_args()
    try:
        process_day(args)
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"Matsya API connection failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
