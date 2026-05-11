from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import Settings
from app.nse_import import NseImportService, NseImportStore
from app.store import TokenStore


def make_service(tmp_path) -> NseImportService:
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    return NseImportService(settings, NseImportStore(settings, token_store))


def full_filename(date_token: str) -> str:
    return f"sec_bhavdata_full_{date_token}.csv"


def udiff_filename(date_token: str) -> str:
    return f"BhavCopy_NSE_CM_0_0_0_{date_token}_F_0000.csv.zip"


def full_csv(date_label: str, symbol: str = "ALPHA", close: float = 110.0, prev_close: float = 100.0) -> bytes:
    return f"""SYMBOL,SERIES,DATE1,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER
{symbol},EQ,{date_label},{prev_close},101,112,99,{close},{close},105,1000,10.5,50,600,60
""".encode()


def bad_full_csv(date_label: str) -> bytes:
    return f"""SYMBOL,SERIES,DATE1,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY
ALPHA,EQ,{date_label},100,101,112,99,110,110,105,1000,10.5,50,600
""".encode()


def udiff_csv(date_iso: str, symbol: str = "ALPHA", isin: str = "INE000000001") -> str:
    return f"""TradDt,Sgmt,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,FinInstrmNm
{date_iso},CM,STK,123,{isin},{symbol},EQ,{symbol} LTD
"""


def udiff_zip(date_token: str, csv_text: str) -> bytes:
    buffer = BytesIO()
    name = udiff_filename(date_token)[:-4]
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(name, csv_text)
    return buffer.getvalue()


def import_pair(
    service: NseImportService,
    ddmmyyyy: str,
    yyyymmdd: str,
    date_label: str,
    date_iso: str,
    symbol: str = "ALPHA",
    isin: str = "INE000000001",
    close: float = 110.0,
    prev_close: float = 100.0,
):
    return service.import_files(
        [
            (full_filename(ddmmyyyy), full_csv(date_label, symbol=symbol, close=close, prev_close=prev_close)),
            (udiff_filename(yyyymmdd), udiff_zip(yyyymmdd, udiff_csv(date_iso, symbol=symbol, isin=isin))),
        ]
    )


def test_upload_full_and_udiff_publishes_normalized_rows(tmp_path):
    service = make_service(tmp_path)

    result = import_pair(service, "08052026", "20260508", "08-May-2026", "2026-05-08")
    coverage = service.coverage()
    rows = service.rows_for_symbol("ALPHA", 10)

    assert result["accepted_count"] == 2
    assert result["published_dates_count"] == 1
    assert coverage["published_session_count"] == 1
    assert coverage["eod_row_count"] == 1
    assert rows[0]["isin"] == "INE000000001"
    assert rows[0]["delivery_percent"] == 60
    assert rows[0]["dirty_flag"] == "clean"


def test_upload_reverse_order_still_pairs_by_trade_date(tmp_path):
    service = make_service(tmp_path)

    result = service.import_files(
        [
            (udiff_filename("20260508"), udiff_zip("20260508", udiff_csv("2026-05-08"))),
            (full_filename("08052026"), full_csv("08-May-2026")),
        ]
    )

    assert result["published_dates_count"] == 1
    assert service.status()["published_session_count"] == 1


def test_duplicate_upload_is_skipped_by_checksum(tmp_path):
    service = make_service(tmp_path)
    content = full_csv("08-May-2026")

    first = service.import_files([(full_filename("08052026"), content)])
    second = service.import_files([(full_filename("08052026"), content)])

    assert first["accepted_count"] == 1
    assert second["duplicate_count"] == 1
    assert second["files"][0]["existing_file_id"] is not None


def test_full_only_date_waits_for_pair(tmp_path):
    service = make_service(tmp_path)

    service.import_files([(full_filename("08052026"), full_csv("08-May-2026"))])
    status = service.status()

    assert status["waiting_for_pair_count"] == 1
    assert status["published_session_count"] == 0


def test_wrong_report_file_is_rejected(tmp_path):
    service = make_service(tmp_path)

    result = service.import_files([("random_report.csv", b"Symbol,Open\nABC,1\n")])

    assert result["rejected_count"] == 1
    assert result["files"][0]["status"] == "rejected"


def test_schema_mismatch_does_not_publish(tmp_path):
    service = make_service(tmp_path)

    result = service.import_files(
        [
            (full_filename("08052026"), bad_full_csv("08-May-2026")),
            (udiff_filename("20260508"), udiff_zip("20260508", udiff_csv("2026-05-08"))),
        ]
    )
    status = service.status()

    assert result["rejected_count"] == 1
    assert status["published_session_count"] == 0
    assert status["schema_error_count"] == 1


def test_symbol_rename_with_same_isin_remains_one_identity(tmp_path):
    service = make_service(tmp_path)

    import_pair(service, "07052026", "20260507", "07-May-2026", "2026-05-07", symbol="OLDNAME")
    import_pair(service, "08052026", "20260508", "08-May-2026", "2026-05-08", symbol="NEWNAME")

    old_rows = service.rows_for_symbol("OLDNAME", 10)
    new_rows = service.rows_for_symbol("NEWNAME", 10)
    with service.store._connect() as conn:
        instrument_count = conn.execute("SELECT COUNT(*) AS count FROM nse_instruments").fetchone()["count"]

    assert instrument_count == 1
    assert old_rows[0]["isin"] == new_rows[0]["isin"]


def test_same_symbol_with_different_isin_creates_separate_identity(tmp_path):
    service = make_service(tmp_path)

    import_pair(service, "07052026", "20260507", "07-May-2026", "2026-05-07", isin="INE000000001")
    import_pair(service, "08052026", "20260508", "08-May-2026", "2026-05-08", isin="INE000000002")

    with service.store._connect() as conn:
        instrument_count = conn.execute("SELECT COUNT(*) AS count FROM nse_instruments").fetchone()["count"]

    assert instrument_count == 2


def test_split_like_move_is_flagged_not_hidden(tmp_path):
    service = make_service(tmp_path)

    import_pair(
        service,
        "07052026",
        "20260507",
        "07-May-2026",
        "2026-05-07",
        close=1000,
        prev_close=990,
    )
    import_pair(
        service,
        "08052026",
        "20260508",
        "08-May-2026",
        "2026-05-08",
        close=100,
        prev_close=1000,
    )

    rows = service.rows_for_symbol("ALPHA", 10)
    latest = rows[0]

    assert latest["trade_date"] == "2026-05-08"
    assert latest["dirty_flag"] == "possible_split_bonus"
    assert service.coverage()["dirty_flag_counts"]["possible_split_bonus"] == 1


def test_inbox_scan_imports_files_without_ui_upload(tmp_path):
    service = make_service(tmp_path)
    inbox = service.store.settings.nse_import_inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / full_filename("08052026")).write_bytes(full_csv("08-May-2026"))
    (inbox / udiff_filename("20260508")).write_bytes(udiff_zip("20260508", udiff_csv("2026-05-08")))

    result = service.import_inbox()

    assert result["accepted_count"] == 2
    assert result["published_dates_count"] == 1
    assert service.coverage()["published_session_count"] == 1
