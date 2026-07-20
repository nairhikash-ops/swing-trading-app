# Backend image release marker

Build from the exact checked-out release commit and derive the marker from Git:

```bash
RELEASE_COMMIT="$(git rev-parse HEAD)"
docker build --build-arg "RELEASE_COMMIT=$RELEASE_COMMIT" \
  -f backend/Dockerfile -t "matsya-backend:$RELEASE_COMMIT" backend
```

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
