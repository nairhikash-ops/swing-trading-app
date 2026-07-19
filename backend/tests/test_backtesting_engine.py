from __future__ import annotations

import json

import pandas as pd
import pytest

from app.backtesting.data import validate_candles
from app.backtesting.engine import BacktestEngine
from app.backtesting.models import BacktestConfig, Signal


class FixedStrategy:
    name = "fixed_test"

    def __init__(self, signals: list[Signal]) -> None:
        self._signals = signals

    def parameters(self) -> dict:
        return {"fixture": True}

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        return candles

    def generate_signals(self, prepared: pd.DataFrame) -> list[Signal]:
        return self._signals


def candles(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"])


def zero_cost_config(**overrides) -> BacktestConfig:
    values = {"commission_bps": 0, "slippage_bps": 0, "taxes_bps": 0, "max_allocation_pct": 1, "risk_per_trade_pct": 1}
    values.update(overrides)
    return BacktestConfig(**values)


def test_signal_fills_only_on_later_open_and_target_closes_trade() -> None:
    data = candles([
        ("AAA", "2026-01-01", 100, 101, 99, 100, 10),
        ("AAA", "2026-01-02", 105, 111, 104, 109, 10),
    ])
    strategy = FixedStrategy([Signal("AAA", "2026-01-01", stop_price=90, target_price=110)])
    result = BacktestEngine(zero_cost_config()).run(data, strategy)
    trade = result.trades.iloc[0]
    assert trade["entry_date"] == "2026-01-02"
    assert trade["entry_price"] == 105
    assert trade["exit_price"] == 110
    assert trade["exit_reason"] == "Target"


def test_ambiguous_bar_uses_pessimistic_stop_by_default() -> None:
    data = candles([
        ("AAA", "2026-01-01", 100, 101, 99, 100, 10),
        ("AAA", "2026-01-02", 100, 112, 88, 101, 10),
    ])
    strategy = FixedStrategy([Signal("AAA", "2026-01-01", stop_price=90, target_price=110)])
    result = BacktestEngine(zero_cost_config()).run(data, strategy)
    assert result.trades.iloc[0]["exit_price"] == 90
    assert result.trades.iloc[0]["exit_reason"] == "Stop (Ambiguous Bar)"


def test_gap_through_stop_exits_at_worse_open() -> None:
    data = candles([
        ("AAA", "2026-01-01", 100, 101, 99, 100, 10),
        ("AAA", "2026-01-02", 100, 102, 98, 101, 10),
        ("AAA", "2026-01-03", 80, 82, 79, 81, 10),
    ])
    strategy = FixedStrategy([Signal("AAA", "2026-01-01", stop_price=90, target_price=120)])
    result = BacktestEngine(zero_cost_config()).run(data, strategy)
    assert result.trades.iloc[0]["exit_price"] == 80
    assert result.trades.iloc[0]["exit_reason"] == "Stop Gap"


def test_entry_order_expires_instead_of_filling_many_sessions_late() -> None:
    data = candles([
        ("AAA", "2026-01-01", 100, 101, 99, 100, 10),
        ("BBB", "2026-01-02", 50, 51, 49, 50, 10),
        ("BBB", "2026-01-03", 50, 51, 49, 50, 10),
        ("AAA", "2026-01-04", 100, 110, 99, 108, 10),
    ])
    strategy = FixedStrategy([Signal("AAA", "2026-01-01", stop_price=90, target_price=109)])
    result = BacktestEngine(zero_cost_config()).run(data, strategy)
    assert result.trades.empty


def test_costs_and_slippage_reduce_equity() -> None:
    data = candles([
        ("AAA", "2026-01-01", 100, 101, 99, 100, 10),
        ("AAA", "2026-01-02", 100, 110, 99, 108, 10),
    ])
    strategy = FixedStrategy([Signal("AAA", "2026-01-01", stop_price=90, target_price=109)])
    gross = BacktestEngine(zero_cost_config()).run(data, strategy).summary["final_equity"]
    costly = BacktestEngine(BacktestConfig(max_allocation_pct=1, risk_per_trade_pct=1)).run(data, strategy).summary["final_equity"]
    assert costly < gross


def test_result_writer_refuses_to_overwrite_and_writes_manifest(tmp_path) -> None:
    data = candles([
        ("AAA", "2026-01-01", 100, 101, 99, 100, 10),
        ("AAA", "2026-01-02", 100, 101, 99, 100, 10),
    ])
    result = BacktestEngine(zero_cost_config()).run(data, FixedStrategy([]))
    output = tmp_path / "run"
    result.write(output)
    manifest = json.loads((output / "run_manifest.json").read_text())
    assert len(manifest["data_sha256"]) == 64
    with pytest.raises(FileExistsError):
        result.write(output)


def test_data_validation_rejects_duplicate_bars() -> None:
    data = candles([
        ("AAA", "2026-01-01", 100, 101, 99, 100, 10),
        ("AAA", "2026-01-01", 100, 101, 99, 100, 10),
    ])
    with pytest.raises(ValueError, match="duplicate"):
        validate_candles(data)
