import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.timezone import now_utc


@dataclass(frozen=True)
class StoredToken:
    dhan_client_id: str
    encrypted_access_token: str
    token_source: str
    expiry_time: datetime | None
    profile: dict[str, Any]
    last_status_check_at: datetime | None
    last_renew_attempt_at: datetime | None
    last_renew_success_at: datetime | None
    last_error: str
    updated_at: datetime


def _dt_to_db(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt_from_db(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class TokenStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dhan_token (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    dhan_client_id TEXT NOT NULL,
                    encrypted_access_token TEXT NOT NULL,
                    token_source TEXT NOT NULL,
                    expiry_time TEXT,
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    last_status_check_at TEXT,
                    last_renew_attempt_at TEXT,
                    last_renew_success_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        if os.name != "nt":
            os.chmod(self.database_path, 0o600)

    def get(self) -> StoredToken | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM dhan_token WHERE id = 1").fetchone()
        if row is None:
            return None
        return StoredToken(
            dhan_client_id=row["dhan_client_id"],
            encrypted_access_token=row["encrypted_access_token"],
            token_source=row["token_source"],
            expiry_time=_dt_from_db(row["expiry_time"]),
            profile=json.loads(row["profile_json"] or "{}"),
            last_status_check_at=_dt_from_db(row["last_status_check_at"]),
            last_renew_attempt_at=_dt_from_db(row["last_renew_attempt_at"]),
            last_renew_success_at=_dt_from_db(row["last_renew_success_at"]),
            last_error=row["last_error"] or "",
            updated_at=_dt_from_db(row["updated_at"]) or now_utc(),
        )

    def upsert_token(
        self,
        dhan_client_id: str,
        encrypted_access_token: str,
        token_source: str,
        expiry_time: datetime | None,
        profile: dict[str, Any] | None = None,
        clear_error: bool = True,
    ) -> None:
        current_time = now_utc()
        profile_json = json.dumps(profile or {})
        last_error = "" if clear_error else (self.get().last_error if self.get() else "")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dhan_token (
                    id, dhan_client_id, encrypted_access_token, token_source, expiry_time,
                    profile_json, last_error, created_at, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    dhan_client_id = excluded.dhan_client_id,
                    encrypted_access_token = excluded.encrypted_access_token,
                    token_source = excluded.token_source,
                    expiry_time = excluded.expiry_time,
                    profile_json = excluded.profile_json,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    dhan_client_id,
                    encrypted_access_token,
                    token_source,
                    _dt_to_db(expiry_time),
                    profile_json,
                    last_error,
                    _dt_to_db(current_time),
                    _dt_to_db(current_time),
                ),
            )

    def update_profile(self, profile: dict[str, Any], expiry_time: datetime | None, error: str = "") -> None:
        current_time = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE dhan_token
                SET profile_json = ?, expiry_time = COALESCE(?, expiry_time),
                    last_status_check_at = ?, last_error = ?, updated_at = ?
                WHERE id = 1
                """,
                (json.dumps(profile), _dt_to_db(expiry_time), _dt_to_db(current_time), error, _dt_to_db(current_time)),
            )

    def mark_renew_attempt(self, error: str = "") -> None:
        current_time = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE dhan_token
                SET last_renew_attempt_at = ?, last_error = ?, updated_at = ?
                WHERE id = 1
                """,
                (_dt_to_db(current_time), error, _dt_to_db(current_time)),
            )

    def mark_renew_success(self) -> None:
        current_time = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE dhan_token
                SET last_renew_success_at = ?, last_error = '', updated_at = ?
                WHERE id = 1
                """,
                (_dt_to_db(current_time), _dt_to_db(current_time)),
            )
