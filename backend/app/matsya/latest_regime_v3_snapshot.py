from __future__ import annotations

import csv
import json
import math
import os
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.matsya.db import connect
from app.matsya.ohlcv_service import INSTRUMENT_LATERAL_JOIN_SQL, MatsyaOHLCVStore
from app.matsya.settings import MatsyaSettings
from app.ml_dataset_v3_anatomy import calculate_candle_anatomy


DATASET_VERSION = "stock_opportunity_ohlcv_regime_v3"
PARENT_DATASET_VERSION = "stock_opportunity_ohlcv_v3"
SPLIT_REFERENCE_VERSION = "timesplit_regime_v3"
LATEST_SNAPSHOT_DIR = Path("/app/data/exports/latest_regime_v3")
DEFAULT_OUTPUT_PATH = LATEST_SNAPSHOT_DIR / "latest_stock_opportunity_ohlcv_regime_v3_snapshot.csv"
DEFAULT_META_PATH = LATEST_SNAPSHOT_DIR / "latest_stock_opportunity_ohlcv_regime_v3_snapshot.meta.json"
NOTES = "latest inference snapshot only; no split; no labels; no scoring"

METADATA_COLUMNS = ["symbol", "security_id", "sample_date"]
RAW_CANDLE_FEATURE_NAMES = ["open_rel", "high_rel", "low_rel", "close_rel", "volume_rel"]
ANATOMY_FEATURE_NAMES = [
    "body_to_range",
    "upper_wick_to_range",
    "lower_wick_to_range",
    "close_position_in_range",
    "signed_body_to_range",
]
CANDLE_FEATURE_NAMES = RAW_CANDLE_FEATURE_NAMES + ANATOMY_FEATURE_NAMES
REGIME_FEATURE_NAMES = [
    "market_median_20d_return",
    "market_breakout_rate",
    "market_breakdown_rate",
    "market_breadth_delta",
    "market_cross_sectional_volatility",
    "stock_20d_return_minus_market_median",
    "stock_is_stronger_than_market",
    "stock_breakout_while_market_weak",
]
TECHNICAL_FEATURE_COUNT = 600
REGIME_FEATURE_COUNT = 8
MODEL_FEATURE_COUNT = 608


def technical_feature_names() -> list[str]:
    return [f"c{index:02d}_{name}" for index in range(60) for name in CANDLE_FEATURE_NAMES]


FEATURE_NAMES = technical_feature_names() + REGIME_FEATURE_NAMES


class SnapshotRepository(Protocol):
    def readiness(self) -> dict[str, Any]:
        ...

    def mapped_symbols(self) -> list[dict[str, Any]]:
        ...

    def latest_candles(self, security_id: str, limit: int = 60) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class SnapshotResult:
    output_path: str
    meta_path: str
    metadata: dict[str, Any]
    feature_names: list[str]


class MatsyaSnapshotReadinessError(ValueError):
    pass


class MatsyaLatestRegimeV3Repository:
    def __init__(self, settings: MatsyaSettings | None = None) -> None:
        self.settings = settings or MatsyaSettings.from_env()
        self.ohlcv_store = MatsyaOHLCVStore(self.settings)

    @contextmanager
    def _connect(self) -> Iterable[Any]:
        conn = connect(self.settings)
        try:
            yield conn
        finally:
            conn.close()

    def readiness(self) -> dict[str, Any]:
        validation = self.ohlcv_store.validation_report(
            self.settings.ohlcv_universe_name,
            self.settings.ohlcv_validation_trading_days,
            self.settings.historical_finalized_after_hour_ist,
            self.settings.market_code,
        )
        with self._connect() as conn:
            latest_run = _one(
                conn.execute(
                    """
                    SELECT id, status, total_symbols, mapped_symbols, skipped_symbols, completed_at, error_message
                    FROM matsya.ohlcv_fetch_runs
                    WHERE universe_name = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (self.settings.ohlcv_universe_name,),
                )
            ) or {}

        latest_stored = validation.get("latest_stored_candle_date")
        expected_latest = validation.get("expected_latest_candle_date")
        latest_run_status = latest_run.get("status") or ""
        ready = (
            latest_stored is not None
            and latest_stored == expected_latest
            and latest_run_status in {"completed", "up_to_date"}
            and int(validation.get("duplicate_count") or 0) == 0
            and int(validation.get("null_ohlcv_count") or 0) == 0
            and int(validation.get("bad_ohlc_count") or 0) == 0
            and int(validation.get("negative_volume_count") or 0) == 0
            and int(validation.get("mapped_symbols") or 0) > 0
            and int(validation.get("zero_candle_symbols") or 0) == 0
            and int(validation.get("stale_symbols") or 0) == 0
            and int(validation.get("missing_recent_symbol_dates") or 0) == 0
        )
        return {
            "status": "ready" if ready else "not_ready",
            "validation_trading_days": int(validation.get("validation_trading_days") or 0),
            "validation_start_date": validation.get("validation_start_date"),
            "latest_ohlcv_date": latest_stored,
            "latest_stored_candle_date": latest_stored,
            "expected_latest_ohlcv_date": expected_latest,
            "expected_latest_candle_date": expected_latest,
            "latest_ohlcv_run": latest_run,
            "latest_ohlcv_run_status": latest_run_status,
            "expected_symbol_count": int(validation.get("mapped_symbols") or 0),
            "mapped_symbols": int(validation.get("mapped_symbols") or 0),
            "zero_candle_symbols": int(validation.get("zero_candle_symbols") or 0),
            "stale_symbols": int(validation.get("stale_symbols") or 0),
            "missing_recent_symbol_dates": int(validation.get("missing_recent_symbol_dates") or 0),
            "duplicate_count": int(validation.get("duplicate_count") or 0),
            "null_count": int(validation.get("null_ohlcv_count") or 0),
            "null_ohlcv_count": int(validation.get("null_ohlcv_count") or 0),
            "bad_ohlc_count": int(validation.get("bad_ohlc_count") or 0),
            "negative_volume_count": int(validation.get("negative_volume_count") or 0),
        }

    def mapped_symbols(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = _all(
                conn.execute(
                    f"""
                    SELECT m.symbol, mi.security_id
                    FROM matsya.market_universe_members m
                    {INSTRUMENT_LATERAL_JOIN_SQL}
                    WHERE m.universe_name = %s AND m.active = true AND mi.id IS NOT NULL
                    ORDER BY m.symbol
                    """,
                    (self.settings.ohlcv_universe_name,),
                )
            )
        return [{"symbol": str(row["symbol"]).upper(), "security_id": str(row["security_id"])} for row in rows]

    def latest_candles(self, security_id: str, limit: int = 60) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = _all(
                conn.execute(
                    """
                    SELECT trading_date, open_price, high_price, low_price, close_price, volume
                    FROM (
                        SELECT trading_date, open_price, high_price, low_price, close_price, volume
                        FROM matsya.ohlcv_daily
                        WHERE provider_code = 'dhan' AND security_id = %s
                        ORDER BY trading_date DESC
                        LIMIT %s
                    ) latest
                    ORDER BY trading_date ASC
                    """,
                    (security_id, limit),
                )
            )
        return [
            {
                "trading_date": _date_text(row["trading_date"]),
                "open": float(row["open_price"]),
                "high": float(row["high_price"]),
                "low": float(row["low_price"]),
                "close": float(row["close_price"]),
                "volume": float(row["volume"]),
            }
            for row in rows
        ]


def generate_latest_regime_v3_snapshot(
    *,
    repository: SnapshotRepository | None = None,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    meta_path: str | Path = DEFAULT_META_PATH,
) -> SnapshotResult:
    resolved_repository = repository or MatsyaLatestRegimeV3Repository()
    readiness = resolved_repository.readiness()
    _validate_readiness(readiness)

    rows: list[dict[str, Any]] = []
    skipped_symbols: list[dict[str, str]] = []
    sample_dates: set[str] = set()

    mapped_symbols = resolved_repository.mapped_symbols()
    expected_symbol_count = int(readiness.get("expected_symbol_count") or len(mapped_symbols))

    for symbol_row in mapped_symbols:
        symbol = str(symbol_row["symbol"]).upper()
        security_id = str(symbol_row["security_id"])
        candles = resolved_repository.latest_candles(security_id, limit=60)
        if len(candles) < 60:
            skipped_symbols.append({"symbol": symbol, "security_id": security_id, "reason": "fewer_than_60_completed_candles"})
            continue
        snapshot_row = build_snapshot_row(symbol=symbol, security_id=security_id, candles=candles[-60:])
        rows.append(snapshot_row)
        sample_dates.add(str(snapshot_row["sample_date"]))

    if not rows:
        raise MatsyaSnapshotReadinessError("No eligible mapped symbols had 60 completed candles.")
    if skipped_symbols:
        raise MatsyaSnapshotReadinessError(f"{len(skipped_symbols)} mapped symbols had fewer than 60 completed candles.")
    if len(sample_dates) != 1:
        raise ValueError(f"Latest snapshot must have exactly one sample_date, got {sorted(sample_dates)}")
    expected_sample_date = readiness.get("expected_latest_candle_date") or readiness.get("expected_latest_ohlcv_date")
    if expected_sample_date and sample_dates != {str(expected_sample_date)}:
        raise ValueError(f"Snapshot sample_date must equal expected latest candle date {expected_sample_date}.")

    df = pd.DataFrame(rows, columns=METADATA_COLUMNS + technical_feature_names())
    df = add_regime_features(df)
    validate_snapshot_frame(df)

    output_file = Path(output_path)
    meta_file = Path(meta_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    meta_file.parent.mkdir(parents=True, exist_ok=True)

    _atomic_write_csv(df, output_file)

    metadata = build_metadata(
        df=df,
        readiness=readiness,
        expected_symbol_count=expected_symbol_count,
        skipped_symbols=skipped_symbols,
    )
    _atomic_write_json(metadata, meta_file)

    return SnapshotResult(
        output_path=str(output_file),
        meta_path=str(meta_file),
        metadata=metadata,
        feature_names=FEATURE_NAMES.copy(),
    )


def build_snapshot_row(*, symbol: str, security_id: str, candles: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if len(candles) != 60:
        raise ValueError(f"Invalid window length {len(candles)} for {symbol}; expected 60")

    entry_close = _finite_float(candles[-1].get("close"), f"{symbol} c59 close")
    average_volume = sum(_finite_float(candle.get("volume"), f"{symbol} volume") for candle in candles) / len(candles)
    row: dict[str, Any] = {
        "symbol": symbol,
        "security_id": security_id,
        "sample_date": str(candles[-1]["trading_date"]),
    }

    for index, candle in enumerate(candles):
        _validate_raw_candle(candle, symbol=symbol, index=index)
        volume = _finite_float(candle["volume"], f"{symbol} c{index:02d} volume")
        relative_candle = {
            "open_rel": relative_price(_finite_float(candle["open"], f"{symbol} c{index:02d} open"), entry_close),
            "high_rel": relative_price(_finite_float(candle["high"], f"{symbol} c{index:02d} high"), entry_close),
            "low_rel": relative_price(_finite_float(candle["low"], f"{symbol} c{index:02d} low"), entry_close),
            "close_rel": relative_price(_finite_float(candle["close"], f"{symbol} c{index:02d} close"), entry_close),
            "volume_rel": 0.0 if average_volume == 0 else volume / average_volume - 1.0,
        }
        anatomy = calculate_candle_anatomy(relative_candle)
        prefix = f"c{index:02d}_"
        for name in CANDLE_FEATURE_NAMES:
            value = relative_candle[name] if name in relative_candle else anatomy[name]
            if not _is_finite_number(value):
                raise ValueError(f"Non-finite feature {prefix}{name} for {symbol}")
            row[f"{prefix}{name}"] = float(value)

    return row


def add_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["current_close_ratio"] = (1.0 + result["c59_close_rel"]).astype(np.float32)
    result["past_close_ratio"] = (1.0 + result["c39_close_rel"]).astype(np.float32)
    result["stock_20d_return"] = (result["current_close_ratio"] / result["past_close_ratio"] - 1.0).astype(np.float32)

    previous_high_cols = [f"c{index:02d}_high_rel" for index in range(39, 59)]
    previous_low_cols = [f"c{index:02d}_low_rel" for index in range(39, 59)]
    max_previous_high = result[previous_high_cols].max(axis=1) + 1.0
    min_previous_low = result[previous_low_cols].min(axis=1) + 1.0

    result["stock_is_breakout"] = (result["current_close_ratio"] > max_previous_high).astype(np.float32)
    result["stock_is_breakdown"] = (result["current_close_ratio"] < min_previous_low).astype(np.float32)

    market_df = (
        result.groupby("sample_date")
        .agg(
            market_median_20d_return=("stock_20d_return", "median"),
            market_cross_sectional_volatility=("stock_20d_return", "std"),
            market_breakout_rate=("stock_is_breakout", "mean"),
            market_breakdown_rate=("stock_is_breakdown", "mean"),
        )
        .reset_index()
    )
    market_df["market_breadth_delta"] = (
        market_df["market_breakout_rate"] - market_df["market_breakdown_rate"]
    ).astype(np.float32)
    for column in (
        "market_median_20d_return",
        "market_cross_sectional_volatility",
        "market_breakout_rate",
        "market_breakdown_rate",
    ):
        market_df[column] = market_df[column].fillna(0.0).astype(np.float32)

    result = result.merge(market_df, on="sample_date", how="left")
    result["stock_20d_return_minus_market_median"] = (
        result["stock_20d_return"] - result["market_median_20d_return"]
    ).astype(np.float32)
    result["stock_is_stronger_than_market"] = (
        result["stock_20d_return"] > result["market_median_20d_return"]
    ).astype(np.float32)
    result["stock_breakout_while_market_weak"] = (
        (result["stock_is_breakout"] == 1.0) & (result["market_breadth_delta"] < 0)
    ).astype(np.float32)

    result.drop(
        columns=["current_close_ratio", "past_close_ratio", "stock_20d_return", "stock_is_breakout", "stock_is_breakdown"],
        inplace=True,
    )
    return result[METADATA_COLUMNS + FEATURE_NAMES]


def validate_snapshot_frame(df: pd.DataFrame) -> None:
    expected_columns = METADATA_COLUMNS + FEATURE_NAMES
    if list(df.columns) != expected_columns:
        raise ValueError("Latest snapshot columns do not match Dataset V3 Regime feature order.")
    if len(FEATURE_NAMES) != MODEL_FEATURE_COUNT:
        raise ValueError(f"Expected {MODEL_FEATURE_COUNT} model features, got {len(FEATURE_NAMES)}")
    if FEATURE_NAMES[:10] != [
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
    ]:
        raise ValueError("First 10 feature names do not match Dataset V3.")
    if FEATURE_NAMES[-8:] != REGIME_FEATURE_NAMES:
        raise ValueError("Last 8 feature names do not match Regime V3.")
    metadata_inside_features = sorted(set(METADATA_COLUMNS).intersection(FEATURE_NAMES))
    if metadata_inside_features:
        raise ValueError(f"Metadata columns leaked into model features: {metadata_inside_features}")
    if df.duplicated(subset=["symbol", "sample_date"]).any():
        duplicate_count = int(df.duplicated(subset=["symbol", "sample_date"]).sum())
        raise ValueError(f"Found {duplicate_count} duplicate symbol + sample_date rows.")
    feature_values = df[FEATURE_NAMES].to_numpy(dtype=np.float32, copy=False)
    if np.isnan(feature_values).any():
        raise ValueError("NaN values found in latest snapshot features.")
    if np.isinf(feature_values).any():
        raise ValueError("Infinite values found in latest snapshot features.")


def build_metadata(
    *,
    df: pd.DataFrame,
    readiness: dict[str, Any],
    expected_symbol_count: int,
    skipped_symbols: list[dict[str, str]],
) -> dict[str, Any]:
    sample_date = str(df["sample_date"].iloc[0])
    return {
        "dataset_version": DATASET_VERSION,
        "parent_dataset_version": PARENT_DATASET_VERSION,
        "split_reference_version": SPLIT_REFERENCE_VERSION,
        "feature_count": MODEL_FEATURE_COUNT,
        "technical_feature_count": TECHNICAL_FEATURE_COUNT,
        "regime_feature_count": REGIME_FEATURE_COUNT,
        "row_count": int(len(df)),
        "expected_symbol_count": int(expected_symbol_count),
        "skipped_symbol_count": int(len(skipped_symbols)),
        "skipped_symbols": skipped_symbols,
        "sample_date": sample_date,
        "latest_ohlcv_date": readiness.get("latest_ohlcv_date") or sample_date,
        "validation_trading_days": int(readiness.get("validation_trading_days") or 0),
        "validation_start_date": readiness.get("validation_start_date"),
        "expected_latest_candle_date": readiness.get("expected_latest_candle_date"),
        "latest_stored_candle_date": readiness.get("latest_stored_candle_date") or readiness.get("latest_ohlcv_date"),
        "mapped_symbols": int(readiness.get("mapped_symbols") or 0),
        "zero_candle_symbols": int(readiness.get("zero_candle_symbols") or 0),
        "stale_symbols": int(readiness.get("stale_symbols") or 0),
        "missing_recent_symbol_dates": int(readiness.get("missing_recent_symbol_dates") or 0),
        "latest_ohlcv_run_status": readiness.get("latest_ohlcv_run_status") or "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matsya_readiness_status": readiness.get("status", "unknown"),
        "duplicate_count": int(readiness.get("duplicate_count") or 0),
        "null_count": int(readiness.get("null_count") or 0),
        "null_ohlcv_count": int(readiness.get("null_ohlcv_count") or readiness.get("null_count") or 0),
        "bad_ohlc_count": int(readiness.get("bad_ohlc_count") or 0),
        "negative_volume_count": int(readiness.get("negative_volume_count") or 0),
        "first_10_feature_names": FEATURE_NAMES[:10],
        "last_8_feature_names": FEATURE_NAMES[-8:],
        "notes": NOTES,
    }


def relative_price(value: float, entry_close: float) -> float:
    if entry_close == 0:
        return 0.0
    return value / entry_close - 1.0


def _validate_readiness(readiness: dict[str, Any]) -> None:
    reasons: list[str] = []
    if readiness.get("status") != "ready":
        reasons.append("Matsya readiness is not ready.")
    if not readiness.get("latest_ohlcv_date"):
        reasons.append("Latest trading date is not finalized.")
    if (
        (readiness.get("expected_latest_candle_date") or readiness.get("expected_latest_ohlcv_date"))
        and readiness.get("latest_ohlcv_date")
        and readiness.get("latest_ohlcv_date") != (readiness.get("expected_latest_candle_date") or readiness.get("expected_latest_ohlcv_date"))
    ):
        reasons.append("Latest trading date is not finalized.")
    if int(readiness.get("duplicate_count") or 0) != 0:
        reasons.append("Duplicate OHLCV rows exist.")
    if int(readiness.get("null_count") or 0) != 0:
        reasons.append("Null OHLCV rows exist.")
    if int(readiness.get("bad_ohlc_count") or 0) != 0:
        reasons.append("Bad OHLC rows exist.")
    if int(readiness.get("negative_volume_count") or 0) != 0:
        reasons.append("Negative volume rows exist.")
    if int(readiness.get("mapped_symbols") or readiness.get("expected_symbol_count") or 0) <= 0:
        reasons.append("No mapped symbols are available.")
    if int(readiness.get("zero_candle_symbols") or 0) != 0:
        reasons.append("Mapped symbols have no OHLCV candles.")
    if int(readiness.get("stale_symbols") or 0) != 0:
        reasons.append("Mapped symbols have stale OHLCV candles.")
    if int(readiness.get("missing_recent_symbol_dates") or 0) != 0:
        reasons.append("Mapped symbols are missing recent completed trading dates.")
    if readiness.get("latest_ohlcv_run_status") not in {"completed", "up_to_date"}:
        reasons.append("Latest OHLCV run status is not completed or up_to_date.")
    if reasons:
        raise MatsyaSnapshotReadinessError(" ".join(reasons))


def _validate_raw_candle(candle: dict[str, Any], *, symbol: str, index: int) -> None:
    for field in ("open", "high", "low", "close", "volume"):
        _finite_float(candle.get(field), f"{symbol} c{index:02d} {field}")
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])
    volume = float(candle["volume"])
    if high < low or close < low or close > high:
        raise ValueError(f"Bad OHLC values for {symbol} c{index:02d}")
    if volume < 0:
        raise ValueError(f"Negative volume for {symbol} c{index:02d}")


def _finite_float(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} is not numeric")
    numeric = float(value)
    if math.isnan(numeric) or math.isinf(numeric):
        raise ValueError(f"{label} is NaN or infinite")
    return numeric


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isnan(float(value)) and not math.isinf(float(value))


def _atomic_write_csv(df: pd.DataFrame, output_path: Path) -> None:
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        df.to_csv(temp_path, index=False, quoting=csv.QUOTE_MINIMAL)
        os.replace(temp_path, output_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _atomic_write_json(payload: dict[str, Any], output_path: Path) -> None:
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp_path, output_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _one(cursor: Any) -> dict[str, Any] | None:
    rows = _all(cursor)
    return rows[0] if rows else None


def _all(cursor: Any) -> list[dict[str, Any]]:
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row, strict=False)) for row in cursor.fetchall()]


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
