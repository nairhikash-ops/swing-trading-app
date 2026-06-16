import csv
import json
import os

import pytest

from app.config import Settings
from app.ml_foundation import ML_LABEL_NAME, ML_MODEL_NAME
from app.ml_samples import MLSampleStore
from app.scripts.export_ml_dataset import export_ml_dataset
from app.store import TokenStore


def make_service(tmp_path) -> tuple[TokenStore, Settings, str]:
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    MLSampleStore(token_store)
    out_path = str(tmp_path / "ml_dataset_ohlcv_v1.csv")
    return token_store, settings, out_path


def insert_sample(
    token_store: TokenStore,
    symbol: str,
    sample_date: str,
    outcome: str,
    trainable: int,
    feature_json: dict | str | list | None,
    instrument_id: int = 1,
):
    with token_store._connect() as conn:
        f_json = json.dumps(feature_json) if not isinstance(feature_json, str) else feature_json
        conn.execute(
            """
            INSERT INTO ml_samples (
                model_name, label_name, instrument_id, symbol, sample_date,
                input_window_start, input_window_end, entry_close, target_price, stop_price,
                outcome, trainable, feature_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '2020-01-01', '2020-01-01', 100, 110, 90, ?, ?, ?, 'now', 'now')
            """,
            (ML_MODEL_NAME, ML_LABEL_NAME, instrument_id, symbol, sample_date, outcome, trainable, f_json),
        )


def valid_feature() -> dict:
    candles = []
    for _ in range(60):
        candles.append(
            {
                "trading_date": "2020-01-01",
                "open_rel": 0.0,
                "high_rel": 0.05,
                "low_rel": -0.05,
                "close_rel": 0.01,
                "volume_rel": 1.2,
            }
        )
    return {"candles": candles}


def test_export_ml_dataset_success(tmp_path):
    token_store, settings, out_path = make_service(tmp_path)

    insert_sample(token_store, "A", "2021-01-01", "WIN", 1, valid_feature())
    insert_sample(token_store, "B", "2021-01-02", "LOSS", 1, valid_feature())
    insert_sample(token_store, "C", "2021-01-03", "TIMEOUT", 1, valid_feature())

    # Excluded samples
    insert_sample(token_store, "D", "2021-01-04", "AMBIGUOUS", 1, valid_feature())
    insert_sample(token_store, "E", "2021-01-05", "INSUFFICIENT_FUTURE_DATA", 1, valid_feature())
    insert_sample(token_store, "F", "2021-01-06", "WIN", 0, valid_feature())

    res = export_ml_dataset(output_path=out_path, settings=settings)

    assert res["row_count"] == 3
    assert res["feature_column_count"] == 300
    assert res["total_column_count"] == 303
    assert os.path.exists(out_path)

    with open(out_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)

        # 1. CSV header has exactly 303 columns.
        assert len(header) == 303

        # 2. Metadata first
        assert header[0:3] == ["symbol", "sample_date", "outcome"]

        # 3. First feature column group starts with "c00_"
        assert header[3] == "c00_open_rel"

        # 4. Last feature column group ends with "c59_"
        assert header[-1] == "c59_volume_rel"

        # 9. Forbidden columns like "rsi" or "macd" are not present.
        for h in header:
            assert "rsi" not in h
            assert "macd" not in h

        rows = list(reader)
        # 5. Row count matches inserted usable/trainable samples.
        assert len(rows) == 3

    # 11. DB row count is unchanged
    with token_store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM ml_samples").fetchone()[0]
        assert count == 6


def test_export_ml_dataset_invalid_fails(tmp_path):
    token_store, settings, out_path = make_service(tmp_path)

    insert_sample(token_store, "A", "2021-01-01", "WIN", 1, valid_feature())

    f_bad = valid_feature()
    f_bad["candles"][0]["rsi"] = 55.0  # Forbidden key
    insert_sample(token_store, "B", "2021-01-02", "WIN", 1, f_bad)

    # 10. Invalid feature rows fail export instead of silently exporting
    with pytest.raises(ValueError, match="Forbidden extra keys"):
        export_ml_dataset(output_path=out_path, settings=settings)

    # Output file must not exist if failed
    assert not os.path.exists(out_path)
    assert not os.path.exists(out_path + ".tmp")
