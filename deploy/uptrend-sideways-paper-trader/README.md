# Uptrend Sideways Paper Trader

Server-side paper runner for the uptrend-sideways branch research setup.

The scheduled wrapper enforces the continuity contract documented in
`docs/matsya_paper_continuity.md`: it uses stored Matsya sessions, refuses
out-of-order gap repair, and exposes continuity health to the dashboard.

This is intentionally paper-only. It reads Matsya OHLCV through the existing
market-data API, records current uptrend-sideways watch candidates, and places
paper orders only when the sideways range breaks upward first.

## Setup Rule

- Universe: Matsya `NIFTY_500`
- Data: Matsya read-only OHLCV API
- Regime bucket: prior 60-session return before the sideways base is `>= 10%`
- Sideways base grid: `10/15/20/30` sessions and max range `6/8/10/12/15%`
- Signal: latest candle breaks above `base_high` and closes at least `0.5%`
  above `base_high`
- Paper target: `base_high * 1.10`
- Paper failure exit: low below `base_low`
- Time exit: `40` bars
- Broker mode: `paper`

## Manual Run

```bash
cd /home/hacker/apps/swing-trading-app
docker compose -f deploy/matsya-setup/docker-compose.yml --profile manual run --rm uptrend-sideways-paper-trader
```

## Safety Boundary

`--broker dhan` intentionally raises an error. Do not add live order placement
until this setup has passed a separate forward paper review gate.
