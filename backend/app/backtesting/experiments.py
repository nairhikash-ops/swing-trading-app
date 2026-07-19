from __future__ import annotations

import hashlib
import json
import math
import operator
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .data import validate_candles
from .engine import BacktestEngine, BacktestResult
from .models import BacktestConfig, Signal
from .strategy import ExperimentStrategy


_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class FilterRule:
    name: str
    description: str
    family: str = "general"

    def __post_init__(self) -> None:
        for label, value in (("rule name", self.name), ("rule family", self.family)):
            if not _SAFE_NAME.fullmatch(value):
                raise ValueError(f"{label} must use lowercase snake_case: {value}")
        if not self.description.strip():
            raise ValueError("rule description is required")


@dataclass(frozen=True)
class EvaluatedSignal:
    signal: Signal
    rule_results: Mapping[str, bool]


@dataclass(frozen=True)
class AcceptanceGate:
    name: str
    scope: str
    metric: str
    operator: str
    threshold: float
    variant: str = "all_filters"
    cost_scenario: str = "base"

    def __post_init__(self) -> None:
        if self.operator not in {">", ">=", "<", "<=", "=="}:
            raise ValueError(f"unsupported gate operator: {self.operator}")
        if not self.name.strip() or not self.metric.strip():
            raise ValueError("gate name and metric are required")


@dataclass(frozen=True)
class ExperimentConfig:
    chronological_split_fraction: float = 0.70
    latest_months: tuple[int, ...] = (12, 24)
    include_family_variants: bool = True
    include_leave_one_out: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.chronological_split_fraction < 1:
            raise ValueError("chronological_split_fraction must be in (0, 1)")
        if any(months <= 0 for months in self.latest_months):
            raise ValueError("latest_months values must be positive")


@dataclass
class PipelineEvaluation:
    diagnostics: pd.DataFrame
    funnel: pd.DataFrame


class FilterPipeline:
    def __init__(self, rules: list[FilterRule]) -> None:
        if not rules:
            raise ValueError("at least one filter rule is required")
        names = [rule.name for rule in rules]
        if len(names) != len(set(names)):
            raise ValueError("filter rule names must be unique")
        self.rules = tuple(rules)
        self.rule_names = tuple(names)

    def evaluate(self, candidates: list[EvaluatedSignal]) -> PipelineEvaluation:
        seen: set[tuple[str, str]] = set()
        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            signal = candidate.signal
            key = (signal.symbol.upper(), str(pd.Timestamp(signal.signal_date).date()))
            if key in seen:
                raise ValueError(f"duplicate candidate for {key[0]} on {key[1]}")
            seen.add(key)
            provided = set(candidate.rule_results)
            expected = set(self.rule_names)
            if provided != expected:
                missing = sorted(expected - provided)
                extra = sorted(provided - expected)
                raise ValueError(f"candidate rule mismatch; missing={missing}, extra={extra}")
            results = {name: bool(candidate.rule_results[name]) for name in self.rule_names}
            rejected = [name for name, passed in results.items() if not passed]
            rows.append(
                {
                    "symbol": key[0],
                    "signal_date": key[1],
                    "stop_price": signal.stop_price,
                    "target_price": signal.target_price,
                    "score": signal.score,
                    "max_holding_bars": signal.max_holding_bars,
                    "entry_valid_bars": signal.entry_valid_bars,
                    "metadata": json.dumps(signal.metadata, sort_keys=True),
                    **results,
                    "all_filters": not rejected,
                    "rejection_count": len(rejected),
                    "rejection_reasons": ";".join(rejected),
                }
            )
        diagnostics = pd.DataFrame(rows)
        active = pd.Series(True, index=diagnostics.index, dtype=bool)
        funnel_rows = [
            {
                "rule": "baseline",
                "family": "baseline",
                "description": "All strategy candidates before optional filters",
                "candidate_count": len(diagnostics),
                "standalone_pass": len(diagnostics),
                "standalone_rate": 1.0 if len(diagnostics) else math.nan,
                "sequential_pass": len(diagnostics),
                "sequential_rate": 1.0 if len(diagnostics) else math.nan,
                "failed": 0,
            }
        ]
        for rule in self.rules:
            values = diagnostics[rule.name].astype(bool) if len(diagnostics) else pd.Series(dtype=bool)
            active &= values
            funnel_rows.append(
                {
                    "rule": rule.name,
                    "family": rule.family,
                    "description": rule.description,
                    "candidate_count": len(diagnostics),
                    "standalone_pass": int(values.sum()),
                    "standalone_rate": float(values.mean()) if len(values) else math.nan,
                    "sequential_pass": int(active.sum()),
                    "sequential_rate": float(active.mean()) if len(active) else math.nan,
                    "failed": int((~values).sum()),
                }
            )
        return PipelineEvaluation(diagnostics, pd.DataFrame(funnel_rows))

    def default_variants(self, config: ExperimentConfig) -> dict[str, tuple[str, ...]]:
        variants: dict[str, tuple[str, ...]] = {
            "baseline": (),
            "all_filters": self.rule_names,
        }
        if config.include_family_variants:
            families: dict[str, list[str]] = {}
            for rule in self.rules:
                families.setdefault(rule.family, []).append(rule.name)
            for family, names in families.items():
                variants[f"family_{family}"] = tuple(names)
        if config.include_leave_one_out:
            for omitted in self.rule_names:
                variants[f"without_{omitted}"] = tuple(name for name in self.rule_names if name != omitted)
        return variants

    def signals_for_variant(
        self,
        candidates: list[EvaluatedSignal],
        required_rules: tuple[str, ...],
    ) -> list[Signal]:
        unknown = sorted(set(required_rules) - set(self.rule_names))
        if unknown:
            raise ValueError(f"variant references unknown rules: {unknown}")
        return [
            candidate.signal
            for candidate in candidates
            if all(bool(candidate.rule_results[name]) for name in required_rules)
        ]


@dataclass
class ExperimentResult:
    diagnostics: pd.DataFrame
    funnel: pd.DataFrame
    summary: pd.DataFrame
    gates: pd.DataFrame
    manifest: dict[str, Any]
    retained_runs: dict[str, BacktestResult] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return bool(len(self.gates) and self.gates["passed"].all())

    def write(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=False)
        self.diagnostics.to_csv(output_dir / "candidate_diagnostics.csv", index=False)
        self.funnel.to_csv(output_dir / "filter_funnel.csv", index=False)
        self.summary.to_csv(output_dir / "variant_summary.csv", index=False)
        self.gates.to_csv(output_dir / "acceptance_gates.csv", index=False)
        (output_dir / "experiment_manifest.json").write_text(
            json.dumps(self.manifest, indent=2), encoding="utf-8"
        )
        runs_dir = output_dir / "retained_runs"
        for key, result in self.retained_runs.items():
            result.write(runs_dir / key)


class ExperimentRunner:
    def __init__(self, config: ExperimentConfig | None = None) -> None:
        self.config = config or ExperimentConfig()

    def run(
        self,
        candles: pd.DataFrame,
        strategy: ExperimentStrategy,
        rules: list[FilterRule],
        *,
        cost_scenarios: Mapping[str, BacktestConfig] | None = None,
        variants: Mapping[str, tuple[str, ...]] | None = None,
        gates: tuple[AcceptanceGate, ...] = (),
    ) -> ExperimentResult:
        data = validate_candles(candles)
        pipeline = FilterPipeline(rules)
        prepared = strategy.prepare(data.copy())
        candidates = strategy.generate_candidates(prepared)
        BacktestEngine._validate_signals([candidate.signal for candidate in candidates], data)
        evaluation = pipeline.evaluate(candidates)
        resolved_variants = dict(variants or pipeline.default_variants(self.config))
        self._validate_variant_names(resolved_variants)
        scenarios = dict(cost_scenarios or {"base": BacktestConfig()})
        if not scenarios:
            raise ValueError("at least one cost scenario is required")
        self._validate_scenario_names(scenarios)
        scopes, split_date = self._scopes(data)
        summary_rows: list[dict[str, Any]] = []
        retained: dict[str, BacktestResult] = {}
        primary_cost = next(iter(scenarios))

        for scope, (start, end) in scopes.items():
            scoped_data = data[(data["date"] >= start) & (data["date"] <= end)].copy()
            for variant, required_rules in resolved_variants.items():
                signals = pipeline.signals_for_variant(candidates, tuple(required_rules))
                scoped_signals = [
                    signal for signal in signals if start <= pd.Timestamp(signal.signal_date).normalize() <= end
                ]
                for cost_name, backtest_config in scenarios.items():
                    result = BacktestEngine(backtest_config).run_signals(
                        scoped_data,
                        scoped_signals,
                        strategy_name=f"{strategy.name}:{variant}",
                        strategy_parameters={
                            **strategy.parameters(),
                            "experiment_variant": variant,
                            "required_rules": list(required_rules),
                            "scope": scope,
                            "cost_scenario": cost_name,
                        },
                    )
                    summary_rows.append(
                        {
                            "variant": variant,
                            "scope": scope,
                            "cost_scenario": cost_name,
                            "required_rules": ";".join(required_rules),
                            **result.summary,
                        }
                    )
                    retain = (
                        cost_name == primary_cost
                        and variant in {"baseline", "all_filters"}
                        and scope in {"full_history", "oos"}
                    )
                    if retain:
                        retained[f"{scope}__{variant}__{cost_name}"] = result

        summary = pd.DataFrame(summary_rows)
        gate_frame = self._evaluate_gates(summary, gates)
        fingerprint = pd.util.hash_pandas_object(data, index=False).values.tobytes()
        manifest = {
            "experiment_version": "1.0.0",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "strategy": strategy.name,
            "strategy_parameters": strategy.parameters(),
            "prepared_once": True,
            "candidate_count": len(candidates),
            "rules": [asdict(rule) for rule in rules],
            "variants": {name: list(required) for name, required in resolved_variants.items()},
            "cost_scenarios": {name: config.to_dict() for name, config in scenarios.items()},
            "scopes": {name: [str(start.date()), str(end.date())] for name, (start, end) in scopes.items()},
            "chronological_split_date": str(split_date.date()),
            "data_sha256": hashlib.sha256(fingerprint).hexdigest(),
            "accepted": bool(len(gate_frame) and gate_frame["passed"].all()),
            "gate_count": len(gate_frame),
            "gates_passed": int(gate_frame["passed"].sum()) if len(gate_frame) else 0,
        }
        return ExperimentResult(evaluation.diagnostics, evaluation.funnel, summary, gate_frame, manifest, retained)

    def _scopes(self, data: pd.DataFrame) -> tuple[dict[str, tuple[pd.Timestamp, pd.Timestamp]], pd.Timestamp]:
        dates = pd.Index(sorted(data["date"].unique()))
        split_index = max(0, min(len(dates) - 2, int(len(dates) * self.config.chronological_split_fraction) - 1))
        split_date = pd.Timestamp(dates[split_index])
        first, last = pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])
        scopes = {
            "full_history": (first, last),
            "is": (first, split_date),
            "oos": (pd.Timestamp(dates[split_index + 1]), last),
        }
        for months in sorted(set(self.config.latest_months)):
            requested = last - pd.DateOffset(months=months) + pd.Timedelta(days=1)
            available = dates[dates >= requested]
            scopes[f"latest_{months}_months"] = (pd.Timestamp(available[0]) if len(available) else first, last)
        return scopes, split_date

    @staticmethod
    def _evaluate_gates(summary: pd.DataFrame, gates: tuple[AcceptanceGate, ...]) -> pd.DataFrame:
        operations = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq}
        rows: list[dict[str, Any]] = []
        for gate in gates:
            selected = summary[
                (summary["variant"] == gate.variant)
                & (summary["scope"] == gate.scope)
                & (summary["cost_scenario"] == gate.cost_scenario)
            ]
            if len(selected) != 1:
                raise ValueError(f"gate {gate.name} matched {len(selected)} summary rows")
            if gate.metric not in selected.columns:
                raise ValueError(f"gate {gate.name} references unknown metric: {gate.metric}")
            value = selected.iloc[0][gate.metric]
            numeric = float(value) if pd.notna(value) else math.nan
            passed = bool(operations[gate.operator](numeric, gate.threshold)) if not math.isnan(numeric) else False
            rows.append({**asdict(gate), "value": numeric, "passed": passed})
        columns = ["name", "scope", "metric", "operator", "threshold", "variant", "cost_scenario", "value", "passed"]
        return pd.DataFrame(rows, columns=columns)

    @staticmethod
    def _validate_variant_names(variants: Mapping[str, tuple[str, ...]]) -> None:
        if not variants:
            raise ValueError("at least one experiment variant is required")
        for name in variants:
            if not _SAFE_NAME.fullmatch(name):
                raise ValueError(f"variant name must use lowercase snake_case: {name}")

    @staticmethod
    def _validate_scenario_names(scenarios: Mapping[str, BacktestConfig]) -> None:
        for name, config in scenarios.items():
            if not _SAFE_NAME.fullmatch(name):
                raise ValueError(f"cost scenario name must use lowercase snake_case: {name}")
            if not isinstance(config, BacktestConfig):
                raise TypeError(f"cost scenario {name} must be BacktestConfig")
