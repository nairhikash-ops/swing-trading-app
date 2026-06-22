from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.crypto import TokenCrypto
from app.dhan_client import DhanClient
from app.matsya.db import connect, run_schema
from app.matsya.ingest import sha256_payload, token_hash
from app.matsya.settings import MatsyaSettings
from app.timezone import now_utc, to_utc


@dataclass(frozen=True)
class MatsyaStoredToken:
    dhan_client_id: str
    encrypted_access_token: str
    access_token_hash: str
    token_source: str
    expiry_time: datetime | None
    profile: dict[str, Any]
    last_status_check_at: datetime | None
    last_renew_attempt_at: datetime | None
    last_renew_success_at: datetime | None
    last_error: str
    updated_at: datetime | None


class MatsyaDhanTokenService:
    def __init__(self, settings: MatsyaSettings, dhan_client: DhanClient | None = None) -> None:
        self.settings = settings
        self.dhan_client = dhan_client or DhanClient(settings.dhan_api_base_url)

    def _crypto(self) -> TokenCrypto:
        return TokenCrypto(self.settings.app_secret_key)

    def status(self) -> dict[str, Any]:
        with connect(self.settings) as conn:
            run_schema(conn)
            token = self._get(conn)
        if token is None:
            return _empty_status()
        return self._status_from_token(token)

    async def save_manual_token(
        self,
        *,
        dhan_client_id: str,
        access_token: str,
        expiry_time: datetime | None,
        validate_with_dhan: bool,
    ) -> dict[str, Any]:
        crypto = self._crypto()
        final_expiry = to_utc(expiry_time) if expiry_time else None
        profile_payload: dict[str, Any] = {}
        last_status_check_at = None

        if validate_with_dhan:
            profile = await self.dhan_client.profile(access_token)
            if profile.dhan_client_id and profile.dhan_client_id != dhan_client_id:
                raise ValueError("Dhan profile client ID does not match the submitted client ID.")
            profile_payload = profile.raw
            final_expiry = profile.token_validity or final_expiry
            last_status_check_at = now_utc()

        with connect(self.settings) as conn:
            run_schema(conn)
            self._upsert(
                conn,
                dhan_client_id=dhan_client_id,
                encrypted_access_token=crypto.encrypt(access_token),
                access_token_hash=token_hash(access_token),
                token_source="manual",
                expiry_time=final_expiry,
                profile=profile_payload,
                last_status_check_at=last_status_check_at,
                clear_error=True,
            )
            if profile_payload:
                self._insert_profile_snapshot(
                    conn,
                    dhan_client_id=dhan_client_id,
                    access_token_hash=token_hash(access_token),
                    profile=profile_payload,
                )
            conn.commit()
            token = self._get(conn)
        return self._status_from_token(token) if token else _empty_status()

    async def refresh_profile(self) -> dict[str, Any]:
        with connect(self.settings) as conn:
            run_schema(conn)
            token = self._get(conn)
            if token is None:
                return _empty_status()
            access_token = self._crypto().decrypt(token.encrypted_access_token)
            try:
                profile = await self.dhan_client.profile(access_token)
                self._update_profile(conn, profile.raw, profile.token_validity, "")
                self._insert_profile_snapshot(
                    conn,
                    dhan_client_id=token.dhan_client_id,
                    access_token_hash=token.access_token_hash,
                    profile=profile.raw,
                )
            except (httpx.HTTPError, ValueError) as exc:
                self._update_profile(conn, token.profile, token.expiry_time, str(exc))
            conn.commit()
            refreshed = self._get(conn)
        return self._status_from_token(refreshed) if refreshed else _empty_status()

    async def renew(self) -> tuple[bool, dict[str, Any], str]:
        with connect(self.settings) as conn:
            run_schema(conn)
            token = self._get(conn)
            if token is None:
                return False, _empty_status(), "No Dhan token has been stored."
            access_token = self._crypto().decrypt(token.encrypted_access_token)
            self._mark_renew_attempt(conn, "")
            try:
                renewed = await self.dhan_client.renew_token(access_token, token.dhan_client_id)
                renewed_hash = token_hash(renewed.access_token)
                self._upsert(
                    conn,
                    dhan_client_id=token.dhan_client_id,
                    encrypted_access_token=self._crypto().encrypt(renewed.access_token),
                    access_token_hash=renewed_hash,
                    token_source="renewed",
                    expiry_time=renewed.expiry_time,
                    profile=token.profile,
                    last_status_check_at=token.last_status_check_at,
                    clear_error=True,
                )
                self._insert_renewal_run(
                    conn,
                    token=token,
                    renewed_access_token_hash=renewed_hash,
                    response=renewed.raw,
                    status="completed",
                )
                self._mark_renew_success(conn)
                conn.commit()
                refreshed = self._get(conn)
                return True, self._status_from_token(refreshed), "Token renewed successfully."
            except (httpx.HTTPError, ValueError) as exc:
                self._mark_renew_attempt(conn, str(exc))
                self._insert_renewal_run(
                    conn,
                    token=token,
                    renewed_access_token_hash="",
                    response={},
                    status="failed",
                    error_message=str(exc),
                )
                conn.commit()
                refreshed = self._get(conn)
                return False, self._status_from_token(refreshed), "Token renewal failed."

    def _get(self, conn: Any) -> MatsyaStoredToken | None:
        row = conn.execute(
            """
            SELECT dhan_client_id, encrypted_access_token, access_token_hash, token_source,
                   expiry_time, profile_json, last_status_check_at, last_renew_attempt_at,
                   last_renew_success_at, last_error, updated_at
            FROM matsya.dhan_token_state
            WHERE id = 1
            """
        ).fetchone()
        if row is None:
            return None
        return MatsyaStoredToken(
            dhan_client_id=row[0],
            encrypted_access_token=row[1],
            access_token_hash=row[2],
            token_source=row[3],
            expiry_time=row[4],
            profile=row[5] or {},
            last_status_check_at=row[6],
            last_renew_attempt_at=row[7],
            last_renew_success_at=row[8],
            last_error=row[9] or "",
            updated_at=row[10],
        )

    def _upsert(
        self,
        conn: Any,
        *,
        dhan_client_id: str,
        encrypted_access_token: str,
        access_token_hash: str,
        token_source: str,
        expiry_time: datetime | None,
        profile: dict[str, Any],
        last_status_check_at: datetime | None,
        clear_error: bool,
    ) -> None:
        current = self._get(conn)
        last_error = "" if clear_error else (current.last_error if current else "")
        conn.execute(
            """
            INSERT INTO matsya.dhan_token_state (
                id, dhan_client_id, encrypted_access_token, access_token_hash, token_source,
                expiry_time, profile_json, last_status_check_at, last_error
            )
            VALUES (1, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                dhan_client_id = EXCLUDED.dhan_client_id,
                encrypted_access_token = EXCLUDED.encrypted_access_token,
                access_token_hash = EXCLUDED.access_token_hash,
                token_source = EXCLUDED.token_source,
                expiry_time = EXCLUDED.expiry_time,
                profile_json = EXCLUDED.profile_json,
                last_status_check_at = COALESCE(EXCLUDED.last_status_check_at, matsya.dhan_token_state.last_status_check_at),
                last_error = EXCLUDED.last_error,
                updated_at = now()
            """,
            (
                dhan_client_id,
                encrypted_access_token,
                access_token_hash,
                token_source,
                expiry_time,
                json.dumps(profile, sort_keys=True),
                last_status_check_at,
                last_error,
            ),
        )

    def _update_profile(
        self,
        conn: Any,
        profile: dict[str, Any],
        expiry_time: datetime | None,
        error: str,
    ) -> None:
        conn.execute(
            """
            UPDATE matsya.dhan_token_state
            SET profile_json = %s::jsonb,
                expiry_time = COALESCE(%s, expiry_time),
                last_status_check_at = now(),
                last_error = %s,
                updated_at = now()
            WHERE id = 1
            """,
            (json.dumps(profile, sort_keys=True), expiry_time, error),
        )

    def _mark_renew_attempt(self, conn: Any, error: str) -> None:
        conn.execute(
            """
            UPDATE matsya.dhan_token_state
            SET last_renew_attempt_at = now(),
                last_error = %s,
                updated_at = now()
            WHERE id = 1
            """,
            (error,),
        )

    def _mark_renew_success(self, conn: Any) -> None:
        conn.execute(
            """
            UPDATE matsya.dhan_token_state
            SET last_renew_success_at = now(),
                last_error = '',
                updated_at = now()
            WHERE id = 1
            """
        )

    def _insert_profile_snapshot(
        self,
        conn: Any,
        *,
        dhan_client_id: str,
        access_token_hash: str,
        profile: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO matsya.dhan_profile_snapshots (
                dhan_client_id, access_token_hash, profile_json, profile_hash
            )
            VALUES (%s, %s, %s::jsonb, %s)
            ON CONFLICT (provider_code, access_token_hash, profile_hash) DO NOTHING
            """,
            (dhan_client_id, access_token_hash, json.dumps(profile, sort_keys=True), sha256_payload(profile)),
        )

    def _insert_renewal_run(
        self,
        conn: Any,
        *,
        token: MatsyaStoredToken,
        renewed_access_token_hash: str,
        response: dict[str, Any],
        status: str,
        error_message: str = "",
    ) -> None:
        conn.execute(
            """
            INSERT INTO matsya.dhan_token_renewal_runs (
                dhan_client_id, previous_access_token_hash, renewed_access_token_hash,
                response_json, response_hash, status, error_message
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (
                token.dhan_client_id,
                token.access_token_hash,
                renewed_access_token_hash,
                json.dumps(response, sort_keys=True),
                sha256_payload(response) if response else "",
                status,
                error_message,
            ),
        )

    def _status_from_token(self, token: MatsyaStoredToken | None) -> dict[str, Any]:
        if token is None:
            return _empty_status()
        state = _token_state(token, self.settings.renew_before_minutes)
        if not self.settings.app_secret_key:
            state = "config_error"
        profile = token.profile or {}
        return {
            "has_token": True,
            "dhan_client_id": mask_client_id(token.dhan_client_id),
            "token_state": state,
            "expiry_time": token.expiry_time,
            "data_plan": profile.get("dataPlan"),
            "data_validity": profile.get("dataValidity"),
            "last_status_check_at": token.last_status_check_at,
            "last_renew_success_at": token.last_renew_success_at,
            "last_error": token.last_error
            or ("" if self.settings.app_secret_key else "Matsya token encryption key is not configured."),
        }


def _token_state(token: MatsyaStoredToken, renew_before_minutes: int) -> str:
    if token.last_error and token.last_renew_attempt_at:
        return "renew_failed"
    if token.expiry_time is None:
        return "unknown"
    current = now_utc()
    if token.expiry_time <= current:
        return "expired"
    if token.expiry_time <= current + timedelta(minutes=renew_before_minutes):
        return "expiring_soon"
    return "active"


def _empty_status() -> dict[str, Any]:
    return {
        "has_token": False,
        "dhan_client_id": None,
        "token_state": "missing",
        "expiry_time": None,
        "data_plan": None,
        "data_validity": None,
        "last_status_check_at": None,
        "last_renew_success_at": None,
        "last_error": "",
    }


def mask_client_id(client_id: str | None) -> str | None:
    if not client_id:
        return None
    if len(client_id) <= 6:
        return "***"
    return f"{client_id[:3]}...{client_id[-3:]}"
