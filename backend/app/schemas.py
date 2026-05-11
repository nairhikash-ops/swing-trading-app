from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str


class ImportFileResult(BaseModel):
    filename: str
    status: str
    trade_date: str | None = None
    row_count: int
    error: str = ""
    file_id: int | None = None
    existing_file_id: int | None = None


class ImportResponse(BaseModel):
    batch_id: int
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    published_dates_count: int
    files: list[ImportFileResult]


class RecentFile(BaseModel):
    id: int
    original_filename: str
    trade_date: str
    status: str
    row_count: int
    error: str
    uploaded_at: datetime


class ImportDateItem(BaseModel):
    trade_date: str
    status: str
    row_count: int
    error: str
    updated_at: datetime
    published_at: datetime | None = None


class ImportStatusResponse(BaseModel):
    generated_at: datetime
    target_sessions: int
    inbox_path: str
    published_session_count: int
    coverage_percent: float
    latest_published_date: str | None = None
    rejected_file_count: int
    schema_error_count: int
    row_count: int
    symbol_count: int
    recent_files: list[RecentFile]
    recent_dates: list[ImportDateItem]


class CoverageResponse(BaseModel):
    generated_at: datetime
    target_sessions: int
    published_session_count: int
    coverage_percent: float
    latest_published_date: str | None = None
    row_count: int
    symbol_count: int
    series_counts: dict[str, int]


class BhavcopyRow(BaseModel):
    trade_date: str
    symbol: str
    series: str
    prev_close: float
    open_price: float
    high_price: float
    low_price: float
    last_price: float
    close_price: float
    avg_price: float
    traded_quantity: float
    turnover_lacs: float
    no_of_trades: int
    delivery_qty: float | None = None
    delivery_percent: float | None = None
    raw_json: dict[str, str]
    updated_at: datetime
