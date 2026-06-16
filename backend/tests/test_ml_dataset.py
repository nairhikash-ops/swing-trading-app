import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, get_ml_dataset_service_dep
from app.ml_dataset import MLDatasetService
from app.ml_foundation import ML_LABEL_NAME, ML_MODEL_NAME
from app.ml_samples import MLSampleStore
from app.store import TokenStore


def make_service(tmp_path) -> tuple[TokenStore, MLDatasetService]:
    settings = Settings(app_secret_key="a" * 44, data_dir=tmp_path)
    token_store = TokenStore(settings.database_path)
    # Init MLSampleStore to create the ml_samples table
    MLSampleStore(token_store)
    return token_store, MLDatasetService(settings=settings, token_store=token_store)


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


def test_ml_dataset_inspection_counts(tmp_path):
    token_store, service = make_service(tmp_path)

    # 1. Usable sample
    insert_sample(token_store, "A", "2021-01-01", "WIN", 1, valid_feature())

    # 2. Non-trainable sample (ignored)
    insert_sample(token_store, "A", "2021-01-02", "TIMEOUT", 0, valid_feature())

    # 3. AMBIGUOUS sample (ignored)
    insert_sample(token_store, "B", "2021-01-03", "AMBIGUOUS", 1, valid_feature())

    # 4. INSUFFICIENT_FUTURE_DATA sample (ignored)
    insert_sample(token_store, "C", "2021-01-04", "INSUFFICIENT_FUTURE_DATA", 1, valid_feature())

    # 5. Invalid JSON string
    insert_sample(token_store, "C", "2021-01-05", "LOSS", 1, "{invalid json")

    # 6. Invalid JSON (no candles list)
    insert_sample(token_store, "C", "2021-01-06", "LOSS", 1, {"wrong": "key"})

    # 7. Invalid window length (59)
    f7 = valid_feature()
    f7["candles"].pop()
    insert_sample(token_store, "D", "2021-01-07", "TIMEOUT", 1, f7)

    # 8. Missing required key
    f8 = valid_feature()
    del f8["candles"][0]["open_rel"]
    insert_sample(token_store, "D", "2021-01-08", "LOSS", 1, f8)

    # 9. Null value
    f9 = valid_feature()
    f9["candles"][10]["high_rel"] = None
    insert_sample(token_store, "E", "2021-01-09", "WIN", 1, f9)

    # 10. Forbidden feature key
    f10 = valid_feature()
    f10["candles"][59]["rsi"] = 55.0
    insert_sample(token_store, "E", "2021-01-10", "LOSS", 1, f10)

    # 11. Duplicate symbol+sample_date
    insert_sample(token_store, "A", "2021-01-01", "WIN", 1, valid_feature(), instrument_id=2)

    res = service.inspect()

    # Excluded: #2, #3, #4. Total usable = 1, 5, 6, 7, 8, 9, 10, 11 => 8 rows
    assert res["total_usable_rows"] == 8
    assert res["invalid_feature_json_count"] == 2  # #5, #6
    assert res["invalid_window_length_count"] == 1  # #7
    assert res["missing_required_key_count"] == 1  # #8
    assert res["null_value_count"] == 1  # #9
    assert res["forbidden_feature_key_count"] == 1  # #10
    assert res["duplicate_sample_count"] == 1  # #11 is a dup of #1

    assert res["expected_feature_column_count"] == 300
    assert res["first_sample_date"] == "2021-01-01"
    assert res["last_sample_date"] == "2021-01-10"

    assert res["rows_by_symbol"] == {"A": 2, "C": 2, "D": 2, "E": 2}
    assert res["rows_by_outcome"] == {"WIN": 3, "LOSS": 4, "TIMEOUT": 1}


def test_ml_dataset_inspection_endpoint(tmp_path):
    token_store, service = make_service(tmp_path)
    app.dependency_overrides[get_ml_dataset_service_dep] = lambda: service
    client = TestClient(app)

    insert_sample(token_store, "XYZ", "2022-01-01", "WIN", 1, valid_feature())

    response = client.get("/api/ml/dataset/inspect")
    assert response.status_code == 200
    data = response.json()
    assert data["total_usable_rows"] == 1
    assert data["expected_feature_column_count"] == 300


def test_ml_dataset_inspection_real_feature_shape(tmp_path):
    token_store, service = make_service(tmp_path)

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

    real_feature_shape = {
        "symbol": "RELIANCE",
        "instrument_id": 1,
        "sample_date": "2020-01-01",
        "entry_close": 100.0,
        "input_window_sessions": 60,
        "future_window_sessions": 20,
        "target_percent": 10.0,
        "stop_percent": 5.0,
        "candles": candles,
    }

    insert_sample(token_store, "RELIANCE", "2020-01-01", "WIN", 1, real_feature_shape)

    res = service.inspect()

    assert res["total_usable_rows"] == 1
    assert res["invalid_feature_json_count"] == 0
    assert res["invalid_window_length_count"] == 0
    assert res["missing_required_key_count"] == 0
    assert res["forbidden_feature_key_count"] == 0
    assert res["null_value_count"] == 0
    assert res["expected_feature_column_count"] == 300
