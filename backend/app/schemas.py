from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TokenState = Literal["missing", "active", "expiring_soon", "expired", "renew_failed", "config_error", "unknown"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str


class TokenUpdateRequest(BaseModel):
    dhan_client_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=20)
    expiry_time: datetime | None = None
    validate_with_dhan: bool = True


class TokenStatusResponse(BaseModel):
    state: TokenState
    has_token: bool
    dhan_client_id: str | None = None
    masked_token: str | None = None
    expiry_time: datetime | None = None
    minutes_to_expiry: int | None = None
    active_segment: str | None = None
    ddpi: str | None = None
    mtf: str | None = None
    data_plan: str | None = None
    data_validity: str | None = None
    last_status_check_at: datetime | None = None
    last_renew_attempt_at: datetime | None = None
    last_renew_success_at: datetime | None = None
    last_error: str = ""
    token_source: str | None = None


class RenewResponse(BaseModel):
    renewed: bool
    status: TokenStatusResponse
    message: str
