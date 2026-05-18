from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.config import Settings
from app.crypto import TokenCrypto, mask_token
from app.schemas import GeminiKeyStatusResponse
from app.store import TokenStore, _dt_from_db, _dt_to_db
from app.timezone import now_utc


GEMINI_PROVIDER = "gemini"


@dataclass(frozen=True)
class StoredAiCredential:
    provider: str
    encrypted_api_key: str
    key_source: str
    last_validated_at: datetime | None
    last_error: str
    updated_at: datetime


class AiCredentialStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_credentials (
                    provider TEXT PRIMARY KEY,
                    encrypted_api_key TEXT NOT NULL,
                    key_source TEXT NOT NULL,
                    last_validated_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get(self, provider: str) -> StoredAiCredential | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ai_credentials WHERE provider = ?", (provider,)).fetchone()
        if row is None:
            return None
        return StoredAiCredential(
            provider=row["provider"],
            encrypted_api_key=row["encrypted_api_key"],
            key_source=row["key_source"],
            last_validated_at=_dt_from_db(row["last_validated_at"]),
            last_error=row["last_error"] or "",
            updated_at=_dt_from_db(row["updated_at"]) or now_utc(),
        )

    def upsert_key(
        self,
        provider: str,
        encrypted_api_key: str,
        key_source: str = "manual",
        validated: bool = False,
        error: str = "",
    ) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_credentials (
                    provider, encrypted_api_key, key_source, last_validated_at,
                    last_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    encrypted_api_key = excluded.encrypted_api_key,
                    key_source = excluded.key_source,
                    last_validated_at = excluded.last_validated_at,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    provider,
                    encrypted_api_key,
                    key_source,
                    _dt_to_db(timestamp if validated else None),
                    error,
                    _dt_to_db(timestamp),
                    _dt_to_db(timestamp),
                ),
            )

    def mark_validation_success(self, provider: str) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ai_credentials
                SET last_validated_at = ?, last_error = '', updated_at = ?
                WHERE provider = ?
                """,
                (_dt_to_db(timestamp), _dt_to_db(timestamp), provider),
            )

    def mark_validation_error(self, provider: str, error: str) -> None:
        timestamp = now_utc()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ai_credentials
                SET last_error = ?, updated_at = ?
                WHERE provider = ?
                """,
                (error, _dt_to_db(timestamp), provider),
            )


class GeminiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def validate_api_key(self, api_key: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.base_url}/v1beta/models",
                headers={"x-goog-api-key": api_key},
            )
            response.raise_for_status()
            payload = response.json()
        return payload


class AiCredentialService:
    def __init__(
        self,
        settings: Settings,
        store: AiCredentialStore,
        gemini_client: GeminiClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.gemini_client = gemini_client or GeminiClient(settings.gemini_api_base_url)

    def _crypto(self) -> TokenCrypto:
        return TokenCrypto(self.settings.app_secret_key)

    def gemini_status(self) -> GeminiKeyStatusResponse:
        try:
            credential = self.store.get(GEMINI_PROVIDER)
            if credential is None:
                return GeminiKeyStatusResponse(provider=GEMINI_PROVIDER, state="missing", has_key=False)
            api_key = self._crypto().decrypt(credential.encrypted_api_key)
            state = "validation_failed" if credential.last_error else "active"
            return GeminiKeyStatusResponse(
                provider=GEMINI_PROVIDER,
                state=state,
                has_key=True,
                masked_key=mask_token(api_key),
                key_source=credential.key_source,
                last_validated_at=credential.last_validated_at,
                last_error=credential.last_error,
                updated_at=credential.updated_at,
            )
        except ValueError as exc:
            return GeminiKeyStatusResponse(
                provider=GEMINI_PROVIDER,
                state="config_error",
                has_key=bool(self.store.get(GEMINI_PROVIDER)),
                last_error=str(exc),
            )

    async def save_gemini_key(self, api_key: str, validate_with_gemini: bool = True) -> GeminiKeyStatusResponse:
        clean_key = api_key.strip()
        validated = False
        if validate_with_gemini:
            await self._validate(clean_key)
            validated = True
        self.store.upsert_key(
            provider=GEMINI_PROVIDER,
            encrypted_api_key=self._crypto().encrypt(clean_key),
            validated=validated,
        )
        return self.gemini_status()

    async def validate_saved_gemini_key(self) -> GeminiKeyStatusResponse:
        credential = self.store.get(GEMINI_PROVIDER)
        if credential is None:
            return GeminiKeyStatusResponse(provider=GEMINI_PROVIDER, state="missing", has_key=False)
        api_key = self._crypto().decrypt(credential.encrypted_api_key)
        try:
            await self._validate(api_key)
            self.store.mark_validation_success(GEMINI_PROVIDER)
        except Exception as exc:
            self.store.mark_validation_error(GEMINI_PROVIDER, readable_gemini_error(exc))
        return self.gemini_status()

    async def _validate(self, api_key: str) -> dict[str, Any]:
        if not api_key:
            raise ValueError("Gemini API key is required.")
        return await self.gemini_client.validate_api_key(api_key)


def readable_gemini_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code in (400, 401, 403):
            return "Gemini rejected the API key."
        return f"Gemini validation failed with HTTP {status_code}."
    return str(exc)
