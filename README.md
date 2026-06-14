# swing-trading-app

Private NSE swing-trading advisory project.

Current implementation stage: **Dhan data foundation + review diagnostics**.

## Branch Rules

- `develop`: active development.
- `main`: production-ready code only.
- Production remains untouched until `develop` is tested and intentionally merged.

## Stage 1 Scope

- Store a Dhan access token server-side only.
- Check token/account status using Dhan `GET /v2/profile`.
- Renew active web-generated tokens using Dhan `GET /v2/RenewToken`.
- Run an automatic renewal loop before expiry.
- Provide a manual fallback update flow if the server was offline or renewal failed.
- No AI decisioning and no order placement.
- Fetch and store the Dhan detailed instrument master for NSE equity segment only.
- Preserve all Dhan CSV fields as raw metadata plus normalized lookup columns.
- Fetch and store the official Nifty 500 constituent CSV from NSE, preserving every source column as raw metadata.
- Fetch rolling 45-calendar-day Dhan daily candles for mapped Nifty 500 stocks through a resumable, rate-limited job.
- Run automated Nifty 500 candle quality checks and show only exceptions for review.
- Scan the latest 45-day Nifty 500 candle window for stocks whose later high clears a selectable upward-move threshold; the default is 20%.
- Keep Drishti, watchlist, learning, and demo trading as retired/museum code until a new design is approved.
- Gemini/AI review and discipline code has been removed from active development.

## Project Layers

The repo separates three concepts:

- **Data layer**: token handling, instruments, universe data, candles, and quality checks.
- **Review / diagnostics tools**: momentum scans, move events, and regime diagnostics. These are manual review aids only.
- **Museum code**: retired Drishti, support/resistance, candlestick, watchlist, learning, and demo modules kept only as reference where still present.

Read the layer map before moving any museum/reference code back into active runtime:

- `docs/layers.md`
- `docs/decisions.md`
- `notes/research/README.md`

There is currently no active signal, demo-trading, or AI review workflow.

## Run Locally

Create `.env` from the example and set `APP_SECRET_KEY` before storing a token.

```powershell
Copy-Item .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Start with Docker:

```powershell
docker compose up --build
```

Backend: `http://localhost:8000/api/health`

Frontend: `http://localhost:5173`

## Safety

- Dhan tokens are encrypted before being written to disk.
- API responses never return the full access token.
- Automatic renewal only works while the token is still active.
- If renewal is missed and the token expires, use the manual fallback screen.
- The NSE equity instrument master is stored in SQLite and can be refreshed from Dhan on demand.
- Historical Dhan fetches run one mapped Nifty 500 instrument at a time, retry temporary failures, and record per-symbol failures without deleting successful candles.
- Automatic candle pruning is disabled by default with `AUTO_PURGE_MARKET_DATA=false`.
- The data-maintenance loop is limited to token maintenance and historical candle refresh. It does not run regime refresh, reversal radar, demo automation, or AI review.
- Data quality checks classify each stock as healthy, warning, or blocked before future analysis uses the candle cache.
