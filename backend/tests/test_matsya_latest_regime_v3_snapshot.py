from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.matsya.latest_regime_v3_snapshot import (
    FEATURE_NAMES,
    MODEL_FEATURE_COUNT,
    REGIME_FEATURE_NAMES,
    MatsyaSnapshotReadinessError,
    add_regime_features,
    build_snapshot_row,
    generate_latest_regime_v3_snapshot,
    technical_feature_names,
    validate_snapshot_frame,
)


class FakeSnapshotRepository:
    def __init__(
        self,
        *,
        ready: bool = True,
        symbols: list[dict[str, str]] | None = None,
        candles_by_security_id: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self._symbols = symbols or [
            {"symbol": "AAA", "security_id": "1001"},
            {"symbol": "BBB", "security_id": "1002"},
        ]
        self._candles_by_security_id = candles_by_security_id or {
            row["security_id"]: make_candles(offset=index)
            for index, row in enumerate(self._symbols)
        }
        self._ready = ready
        self.latest_calls: list[tuple[str, int]] = []

    def readiness(self) -> dict[str, object]:
        return {
            "status": "ready" if self._ready else "not_ready",
            "latest_ohlcv_date": "2026-06-25" if self._ready else None,
            "expected_symbol_count": len(self._symbols),
            "mapped_symbols_missing": 0,
            "duplicate_count": 0,
            "null_count": 0,
            "bad_ohlc_count": 0,
            "negative_volume_count": 0,
        }

    def mapped_symbols(self) -> list[dict[str, str]]:
        return self._symbols

    def latest_candles(self, security_id: str, limit: int = 60) -> list[dict[str, object]]:
        self.latest_calls.append((security_id, limit))
        return self._candles_by_security_id[security_id][-limit:]


def make_candles(*, offset: int = 0, count: int = 60) -> list[dict[str, object]]:
    candles: list[dict[str, object]] = []
    for index in range(count):
        close = 100.0 + offset + index
        candles.append(
            {
                "trading_date": f"2026-04-{index + 1:02d}",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000.0 + index,
            }
        )
    if candles:
        candles[-1]["trading_date"] = "2026-06-25"
    return candles


def test_builds_60_by_10_candle_anatomy_columns_in_exact_order() -> None:
    names = technical_feature_names()

    assert len(names) == 600
    assert names[:10] == [
        "c00_open_rel",
        "c00_high_rel",
        "c00_low_rel",
        "c00_close_rel",
        "c00_volume_rel",
        "c00_body_to_range",
        "c00_upper_wick_to_range",
        "c00_lower_wick_to_range",
        "c00_close_position_in_range",
        "c00_signed_body_to_range",
    ]
    assert names[-1] == "c59_signed_body_to_range"


def test_adds_final_8_regime_columns_in_exact_order() -> None:
    row = build_snapshot_row(symbol="AAA", security_id="1001", candles=make_candles())
    df = add_regime_features(pd.DataFrame([row, build_snapshot_row(symbol="BBB", security_id="1002", candles=make_candles(offset=2))]))

    assert list(df.columns[-8:]) == REGIME_FEATURE_NAMES


def test_validates_exactly_608_model_features_and_writes_metadata(tmp_path: Path) -> None:
    output_path = tmp_path / "latest_stock_opportunity_ohlcv_regime_v3_snapshot.csv"
    meta_path = tmp_path / "latest_stock_opportunity_ohlcv_regime_v3_snapshot.meta.json"

    result = generate_latest_regime_v3_snapshot(
        repository=FakeSnapshotRepository(),
        output_path=output_path,
        meta_path=meta_path,
    )

    assert len(result.feature_names) == MODEL_FEATURE_COUNT
    assert result.metadata["feature_count"] == 608
    assert result.metadata["technical_feature_count"] == 600
    assert result.metadata["regime_feature_count"] == 8
    assert json.loads(meta_path.read_text(encoding="utf-8"))["notes"] == "latest inference snapshot only; no split; no labels; no scoring"


def test_metadata_is_not_included_in_model_features() -> None:
    assert "symbol" not in FEATURE_NAMES
    assert "security_id" not in FEATURE_NAMES
    assert "sample_date" not in FEATURE_NAMES


def test_rejects_fewer_than_60_candles() -> None:
    with pytest.raises(ValueError, match="Invalid window length 59"):
        build_snapshot_row(symbol="AAA", security_id="1001", candles=make_candles(count=59))


def test_generator_fails_closed_when_any_mapped_symbol_has_fewer_than_60_candles(tmp_path: Path) -> None:
    repository = FakeSnapshotRepository(
        candles_by_security_id={
            "1001": make_candles(),
            "1002": make_candles(count=59),
        }
    )

    with pytest.raises(MatsyaSnapshotReadinessError, match="fewer than 60 completed candles"):
        generate_latest_regime_v3_snapshot(
            repository=repository,
            output_path=tmp_path / "snapshot.csv",
            meta_path=tmp_path / "snapshot.meta.json",
        )


def test_rejects_nan_or_inf_features() -> None:
    row = build_snapshot_row(symbol="AAA", security_id="1001", candles=make_candles())
    df = add_regime_features(pd.DataFrame([row, build_snapshot_row(symbol="BBB", security_id="1002", candles=make_candles(offset=1))]))
    df.loc[0, "c00_open_rel"] = math.inf

    with pytest.raises(ValueError, match="Infinite values"):
        validate_snapshot_frame(df)

    df.loc[0, "c00_open_rel"] = np.nan
    with pytest.raises(ValueError, match="NaN values"):
        validate_snapshot_frame(df)


def test_rejects_duplicate_symbol_sample_date() -> None:
    row = build_snapshot_row(symbol="AAA", security_id="1001", candles=make_candles())
    df = add_regime_features(pd.DataFrame([row, row]))

    with pytest.raises(ValueError, match=r"duplicate symbol \+ sample_date"):
        validate_snapshot_frame(df)


def test_rejects_readiness_not_ready(tmp_path: Path) -> None:
    with pytest.raises(MatsyaSnapshotReadinessError, match="Matsya readiness is not ready"):
        generate_latest_regime_v3_snapshot(
            repository=FakeSnapshotRepository(ready=False),
            output_path=tmp_path / "snapshot.csv",
            meta_path=tmp_path / "snapshot.meta.json",
        )


def test_confirms_no_split_files_are_created(tmp_path: Path) -> None:
    generate_latest_regime_v3_snapshot(
        repository=FakeSnapshotRepository(),
        output_path=tmp_path / "snapshot.csv",
        meta_path=tmp_path / "snapshot.meta.json",
    )

    assert not (tmp_path / "train.csv").exists()
    assert not (tmp_path / "test.csv").exists()


def test_confirms_no_scoring_or_model_artifact_code_is_used() -> None:
    source = Path("app/matsya/latest_regime_v3_snapshot.py").read_text(encoding="utf-8")

    assert "joblib" not in source
    assert "predict_proba" not in source
    assert "model.joblib" not in source
    assert "score_timesplit" not in source
    assert "kurma" not in source.lower()
    assert "varaha" not in source.lower()


def test_confirms_no_dhan_calls() -> None:
    source = Path("app/matsya/latest_regime_v3_snapshot.py").read_text(encoding="utf-8")

    assert "DhanClient" not in source
    assert "historical_daily" not in source
    assert "/orders" not in source


def test_confirms_no_matsya_ohlcv_write_or_delete_operations() -> None:
    source = Path("app/matsya/latest_regime_v3_snapshot.py").read_text(encoding="utf-8").upper()

    assert "INSERT INTO MATSYA.OHLCV_DAILY" not in source
    assert "UPDATE MATSYA.OHLCV_DAILY" not in source
    assert "DELETE FROM MATSYA.OHLCV_DAILY" not in source
    assert "TRUNCATE MATSYA.OHLCV_DAILY" not in source
