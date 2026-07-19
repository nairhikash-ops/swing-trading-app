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
