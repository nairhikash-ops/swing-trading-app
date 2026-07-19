#!/usr/bin/env bash
set -euo pipefail

# This script is intended to be the forced command for a dedicated SSH key.
# It exposes candle CSV data only and never accepts arbitrary SQL or shell input.

readonly container="${MATSYA_MIRROR_POSTGRES_CONTAINER:-matsya-postgres}"
readonly database="${MATSYA_MIRROR_POSTGRES_DB:-matsya}"
readonly database_user="${MATSYA_MIRROR_POSTGRES_USER:-matsya_user}"
readonly requested_command="${SSH_ORIGINAL_COMMAND:-health}"
readonly columns="provider_code,security_id,exchange_segment,instrument,trading_date,source_timestamp,open_price,high_price,low_price,close_price,volume,open_interest,raw_candle,first_seen_at,updated_at"

run_psql() {
  docker exec "$container" psql -X -v ON_ERROR_STOP=1 -U "$database_user" -d "$database" "$@"
}

case "$requested_command" in
  health)
    run_psql -Atc "
      SELECT COUNT(*) || '|' || COALESCE(MAX(trading_date)::text, '') || '|' ||
             COALESCE(to_char(MAX(updated_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), '')
      FROM matsya.ohlcv_daily;
    "
    ;;
  snapshot)
    run_psql -c "COPY (
      SELECT $columns
      FROM matsya.ohlcv_daily
      ORDER BY provider_code, security_id, trading_date
    ) TO STDOUT WITH (FORMAT csv)" | gzip -1
    ;;
  since\ *)
    since="${requested_command#since }"
    if [[ ! "$since" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$ ]]; then
      echo "Invalid mirror watermark." >&2
      exit 64
    fi
    run_psql -c "COPY (
      SELECT $columns
      FROM matsya.ohlcv_daily
      WHERE updated_at >= TIMESTAMPTZ '$since'
      ORDER BY updated_at, provider_code, security_id, trading_date
    ) TO STDOUT WITH (FORMAT csv)" | gzip -1
    ;;
  *)
    echo "Unsupported mirror command." >&2
    exit 64
    ;;
esac
