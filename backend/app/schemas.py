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


class InstrumentImportSummary(BaseModel):
    run_id: int
    source_url: str
    exchange_filter: str
    segment_filter: str
    source_columns: list[str]
    total_rows_seen: int
    imported_rows: int
    inserted_rows: int
    updated_rows: int
    unchanged_rows: int
    deactivated_rows: int
    started_at: datetime
    completed_at: datetime


class InstrumentMasterStatusResponse(BaseModel):
    total_count: int
    active_count: int
    nse_count: int
    active_nse_count: int
    last_import: dict | None = None


class InstrumentSearchItem(BaseModel):
    id: int
    exchange_id: str
    segment: str
    security_id: str
    isin: str
    instrument: str
    symbol_name: str
    display_name: str
    instrument_type: str
    series: str
    lot_size: float | None = None
    expiry_date: str
    strike_price: float | None = None
    option_type: str
    tick_size: float | None = None
    buy_sell_indicator: str
    asm_gsm_flag: str
    mtf_leverage: str
    raw: dict


class UniverseImportSummary(BaseModel):
    run_id: int
    index_name: str
    source_url: str
    source_columns: list[str]
    total_rows_seen: int
    imported_rows: int
    inserted_rows: int
    updated_rows: int
    unchanged_rows: int
    deactivated_rows: int
    started_at: datetime
    completed_at: datetime


class UniverseStatusResponse(BaseModel):
    index_name: str
    total_count: int
    active_count: int
    industry_count: int
    last_import: dict | None = None


class UniverseConstituentItem(BaseModel):
    id: int
    index_name: str
    company_name: str
    industry: str
    symbol: str
    series: str
    isin: str
    raw: dict
