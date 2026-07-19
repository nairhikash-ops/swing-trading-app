import pandas as pd

from app.backtesting.cli import load_strategy
from app.backtesting.strategies import MovingAverageCrossStrategy


def test_reference_strategy_is_dynamically_loadable() -> None:
    strategy = load_strategy(
        "app.backtesting.strategies.moving_average_cross:MovingAverageCrossStrategy",
        {"fast_window": 2, "slow_window": 3, "atr_window": 2},
    )
    assert isinstance(strategy, MovingAverageCrossStrategy)


def test_reference_strategy_uses_current_and_past_data() -> None:
    frame = pd.DataFrame(
        [("AAA", f"2026-01-0{day}", value, value + 1, value - 1, value, 100) for day, value in enumerate([10, 9, 8, 10, 12, 13], 1)],
        columns=["symbol", "date", "open", "high", "low", "close", "volume"],
    )
    frame["date"] = pd.to_datetime(frame["date"])
    strategy = MovingAverageCrossStrategy(fast_window=2, slow_window=3, atr_window=2)
    signals = strategy.generate_signals(strategy.prepare(frame))
    assert signals
    assert signals[0].signal_date == "2026-01-05"
