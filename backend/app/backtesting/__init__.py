"""Reusable, deterministic daily-bar backtesting engine."""

from .engine import BacktestEngine, BacktestResult
from .experiments import (
    AcceptanceGate,
    EvaluatedSignal,
    ExperimentConfig,
    ExperimentResult,
    ExperimentRunner,
    FilterPipeline,
    FilterRule,
)
from .models import BacktestConfig, Signal
from .execution import IntradayExecutionConfig, IntradayExecutionEngine, IntradayOrder
from .intraday import MatsyaIntradayDataSource, validate_intraday_candles
from .strategy import ExperimentStrategy, Strategy

__all__ = [
    "AcceptanceGate", "BacktestConfig", "BacktestEngine", "BacktestResult",
    "EvaluatedSignal", "ExperimentConfig", "ExperimentResult", "ExperimentRunner",
    "ExperimentStrategy", "FilterPipeline", "FilterRule", "Signal", "Strategy",
    "IntradayExecutionConfig", "IntradayExecutionEngine", "IntradayOrder",
    "MatsyaIntradayDataSource", "validate_intraday_candles",
]
