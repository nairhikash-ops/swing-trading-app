# Backend image release marker

Build from the exact checked-out release commit and derive the marker from Git:

```bash
RELEASE_COMMIT="$(git rev-parse HEAD)"
docker build --build-arg "RELEASE_COMMIT=$RELEASE_COMMIT" \
  -f backend/Dockerfile -t "matsya-backend:$RELEASE_COMMIT" backend
```

For the Matsya deployment Compose stack, use the checked-out commit directly;
the command fails closed when the value is missing or malformed:

```bash
RELEASE_COMMIT="$(git rev-parse HEAD)"
test "$(git rev-parse --verify HEAD)" = "$RELEASE_COMMIT"
printf '%s' "$RELEASE_COMMIT" | grep -Eq '^[0-9a-f]{40}$'
export RELEASE_COMMIT
docker compose -f deploy/matsya-setup/docker-compose.yml build
```

The required argument is applied to `matsya-api`, `v8-demo-trader`,
`uptrend-sideways-paper-trader`, `matsya-intraday-paper-worker`,
`matsya-renewal-worker`, and `matsya-ohlcv-worker`. No SHA is defaulted.

The Matsya Compose deployment also requires persistent paths to be supplied
outside the versioned release directory:

```text
MATSYA_DATA_ROOT=/opt/matsya-persistent/data
MATSYA_ENV_FILE=/etc/matsya/matsya.env
```

Use them explicitly when rendering or building Compose:

```bash
export MATSYA_DATA_ROOT=/opt/matsya-persistent/data
export MATSYA_ENV_FILE=/etc/matsya/matsya.env
docker compose --profile manual -f deploy/matsya-setup/docker-compose.yml config
docker compose --profile manual -f deploy/matsya-setup/docker-compose.yml build
```

Provisioning `/opt/matsya-persistent/data` and `/etc/matsya/matsya.env`, and
migrating existing data into the persistent root, are separate controlled
operational steps. This PR does not provision, copy, migrate, or modify server
data or secrets.

The Dockerfile rejects missing or malformed values and writes
`/app/RELEASE_COMMIT` during image build only. It is a regular root-owned
file with mode `0444` and one trailing newline; no runtime generation occurs.

Verify before deployment:

```bash
docker run --rm --entrypoint sh "matsya-backend:$RELEASE_COMMIT" -c \
  'test "$(readlink -f /app/RELEASE_COMMIT)" = /app/RELEASE_COMMIT &&
   test "$(cat /app/RELEASE_COMMIT)" = "$RELEASE_COMMIT" &&
   test "$(stat -c %u:%g:%a /app/RELEASE_COMMIT)" = 0:0:444'
```
