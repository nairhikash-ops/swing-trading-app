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


class HistoricalFetchStatusResponse(BaseModel):
    id: int
    universe_name: str
    lookback_calendar_days: int
    from_date: str
    to_date_exclusive: str
    status: str
    total_symbols: int
    mapped_symbols: int
    skipped_symbols: int
    queued_count: int
    fetching_count: int
    done_count: int
    failed_count: int
    skipped_count: int
    candles_received: int
    stored_candle_count: int
    error: str
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class HistoricalFetchItem(BaseModel):
    id: int
    run_id: int
    index_constituent_id: int
    instrument_id: int | None = None
    company_name: str
    industry: str
    symbol: str
    isin: str
    security_id: str
    status: str
    attempts: int
    candles_received: int
    error: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class DailyCandleItem(BaseModel):
    instrument_id: int
    security_id: str
    exchange_segment: str
    instrument: str
    trading_date: str
    source_timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float | None = None
    source: str
    fetched_at: datetime


class QualityItem(BaseModel):
    symbol: str
    company_name: str
    industry: str
    isin: str
    security_id: str
    quality_status: str
    issues: list[str]
    latest_candle_date: str | None = None
    expected_sessions: int
    candle_count: int
    missing_sessions: int
    invalid_ohlc_count: int
    zero_volume_count: int
    negative_volume_count: int
    extreme_move_count: int
    fetch_status: str
    fetch_error: str


class QualityReportResponse(BaseModel):
    generated_at: datetime
    historical_run_id: int | None = None
    historical_run_status: str
    from_date: str
    to_date_exclusive: str
    latest_expected_session: str | None = None
    expected_session_count: int
    total_symbols: int
    healthy_count: int
    warning_count: int
    blocked_count: int
    issue_counts: dict[str, int]
    items: list[QualityItem]
