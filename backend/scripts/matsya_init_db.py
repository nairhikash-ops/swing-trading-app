from __future__ import annotations

from app.matsya.db import connect, health_check, run_schema
from app.matsya.settings import MatsyaSettings


def main() -> None:
    settings = MatsyaSettings.from_env()
    with connect(settings) as conn:
        run_schema(conn)
        status = health_check(conn)
    print(f"Matsya schema initialized: database={status['database']} user={status['user']}")


if __name__ == "__main__":
    main()

