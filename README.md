# bhavcopy-app

Private NSE bhavcopy research project.

Current implementation stage: **Full Bhavcopy only**.

## Branch Rules

- `develop`: active development.
- `main`: production-ready code only.
- Production remains untouched until `develop` is tested and intentionally merged.

## Scope

- Import manually downloaded NSE Full Bhavcopy + Security Deliverable files.
- Supported filename: `sec_bhavdata_full_DDMMYYYY.csv`.
- Store every bhavcopy row in SQLite.
- Deduplicate uploaded/imported files by checksum.
- Scan a server inbox folder for bulk imports.
- Provide a UI fallback for drag/drop upload.

No other data provider or trading workflow is part of the active app right now.

## Run Locally

Create `.env` from the example:

```powershell
Copy-Item .env.example .env
```

Start with Docker:

```powershell
docker compose up --build
```

Backend: `http://localhost:8000/api/health`

Frontend: `http://localhost:5173`

## Import Folder

Docker exposes the import inbox as:

```text
./bhavcopy_inbox
```

Drop `sec_bhavdata_full_DDMMYYYY.csv` files there, then click **Scan folder** in the UI.
