from datetime import timedelta

import httpx

from app.config import Settings
from app.crypto import TokenCrypto, mask_token
from app.dhan_client import DhanClient
from app.schemas import TokenStatusResponse
from app.store import StoredToken, TokenStore
from app.timezone import now_utc, to_utc


class TokenService:
    def __init__(self, settings: Settings, store: TokenStore, dhan_client: DhanClient | None = None) -> None:
        self.settings = settings
        self.store = store
        self.dhan_client = dhan_client or DhanClient(settings.dhan_api_base_url)

    def _crypto(self) -> TokenCrypto:
        return TokenCrypto(self.settings.app_secret_key)

    async def save_manual_token(
        self,
        dhan_client_id: str,
        access_token: str,
        expiry_time,
        validate_with_dhan: bool,
    ) -> TokenStatusResponse:
        crypto = self._crypto()
        profile_data = None
        final_expiry = to_utc(expiry_time) if expiry_time else None

        if validate_with_dhan:
            profile = await self.dhan_client.profile(access_token)
            if profile.dhan_client_id and profile.dhan_client_id != dhan_client_id:
                raise ValueError("Dhan profile client ID does not match the submitted client ID.")
            profile_data = profile.raw
            final_expiry = profile.token_validity or final_expiry

        self.store.upsert_token(
            dhan_client_id=dhan_client_id,
            encrypted_access_token=crypto.encrypt(access_token),
            token_source="manual",
            expiry_time=final_expiry,
            profile=profile_data,
        )
        if profile_data:
            self.store.update_profile(profile_data, final_expiry)
        return self.status()

    def status(self) -> TokenStatusResponse:
        try:
            token = self.store.get()
            if token is None:
                return TokenStatusResponse(state="missing", has_token=False)
            access_token = self._crypto().decrypt(token.encrypted_access_token)
            return self._status_from_token(token, access_token)
        except ValueError as exc:
            return TokenStatusResponse(state="config_error", has_token=bool(self.store.get()), last_error=str(exc))

    async def refresh_profile(self) -> TokenStatusResponse:
        token = self.store.get()
        if token is None:
            return TokenStatusResponse(state="missing", has_token=False)

        access_token = self._crypto().decrypt(token.encrypted_access_token)
        try:
            profile = await self.dhan_client.profile(access_token)
            self.store.update_profile(profile.raw, profile.token_validity)
        except (httpx.HTTPError, ValueError) as exc:
            self.store.update_profile(token.profile, token.expiry_time, str(exc))
        return self.status()

    async def renew_if_needed(self, force: bool = False) -> tuple[bool, TokenStatusResponse, str]:
        token = self.store.get()
        if token is None:
            return False, TokenStatusResponse(state="missing", has_token=False), "No Dhan token has been stored."

        access_token = self._crypto().decrypt(token.encrypted_access_token)
        status = self._status_from_token(token, access_token)
        if status.state == "expired":
            return False, status, "Token is expired. Use the manual fallback update flow."
        if status.state == "config_error":
            return False, status, status.last_error
        if not force and not self._needs_renewal(token):
            return False, status, "Token does not need renewal yet."

        self.store.mark_renew_attempt()
        try:
            renewed = await self.dhan_client.renew_token(access_token, token.dhan_client_id)
            self.store.upsert_token(
                dhan_client_id=token.dhan_client_id,
                encrypted_access_token=self._crypto().encrypt(renewed.access_token),
                token_source="renewed",
                expiry_time=renewed.expiry_time,
                profile=token.profile,
            )
            self.store.mark_renew_success()
            await self.refresh_profile()
            return True, self.status(), "Token renewed successfully."
        except (httpx.HTTPError, ValueError) as exc:
            self.store.mark_renew_attempt(str(exc))
            return False, self.status(), "Token renewal failed."

    def _needs_renewal(self, token: StoredToken) -> bool:
        if token.expiry_time is None:
            return True
        renew_at = token.expiry_time - timedelta(minutes=self.settings.dhan_renew_before_minutes)
        return now_utc() >= renew_at

    def _status_from_token(self, token: StoredToken, access_token: str) -> TokenStatusResponse:
        current = now_utc()
        expiry = token.expiry_time
        minutes_to_expiry = int((expiry - current).total_seconds() // 60) if expiry else None
        state = "unknown"
        if expiry and expiry <= current:
            state = "expired"
        elif token.last_error and token.last_renew_attempt_at:
            state = "renew_failed"
        elif expiry and expiry <= current + timedelta(minutes=self.settings.dhan_renew_before_minutes):
            state = "expiring_soon"
        else:
            state = "active"

        return TokenStatusResponse(
            state=state,
            has_token=True,
            dhan_client_id=token.dhan_client_id,
            masked_token=mask_token(access_token),
            expiry_time=expiry,
            minutes_to_expiry=minutes_to_expiry,
            active_segment=token.profile.get("activeSegment"),
            ddpi=token.profile.get("ddpi"),
            mtf=token.profile.get("mtf"),
            data_plan=token.profile.get("dataPlan"),
            data_validity=token.profile.get("dataValidity"),
            last_status_check_at=token.last_status_check_at,
            last_renew_attempt_at=token.last_renew_attempt_at,
            last_renew_success_at=token.last_renew_success_at,
            last_error=token.last_error,
            token_source=token.token_source,
        )
