# Matsya validated one-minute foundation: approved pilot report

## Decision

The separate one-minute PostgreSQL foundation and normal-session reconciliation policy are approved.
The trusted minute-data start date is **2026-07-06**.

The existing daily database remains authoritative for official daily and higher-timeframe historical
research. The separate minute database is authoritative for normal-session one-minute movement,
deterministic 5m/15m/30m/60m candles, same-day sequence, intraday entries and exits, and forward
testing. Minute-derived daily aggregates are diagnostics and never replace official daily data.

## Pilot evidence

- Two independent recent ten-session windows: 2026-06-19–2026-07-03 and 2026-07-06–2026-07-17.
- 27 active NSE equities across high, medium and relatively illiquid volume strata.
- 54 Dhan `/v2/charts/intraday` requests with `interval=1`; all returned HTTP 200.
- 540 symbol-days and 202,500 candles.
- 540/540 days contained exactly 375 timestamps from 09:15 through 15:29 IST.
- No malformed arrays, duplicate or non-increasing timestamps, wrong dates, out-of-session candles,
  invalid OHLC, non-positive prices, negative volume, or missing session minutes.
- Normal-session open/high/low matched the authoritative daily source on 539/540 days.
- One cross-source warning: TATACHEM on 2026-07-01 had normal-session low 683.10 versus official
  daily low 683.00, a 0.014641% difference. Its minute grid was structurally complete and valid.
- Last-minute close equalled official daily close on 10/540 days. Absolute percentage difference:
  mean 0.212131%, median 0.149647%, maximum 2.868977%.
- Normal-session volume was below official daily volume on all 540 days. Absolute percentage
  difference: mean 0.448497%, median 0.316639%, maximum 5.823901%.

## Approved semantics and gates

Minute reconciliation fields:

- `intraday_open`
- `intraday_high`
- `intraday_low`
- `last_minute_close`
- `normal_session_volume`

Authoritative daily reconciliation fields:

- `official_daily_open`
- `official_daily_high`
- `official_daily_low`
- `official_daily_close`
- `official_daily_volume`

Acceptance is controlled by structural completeness. Malformed or invalid candles are rejected and
quarantined; missing normal-session minutes produce a warning. Open/high/low discrepancies against
the daily source are prominent cross-source warnings. Close and volume comparisons are informational.

Dhan documents its intraday endpoint as timeframe-specific OHLCV but does not explicitly define
equivalence with official daily statistics. NSE documents a separate 15:40–16:00 closing session at
the official close price and states that its trades count as Normal Market trades. Direct written
confirmation from Dhan about minute-versus-daily volume inclusion remains desirable.

References:

- https://dhanhq.co/docs/v2/historical-data/
- https://www.nseindia.com/static/products-services/equity-market-segment

## Operational boundary

The pilot used read-only access to the existing daily database and made no production database,
Docker, scheduler, deployment, trading, or order changes. No bulk backfill was performed. Raw pilot
JSON and CSV outputs remain local under ignored `test-output/` paths and are not part of this change.

Final verdict: **Separate 1-minute database foundation completed; recent minute-data quality
acceptable, subject to documenting close and volume semantics.**
