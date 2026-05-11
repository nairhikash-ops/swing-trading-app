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


class RangeMoverItem(BaseModel):
    index_constituent_id: int | None = None
    instrument_id: int | None = None
    symbol: str
    company_name: str
    industry: str
    isin: str
    security_id: str
    lowest_low: float
    lowest_low_date: str
    highest_high: float
    highest_high_date: str
    move_percent: float
    range_amount: float
    candle_count: int


class RangeMoverReportResponse(BaseModel):
    generated_at: datetime
    historical_run_id: int | None = None
    from_date: str
    to_date_exclusive: str
    threshold_percent: float
    total_scanned: int
    match_count: int
    items: list[RangeMoverItem]


class MoveEventItem(BaseModel):
    id: int
    run_id: int
    index_constituent_id: int
    instrument_id: int
    company_name: str
    industry: str
    symbol: str
    isin: str
    security_id: str
    event_number: int
    bucket: str
    low_date: str
    low_price: float
    high_date: str
    high_price: float
    move_percent: float
    duration_calendar_days: int
    duration_trading_sessions: int
    threshold_percent: float
    pullback_percent: float
    split_pullback_date: str | None = None
    split_pullback_close: float | None = None
    created_at: datetime


class MoveEventReportResponse(BaseModel):
    run_id: int | None = None
    universe_name: str
    threshold_percent: float
    pullback_percent: float
    from_date: str
    to_date_exclusive: str
    status: str
    total_symbols: int
    scanned_symbols: int
    candidate_symbols: int
    event_count: int
    error: str
    generated_at: datetime
    items: list[MoveEventItem]


class NseImportFileResult(BaseModel):
    filename: str
    status: str
    report_type: str | None = None
    trade_date: str | None = None
    row_count: int
    error: str = ""
    file_id: int | None = None
    existing_file_id: int | None = None


class NseImportUploadResponse(BaseModel):
    batch_id: int
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    published_dates_count: int
    files: list[NseImportFileResult]


class NseImportRecentFile(BaseModel):
    id: int
    original_filename: str
    report_type: str
    trade_date: str
    status: str
    row_count: int
    error: str
    uploaded_at: datetime


class NseImportDateItem(BaseModel):
    trade_date: str
    status: str
    full_row_count: int
    udiff_row_count: int
    published_row_count: int
    unresolved_row_count: int
    error: str
    updated_at: datetime
    published_at: datetime | None = None


class NseImportStatusResponse(BaseModel):
    generated_at: datetime
    target_sessions: int
    inbox_path: str
    published_session_count: int
    coverage_percent: float
    latest_published_date: str | None = None
    waiting_for_pair_count: int
    schema_error_count: int
    rejected_file_count: int
    schema_file_count: int
    instrument_count: int
    eod_row_count: int
    recent_files: list[NseImportRecentFile]
    recent_dates: list[NseImportDateItem]


class NseEodCoverageResponse(BaseModel):
    generated_at: datetime
    target_sessions: int
    published_session_count: int
    coverage_percent: float
    latest_published_date: str | None = None
    instrument_count: int
    eod_row_count: int
    dirty_flag_counts: dict[str, int]


class NseEodRowItem(BaseModel):
    isin: str
    trade_date: str
    symbol: str
    series: str
    company_name: str
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    last_price: float
    avg_price: float
    volume: float
    turnover_lacs: float
    no_of_trades: int
    delivery_qty: float | None = None
    delivery_percent: float | None = None
    price_basis: str
    dirty_flag: str
    dirty_reason: str
    updated_at: datetime
