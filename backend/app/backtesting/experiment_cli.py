from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
from typing import Any

from .data import CsvDataSource, MatsyaPostgresDataSource, load_or_create_cache
from .experiments import AcceptanceGate, ExperimentConfig, ExperimentRunner, FilterRule
from .models import BacktestConfig
from .strategy import ExperimentStrategy


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("value must be a JSON object")
    return parsed


def load_experiment_strategy(path: str, parameters: dict[str, Any]) -> ExperimentStrategy:
    try:
        module_name, object_name = path.split(":", 1)
        strategy_type = getattr(importlib.import_module(module_name), object_name)
        strategy = strategy_type(**parameters)
    except (ValueError, ImportError, AttributeError, TypeError) as exc:
        raise ValueError(f"cannot load experiment strategy {path}: {exc}") from exc
    if not isinstance(strategy, ExperimentStrategy):
        raise TypeError(f"{path} does not implement the ExperimentStrategy contract")
    return strategy


def parse_experiment_spec(raw: dict[str, Any]) -> tuple[
    ExperimentConfig,
    list[FilterRule],
    dict[str, BacktestConfig],
    dict[str, tuple[str, ...]] | None,
    tuple[AcceptanceGate, ...],
]:
    allowed = {"experiment", "rules", "cost_scenarios", "variants", "gates"}
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ValueError(f"unknown experiment spec fields: {extra}")
    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ValueError("experiment spec requires a non-empty rules list")
    rules = [FilterRule(**item) for item in rules_raw]
    config = ExperimentConfig(**raw.get("experiment", {}))
    costs_raw = raw.get("cost_scenarios", {"base": {}})
    if not isinstance(costs_raw, dict) or not costs_raw:
        raise ValueError("cost_scenarios must be a non-empty object")
    costs = {name: BacktestConfig(**values) for name, values in costs_raw.items()}
    variants_raw = raw.get("variants")
    variants = None
    if variants_raw is not None:
        if not isinstance(variants_raw, dict) or not variants_raw:
            raise ValueError("variants must be a non-empty object when provided")
        variants = {}
        for name, rule_names in variants_raw.items():
            if not isinstance(rule_names, list) or not all(isinstance(rule, str) for rule in rule_names):
                raise ValueError(f"variant {name} must be a list of rule names")
            variants[name] = tuple(rule_names)
    gates_raw = raw.get("gates", [])
    if not isinstance(gates_raw, list):
        raise ValueError("gates must be a list")
    gates = tuple(AcceptanceGate(**item) for item in gates_raw)
    return config, rules, costs, variants, gates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run reusable filter, ablation, and chronological experiments")
    parser.add_argument("--source", choices=["csv", "matsya-postgres"], required=True)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--database-url")
    parser.add_argument("--universe", default="NIFTY_500")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--strategy", required=True, help="Python module:Object experiment strategy plug-in")
    parser.add_argument("--strategy-params", type=_json_object, default={})
    parser.add_argument("--experiment-spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output_dir.exists():
        raise SystemExit(f"output directory already exists: {args.output_dir}")
    spec_raw = json.loads(args.experiment_spec.read_text(encoding="utf-8"))
    if not isinstance(spec_raw, dict):
        raise SystemExit("experiment spec root must be a JSON object")
    config, rules, costs, variants, gates = parse_experiment_spec(spec_raw)
    strategy = load_experiment_strategy(args.strategy, args.strategy_params)
    if args.source == "csv":
        if not args.csv:
            raise SystemExit("--csv is required for --source csv")
        source = CsvDataSource(args.csv)
    else:
        database_url = args.database_url or os.getenv("MATSYA_DATABASE_URL")
        if not database_url:
            raise SystemExit("--database-url or MATSYA_DATABASE_URL is required for Matsya PostgreSQL")
        source = MatsyaPostgresDataSource(database_url, args.universe)
    candles, cache_hit = load_or_create_cache(
        source, args.cache, start_date=args.start_date, end_date=args.end_date, refresh=args.refresh_cache
    )
    result = ExperimentRunner(config).run(
        candles,
        strategy,
        rules,
        cost_scenarios=costs,
        variants=variants,
        gates=gates,
    )
    result.manifest["cache_hit"] = cache_hit
    result.manifest["experiment_spec"] = str(args.experiment_spec)
    result.write(args.output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "accepted": result.accepted,
                "candidates": result.manifest["candidate_count"],
                "variants": len(result.manifest["variants"]),
                "gates_passed": result.manifest["gates_passed"],
                "gate_count": result.manifest["gate_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
