#!/bin/sh
set -eu

fail() { printf '%s\n' "matsya-compose: $1" >&2; exit 2; }
NL=$(printf '\n_'); NL=${NL%_}
CR=$(printf '\r_'); CR=${CR%_}

validate_sha() {
  value=${RELEASE_COMMIT-}
  printf '%s' "$value" | grep -Eq '^[0-9a-f]{40}$' || fail 'RELEASE_COMMIT must be exactly 40 lowercase hexadecimal characters'
}

validate_abs_path() {
  name=$1
  value=$2
  [ -n "$value" ] || fail "$name must be set"
  case "$value" in
    /*) ;;
    *) fail "$name must be an absolute POSIX path" ;;
  esac
  case "$value" in
    /) fail "$name must not be /" ;;
    */) fail "$name must not have a trailing slash" ;;
  esac
  case "$value" in
    *"$NL"*|*"$CR"*) fail "$name must not contain newline characters" ;;
  esac
  if printf '%s' "$value" | LC_ALL=C grep -q '[[:cntrl:]]'; then
    fail "$name must not contain control characters"
  fi
}

validate_sha
validate_abs_path MATSYA_DATA_ROOT "${MATSYA_DATA_ROOT-}"
validate_abs_path MATSYA_ENV_FILE "${MATSYA_ENV_FILE-}"
[ -f "$MATSYA_ENV_FILE" ] || fail 'MATSYA_ENV_FILE must name an existing regular file'
[ ! -L "$MATSYA_ENV_FILE" ] || fail 'MATSYA_ENV_FILE must not be a symlink'

if ! SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd); then
  fail 'could not resolve wrapper directory'
fi
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
[ -f "$COMPOSE_FILE" ] || fail "Compose file not found: $COMPOSE_FILE"
[ ! -L "$COMPOSE_FILE" ] || fail "Compose file must not be a symlink: $COMPOSE_FILE"

exec docker compose --profile manual -f "$COMPOSE_FILE" "$@"
