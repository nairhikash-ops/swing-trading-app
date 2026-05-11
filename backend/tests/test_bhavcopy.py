import hashlib

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
    assert service.status()["next_missing_date"] == "2026-05-07"
    assert service.status()["next_missing_filename"] == "sec_bhavdata_full_07052026.csv"


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


def test_filename_date_mismatch_is_saved_under_csv_date(tmp_path):
    service = make_service(tmp_path)

    result = service.import_files([(filename("08052026"), bhavcopy_csv("07-May-2026"))])
    rows = service.rows_for_symbol("ALPHA", 10)
    dates = {row["trade_date"] for row in rows}

    assert result["accepted_count"] == 1
    assert result["files"][0]["trade_date"] == "2026-05-07"
    assert "2026-05-07" in dates
    assert service.coverage()["published_session_count"] == 1


def test_reprocessing_old_date_mismatch_clears_stale_date_error(tmp_path):
    service = make_service(tmp_path)
    content = bhavcopy_csv("07-May-2026")
    checksum = hashlib.sha256(content).hexdigest()

    with service.store.store.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO import_files (
                batch_id, original_filename, stored_path, checksum, trade_date, status,
                file_size_bytes, row_count, source_columns_json, error, uploaded_at, parsed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                None,
                filename("08052026"),
                "",
                checksum,
                "2026-05-08",
                "schema_error",
                len(content),
                0,
                "[]",
                "CSV row DATE1 does not match filename date.",
                "2026-05-11T00:00:00Z",
                None,
            ),
        )
        file_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO import_dates (trade_date, file_id, status, row_count, error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-05-08",
                file_id,
                "schema_error",
                0,
                "CSV row DATE1 does not match filename date.",
                "2026-05-11T00:00:00Z",
            ),
        )

    result = service.import_files([(filename("08052026"), content)])
    recent_dates = {item["trade_date"]: item for item in service.status()["recent_dates"]}

    assert result["accepted_count"] == 1
    assert result["files"][0]["trade_date"] == "2026-05-07"
    assert "2026-05-08" not in recent_dates
    assert recent_dates["2026-05-07"]["status"] == "published"


def test_inbox_scan_imports_matching_files(tmp_path):
    service = make_service(tmp_path)
    inbox = service.store.settings.import_inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / filename()).write_bytes(bhavcopy_csv())

    result = service.import_inbox()

    assert result["accepted_count"] == 1
    assert service.coverage()["published_session_count"] == 1


def test_wrong_requested_date_is_still_saved_under_actual_file_date(tmp_path):
    service = make_service(tmp_path)

    service.import_files([(filename("08052026"), bhavcopy_csv("08-May-2026"))])
    assert service.status()["next_missing_date"] == "2026-05-07"

    result = service.import_files([(filename("06052026"), bhavcopy_csv("06-May-2026"))])
    rows = service.rows_for_symbol("ALPHA", 10)
    dates = {row["trade_date"] for row in rows}

    assert result["accepted_count"] == 1
    assert "2026-05-06" in dates
    assert service.status()["next_missing_date"] == "2026-05-07"


def test_reupload_previous_schema_error_can_be_reprocessed(tmp_path):
    service = make_service(tmp_path)

    first = service.import_files([(filename(), bad_schema_csv())])
    second = service.import_files([(filename(), bhavcopy_csv())])

    assert first["rejected_count"] == 1
    assert second["accepted_count"] == 1
    assert second["files"][0]["status"] == "valid"
    assert service.coverage()["published_session_count"] == 1
