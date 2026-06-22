from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

from app.matsya.settings import MatsyaSettings


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(settings: MatsyaSettings | None = None) -> psycopg.Connection[Any]:
    resolved = settings or MatsyaSettings.from_env()
    return psycopg.connect(resolved.database_url, autocommit=False)


def load_schema_sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def run_schema(conn: psycopg.Connection[Any]) -> None:
    conn.execute(load_schema_sql())
    conn.commit()


def health_check(conn: psycopg.Connection[Any]) -> dict[str, str]:
    row = conn.execute(
        "SELECT current_database() AS database_name, current_user AS user_name"
    ).fetchone()
    return {"database": row[0], "user": row[1]}
