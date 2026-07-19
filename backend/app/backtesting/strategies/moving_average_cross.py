from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from ..models import Signal


@dataclass(frozen=True)
class MovingAverageCrossStrategy:
    """Reference plug-in, intended to demonstrate the strategy contract."""

    fast_window: int = 20
    slow_window: int = 50
    atr_window: int = 14
    stop_atr: float = 2.0
    target_r: float = 2.0
    max_holding_bars: int = 30

    def __post_init__(self) -> None:
        if not 1 < self.fast_window < self.slow_window:
            raise ValueError("windows must satisfy 1 < fast_window < slow_window")
        if self.atr_window < 2 or self.stop_atr <= 0 or self.target_r <= 0:
            raise ValueError("ATR and reward/risk parameters must be positive")

    @property
    def name(self) -> str:
        return "moving_average_cross"

    def parameters(self) -> dict[str, int | float]:
        return asdict(self)

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        frames = []
        for _, group in candles.groupby("symbol", sort=False):
            item = group.sort_values("date").copy()
            previous_close = item["close"].shift(1)
            true_range = pd.concat(
                [
                    item["high"] - item["low"],
                    (item["high"] - previous_close).abs(),
                    (item["low"] - previous_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            item["fast_ma"] = item["close"].rolling(self.fast_window, min_periods=self.fast_window).mean()
            item["slow_ma"] = item["close"].rolling(self.slow_window, min_periods=self.slow_window).mean()
            item["atr"] = true_range.rolling(self.atr_window, min_periods=self.atr_window).mean()
            frames.append(item)
        return pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"])

    def generate_signals(self, prepared: pd.DataFrame) -> list[Signal]:
        signals: list[Signal] = []
        for symbol, group in prepared.groupby("symbol", sort=False):
            rows = group.sort_values("date").copy()
            crossed = (rows["fast_ma"] > rows["slow_ma"]) & (rows["fast_ma"].shift(1) <= rows["slow_ma"].shift(1))
            for row in rows[crossed & rows["atr"].notna()].itertuples():
                risk = float(row.atr) * self.stop_atr
                signals.append(
                    Signal(
                        symbol=str(symbol),
                        signal_date=pd.Timestamp(row.date).date().isoformat(),
                        stop_price=float(row.close) - risk,
                        target_price=float(row.close) + risk * self.target_r,
                        score=float(row.fast_ma / row.slow_ma - 1),
                        max_holding_bars=self.max_holding_bars,
                        metadata={"signal_close": float(row.close), "atr": float(row.atr)},
                    )
                )
        return signals
