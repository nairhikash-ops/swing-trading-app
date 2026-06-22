# Matsya PostgreSQL Foundation

This package is the isolated PostgreSQL foundation for Matsya raw market data.
It does not replace the existing SQLite-backed app storage and does not restore
old Docker volumes or old SQLite data.

Owned areas:

- PostgreSQL schema in `app/matsya/schema.sql`
- Connection bootstrap in `app/matsya/db.py`
- Environment loading in `app/matsya/settings.py`
- Raw/normalized persistence helpers in `app/matsya/repository.py`
- Dhan/NSE normalization helpers in `app/matsya/ingest.py`

Required secret material must come from environment variables or the server-side
`.env` file. Do not print or commit those values.
