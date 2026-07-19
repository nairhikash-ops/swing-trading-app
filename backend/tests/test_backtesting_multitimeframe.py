from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.backtesting.execution import IntradayExecutionConfig, IntradayExecutionEngine, IntradayOrder
from app.backtesting.intraday import merge_required_windows, parse_dhan_intraday_payload, validate_intraday_candles
from app.backtesting.strategies.mtf_weekly_trap import WeeklyTrapConfig, prepare_daily_traps


def intraday(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])


def test_fetch_windows_merge_and_respect_provider_limit() -> None:
    windows = merge_required_windows([
        ("aaa", date(2026, 1, 1), date(2026, 1, 20)),
        ("AAA", date(2026, 1, 15), date(2026, 2, 1)),
        ("BBB", date(2026, 1, 1), date(2026, 5, 1)),
    ])
    assert windows[0].symbol == "AAA"
    assert windows[0].start_date == date(2026, 1, 1)
    assert windows[0].end_date == date(2026, 2, 1)
    assert all((item.end_date - item.start_date).days <= 89 for item in windows)


def test_dhan_parser_keeps_volume_and_uses_utc() -> None:
    frame = parse_dhan_intraday_payload(
        {"timestamp": [1_700_000_000], "open": [10], "high": [11], "low": [9], "close": [10.5], "volume": [123]},
        symbol="aaa",
    )
    assert frame.iloc[0]["symbol"] == "AAA"
    assert frame.iloc[0]["volume"] == 123
    assert str(frame["timestamp"].dt.tz) == "UTC"


def test_intraday_validation_rejects_duplicate_timestamp() -> None:
    frame = intraday([
        ("AAA", "2026-01-01T09:15:00Z", 10, 11, 9, 10, 1),
        ("AAA", "2026-01-01T09:15:00Z", 10, 11, 9, 10, 1),
    ])
    with pytest.raises(ValueError, match="duplicate"):
        validate_intraday_candles(frame)


def test_short_execution_enters_next_bar_and_scales_out() -> None:
    frame = intraday([
        ("AAA", "2026-01-01T03:45:00Z", 100, 101, 97, 98, 10),
        ("AAA", "2026-01-01T04:00:00Z", 98, 99, 97, 97, 10),
        ("AAA", "2026-01-01T04:15:00Z", 97, 98, 93, 94, 10),
        ("AAA", "2026-01-01T04:30:00Z", 94, 94, 89, 90, 10),
    ])
    order = IntradayOrder(
        symbol="AAA", side="short", activation_time=pd.Timestamp("2026-01-01 09:15", tz="Asia/Kolkata"),
        entry_expiration_time=pd.Timestamp("2026-01-01 10:00", tz="Asia/Kolkata"),
        expiration_time=pd.Timestamp("2026-01-01 10:30", tz="Asia/Kolkata"),
        trigger_price=99, stop_price=102, final_target_price=90, trailing_pivot_bars=0,
    )
    trade = IntradayExecutionEngine(IntradayExecutionConfig(slippage_bps=0, round_trip_cost_bps=0)).run(frame, [order]).iloc[0]
    assert trade["entry_time"] == "2026-01-01T04:00:00+00:00"
    assert trade["first_target_time"] == "2026-01-01T04:15:00+00:00"
    assert trade["exit_reason"] == "final_target"
    assert trade["net_r"] == pytest.approx(1.5)


def test_same_bar_stop_and_target_is_pessimistically_stopped() -> None:
    frame = intraday([
        ("AAA", "2026-01-01T03:45:00Z", 100, 101, 97, 98, 10),
        ("AAA", "2026-01-01T04:00:00Z", 98, 103, 89, 97, 10),
    ])
    order = IntradayOrder(
        symbol="AAA", side="short", activation_time=pd.Timestamp("2026-01-01 09:15", tz="Asia/Kolkata"),
        entry_expiration_time=pd.Timestamp("2026-01-01 10:00", tz="Asia/Kolkata"),
        expiration_time=pd.Timestamp("2026-01-01 10:00", tz="Asia/Kolkata"),
        trigger_price=99, stop_price=102, final_target_price=90, trailing_pivot_bars=0,
    )
    trade = IntradayExecutionEngine(IntradayExecutionConfig(slippage_bps=0, round_trip_cost_bps=0)).run(frame, [order]).iloc[0]
    assert trade["exit_reason"] == "stop"
    assert trade["net_r"] == pytest.approx(-1)


def test_daily_trap_uses_completed_previous_week_and_past_liquidity() -> None:
    rows = []
    for index, day in enumerate(pd.date_range("2026-01-05", periods=5, freq="D")):
        rows.append(("AAA", day, 100, 110 if index == 2 else 105, 90 if index == 1 else 95, 100, 1000))
    rows.append(("AAA", pd.Timestamp("2026-01-12"), 109, 112, 105, 108, 1000))
    frame = pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    cfg = WeeklyTrapConfig(liquidity_lookback_sessions=3, minimum_liquidity_sessions=2, liquidity_top_n=1)
    traps = prepare_daily_traps(frame, cfg)
    assert len(traps) == 1
    assert traps.iloc[0]["side"] == "short"
    assert traps.iloc[0]["previous_week_high"] == 110
    assert traps.iloc[0]["previous_week_low"] == 90
