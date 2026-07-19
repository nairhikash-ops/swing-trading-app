# V8 Demo Trader Paper Runner

This deployment is paper-only. It reads Matsya OHLCV data and writes paper broker reports for the frontend dashboard. It does not place live Dhan orders.

## Services

The Matsya Compose stack includes a manual one-shot service:

```bash
docker compose --profile manual run --rm v8-demo-trader
```

The service runs:

```bash
python scripts/run_v8_demo_trader_once.py
```

The wrapper reads Matsya's latest candle date from `http://matsya-api:8020/api/matsya/market-data/status` and skips if that date is already present in `daily_report.csv`. This prevents duplicate paper reports or duplicate pending orders when the job is run more than once for the same candle date.

The wrapper also compares `daily_report.csv` with Matsya's stored trading-date
sequence. Interior gaps fail closed and appear as invalid on the dashboard.
Trailing recovery is chronological and permanently labeled reconstructed. See
`docs/matsya_paper_continuity.md` for the recovery contract.

## Output

The paper runner writes to the host directory:

```text
/home/hacker/apps/swing-trading-app/data/v8_demo_trader
```

The Matsya API mounts the same directory read-only at:

```text
/app/data/v8_demo_trader
```

The frontend reads it through:

```text
GET /api/matsya/demo/v8/status
```

## Cron

The server cron entry for user `hacker` is:

```cron
30 7 * * 1-6 cd /home/hacker/apps/swing-trading-app/deploy/matsya-setup && /usr/bin/docker compose --profile manual run --rm v8-demo-trader >> /home/hacker/apps/swing-trading-app/data/v8_demo_trader/v8_demo_trader_cron.log 2>&1
```

This is scheduled at 07:30 IST Monday through Saturday, after the Matsya daily OHLCV ingestion window.

## Verification

Manual proof command:

```bash
cd /home/hacker/apps/swing-trading-app/deploy/matsya-setup
docker compose --profile manual run --rm v8-demo-trader
```

Dashboard proof:

```bash
curl 'http://100.76.218.124:8020/api/matsya/demo/v8/status?limit=5'
```

Expected health gates:

- `broker`: `paper`
- `matsya_token_state`: `active`
- `symbols_loaded`: `500`
- `fetch_failures`: `0`

## Live Trading Boundary

The V8 runner must remain paper-only until explicitly approved after forward paper validation. Do not wire Dhan live execution into this service without a separate review and deployment step.
