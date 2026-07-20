# Matsya validated intraday database runbook

This store is deliberately separate from the authoritative daily Matsya database. Set
`MATSYA_INTRADAY_DATABASE_URL` to the new PostgreSQL database and
`MATSYA_DAILY_DATABASE_URL` to the existing database. Startup refuses identical database
identities. The daily connection is used only inside `SET TRANSACTION READ ONLY` transactions.

## Configuration

- `MATSYA_INTRADAY_DATABASE_URL`: required, writable, separate PostgreSQL database.
- `MATSYA_DAILY_DATABASE_URL`: required, read-only daily database account preferred.
- `MATSYA_INTRADAY_TRUSTED_START_DATE`: optional override of the declared `2026-07-06`
  trusted start. Requests before it are refused.
- `MATSYA_INTRADAY_SYMBOL_UNIVERSE`: configurable comma-separated symbols.
- `MATSYA_MANUAL_DHAN_TOKEN`: required only for manual fetches; never pass it as a CLI argument.

No scheduler or WebSocket is installed. Run after market close for completed sessions only.
Dhan `toDate` is exclusive; a request for July 6–17 uses `fromDate=2026-07-06` and
`toDate=2026-07-18`.

## Commands

Run from `backend` with `python -m scripts.matsya_intraday_db`:

```text
migrate
validate --symbol RELIANCE --security-id 2885 --from-date 2026-07-17 --to-date 2026-07-17 --trading-dates 2026-07-17 --dry-run
ingest --symbol RELIANCE --security-id 2885 --from-date 2026-07-17 --to-date 2026-07-17 --trading-dates 2026-07-17
reconcile --symbol RELIANCE --security-id 2885 --from-date 2026-07-17 --to-date 2026-07-17 --trading-dates 2026-07-17 --dry-run
aggregate --symbol RELIANCE --security-id 2885 --from-date 2026-07-17 --to-date 2026-07-17 --trading-dates 2026-07-17
pilot --universe-csv pilot_symbols.csv --from-date 2026-07-06 --to-date 2026-07-17 --trading-dates 2026-07-06,2026-07-07,2026-07-08,2026-07-09,2026-07-10,2026-07-13,2026-07-14,2026-07-15,2026-07-16,2026-07-17 --dry-run
```

For a pilot, invoke `validate --dry-run` per mapped symbol over the same explicit completed
session list. Production ingestion is idempotent by provider/security/timestamp and symbol-day.
A rerun replaces only that separate database's symbol-day candles. Rejected responses are hashed
and quarantined with the raw API response; unavailable days are recorded without candles.

Only `accepted` complete 375-minute days may produce trusted derived bars. Five-, 15-, 30- and
60-minute buckets are anchored at 09:15 IST; the last 30/60-minute bucket is deliberately partial.
Trusted derivation additionally requires a completed reconciliation and a passing structural gate.
Daily reconciliation uses deliberately different names: `intraday_open/high/low`,
`last_minute_close`, and `normal_session_volume` versus `official_daily_*`. Exact open/high/low
equality is a strong cross-source validation flag; a mismatch is recorded as a warning, not a
structural rejection. Close and volume differences are informational because the
normal-session minute series and official daily statistics do not have identical session semantics.
Reconciliation never updates either candle source. The existing daily database remains authoritative
for daily and higher-timeframe historical research; minute-derived daily bars are diagnostics only.

The trusted-start declaration is based on two independent ten-session pilots (540 symbol-days,
202,500 candles) with complete 09:15–15:29 IST grids and no structural defects. Dhan's public
historical-data documentation describes per-timeframe OHLCV but does not explicitly define how its
minute volume relates to official daily statistics. NSE documents a separate 15:40–16:00 closing
session whose trades count as Normal Market trades. Therefore close and volume comparisons remain
stored diagnostics, not equivalence gates.
