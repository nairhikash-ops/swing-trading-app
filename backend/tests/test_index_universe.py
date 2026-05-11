import pytest

from app.config import Settings
from app.index_universe import IndexUniverseService, IndexUniverseStore, parse_nifty_500_csv
from app.store import TokenStore


CSV_ONE = """Company Name,Industry,Symbol,Series,ISIN Code,Extra Field
HDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034,largecap
Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018,largecap
"""


CSV_UPDATED = """Company Name,Industry,Symbol,Series,ISIN Code,Extra Field
HDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034,largecap
Reliance Industries Ltd.,Energy,RELIANCE,EQ,INE002A01018,largecap
Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029,largecap
"""


def make_service(tmp_path) -> IndexUniverseService:
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    store = IndexUniverseStore(TokenStore(settings.database_path))
    return IndexUniverseService(settings, store)


def test_parse_nifty_500_csv_extracts_company_and_industry():
    columns, total_rows, rows = parse_nifty_500_csv(CSV_ONE)

    assert columns == ["Company Name", "Industry", "Symbol", "Series", "ISIN Code", "Extra Field"]
    assert total_rows == 2
    assert rows[0]["COMPANY NAME"] == "HDFC Bank Ltd."
    assert rows[0]["INDUSTRY"] == "Financial Services"
    assert rows[0]["EXTRA FIELD"] == "largecap"


@pytest.mark.asyncio
async def test_refresh_stores_nifty_500_company_names_and_industries(tmp_path, monkeypatch):
    async def fake_fetch_csv(url: str) -> str:
        return CSV_ONE

    monkeypatch.setattr("app.index_universe.fetch_csv", fake_fetch_csv)
    service = make_service(tmp_path)

    stats = await service.refresh_nifty_500()
    status = service.nifty_500_status()
    constituents = service.nifty_500_constituents()

    assert stats.imported_rows == 2
    assert status["active_count"] == 2
    assert status["industry_count"] == 2
    assert constituents[0]["company_name"] == "HDFC Bank Ltd."
    assert constituents[0]["industry"] == "Financial Services"
    assert constituents[0]["raw"]["EXTRA FIELD"] == "largecap"


@pytest.mark.asyncio
async def test_refresh_updates_existing_constituents_by_isin(tmp_path, monkeypatch):
    async def first_csv(url: str) -> str:
        return CSV_ONE

    async def updated_csv(url: str) -> str:
        return CSV_UPDATED

    service = make_service(tmp_path)
    monkeypatch.setattr("app.index_universe.fetch_csv", first_csv)
    await service.refresh_nifty_500()

    monkeypatch.setattr("app.index_universe.fetch_csv", updated_csv)
    stats = await service.refresh_nifty_500()
    reliance = service.nifty_500_constituents("RELIANCE")[0]

    assert stats.inserted_rows == 1
    assert stats.updated_rows == 1
    assert service.nifty_500_status()["active_count"] == 3
    assert reliance["industry"] == "Energy"
