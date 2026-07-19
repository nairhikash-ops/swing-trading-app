from __future__ import annotations

import json

import pandas as pd
import pytest

from app.backtesting import (
    AcceptanceGate,
    BacktestConfig,
    EvaluatedSignal,
    ExperimentConfig,
    ExperimentRunner,
    FilterPipeline,
    FilterRule,
    Signal,
)
from app.backtesting.experiment_cli import main as experiment_main, parse_experiment_spec
from app.backtesting.strategies import MovingAverageCrossExperimentStrategy


RULES = [
    FilterRule("strong_close", "Close is structurally strong", "anatomy"),
    FilterRule("volume_expansion", "Volume confirms the move", "volume"),
]


class CountingExperimentStrategy:
    name = "counting_experiment"

    def __init__(self) -> None:
        self.prepare_calls = 0

    def parameters(self) -> dict:
        return {"fixture": True}

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        self.prepare_calls += 1
        return candles

    def generate_candidates(self, prepared: pd.DataFrame) -> list[EvaluatedSignal]:
        return [
            EvaluatedSignal(Signal("AAA", "2026-01-01", 90, 102), {"strong_close": True, "volume_expansion": True}),
            EvaluatedSignal(Signal("AAA", "2026-01-04", 90, 102), {"strong_close": True, "volume_expansion": False}),
            EvaluatedSignal(Signal("AAA", "2026-01-07", 90, 102), {"strong_close": False, "volume_expansion": True}),
            EvaluatedSignal(Signal("AAA", "2026-01-10", 90, 102), {"strong_close": True, "volume_expansion": True}),
        ]


def candle_frame() -> pd.DataFrame:
    rows = []
    for day in range(1, 13):
        rows.append(("AAA", f"2026-01-{day:02d}", 100, 103, 97, 100, 1000))
    return pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"])


def zero_cost() -> BacktestConfig:
    return BacktestConfig(
        commission_bps=0,
        slippage_bps=0,
        taxes_bps=0,
        max_allocation_pct=1,
        risk_per_trade_pct=1,
    )


def test_filter_pipeline_creates_rejection_ledger_and_funnel() -> None:
    strategy = CountingExperimentStrategy()
    candidates = strategy.generate_candidates(candle_frame())
    result = FilterPipeline(RULES).evaluate(candidates)
    assert list(result.diagnostics["rejection_reasons"]) == ["", "volume_expansion", "strong_close", ""]
    assert list(result.diagnostics["all_filters"]) == [True, False, False, True]
    funnel = result.funnel.set_index("rule")
    assert funnel.loc["strong_close", "standalone_pass"] == 3
    assert funnel.loc["volume_expansion", "standalone_pass"] == 3
    assert funnel.loc["volume_expansion", "sequential_pass"] == 2


def test_pipeline_rejects_rule_schema_mismatch() -> None:
    candidate = EvaluatedSignal(Signal("AAA", "2026-01-01", 90, 102), {"strong_close": True})
    with pytest.raises(ValueError, match="rule mismatch"):
        FilterPipeline(RULES).evaluate([candidate])


def test_experiment_rejects_candidate_outside_candle_data() -> None:
    class BadStrategy(CountingExperimentStrategy):
        def generate_candidates(self, prepared: pd.DataFrame) -> list[EvaluatedSignal]:
            return [EvaluatedSignal(Signal("MISSING", "2026-01-01", 90, 102), {"strong_close": True, "volume_expansion": True})]

    with pytest.raises(ValueError, match="symbol not in candle data"):
        ExperimentRunner().run(candle_frame(), BadStrategy(), RULES, cost_scenarios={"base": zero_cost()})


def test_experiment_prepares_once_and_runs_scopes_variants_costs_and_gates(tmp_path) -> None:
    strategy = CountingExperimentStrategy()
    gates = (
        AcceptanceGate("oos_has_signal", "oos", "signal_count", ">=", 1),
        AcceptanceGate("oos_has_trade", "oos", "trade_count", ">=", 1),
    )
    scenarios = {
        "base": zero_cost(),
        "harsh": BacktestConfig(
            commission_bps=50,
            slippage_bps=0,
            taxes_bps=0,
            max_allocation_pct=1,
            risk_per_trade_pct=1,
        ),
    }
    result = ExperimentRunner(ExperimentConfig(chronological_split_fraction=0.5, latest_months=(1,))).run(
        candle_frame(), strategy, RULES, cost_scenarios=scenarios, gates=gates
    )
    assert strategy.prepare_calls == 1
    assert set(result.summary["scope"]) == {"full_history", "is", "oos", "latest_1_months"}
    assert {"baseline", "all_filters", "family_anatomy", "family_volume", "without_strong_close", "without_volume_expansion"} <= set(result.summary["variant"])
    assert set(result.summary["cost_scenario"]) == {"base", "harsh"}
    assert result.accepted
    assert result.manifest["prepared_once"] is True
    assert result.manifest["chronological_split_date"] == "2026-01-06"

    full = result.summary[(result.summary.scope == "full_history") & (result.summary.variant == "all_filters")]
    base_equity = float(full[full.cost_scenario == "base"].iloc[0].final_equity)
    harsh_equity = float(full[full.cost_scenario == "harsh"].iloc[0].final_equity)
    assert harsh_equity < base_equity

    output = tmp_path / "experiment"
    result.write(output)
    manifest = json.loads((output / "experiment_manifest.json").read_text())
    assert manifest["accepted"] is True
    assert (output / "candidate_diagnostics.csv").exists()
    assert (output / "retained_runs" / "oos__all_filters__base" / "trades.csv").exists()
    with pytest.raises(FileExistsError):
        result.write(output)


def test_experiment_spec_parser_builds_typed_configuration() -> None:
    config, rules, costs, variants, gates = parse_experiment_spec(
        {
            "experiment": {"chronological_split_fraction": 0.6, "latest_months": [6]},
            "rules": [{"name": "strong_close", "description": "Strong close", "family": "anatomy"}],
            "cost_scenarios": {"base": {"commission_bps": 1, "slippage_bps": 2, "taxes_bps": 3}},
            "variants": {"baseline": [], "all_filters": ["strong_close"]},
            "gates": [{"name": "enough", "scope": "oos", "metric": "trade_count", "operator": ">=", "threshold": 1}],
        }
    )
    assert config.chronological_split_fraction == 0.6
    assert rules[0].family == "anatomy"
    assert costs["base"].slippage_bps == 2
    assert variants == {"baseline": (), "all_filters": ("strong_close",)}
    assert gates[0].scope == "oos"


def test_reference_experiment_strategy_emits_exact_spec_rules() -> None:
    values = [10, 9, 8, 10, 12, 13, 14]
    frame = pd.DataFrame(
        [("AAA", f"2026-01-{day:02d}", value - 0.5, value + 1, value - 1, value, 100) for day, value in enumerate(values, 1)],
        columns=["symbol", "date", "open", "high", "low", "close", "volume"],
    )
    frame["date"] = pd.to_datetime(frame["date"])
    strategy = MovingAverageCrossExperimentStrategy(fast_window=2, slow_window=3, atr_window=2)
    candidates = strategy.generate_candidates(strategy.prepare(frame))
    assert candidates
    assert set(candidates[0].rule_results) == {"strong_close", "volume_expansion"}


def test_experiment_cli_runs_from_reproducible_spec(tmp_path) -> None:
    csv_path = tmp_path / "candles.csv"
    spec_path = tmp_path / "spec.json"
    output = tmp_path / "output"
    values = list(range(30, 10, -1)) + list(range(11, 31))
    dates = pd.date_range("2026-01-01", periods=len(values), freq="D")
    pd.DataFrame(
        [("AAA", day.date().isoformat(), value - 0.5, value + 1, value - 1, value, 100) for day, value in zip(dates, values)],
        columns=["symbol", "date", "open", "high", "low", "close", "volume"],
    ).to_csv(csv_path, index=False)
    spec_path.write_text(
        json.dumps(
            {
                "experiment": {"chronological_split_fraction": 0.5, "latest_months": [1]},
                "rules": [
                    {"name": "strong_close", "description": "Strong close", "family": "anatomy"},
                    {"name": "volume_expansion", "description": "Volume expansion", "family": "volume"},
                ],
                "cost_scenarios": {"base": {"commission_bps": 0, "slippage_bps": 0, "taxes_bps": 0}},
                "variants": {"baseline": [], "all_filters": ["strong_close", "volume_expansion"]},
                "gates": [],
            }
        ),
        encoding="utf-8",
    )
    assert experiment_main(
        [
            "--source", "csv", "--csv", str(csv_path),
            "--strategy", "app.backtesting.strategies.moving_average_cross_experiment:MovingAverageCrossExperimentStrategy",
            "--strategy-params", '{"fast_window":2,"slow_window":3,"atr_window":2}',
            "--experiment-spec", str(spec_path), "--output-dir", str(output),
        ]
    ) == 0
    manifest = json.loads((output / "experiment_manifest.json").read_text())
    assert manifest["prepared_once"] is True
    assert set(manifest["variants"]) == {"baseline", "all_filters"}
