import pytest

from app.config import Settings
from app.instrument_master import InstrumentMasterService, InstrumentMasterStore, parse_instrument_csv
from app.store import TokenStore


CSV_ONE = """EXCH_ID,SEGMENT,SECURITY_ID,ISIN,INSTRUMENT,UNDERLYING_SECURITY_ID,UNDERLYING_SYMBOL,SYMBOL_NAME,DISPLAY_NAME,INSTRUMENT_TYPE,SERIES,LOT_SIZE,SM_EXPIRY_DATE,STRIKE_PRICE,OPTION_TYPE,TICK_SIZE,BUY_SELL_INDICATOR,SM_UPPER_LIMIT,SM_LOWER_LIMIT,
NSE,E,1333,INE040A01034,EQUITY,NA,NA,HDFCBANK,HDFC BANK LTD,EQUITY,EQ,1.0,NA,-0.01000,XX,0.0500,A,100.00,80.00,
BSE,E,500180,INE040A01034,EQUITY,NA,NA,HDFCBANK,HDFC BANK LTD,EQUITY,A,1.0,NA,-0.01000,XX,0.0500,A,100.00,80.00,
NSE,D,12345,NA,FUTSTK,1333,HDFCBANK,HDFCBANK,HDFCBANK JAN FUT,FUTSTK,NA,550.0,2026-01-29,-0.01000,XX,0.0500,A,0,0,
"""


CSV_RENAMED = """EXCH_ID,SEGMENT,SECURITY_ID,ISIN,INSTRUMENT,UNDERLYING_SECURITY_ID,UNDERLYING_SYMBOL,SYMBOL_NAME,DISPLAY_NAME,INSTRUMENT_TYPE,SERIES,LOT_SIZE,SM_EXPIRY_DATE,STRIKE_PRICE,OPTION_TYPE,TICK_SIZE,BUY_SELL_INDICATOR,SM_UPPER_LIMIT,SM_LOWER_LIMIT,
NSE,E,1333,INE040A01034,EQUITY,NA,NA,HDFCBANKNEW,HDFC BANK RENAMED,EQUITY,EQ,1.0,NA,-0.01000,XX,0.0500,A,100.00,80.00,
"""


class FakeDhanClient:
    def __init__(self, csv_text: str) -> None:
        self.csv_text = csv_text

    async def fetch_instrument_master_csv(self, url: str) -> str:
        return self.csv_text


def make_service(tmp_path, csv_text: str) -> InstrumentMasterService:
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    store = InstrumentMasterStore(TokenStore(settings.database_path))
    return InstrumentMasterService(settings, store, FakeDhanClient(csv_text))


def test_parse_filters_nse_and_preserves_live_extra_columns():
    columns, total_rows, rows = parse_instrument_csv(CSV_ONE, "NSE")

    assert total_rows == 3
    assert len(rows) == 2
    assert "SM_UPPER_LIMIT" in columns
    assert rows[0]["SM_UPPER_LIMIT"] == "100.00"
    assert all(row["EXCH_ID"] == "NSE" for row in rows)


@pytest.mark.asyncio
async def test_refresh_stores_all_raw_columns_and_supports_search(tmp_path):
    service = make_service(tmp_path, CSV_ONE)

    stats = await service.refresh()
    status = service.status()
    results = service.search("HDFC")

    assert stats.imported_rows == 2
    assert status["active_nse_count"] == 2
    assert results[0]["security_id"] == "1333"
    assert results[0]["raw"]["SM_UPPER_LIMIT"] == "100.00"


@pytest.mark.asyncio
async def test_symbol_rename_updates_existing_identity_and_deactivates_missing_rows(tmp_path):
    service = make_service(tmp_path, CSV_ONE)
    await service.refresh()

    service.dhan_client = FakeDhanClient(CSV_RENAMED)
    stats = await service.refresh()
    results = service.search("HDFCBANKNEW")

    assert stats.inserted_rows == 0
    assert stats.updated_rows == 1
    assert stats.deactivated_rows == 1
    assert service.status()["active_nse_count"] == 1
    assert results[0]["symbol_name"] == "HDFCBANKNEW"
