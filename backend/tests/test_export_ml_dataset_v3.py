import json
import math
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from app.scripts.export_ml_dataset_v3 import export_ml_dataset_v3, DEFAULT_OUTPUT_PATH

@pytest.fixture
def temp_output_csv():
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)

def build_mock_rows(candles=None, num_samples=1):
    if candles is None:
        candles = []
        for i in range(60):
            candles.append({
                "open_rel": 1.0,
                "high_rel": 1.10,
                "low_rel": 0.90,
                "close_rel": 1.05,
                "volume_rel": 0.5
            })
    
    rows = []
    for i in range(num_samples):
        rows.append({
            "symbol": f"TEST_SYM_{i}",
            "sample_date": f"2025-01-{i+1:02d}",
            "outcome": "WIN",
            "feature_json": json.dumps({"candles": candles})
        })
    return rows

def test_v3_header_and_feature_counts(temp_output_csv):
    mock_rows = build_mock_rows()
    with patch("app.scripts.export_ml_dataset_v3.TokenStore") as mock_store:
        mock_conn = MagicMock()
        mock_store.return_value._connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        res = export_ml_dataset_v3(output_path=temp_output_csv)

        assert res["total_column_count"] == 603
        assert res["feature_column_count"] == 600

        with open(temp_output_csv, "r") as f:
            header = f.readline().strip().split(",")
            
        assert len(header) == 603
        assert header[:3] == ["symbol", "sample_date", "outcome"]
        
        # Check first candle exact columns
        expected_first = [
            "c00_open_rel", "c00_high_rel", "c00_low_rel", "c00_close_rel", "c00_volume_rel",
            "c00_body_to_range", "c00_upper_wick_to_range", "c00_lower_wick_to_range",
            "c00_close_position_in_range", "c00_signed_body_to_range"
        ]
        assert header[3:13] == expected_first

        # Check last candle anatomy columns exist
        expected_last_anatomy = [
            "c59_body_to_range", "c59_upper_wick_to_range", "c59_lower_wick_to_range",
            "c59_close_position_in_range", "c59_signed_body_to_range"
        ]
        for col in expected_last_anatomy:
            assert col in header

        # Verify no regime features
        assert "market_median_20d_return" not in header
        assert "market_breakout_rate" not in header
        assert "stock_is_stronger_than_market" not in header

def test_anatomy_calculated_correctly(temp_output_csv):
    candles = []
    # Known OHLC for first candle
    candles.append({
        "open_rel": 1.0,
        "high_rel": 1.10,
        "low_rel": 0.90,
        "close_rel": 1.05,
        "volume_rel": 0.5
    })
    # Fill remaining 59 with dummy data
    for i in range(59):
        candles.append({
            "open_rel": 1.0, "high_rel": 1.1, "low_rel": 0.9, "close_rel": 1.0, "volume_rel": 1.0
        })
    
    mock_rows = build_mock_rows(candles=candles)
    with patch("app.scripts.export_ml_dataset_v3.TokenStore") as mock_store:
        mock_conn = MagicMock()
        mock_store.return_value._connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        export_ml_dataset_v3(output_path=temp_output_csv)

        with open(temp_output_csv, "r") as f:
            lines = f.readlines()
            header = lines[0].strip().split(",")
            values = lines[1].strip().split(",")
            row_dict = dict(zip(header, values))
            
            # 1.0, 1.10, 0.90, 1.05 => range=0.20
            # body=0.05 => body_to_range=0.25
            # upper_wick=(1.10-1.05)=0.05 => upper_wick_to_range=0.25
            # lower_wick=(1.00-0.90)=0.10 => lower_wick_to_range=0.50
            # close_pos=(1.05-0.90)=0.15 => close_position_in_range=0.75
            # signed_body=(1.05-1.0)=0.05 => signed_body_to_range=0.25
            assert float(row_dict["c00_body_to_range"]) == pytest.approx(0.25)
            assert float(row_dict["c00_upper_wick_to_range"]) == pytest.approx(0.25)
            assert float(row_dict["c00_lower_wick_to_range"]) == pytest.approx(0.50)
            assert float(row_dict["c00_close_position_in_range"]) == pytest.approx(0.75)
            assert float(row_dict["c00_signed_body_to_range"]) == pytest.approx(0.25)

def test_zero_range_candle(temp_output_csv):
    candles = []
    # Zero range candle
    candles.append({
        "open_rel": 1.0,
        "high_rel": 1.0,
        "low_rel": 1.0,
        "close_rel": 1.0,
        "volume_rel": 0.5
    })
    for i in range(59):
        candles.append({
            "open_rel": 1.0, "high_rel": 1.1, "low_rel": 0.9, "close_rel": 1.0, "volume_rel": 1.0
        })
    
    mock_rows = build_mock_rows(candles=candles)
    with patch("app.scripts.export_ml_dataset_v3.TokenStore") as mock_store:
        mock_conn = MagicMock()
        mock_store.return_value._connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        export_ml_dataset_v3(output_path=temp_output_csv)

        with open(temp_output_csv, "r") as f:
            lines = f.readlines()
            header = lines[0].strip().split(",")
            values = lines[1].strip().split(",")
            row_dict = dict(zip(header, values))
            
            assert float(row_dict["c00_body_to_range"]) == pytest.approx(0.0)
            assert float(row_dict["c00_upper_wick_to_range"]) == pytest.approx(0.0)
            assert float(row_dict["c00_lower_wick_to_range"]) == pytest.approx(0.0)
            assert float(row_dict["c00_close_position_in_range"]) == pytest.approx(0.5)
            assert float(row_dict["c00_signed_body_to_range"]) == pytest.approx(0.0)

def test_missing_raw_candle_field(temp_output_csv):
    candles = []
    # Missing 'high_rel'
    candles.append({
        "open_rel": 1.0,
        "low_rel": 0.90,
        "close_rel": 1.05,
        "volume_rel": 0.5
    })
    for i in range(59):
        candles.append({
            "open_rel": 1.0, "high_rel": 1.1, "low_rel": 0.9, "close_rel": 1.0, "volume_rel": 1.0
        })
    
    mock_rows = build_mock_rows(candles=candles)
    with patch("app.scripts.export_ml_dataset_v3.TokenStore") as mock_store:
        mock_conn = MagicMock()
        mock_store.return_value._connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        with pytest.raises(ValueError, match="Missing required keys"):
            export_ml_dataset_v3(output_path=temp_output_csv)

def test_wrong_candle_count(temp_output_csv):
    candles = []
    # 59 candles only
    for i in range(59):
        candles.append({
            "open_rel": 1.0, "high_rel": 1.1, "low_rel": 0.9, "close_rel": 1.0, "volume_rel": 1.0
        })
    
    mock_rows = build_mock_rows(candles=candles)
    with patch("app.scripts.export_ml_dataset_v3.TokenStore") as mock_store:
        mock_conn = MagicMock()
        mock_store.return_value._connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        with pytest.raises(ValueError, match="Invalid window length"):
            export_ml_dataset_v3(output_path=temp_output_csv)

def test_no_nan_or_inf_in_rows(temp_output_csv):
    candles = []
    candles.append({
        "open_rel": 1.0, "high_rel": float('inf'), "low_rel": 0.9, "close_rel": 1.0, "volume_rel": 1.0
    })
    for i in range(59):
        candles.append({
            "open_rel": 1.0, "high_rel": 1.1, "low_rel": 0.9, "close_rel": 1.0, "volume_rel": 1.0
        })
        
    mock_rows = build_mock_rows(candles=candles)
    with patch("app.scripts.export_ml_dataset_v3.TokenStore") as mock_store:
        mock_conn = MagicMock()
        mock_store.return_value._connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        with pytest.raises(ValueError, match="Null/NaN/Inf value"):
            export_ml_dataset_v3(output_path=temp_output_csv)

def test_duplicate_sample_counting(temp_output_csv):
    mock_rows = build_mock_rows(num_samples=1)
    # Duplicate the row
    mock_rows.append(mock_rows[0])
    
    with patch("app.scripts.export_ml_dataset_v3.TokenStore") as mock_store:
        mock_conn = MagicMock()
        mock_store.return_value._connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        res = export_ml_dataset_v3(output_path=temp_output_csv)
        assert res["duplicate_sample_count"] == 1

def test_default_output_path_constant():
    assert DEFAULT_OUTPUT_PATH == "/app/data/exports/ml_dataset_ohlcv_v3.csv"

def test_string_numeric_value_rejected(temp_output_csv):
    candles = []
    # string volume_rel
    candles.append({
        "open_rel": 1.0, "high_rel": 1.1, "low_rel": 0.9, "close_rel": 1.0, "volume_rel": "1.0"
    })
    for i in range(59):
        candles.append({
            "open_rel": 1.0, "high_rel": 1.1, "low_rel": 0.9, "close_rel": 1.0, "volume_rel": 1.0
        })
        
    mock_rows = build_mock_rows(candles=candles)
    with patch("app.scripts.export_ml_dataset_v3.TokenStore") as mock_store:
        mock_conn = MagicMock()
        mock_store.return_value._connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        with pytest.raises(ValueError, match="Non-numeric value"):
            export_ml_dataset_v3(output_path=temp_output_csv)
