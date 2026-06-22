# Matsya Setup UI/API

This compose bundle runs only the Matsya setup API and the Matsya Dhan setup UI.
It does not deploy the old backend, old frontend, ML tools, or a PostgreSQL
container.

Expected existing database foundation:

- Container: `matsya-postgres`
- Database: `matsya`
- Docker network: `matsya-db_default`

Local ports:

- Matsya API: `127.0.0.1:8020`
- Matsya UI: `127.0.0.1:5190`

Setup:

```bash
cd /home/hacker/apps/matsya-setup
cp .env.example .env
chmod 600 .env
docker compose up -d --build
```

Generate `MATSYA_APP_SECRET_KEY` with:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

The `.env` file contains secrets. Do not print it and do not commit it.
