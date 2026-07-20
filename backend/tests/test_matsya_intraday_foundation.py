from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.matsya_intraday.aggregation import aggregate
from app.matsya_intraday.reconciliation import reconcile
from app.matsya_intraday.settings import DEFAULT_TRUSTED_START_DATE, IntradaySettings
from app.matsya_intraday.validation import IST, validate_payload
from scripts.matsya_intraday_db import parser


def payload_for(day: date, count: int = 375) -> dict[str, list[object]]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=9,minute=15)
    timestamps = [int((start + timedelta(minutes=index)).timestamp()) for index in range(count)]
    return {"timestamp":timestamps,"open":[100]*count,"high":[102]*count,"low":[99]*count,
            "close":[101]*count,"volume":[0 if index % 10 == 0 else 10 for index in range(count)]}


def test_database_configuration_must_be_physically_separate() -> None:
    with pytest.raises(ValueError, match="different PostgreSQL databases"):
        IntradaySettings("postgresql://u:a@host/matsya","postgresql://u:b@host/matsya")
    with pytest.raises(ValueError, match="different PostgreSQL databases"):
        IntradaySettings("postgresql://u:a@host/matsya","postgresql://u:b@host:5432/matsya")
    assert DEFAULT_TRUSTED_START_DATE == date(2026,7,6)


def test_complete_zero_volume_day_is_accepted() -> None:
    day = date(2026,7,17)
    result = validate_payload(payload_for(day),[day])[day]
    assert result.status == "accepted"
    assert len(result.candles) == 375
    assert result.zero_volume_minutes == 38


def test_malformed_arrays_and_negative_volume_are_rejected() -> None:
    day = date(2026,7,17)
    malformed = payload_for(day)
    malformed["close"] = malformed["close"][:-1]
    assert validate_payload(malformed,[day])[day].status == "rejected"
    negative = payload_for(day)
    negative["volume"][12] = -1
    result = validate_payload(negative,[day])[day]
    assert result.status == "rejected"
    assert "negative_volume[12]" in result.defects


def test_missing_minute_warns_and_no_data_is_unavailable() -> None:
    day = date(2026,7,17)
    assert validate_payload(payload_for(day,374),[day])[day].status == "warning"
    assert validate_payload({field: [] for field in ("timestamp","open","high","low","close","volume")},[day])[day].status == "unavailable"


def test_deterministic_session_aligned_aggregations_and_reconciliation() -> None:
    day = date(2026,7,17)
    candles = validate_payload(payload_for(day),[day])[day].candles
    assert len(aggregate(candles,5)) == 75
    assert len(aggregate(candles,15)) == 25
    assert len(aggregate(candles,30)) == 13
    assert len(aggregate(candles,60)) == 7
    assert len(aggregate(candles,1440)) == 1
    daily = aggregate(candles,1440)[0]
    result = reconcile(candles,(daily.open,daily.high,daily.low,daily.close,daily.volume))
    assert result.structural_acceptance_gate_passed
    assert result.open_high_low_match
    assert result.close_match
    assert result.volume_match
    assert result.cross_source_status == "validated"


def test_close_and_volume_differences_are_informational() -> None:
    day = date(2026,7,17)
    candles = validate_payload(payload_for(day),[day])[day].candles
    result = reconcile(candles,(100,102,99,100.5,4000))
    assert result.structural_acceptance_gate_passed
    assert result.open_high_low_match
    assert not result.close_match
    assert not result.volume_match
    assert result.cross_source_status == "validated"
    warning = reconcile(candles,(100,102,98.9,101,3370))
    assert warning.structural_acceptance_gate_passed
    assert not warning.open_high_low_match
    assert warning.cross_source_status == "warning"


def test_migration_is_additive_and_has_quality_tables() -> None:
    sql = (Path(__file__).parents[1]/"app"/"matsya_intraday"/"migrations"/"0001_intraday_foundation.sql").read_text().lower()
    for table in ("symbol_days","minute_candles","quarantine","daily_reconciliation","derived_candles"):
        assert f"create table if not exists matsya_intraday.{table}" in sql
    assert "drop table" not in sql and "drop schema" not in sql
    assert "accepted','warning','rejected','unavailable" in sql
    for column in ("intraday_open","intraday_high","intraday_low","last_minute_close",
                   "normal_session_volume","official_daily_open","official_daily_high",
                   "official_daily_low","official_daily_close","official_daily_volume"):
        assert column in sql
    assert "cross_source_status" in sql


def test_cli_exposes_all_manual_workflows() -> None:
    cli=parser()
    help_text=cli.format_help()
    for command in ("migrate","ingest","validate","reconcile","aggregate","pilot"):
        assert command in help_text
