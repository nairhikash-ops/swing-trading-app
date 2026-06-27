from __future__ import annotations

from pathlib import Path

import pytest

from app.matsya.virtual_demo_signals import load_virtual_demo_signals, parse_virtual_demo_signal


FIXTURE = Path("tests/fixtures/virtual_demo_signals_sample.json")


def test_loads_synthetic_signal_fixture() -> None:
    signals = load_virtual_demo_signals(FIXTURE)

    assert len(signals) == 2
    assert signals[0].symbol == "ALPHA"
    assert signals[0].security_id == "1001"
    assert signals[0].sample_date == "2026-06-25"
    assert signals[0].kurma_probability == 0.62
    assert signals[0].varaha_probability == 0.58
    assert signals[0].close_price == 100.0
    assert signals[0].model_versions == {
        "kurma": "stock_opportunity_ohlcv_regime_timesplit_kurma_v3",
        "varaha": "stock_opportunity_ohlcv_regime_timesplit_varaha_v3",
    }


@pytest.mark.parametrize("field", ["kurma_probability", "varaha_probability"])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("inf"), float("nan")])
def test_invalid_probability_rejected(field: str, value: float) -> None:
    record = {
        "symbol": "ALPHA",
        "security_id": "1001",
        "sample_date": "2026-06-25",
        "kurma_probability": 0.5,
        "varaha_probability": 0.5,
    }
    record[field] = value

    with pytest.raises(ValueError, match=field):
        parse_virtual_demo_signal(record)


def test_missing_required_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="symbol"):
        parse_virtual_demo_signal(
            {
                "security_id": "1001",
                "sample_date": "2026-06-25",
                "kurma_probability": 0.5,
                "varaha_probability": 0.5,
            }
        )


def test_invalid_sample_date_rejected() -> None:
    with pytest.raises(ValueError, match="sample_date"):
        parse_virtual_demo_signal(
            {
                "symbol": "ALPHA",
                "security_id": "1001",
                "sample_date": "not-a-date",
                "kurma_probability": 0.5,
                "varaha_probability": 0.5,
            }
        )


def test_invalid_close_price_rejected() -> None:
    with pytest.raises(ValueError, match="close_price"):
        parse_virtual_demo_signal(
            {
                "symbol": "ALPHA",
                "security_id": "1001",
                "sample_date": "2026-06-25",
                "kurma_probability": 0.5,
                "varaha_probability": 0.5,
                "close_price": 0,
            }
        )


def test_signal_files_do_not_import_dhan_db_prediction_or_order_paths() -> None:
    combined = "\n".join(
        [
            Path("app/matsya/virtual_demo_signals.py").read_text(encoding="utf-8").lower(),
            Path("scripts/matsya_virtual_demo_smoke.py").read_text(encoding="utf-8").lower(),
        ]
    )

    assert "dhan" not in combined
    assert "connect(" not in combined
    assert "insert " not in combined
    assert "update " not in combined
    assert "delete " not in combined
    assert "predict(" not in combined
    assert "predict_proba" not in combined
    assert "order api" not in combined
