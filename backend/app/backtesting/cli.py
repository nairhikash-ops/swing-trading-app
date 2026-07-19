from __future__ import annotations

import argparse
import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .data import CsvDataSource, MatsyaPostgresDataSource, load_or_create_cache
from .engine import BacktestEngine
from .models import BacktestConfig
from .strategy import Strategy


DEFAULT_STRATEGY = "app.backtesting.strategies.moving_average_cross:MovingAverageCrossStrategy"


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("value must be a JSON object")
    return parsed


def load_strategy(path: str, parameters: dict[str, Any]) -> Strategy:
    try:
        module_name, object_name = path.split(":", 1)
        strategy_type = getattr(importlib.import_module(module_name), object_name)
        strategy = strategy_type(**parameters)
    except (ValueError, ImportError, AttributeError, TypeError) as exc:
        raise ValueError(f"cannot load strategy {path}: {exc}") from exc
    if not isinstance(strategy, Strategy):
        raise TypeError(f"{path} does not implement the Strategy contract")
    return strategy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reusable chronological daily-bar backtesting engine")
    parser.add_argument("--source", choices=["csv", "matsya-postgres"], required=True)
    parser.add_argument("--csv", type=Path, help="Canonical OHLCV CSV; required for --source csv")
    parser.add_argument("--database-url", help="Matsya PostgreSQL URL; defaults to MATSYA_DATABASE_URL")
    parser.add_argument("--universe", default="NIFTY_500")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--cache", type=Path, help="Optional .csv.gz candle cache")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--strategy", default=DEFAULT_STRATEGY, help="Python module:Object strategy plug-in")
    parser.add_argument("--strategy-params", type=_json_object, default={})
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--max-allocation-pct", type=float, default=0.20)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--commission-bps", type=float, default=3.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--taxes-bps", type=float, default=12.0)
    parser.add_argument("--ambiguous-fill-policy", choices=["stop_first", "target_first"], default="stop_first")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output_dir.exists():
        raise SystemExit(f"output directory already exists: {args.output_dir}")
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
    strategy = load_strategy(args.strategy, args.strategy_params)
    config = BacktestConfig(
        initial_cash=args.initial_cash,
        max_positions=args.max_positions,
        max_allocation_pct=args.max_allocation_pct,
        risk_per_trade_pct=args.risk_per_trade_pct,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        taxes_bps=args.taxes_bps,
        ambiguous_fill_policy=args.ambiguous_fill_policy,
    )
    result = BacktestEngine(config).run(candles, strategy)
    result.manifest.update({"cache_hit": cache_hit, "command_completed_at_utc": datetime.now(timezone.utc).isoformat()})
    result.write(args.output_dir)
    print(json.dumps({"output_dir": str(args.output_dir), **result.summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
