# Reusable backtesting system

Full market-history runs execute on the swing server. Local execution is limited to implementation tests, deterministic fixtures, and diagnostics. Before adding strategy-specific code, inspect the existing data adapters, execution models, experiment runner, and server datasets. Add a capability only when the current system cannot express the rule honestly.

## Current capabilities

- Daily and 15-minute PostgreSQL data sources with strict OHLC validation.
- Candidate-first multi-timeframe preparation so expensive intraday history is fetched only for qualifying daily setups.
- Resumable, idempotent Dhan 15-minute archives in 90-day-or-smaller request windows.
- Long and short next-bar execution, pessimistic ambiguous-bar handling, slippage and costs.
- Gap rejection, partial exit at configurable R, breakeven stops, confirmed-pivot trailing, final targets, and time exits.
- Immutable plan and result directories with candidates, rejection reasons, trade ledgers, summaries, parameters, costs, and known biases.

## MTF weekly-trap v1 locked rules

1. Rank the current NIFTY 500 universe each session by the median daily turnover from the prior 60 sessions; retain the top 150. Current membership creates a documented survivorship bias.
2. Use only the completed previous trading week's high and low.
3. Monday through Thursday, select a short when price trades above the prior weekly high and closes below it. Select a long symmetrically at the prior weekly low. Reject candles that trap both sides.
4. On the 15-minute trap session, find the last 2-left/2-right confirmed swing immediately before the trap extreme. The right bars must exist before the extreme, preventing future leakage.
5. If the structure shift closes through that level on the trap day, enter at the next session's open. Otherwise, require the shift on the next session and enter at the following 15-minute open.
6. Place the stop 5 bps beyond the trap extreme. Reject entries beyond the stop, entries whose opposite weekly target is below 1R, and opens that have already travelled 1R from the planned structure entry.
7. Exit 50% at 1R, move the remainder's stop to breakeven, then trail confirmed 2-left/2-right 15-minute pivots. The final target is the opposite prior-week boundary. Liquidate after 20 sessions.
8. When stop and target are both touched in one candle, assume the stop occurs first.

## Server workflow

Create a candidate plan first. This is cheap because it reads daily history only:

```bash
python scripts/backtest_mtf_weekly_trap.py plan \
  --plan-dir /app/data/backtests/mtf-weekly-trap-plan-YYYYMMDD \
  --start-date 2021-07-01
```

Fetch only required 15-minute windows. A usable Dhan token must already be stored by Matsya, or supplied only in the process environment as `DHAN_ACCESS_TOKEN`:

```bash
python scripts/backtest_mtf_weekly_trap.py fetch \
  --plan-dir /app/data/backtests/mtf-weekly-trap-plan-YYYYMMDD
```

Run the server backtest after archive coverage is complete:

```bash
python scripts/backtest_mtf_weekly_trap.py run \
  --plan-dir /app/data/backtests/mtf-weekly-trap-plan-YYYYMMDD \
  --output-dir /app/data/backtests/mtf-weekly-trap-run-YYYYMMDD
```

Never substitute daily candles for the 15-minute structure shift. If data or a required execution capability is absent, build and validate the smallest reusable extension first, then run the backtest.
