#!/usr/bin/env bash
set -euo pipefail

readonly primary_host="${MATSYA_MIRROR_PRIMARY_HOST:?MATSYA_MIRROR_PRIMARY_HOST is required}"
readonly primary_user="${MATSYA_MIRROR_PRIMARY_USER:-matsya_mirror}"
readonly ssh_key="${MATSYA_MIRROR_SSH_KEY:?MATSYA_MIRROR_SSH_KEY is required}"
readonly known_hosts="${MATSYA_MIRROR_KNOWN_HOSTS:?MATSYA_MIRROR_KNOWN_HOSTS is required}"
readonly state_dir="${MATSYA_MIRROR_STATE_DIR:-/var/lib/matsya-candle-mirror}"
readonly backup_dir="${MATSYA_MIRROR_BACKUP_DIR:-/var/backups/matsya-candle-mirror}"
readonly container="${MATSYA_MIRROR_POSTGRES_CONTAINER:-matsya-postgres}"
readonly database="${MATSYA_MIRROR_POSTGRES_DB:-matsya}"
readonly database_user="${MATSYA_MIRROR_POSTGRES_USER:-matsya_user}"
readonly full_snapshot="${MATSYA_MIRROR_FULL_SNAPSHOT:-false}"
readonly columns="provider_code,security_id,exchange_segment,instrument,trading_date,source_timestamp,open_price,high_price,low_price,close_price,volume,open_interest,raw_candle,first_seen_at,updated_at"

mkdir -p "$state_dir" "$backup_dir"
chmod 700 "$state_dir" "$backup_dir"
exec 9>"$state_dir/sync.lock"
flock -n 9 || exit 0

tmp_dir="$(mktemp -d "$state_dir/run.XXXXXX")"
container_csv="/tmp/matsya-candle-mirror.csv"
cleanup() {
  docker exec "$container" rm -f "$container_csv" >/dev/null 2>&1 || true
  rm -rf -- "$tmp_dir"
}
trap cleanup EXIT

ssh_args=(
  -i "$ssh_key"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes
  -o UserKnownHostsFile="$known_hosts"
)

watermark_file="$state_dir/watermark"
initial_sync=false
replace_target=false
if [[ "$full_snapshot" == true ]]; then
  remote_command="snapshot"
  replace_target=true
  if [[ ! -s "$watermark_file" ]]; then
    initial_sync=true
  fi
elif [[ -s "$watermark_file" ]]; then
  watermark="$(tr -d '\r\n' < "$watermark_file")"
  remote_command="since $watermark"
else
  initial_sync=true
  replace_target=true
  remote_command="snapshot"
fi

if [[ "$initial_sync" == true ]]; then
  backup="$backup_dir/matsya-before-candle-mirror-$(date -u +%Y%m%dT%H%M%SZ).dump"
  docker exec "$container" pg_dump -Fc -U "$database_user" -d "$database" > "$backup"
  chmod 600 "$backup"
fi

payload="$tmp_dir/candles.csv.gz"
ssh "${ssh_args[@]}" "$primary_user@$primary_host" "$remote_command" > "$payload"
gzip -t "$payload"
gzip -dc "$payload" > "$tmp_dir/candles.csv"
docker cp "$tmp_dir/candles.csv" "$container:$container_csv" >/dev/null

mode_sql=""
if [[ "$replace_target" == true ]]; then
  mode_sql="TRUNCATE matsya.ohlcv_daily RESTART IDENTITY;"
fi

docker exec -i "$container" psql -X -v ON_ERROR_STOP=1 -U "$database_user" -d "$database" <<SQL
BEGIN;
CREATE TEMP TABLE matsya_candle_mirror_stage ON COMMIT DROP AS
  SELECT $columns FROM matsya.ohlcv_daily WITH NO DATA;
COPY matsya_candle_mirror_stage ($columns)
  FROM '$container_csv' WITH (FORMAT csv);
$mode_sql
INSERT INTO matsya.ohlcv_daily ($columns)
SELECT $columns FROM matsya_candle_mirror_stage
ON CONFLICT (provider_code, security_id, trading_date) DO UPDATE SET
  exchange_segment = EXCLUDED.exchange_segment,
  instrument = EXCLUDED.instrument,
  source_timestamp = EXCLUDED.source_timestamp,
  open_price = EXCLUDED.open_price,
  high_price = EXCLUDED.high_price,
  low_price = EXCLUDED.low_price,
  close_price = EXCLUDED.close_price,
  volume = EXCLUDED.volume,
  open_interest = EXCLUDED.open_interest,
  raw_candle = EXCLUDED.raw_candle,
  first_seen_at = EXCLUDED.first_seen_at,
  updated_at = EXCLUDED.updated_at,
  last_import_run_id = NULL;
COMMIT;
SQL

new_watermark="$(docker exec "$container" psql -X -U "$database_user" -d "$database" -Atc \
  "SELECT COALESCE(to_char(MAX(updated_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), '') FROM matsya.ohlcv_daily;")"
if [[ -z "$new_watermark" ]]; then
  echo "Mirror produced an empty target table; refusing to advance watermark." >&2
  exit 1
fi
printf '%s\n' "$new_watermark" > "$watermark_file.tmp"
chmod 600 "$watermark_file.tmp"
mv -f "$watermark_file.tmp" "$watermark_file"

source_health="$(ssh "${ssh_args[@]}" "$primary_user@$primary_host" health)"
target_health="$(docker exec "$container" psql -X -U "$database_user" -d "$database" -Atc \
  "SELECT COUNT(*) || '|' || COALESCE(MAX(trading_date)::text, '') || '|' || COALESCE(to_char(MAX(updated_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), '') FROM matsya.ohlcv_daily;")"
echo "source=$source_health target=$target_health mode=$remote_command"
