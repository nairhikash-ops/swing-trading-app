from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from ..experiments import EvaluatedSignal
from ..models import Signal
from .moving_average_cross import MovingAverageCrossStrategy


@dataclass(frozen=True)
class MovingAverageCrossExperimentStrategy:
    """Reference experiment plug-in; it is not an approved trading strategy."""

    fast_window: int = 20
    slow_window: int = 50
    atr_window: int = 14
    stop_atr: float = 2.0
    target_r: float = 2.0
    max_holding_bars: int = 30
    strong_close_min: float = 0.75
    volume_ratio_min: float = 1.50

    def __post_init__(self) -> None:
        MovingAverageCrossStrategy(
            fast_window=self.fast_window,
            slow_window=self.slow_window,
            atr_window=self.atr_window,
            stop_atr=self.stop_atr,
            target_r=self.target_r,
            max_holding_bars=self.max_holding_bars,
        )
        if not 0 <= self.strong_close_min <= 1 or self.volume_ratio_min <= 0:
            raise ValueError("reference filter thresholds are invalid")

    @property
    def name(self) -> str:
        return "moving_average_cross_experiment_reference"

    def parameters(self) -> dict[str, int | float]:
        return asdict(self)

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        base = MovingAverageCrossStrategy(
            fast_window=self.fast_window,
            slow_window=self.slow_window,
            atr_window=self.atr_window,
            stop_atr=self.stop_atr,
            target_r=self.target_r,
            max_holding_bars=self.max_holding_bars,
        ).prepare(candles)
        frames = []
        for _, group in base.groupby("symbol", sort=False):
            item = group.sort_values("date").copy()
            day_range = (item["high"] - item["low"]).where(item["high"] > item["low"])
            item["close_position_in_range"] = (item["close"] - item["low"]) / day_range
            prior_volume = item["volume"].shift(1).rolling(20, min_periods=20).mean()
            item["volume_ratio20_prior"] = item["volume"] / prior_volume.where(prior_volume > 0)
            frames.append(item)
        return pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"])

    def generate_candidates(self, prepared: pd.DataFrame) -> list[EvaluatedSignal]:
        candidates: list[EvaluatedSignal] = []
        for symbol, group in prepared.groupby("symbol", sort=False):
            rows = group.sort_values("date").copy()
            crossed = (rows["fast_ma"] > rows["slow_ma"]) & (rows["fast_ma"].shift(1) <= rows["slow_ma"].shift(1))
            for row in rows[crossed & rows["atr"].notna()].itertuples():
                risk = float(row.atr) * self.stop_atr
                signal = Signal(
                    symbol=str(symbol),
                    signal_date=pd.Timestamp(row.date).date().isoformat(),
                    stop_price=float(row.close) - risk,
                    target_price=float(row.close) + risk * self.target_r,
                    score=float(row.fast_ma / row.slow_ma - 1),
                    max_holding_bars=self.max_holding_bars,
                    metadata={
                        "signal_close": float(row.close),
                        "atr": float(row.atr),
                        "close_position_in_range": float(row.close_position_in_range),
                        "volume_ratio20_prior": float(row.volume_ratio20_prior),
                    },
                )
                candidates.append(
                    EvaluatedSignal(
                        signal,
                        {
                            "strong_close": bool(row.close_position_in_range >= self.strong_close_min),
                            "volume_expansion": bool(row.volume_ratio20_prior >= self.volume_ratio_min),
                        },
                    )
                )
        return candidates
