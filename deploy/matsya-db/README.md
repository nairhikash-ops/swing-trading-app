# Matsya PostgreSQL Deployment Template

This folder is only the isolated Matsya PostgreSQL foundation. It does not
deploy the swing-trading backend or frontend.

Server setup:

```bash
cd /home/hacker/apps/matsya-db
cp .env.example .env
chmod 600 .env
docker compose -p matsya-db up -d
docker compose -p matsya-db ps
```

PostgreSQL is bound to `127.0.0.1:5432` and is not publicly exposed.

Database initialization from the backend environment:

```bash
cd backend
python scripts/matsya_init_db.py
python scripts/matsya_status.py
```

The `.env` file contains secrets. Do not print it and do not commit it.
