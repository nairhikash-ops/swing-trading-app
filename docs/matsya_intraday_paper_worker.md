# Matsya intraday paper execution worker

## Safety boundary

This worker is paper-only. It reads DhanHQ v2 live market packets and the read-only
intraday historical chart endpoint. It has no broker-order adapter, order endpoint,
or order mutation method. `MATSYA_INTRADAY_PAPER_ENABLED` defaults to `false`.

When disabled, the existing V8 and Uptrend-Sideways EOD runners continue to fill
pending orders and process exits exactly as before. When enabled, those runners
still generate EOD signals and pending paper orders, but only this worker may turn
pending orders into positions or close positions.

## State machine

1. The EOD strategy writes a pending paper order with its existing sizing and
   structural fields.
2. The worker subscribes only to symbols present in pending orders or open
   positions.
3. A pending order can enter only on a later trading date, during the live market
   session, at the first valid observed ticker price. A missing or late feed never
   creates a synthetic entry.
4. An open position is evaluated packet-by-packet. The first chronological stop or
   target observation closes it. A price first observed through a stop uses that
   worse observed price, plus the strategy's existing paper friction.
5. After the market, one-minute intraday candles reconcile missed exit observations
   chronologically. If stop and target both occur in one minute, the stop wins and
   the event is labelled `ambiguous`.
6. Orders with no valid next-session live entry are recorded as missed, not filled.

State and CSV writes use an inter-process lock plus temporary-file `fsync` and
atomic replacement. Stable event IDs make entry, exit, and ledger replay
idempotent across worker restarts. Existing positions without intraday metadata are
reported as `legacy`; worker events use `live`, `recovered`, or `ambiguous`.

## Preserved strategy policies

- V8: allocation is capped by `liquidity_cap`; 0.25% base and 0.50% harsh
  friction; target 10% above observed raw entry; stop 5% below it; inclusive stop;
  maximum 20 reconciled sessions.
- Uptrend-Sideways: existing allocation and 0.25%/0.50% friction; signal target is
  preserved; structural `base_low` stop is strict (`price < base_low`); maximum 40
  reconciled sessions.

## DhanHQ v2 protocol

Implementation follows the official [Live Market Feed](https://dhanhq.co/docs/v2/live-market-feed/),
[Historical Data](https://dhanhq.co/docs/v2/historical-data/), and
[Annexure](https://dhanhq.co/docs/v2/annexure/) documentation. It uses ticker
subscription request code 15, unsubscribe code 16, little-endian binary ticker
response code 2, NSE_EQ, ping/pong health checks, reconnect backoff, and the
`/v2/charts/intraday` one-minute endpoint for EOD recovery.

## Prepared deployment commands (not executed during development)

From `deploy/matsya-setup` after setting the feature flag deliberately:

```bash
docker compose build matsya-api matsya-ui matsya-intraday-paper-worker v8-demo-trader uptrend-sideways-paper-trader
docker compose up -d matsya-api matsya-ui matsya-intraday-paper-worker
docker compose ps
docker compose logs --tail=200 matsya-intraday-paper-worker
```

Read-only Compose validation can be run separately with
`docker compose --env-file .env.example config -q`.

The worker service has no `ports` entry and remains private on
`matsya-db_default`.

## Operational limitations

- Ticker packets provide observed prices, not exchange order-book sequencing. A
  same-minute recovery candle that contains both thresholds is intentionally
  pessimistic.
- A feed outage can recover exits from minute candles, but it cannot recover an
  entry without violating the first-live-price rule.
- Trading holidays are inferred from the presence of Dhan intraday candles; the
  worker does not maintain its own exchange calendar.
- The file-backed strategy ledgers remain single-host storage and are not intended
  for multi-node active/active workers.
