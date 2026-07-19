from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from ..data import validate_candles
from ..execution import IntradayOrder
from ..intraday import IST, validate_intraday_candles


@dataclass(frozen=True)
class WeeklyTrapConfig:
    liquidity_lookback_sessions: int = 60
    liquidity_top_n: int = 150
    minimum_liquidity_sessions: int = 20
    pivot_bars: int = 2
    stop_buffer_bps: float = 5.0
    entry_valid_sessions: int = 1
    max_holding_sessions: int = 20
    first_exit_fraction: float = 0.5
    trailing_pivot_bars: int = 2

    def __post_init__(self) -> None:
        if self.liquidity_lookback_sessions <= 0 or self.liquidity_top_n <= 0:
            raise ValueError("liquidity parameters must be positive")
        if self.minimum_liquidity_sessions <= 0 or self.pivot_bars <= 0:
            raise ValueError("minimum sessions and pivot bars must be positive")
        if self.stop_buffer_bps < 0 or self.entry_valid_sessions <= 0 or self.max_holding_sessions <= 0:
            raise ValueError("stop buffer and session limits are invalid")
        if not 0 < self.first_exit_fraction < 1:
            raise ValueError("first_exit_fraction must be in (0, 1)")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def prepare_daily_traps(candles: pd.DataFrame, config: WeeklyTrapConfig | None = None) -> pd.DataFrame:
    """Create close-known trap candidates using only completed prior weeks and past liquidity."""
    cfg = config or WeeklyTrapConfig()
    data = validate_candles(candles).sort_values(["symbol", "date"], kind="stable")
    data["turnover"] = data["close"] * data["volume"]
    data["median_turnover"] = data.groupby("symbol", sort=False)["turnover"].transform(
        lambda series: series.shift(1).rolling(cfg.liquidity_lookback_sessions, min_periods=cfg.minimum_liquidity_sessions).median()
    )
    data["liquidity_rank"] = data.groupby("date")["median_turnover"].rank(method="first", ascending=False)
    data["week"] = data["date"].dt.to_period("W-FRI")
    weekly = (
        data.groupby(["symbol", "week"], as_index=False)
        .agg(week_high=("high", "max"), week_low=("low", "min"))
        .sort_values(["symbol", "week"])
    )
    weekly["previous_week_high"] = weekly.groupby("symbol")["week_high"].shift(1)
    weekly["previous_week_low"] = weekly.groupby("symbol")["week_low"].shift(1)
    data = data.merge(
        weekly[["symbol", "week", "previous_week_high", "previous_week_low"]],
        on=["symbol", "week"], how="left", validate="many_to_one",
    )
    weekday_ok = data["date"].dt.weekday <= 3
    liquid = data["liquidity_rank"] <= cfg.liquidity_top_n
    short = (data["high"] > data["previous_week_high"]) & (data["close"] < data["previous_week_high"])
    long = (data["low"] < data["previous_week_low"]) & (data["close"] > data["previous_week_low"])
    candidates = data[weekday_ok & liquid & (short ^ long)].copy()
    candidates["side"] = ""
    candidates.loc[short.loc[candidates.index], "side"] = "short"
    candidates.loc[long.loc[candidates.index], "side"] = "long"
    return candidates.sort_values(["date", "liquidity_rank", "symbol"]).reset_index(drop=True)


def required_intraday_windows(
    daily_candles: pd.DataFrame, candidates: pd.DataFrame, config: WeeklyTrapConfig | None = None
) -> list[tuple[str, date, date]]:
    cfg = config or WeeklyTrapConfig()
    daily = validate_candles(daily_candles)
    sessions = sorted(pd.Timestamp(value).date() for value in daily["date"].unique())
    session_index = {value: index for index, value in enumerate(sessions)}
    windows = []
    for row in candidates.itertuples(index=False):
        trap_date = pd.Timestamp(row.date).date()
        idx = session_index[trap_date]
        end_idx = min(len(sessions) - 1, idx + cfg.max_holding_sessions + cfg.entry_valid_sessions)
        windows.append((str(row.symbol), trap_date, sessions[end_idx]))
    return windows


def build_intraday_orders(
    daily_candles: pd.DataFrame,
    intraday_candles: pd.DataFrame,
    candidates: pd.DataFrame,
    config: WeeklyTrapConfig | None = None,
) -> tuple[list[IntradayOrder], pd.DataFrame]:
    cfg = config or WeeklyTrapConfig()
    daily = validate_candles(daily_candles)
    intraday = validate_intraday_candles(intraday_candles)
    sessions = sorted(pd.Timestamp(value).date() for value in daily["date"].unique())
    session_index = {value: index for index, value in enumerate(sessions)}
    by_symbol = {symbol: group.reset_index(drop=True) for symbol, group in intraday.groupby("symbol", sort=False)}
    orders: list[IntradayOrder] = []
    rejected: list[dict[str, Any]] = []

    for row in candidates.itertuples(index=False):
        symbol, side = str(row.symbol), str(row.side)
        trap_date = pd.Timestamp(row.date).date()
        bars = by_symbol.get(symbol)
        if bars is None:
            rejected.append({"symbol": symbol, "trap_date": trap_date, "reason": "missing_intraday_data"})
            continue
        local_dates = bars["timestamp"].dt.tz_convert(IST).dt.date
        trap_bars = bars[local_dates == trap_date].reset_index(drop=True)
        if len(trap_bars) < cfg.pivot_bars * 2 + 2:
            rejected.append({"symbol": symbol, "trap_date": trap_date, "reason": "incomplete_trap_session"})
            continue
        extreme_idx = int(trap_bars["high"].idxmax() if side == "short" else trap_bars["low"].idxmin())
        pivot = _last_confirmed_pivot_before_extreme(trap_bars, side, extreme_idx, cfg.pivot_bars)
        if pivot is None:
            rejected.append({"symbol": symbol, "trap_date": trap_date, "reason": "no_confirmed_pre_extreme_pivot"})
            continue
        structure_idx, trigger = pivot
        post_extreme = trap_bars.iloc[extreme_idx + 1 :]
        shifted_same_day = bool((post_extreme["close"] < trigger).any() if side == "short" else (post_extreme["close"] > trigger).any())
        idx = session_index[trap_date]
        if idx + 1 >= len(sessions):
            rejected.append({"symbol": symbol, "trap_date": trap_date, "reason": "no_next_session"})
            continue
        activation_date = sessions[idx + 1]
        entry_end = sessions[min(len(sessions) - 1, idx + cfg.entry_valid_sessions)]
        holding_end = sessions[min(len(sessions) - 1, idx + cfg.entry_valid_sessions + cfg.max_holding_sessions)]
        activation = pd.Timestamp(f"{activation_date} 09:15", tz=IST)
        entry_expiration = pd.Timestamp(f"{entry_end} 15:30", tz=IST)
        expiration = pd.Timestamp(f"{holding_end} 15:30", tz=IST)
        trap_extreme = float(trap_bars["high"].max() if side == "short" else trap_bars["low"].min())
        buffer = cfg.stop_buffer_bps / 10_000
        stop = trap_extreme * (1 + buffer if side == "short" else 1 - buffer)
        final_target = float(row.previous_week_low if side == "short" else row.previous_week_high)
        orders.append(
            IntradayOrder(
                symbol=symbol, side=side, activation_time=activation,
                entry_expiration_time=entry_expiration, expiration_time=expiration,
                stop_price=stop, final_target_price=final_target, trigger_price=trigger,
                gap_reference_price=trigger,
                enter_at_activation_open=shifted_same_day, first_exit_fraction=cfg.first_exit_fraction,
                trailing_pivot_bars=cfg.trailing_pivot_bars,
                metadata={
                    "trap_date": trap_date.isoformat(), "weekly_high": float(row.previous_week_high),
                    "weekly_low": float(row.previous_week_low), "trap_extreme": trap_extreme,
                    "structure_level": trigger, "structure_pivot_index": structure_idx,
                    "shifted_same_day": shifted_same_day, "liquidity_rank": float(row.liquidity_rank),
                },
            )
        )
    return orders, pd.DataFrame(rejected, columns=["symbol", "trap_date", "reason"])


def _last_confirmed_pivot_before_extreme(
    bars: pd.DataFrame, side: str, extreme_idx: int, width: int
) -> tuple[int, float] | None:
    pivot_column = "low" if side == "short" else "high"
    pivots = []
    # right-side bars must exist before the extreme, ensuring the pivot was known then.
    for center in range(width, max(width, extreme_idx - width + 1)):
        window = bars.iloc[center - width : center + width + 1][pivot_column]
        value = float(bars.at[center, pivot_column])
        is_pivot = value == float(window.min()) if side == "short" else value == float(window.max())
        if is_pivot:
            pivots.append((center, value))
    return pivots[-1] if pivots else None
