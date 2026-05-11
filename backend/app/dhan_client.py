from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.timezone import parse_dhan_datetime


@dataclass(frozen=True)
class DhanProfile:
    dhan_client_id: str
    token_validity: datetime | None
    active_segment: str
    ddpi: str
    mtf: str
    data_plan: str
    data_validity: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class DhanRenewedToken:
    access_token: str
    expiry_time: datetime | None
    raw: dict[str, Any]


class DhanClient:
    def __init__(self, base_url: str = "https://api.dhan.co", timeout_seconds: float = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def profile(self, access_token: str) -> DhanProfile:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(
                f"{self.base_url}/v2/profile",
                headers={"access-token": access_token, "Accept": "application/json"},
            )
        response.raise_for_status()
        payload = response.json()
        token_validity = _parse_optional_datetime(payload.get("tokenValidity"))
        return DhanProfile(
            dhan_client_id=str(payload.get("dhanClientId") or ""),
            token_validity=token_validity,
            active_segment=str(payload.get("activeSegment") or ""),
            ddpi=str(payload.get("ddpi") or ""),
            mtf=str(payload.get("mtf") or ""),
            data_plan=str(payload.get("dataPlan") or ""),
            data_validity=str(payload.get("dataValidity") or ""),
            raw=payload,
        )

    async def renew_token(self, access_token: str, dhan_client_id: str) -> DhanRenewedToken:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(
                f"{self.base_url}/v2/RenewToken",
                headers={
                    "access-token": access_token,
                    "dhanClientId": dhan_client_id,
                    "Accept": "application/json",
                },
            )
        response.raise_for_status()
        payload = response.json()
        renewed_token = renewed_access_token(payload)
        if not renewed_token:
            raise ValueError("Dhan RenewToken response did not include accessToken.")
        expiry = payload.get("expiryTime") or payload.get("tokenValidity")
        return DhanRenewedToken(
            access_token=str(renewed_token),
            expiry_time=_parse_optional_datetime(expiry),
            raw=payload,
        )

    async def fetch_instrument_master_csv(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "text/csv,*/*"})
        response.raise_for_status()
        return response.text

    async def historical_daily(
        self,
        access_token: str,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        payload = {
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_date,
            "toDate": to_date,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/v2/charts/historical",
                headers={
                    "access-token": access_token,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        return response.json()


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    return parse_dhan_datetime(str(value))


def renewed_access_token(payload: dict[str, Any]) -> str:
    token = payload.get("accessToken") or payload.get("access_token") or payload.get("token")
    return str(token) if token else ""
