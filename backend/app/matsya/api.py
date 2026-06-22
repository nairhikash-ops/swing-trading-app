from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.matsya.settings import MatsyaSettings
from app.matsya.token_service import MatsyaDhanTokenService


router = APIRouter(prefix="/api/matsya", tags=["Matsya"])


TokenState = Literal["missing", "active", "expiring_soon", "expired", "renew_failed", "config_error", "unknown"]


class MatsyaHealthResponse(BaseModel):
    status: str
    app: str


class MatsyaDhanStatusResponse(BaseModel):
    has_token: bool
    dhan_client_id: str | None = None
    token_state: TokenState
    expiry_time: datetime | None = None
    data_plan: str | None = None
    data_validity: str | None = None
    last_status_check_at: datetime | None = None
    last_renew_success_at: datetime | None = None
    last_error: str = ""


class MatsyaDhanTokenRequest(BaseModel):
    dhan_client_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=20)
    expiry_time: datetime | None = None
    validate_with_dhan: bool = True


class MatsyaRenewResponse(BaseModel):
    renewed: bool
    status: MatsyaDhanStatusResponse
    message: str


def build_token_service() -> MatsyaDhanTokenService:
    return MatsyaDhanTokenService(MatsyaSettings.from_env())


@router.get("/health", response_model=MatsyaHealthResponse)
async def health() -> MatsyaHealthResponse:
    return MatsyaHealthResponse(status="ok", app="matsya-api")


@router.get("/dhan/status", response_model=MatsyaDhanStatusResponse)
async def dhan_status() -> MatsyaDhanStatusResponse:
    try:
        return MatsyaDhanStatusResponse(**build_token_service().status())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/dhan/token", response_model=MatsyaDhanStatusResponse)
async def save_dhan_token(request: MatsyaDhanTokenRequest) -> MatsyaDhanStatusResponse:
    try:
        status = await build_token_service().save_manual_token(
            dhan_client_id=request.dhan_client_id.strip(),
            access_token=request.access_token.strip(),
            expiry_time=request.expiry_time,
            validate_with_dhan=request.validate_with_dhan,
        )
        return MatsyaDhanStatusResponse(**status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/dhan/status/refresh", response_model=MatsyaDhanStatusResponse)
async def refresh_dhan_status() -> MatsyaDhanStatusResponse:
    try:
        return MatsyaDhanStatusResponse(**await build_token_service().refresh_profile())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/dhan/renew", response_model=MatsyaRenewResponse)
async def renew_dhan_token() -> MatsyaRenewResponse:
    try:
        renewed, status, message = await build_token_service().renew()
        return MatsyaRenewResponse(renewed=renewed, status=MatsyaDhanStatusResponse(**status), message=message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
