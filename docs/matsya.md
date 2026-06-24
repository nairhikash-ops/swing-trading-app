# Matsya PostgreSQL Raw Data Foundation

Matsya is the clean PostgreSQL foundation for raw market data and provider
metadata. It is separate from the existing SQLite-backed control app.

## Scope

- Store Dhan/NSE provider metadata.
- Store raw import run metadata and errors.
- Store Dhan raw response hashes and JSON payloads where appropriate.
- Store normalized instrument master rows with original raw rows.
- Store normalized market universe membership rows with original raw rows.
- Store daily OHLCV candles with original raw candle payloads.
- Capture Dhan profile and token-renewal metadata without storing plaintext tokens.

## Non-goals

- No restore of old SQLite data.
- No restore of old Docker volumes.
- No frontend or backend deployment.
- No mutation of GitHub `main`.
- No public database exposure.

## Server Database

Use the isolated deployment folder:

```text
deploy/matsya-db/docker-compose.yml
```

Expected project/container/volume:

- Compose project: `matsya-db`
- Container: `matsya-postgres`
- Database: `matsya`
- User: `matsya_user`
- Volume: `matsya-postgres-data`
- Port binding: `127.0.0.1:5432:5432`

## Operational Commands

Run from `backend/` with the server-side database environment loaded:

```bash
python scripts/matsya_init_db.py
python scripts/matsya_status.py
python scripts/matsya_import_instruments.py --dry-run
python scripts/matsya_import_universe.py --dry-run
python scripts/matsya_fetch_ohlcv.py --security-id 1333 --from-date 2026-01-01 --to-date 2026-01-31 --dry-run
```

Secrets must stay in environment variables or the server `.env`; they should not
be printed, committed, or copied into docs.

## Read-Only Market Data API

Matsya owns the PostgreSQL market-data tables. Other modules must consume
Matsya data through read-only HTTP endpoints instead of connecting to or writing
Matsya tables directly.

All market-data endpoints are `GET` only:

```text
GET /api/matsya/market-data/status
GET /api/matsya/market-data/symbols?universe=NIFTY_500&limit=50&offset=0
GET /api/matsya/market-data/ohlcv?symbol=RELIANCE&from=2026-01-01&to=2026-06-23&limit=250&order=asc
GET /api/matsya/market-data/ohlcv?security_id=2885&limit=5&order=desc
GET /api/matsya/market-data/ohlcv/latest?symbol=RELIANCE&days=365
GET /api/matsya/market-data/validation
```

Responses include normalized instruments, universe membership, OHLCV candles,
and safe validation/status summaries. They do not include token values,
encrypted tokens, raw candle payloads, database URLs, or secret-bearing fields.

Consumers should treat the API as the only supported contract for Matsya market
data. Only Matsya ingestion, renewal, and OHLCV worker services may write to
Matsya tables.
