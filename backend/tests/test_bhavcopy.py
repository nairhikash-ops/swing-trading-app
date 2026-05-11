from app.bhavcopy import BhavcopyService, BhavcopyStore
from app.config import Settings
from app.store import AppStore


def make_service(tmp_path) -> BhavcopyService:
    settings = Settings(data_dir=tmp_path)
    store = AppStore(settings.database_path)
    return BhavcopyService(settings, BhavcopyStore(settings, store))


def filename(date_token: str = "08052026") -> str:
    return f"sec_bhavdata_full_{date_token}.csv"


def bhavcopy_csv(date_label: str = "08-May-2026", symbol: str = "ALPHA", close: float = 110.0) -> bytes:
    return f"""SYMBOL,SERIES,DATE1,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER
{symbol},EQ,{date_label},100,101,112,99,{close},{close},105,1000,10.5,50,600,60
{symbol},BE,{date_label},100,102,113,98,{close},{close},106,500,5.5,25,200,40
""".encode()


def bad_schema_csv() -> bytes:
    return b"SYMBOL,SERIES,DATE1,OPEN_PRICE\nALPHA,EQ,08-May-2026,101\n"


def test_import_bhavcopy_publishes_rows(tmp_path):
    service = make_service(tmp_path)

    result = service.import_files([(filename(), bhavcopy_csv())])
    coverage = service.coverage()
    rows = service.rows_for_symbol("ALPHA", 10)

    assert result["accepted_count"] == 1
    assert result["published_dates_count"] == 1
    assert coverage["published_session_count"] == 1
    assert coverage["row_count"] == 2
    assert coverage["series_counts"] == {"BE": 1, "EQ": 1}
    eq_row = next(row for row in rows if row["series"] == "EQ")
    assert eq_row["symbol"] == "ALPHA"
    assert eq_row["delivery_percent"] == 60


def test_duplicate_upload_is_skipped_by_checksum(tmp_path):
    service = make_service(tmp_path)
    content = bhavcopy_csv()

    first = service.import_files([(filename(), content)])
    second = service.import_files([(filename(), content)])

    assert first["accepted_count"] == 1
    assert second["duplicate_count"] == 1
    assert second["files"][0]["existing_file_id"] is not None
    assert service.coverage()["published_session_count"] == 1


def test_wrong_filename_is_rejected(tmp_path):
    service = make_service(tmp_path)

    result = service.import_files([("random.csv", bhavcopy_csv())])

    assert result["rejected_count"] == 1
    assert result["files"][0]["status"] == "rejected"
    assert service.coverage()["published_session_count"] == 0


def test_schema_mismatch_is_rejected(tmp_path):
    service = make_service(tmp_path)

    result = service.import_files([(filename(), bad_schema_csv())])

    assert result["rejected_count"] == 1
    assert result["files"][0]["status"] == "schema_error"
    assert "Missing required column" in result["files"][0]["error"]
    assert service.status()["schema_error_count"] == 1


def test_date_mismatch_is_rejected(tmp_path):
    service = make_service(tmp_path)

    result = service.import_files([(filename("08052026"), bhavcopy_csv("07-May-2026"))])

    assert result["rejected_count"] == 1
    assert result["files"][0]["status"] == "schema_error"
    assert service.coverage()["published_session_count"] == 0


def test_inbox_scan_imports_matching_files(tmp_path):
    service = make_service(tmp_path)
    inbox = service.store.settings.import_inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / filename()).write_bytes(bhavcopy_csv())

    result = service.import_inbox()

    assert result["accepted_count"] == 1
    assert service.coverage()["published_session_count"] == 1
