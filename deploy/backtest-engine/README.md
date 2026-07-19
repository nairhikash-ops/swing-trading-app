# Reusable backtesting engine

The engine is a manual, research-only service. It reads Matsya OHLCV data and writes a fresh,
immutable result folder. It does not place orders, mutate market data, or run on a schedule.

## Guarantees

- Signals are known at a daily close and can fill only on a later open.
- Portfolio cash, position limits, risk sizing, fees, taxes, and slippage are applied centrally.
- A bar touching stop and target uses the pessimistic `stop_first` policy by default.
- Gap-through-stop exits use the worse opening price.
- Each run records trades, signals, equity, metrics, parameters, and a SHA-256 data fingerprint.
- Existing result folders are never overwritten.

## Experiment and filter diagnostics

Engine 1.1 adds a reusable `ExperimentStrategy` contract for strategies that expose candidate
signals plus named boolean rule results. `ExperimentRunner` prepares indicators once, then reuses
the candidates for:

- per-signal rejection reasons and a sequential/standalone filter funnel;
- baseline, all-filter, filter-family, custom, and leave-one-rule-out variants;
- full-history, chronological IS/OOS, and latest 12/24-month scopes;
- multiple portfolio-aware cost scenarios;
- pre-declared acceptance gates; and
- retained baseline/all-filter trade and equity ledgers for audit.

The experiment report is immutable and includes `candidate_diagnostics.csv`, `filter_funnel.csv`,
`variant_summary.csv`, `acceptance_gates.csv`, `experiment_manifest.json`, and selected full
trade/equity ledgers. A strategy's `prepare()` method is called exactly once per experiment.

Use [`experiment-spec.example.json`](experiment-spec.example.json) as the starting specification.
The strategy plug-in must implement `generate_candidates()` and return `EvaluatedSignal` objects
whose rule names exactly match the specification.

```bash
docker compose --profile manual run --rm backtest-runner \
  python -m app.backtesting.experiment_cli \
  --source matsya-postgres --universe NIFTY_500 \
  --strategy your_package.your_strategy:YourExperimentStrategy \
  --strategy-params '{"parameter":123}' \
  --experiment-spec /app/specs/your-experiment.json \
  --cache /app/data/backtests/cache/nifty500-daily.csv.gz \
  --output-dir /app/data/backtests/experiments/your-fresh-run-id
```

Mount or include the strategy module and experiment specification in the backend image before a
server run. Acceptance gates should be locked before results are inspected.

## Strategy plug-in

Implement `app.backtesting.strategy.Strategy`: `prepare()` calculates indicators once and
`generate_signals()` returns `Signal` objects. Execution and reporting stay in the engine.
The included moving-average cross is a reference implementation, not an approved strategy.

## Local CSV run

The CSV columns are `symbol,date,open,high,low,close,volume`.

```powershell
cd backend
python -m app.backtesting.cli `
  --source csv `
  --csv D:\data\candles.csv `
  --strategy app.backtesting.strategies.moving_average_cross:MovingAverageCrossStrategy `
  --strategy-params '{"fast_window":20,"slow_window":50}' `
  --output-dir D:\data\backtests\ma-cross-001
```

## Swing server run

From `/home/hacker/apps/swing-trading-app/deploy/matsya-setup`:

```bash
run_id="ma-cross-$(date -u +%Y%m%dT%H%M%SZ)"
docker compose --profile manual run --rm backtest-runner \
  python -m app.backtesting.cli \
  --source matsya-postgres --universe NIFTY_500 \
  --start-date 2022-01-01 \
  --strategy-params '{"fast_window":20,"slow_window":50}' \
  --cache /app/data/backtests/cache/nifty500-daily.csv.gz \
  --output-dir "/app/data/backtests/runs/$run_id"
```

Results appear under `data/backtests/runs/<run-id>/`:

- `summary.json`
- `trades.csv`
- `equity_curve.csv`
- `signals.csv`
- `run_manifest.json`

Use a new run ID for changed strategy or engine parameters. Use `--refresh-cache` after the
Matsya candle store has been updated and a newer end date is required.
