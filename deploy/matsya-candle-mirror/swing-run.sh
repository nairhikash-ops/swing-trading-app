#!/usr/bin/env bash
set -euo pipefail

readonly environment_file="${MATSYA_MIRROR_ENV_FILE:-/home/hacker/.config/matsya-candle-mirror.env}"
set -a
# shellcheck disable=SC1090
source "$environment_file"
set +a

readonly state_dir="${MATSYA_MIRROR_STATE_DIR:-/home/hacker/.local/state/matsya-candle-mirror}"
readonly log_file="$state_dir/mirror.log"
mkdir -p "$state_dir"
chmod 700 "$state_dir"
if [[ -f "$log_file" ]] && (( $(stat -c %s "$log_file") >= 10485760 )); then
  mv -f "$log_file" "$log_file.1"
fi
exec /home/hacker/.local/bin/matsya-candle-mirror-sync >> "$log_file" 2>&1
