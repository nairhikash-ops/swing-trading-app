import math
import pytest
from app.ml_dataset_v3_anatomy import calculate_candle_anatomy, add_candle_anatomy_features

def test_green_candle_normal_range():
    candle = {
        "open_rel": 1.0,
        "high_rel": 1.10,
        "low_rel": 0.90,
        "close_rel": 1.05,
    }
    anatomy = calculate_candle_anatomy(candle)
    assert anatomy["body_to_range"] == pytest.approx(0.25)
    assert anatomy["upper_wick_to_range"] == pytest.approx(0.25)
    assert anatomy["lower_wick_to_range"] == pytest.approx(0.50)
    assert anatomy["close_position_in_range"] == pytest.approx(0.75)
    assert anatomy["signed_body_to_range"] == pytest.approx(0.25)

def test_red_candle_normal_range():
    candle = {
        "open_rel": 1.05,
        "high_rel": 1.10,
        "low_rel": 0.90,
        "close_rel": 1.00,
    }
    anatomy = calculate_candle_anatomy(candle)
    assert anatomy["body_to_range"] == pytest.approx(0.25)
    assert anatomy["upper_wick_to_range"] == pytest.approx(0.25)
    assert anatomy["lower_wick_to_range"] == pytest.approx(0.50)
    assert anatomy["close_position_in_range"] == pytest.approx(0.50)
    assert anatomy["signed_body_to_range"] == pytest.approx(-0.25)

def test_full_body_green_candle():
    candle = {
        "open_rel": 0.90,
        "high_rel": 1.10,
        "low_rel": 0.90,
        "close_rel": 1.10,
    }
    anatomy = calculate_candle_anatomy(candle)
    assert anatomy["body_to_range"] == pytest.approx(1.0)
    assert anatomy["upper_wick_to_range"] == pytest.approx(0.0)
    assert anatomy["lower_wick_to_range"] == pytest.approx(0.0)
    assert anatomy["close_position_in_range"] == pytest.approx(1.0)
    assert anatomy["signed_body_to_range"] == pytest.approx(1.0)

def test_full_body_red_candle():
    candle = {
        "open_rel": 1.10,
        "high_rel": 1.10,
        "low_rel": 0.90,
        "close_rel": 0.90,
    }
    anatomy = calculate_candle_anatomy(candle)
    assert anatomy["body_to_range"] == pytest.approx(1.0)
    assert anatomy["upper_wick_to_range"] == pytest.approx(0.0)
    assert anatomy["lower_wick_to_range"] == pytest.approx(0.0)
    assert anatomy["close_position_in_range"] == pytest.approx(0.0)
    assert anatomy["signed_body_to_range"] == pytest.approx(-1.0)

def test_zero_range_candle():
    candle = {
        "open_rel": 1.0,
        "high_rel": 1.0,
        "low_rel": 1.0,
        "close_rel": 1.0,
    }
    anatomy = calculate_candle_anatomy(candle)
    assert anatomy["body_to_range"] == pytest.approx(0.0)
    assert anatomy["upper_wick_to_range"] == pytest.approx(0.0)
    assert anatomy["lower_wick_to_range"] == pytest.approx(0.0)
    assert anatomy["close_position_in_range"] == pytest.approx(0.5)
    assert anatomy["signed_body_to_range"] == pytest.approx(0.0)

def test_negative_range_rejected():
    candle = {
        "open_rel": 1.0,
        "high_rel": 0.9,
        "low_rel": 1.1,
        "close_rel": 1.0,
    }
    with pytest.raises(ValueError):
        calculate_candle_anatomy(candle)

def test_missing_required_field_rejected():
    candle = {
        "open_rel": 1.0,
        "high_rel": 1.1,
        "low_rel": 0.9,
    }
    with pytest.raises(ValueError):
        calculate_candle_anatomy(candle)

def test_nan_rejected():
    candle = {
        "open_rel": 1.0,
        "high_rel": float('nan'),
        "low_rel": 0.9,
        "close_rel": 1.0,
    }
    with pytest.raises(ValueError):
        calculate_candle_anatomy(candle)

def test_positive_infinity_rejected():
    candle = {
        "open_rel": 1.0,
        "high_rel": float('inf'),
        "low_rel": 0.9,
        "close_rel": 1.0,
    }
    with pytest.raises(ValueError):
        calculate_candle_anatomy(candle)

def test_string_non_numeric_rejected():
    candle = {
        "open_rel": 1.0,
        "high_rel": "1.1",
        "low_rel": 0.9,
        "close_rel": 1.0,
    }
    with pytest.raises(ValueError):
        calculate_candle_anatomy(candle)

def test_output_keys_exactly_five():
    candle = {
        "open_rel": 1.0,
        "high_rel": 1.10,
        "low_rel": 0.90,
        "close_rel": 1.05,
    }
    anatomy = calculate_candle_anatomy(candle)
    expected_keys = {
        "body_to_range",
        "upper_wick_to_range",
        "lower_wick_to_range",
        "close_position_in_range",
        "signed_body_to_range",
    }
    assert set(anatomy.keys()) == expected_keys

def test_add_candle_anatomy_features():
    candle = {
        "trading_date": "2025-01-01",
        "open_rel": 1.0,
        "high_rel": 1.10,
        "low_rel": 0.90,
        "close_rel": 1.05,
        "volume_rel": 2.5
    }
    result = add_candle_anatomy_features(candle)
    
    assert result["trading_date"] == "2025-01-01"
    assert result["volume_rel"] == 2.5
    assert result["open_rel"] == 1.0
    
    expected_anatomy_keys = {
        "body_to_range",
        "upper_wick_to_range",
        "lower_wick_to_range",
        "close_position_in_range",
        "signed_body_to_range",
    }
    assert expected_anatomy_keys.issubset(set(result.keys()))
    assert len(result) == len(candle) + 5

def test_deterministic_output():
    candle = {
        "open_rel": 1.0,
        "high_rel": 1.10,
        "low_rel": 0.90,
        "close_rel": 1.05,
    }
    result1 = calculate_candle_anatomy(candle)
    result2 = calculate_candle_anatomy(candle)
    assert result1 == result2

def test_no_pandas_imported():
    import app.ml_dataset_v3_anatomy as anatomy_module
    
    assert "pandas" not in dir(anatomy_module)
    assert "pd" not in dir(anatomy_module)
    assert "numpy" not in dir(anatomy_module)
    assert "np" not in dir(anatomy_module)
