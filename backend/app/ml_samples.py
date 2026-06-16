import json
from collections import Counter
from typing import Any

from app.config import Settings
from app.data_quality import DataQualityService
from app.ml_foundation import (
    ML_FUTURE_WINDOW_SESSIONS,
    ML_INPUT_WINDOW_SESSIONS,
    ML_LABEL_NAME,
    ML_MODEL_NAME,
    ML_STOP_PERCENT,
    ML_TARGET_PERCENT,
)
from app.store import TokenStore
from app.timezone import now_utc


TRAINABLE_OUTCOMES = {"WIN", "LOSS", "TIMEOUT"}
AMBIGUOUS_EXCLUDE_REASON = "both_barriers_touched_same_daily_candle"
INSUFFICIENT_FUTURE_EXCLUDE_REASON = "insufficient_future_candles"


class MLSampleStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ml_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT NOT NULL,
                    label_name TEXT NOT NULL,
                    instrument_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    sample_date TEXT NOT NULL,
                    input_window_start TEXT NOT NULL,
                    input_window_end TEXT NOT NULL,
                    future_window_start TEXT,
                    future_window_end TEXT,
                    entry_close REAL NOT NULL,
                    target_price REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    trainable INTEGER NOT NULL DEFAULT 0,
                    exclude_reason TEXT NOT NULL DEFAULT '',
                    barrier_hit_date TEXT,
                    barrier_hit_type TEXT NOT NULL DEFAULT '',
                    days_to_outcome INTEGER,
                    feature_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(model_name, label_name, instrument_id, sample_date)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_samples_symbol_date ON ml_samples(symbol, sample_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_samples_outcome ON ml_samples(outcome, trainable)")

    def resolve_symbol(self, symbol: str) -> dict[str, Any] | None:
        normalized_symbol = symbol.strip().upper()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM instruments
                WHERE active = 1
                  AND exchange_id = 'NSE'
                  AND segment = 'E'
                  AND UPPER(underlying_symbol) = ?
                ORDER BY
                  CASE WHEN instrument = 'EQUITY' THEN 0 ELSE 1 END,
                  CASE WHEN series = 'EQ' THEN 0 ELSE 1 END,
                  id
                LIMIT 1
                """,
                (normalized_symbol,),
            ).fetchone()
        return dict(row) if row else None

    def candles_for_instrument(self, instrument_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM daily_candles
                WHERE instrument_id = ?
                ORDER BY trading_date ASC
                """,
                (instrument_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_sample(self, sample: dict[str, Any]) -> str:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM ml_samples
                WHERE model_name = ?
                  AND label_name = ?
                  AND instrument_id = ?
                  AND sample_date = ?
                """,
                (
                    sample["model_name"],
                    sample["label_name"],
                    sample["instrument_id"],
                    sample["sample_date"],
                ),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO ml_samples (
                    model_name, label_name, instrument_id, symbol, sample_date,
                    input_window_start, input_window_end, future_window_start, future_window_end,
                    entry_close, target_price, stop_price, outcome, trainable, exclude_reason,
                    barrier_hit_date, barrier_hit_type, days_to_outcome, feature_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_name, label_name, instrument_id, sample_date) DO UPDATE SET
                    symbol = excluded.symbol,
                    input_window_start = excluded.input_window_start,
                    input_window_end = excluded.input_window_end,
                    future_window_start = excluded.future_window_start,
                    future_window_end = excluded.future_window_end,
                    entry_close = excluded.entry_close,
                    target_price = excluded.target_price,
                    stop_price = excluded.stop_price,
                    outcome = excluded.outcome,
                    trainable = excluded.trainable,
                    exclude_reason = excluded.exclude_reason,
                    barrier_hit_date = excluded.barrier_hit_date,
                    barrier_hit_type = excluded.barrier_hit_type,
                    days_to_outcome = excluded.days_to_outcome,
                    feature_json = excluded.feature_json,
                    updated_at = excluded.updated_at
                """,
                (
                    sample["model_name"],
                    sample["label_name"],
                    sample["instrument_id"],
                    sample["symbol"],
                    sample["sample_date"],
                    sample["input_window_start"],
                    sample["input_window_end"],
                    sample["future_window_start"],
                    sample["future_window_end"],
                    sample["entry_close"],
                    sample["target_price"],
                    sample["stop_price"],
                    sample["outcome"],
                    1 if sample["trainable"] else 0,
                    sample["exclude_reason"],
                    sample["barrier_hit_date"],
                    sample["barrier_hit_type"],
                    sample["days_to_outcome"],
                    json.dumps(sample["feature"], sort_keys=True),
                    timestamp if existing is None else sample.get("created_at", timestamp),
                    timestamp,
                ),
            )
        return "created" if existing is None else "updated"

    def sample_for_date(self, instrument_id: int, sample_date: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM ml_samples
                WHERE model_name = ?
                  AND label_name = ?
                  AND instrument_id = ?
                  AND sample_date = ?
                """,
                (ML_MODEL_NAME, ML_LABEL_NAME, instrument_id, sample_date),
            ).fetchone()
        return sample_row_to_dict(row) if row else None

    def sample_exists(self, model_name: str, label_name: str, instrument_id: int, sample_date: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM ml_samples
                WHERE model_name = ?
                  AND label_name = ?
                  AND instrument_id = ?
                  AND sample_date = ?
                """,
                (model_name, label_name, instrument_id, sample_date),
            ).fetchone()
        return row is not None

    def sample_count_for_instrument(self, instrument_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM ml_samples
                WHERE model_name = ?
                  AND label_name = ?
                  AND instrument_id = ?
                """,
                (ML_MODEL_NAME, ML_LABEL_NAME, instrument_id),
            ).fetchone()
        return int(row["count"] if row else 0)


class MLSampleService:
    def __init__(self, settings: Settings, store: MLSampleStore) -> None:
        self.settings = settings
        self.store = store
        self.quality_service = DataQualityService(settings=settings, token_store=store.token_store)

    def _enforce_healthy_quality_gate(self, symbol: str) -> None:
        report = self.quality_service.report(status_filter="exceptions", limit=500)
        historical_run_id = report.get("historical_run_id")
        if not historical_run_id:
            raise ValueError("historical_run_id is missing from data quality report")

        for item in report.get("items", []):
            if str(item.get("symbol", "")).upper() == symbol:
                raise ValueError(f"Symbol {symbol} failed quality gate: {item['quality_status']} - {item['issues']}")

        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM historical_fetch_items WHERE run_id = ? AND UPPER(symbol) = ?",
                (historical_run_id, symbol),
            ).fetchone()
            if not row:
                raise ValueError(f"Symbol {symbol} not found in historical_fetch_items for run {historical_run_id}")

    def generate_one(
        self,
        symbol: str = "RELIANCE",
        lookback_sessions: int = ML_INPUT_WINDOW_SESSIONS,
        future_window_sessions: int = ML_FUTURE_WINDOW_SESSIONS,
        target_percent: float = ML_TARGET_PERCENT,
        stop_percent: float = ML_STOP_PERCENT,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        normalized_symbol = symbol.strip().upper() or "RELIANCE"
        if lookback_sessions != ML_INPUT_WINDOW_SESSIONS:
            raise ValueError("ML-1 only supports the 60-session V1 input window.")
        if future_window_sessions != ML_FUTURE_WINDOW_SESSIONS:
            raise ValueError("ML-1 only supports the 20-session V1 future window.")

        instrument = self.store.resolve_symbol(normalized_symbol)
        if instrument is None:
            raise ValueError(f"No active NSE equity instrument found for symbol {normalized_symbol}.")

        self._enforce_healthy_quality_gate(normalized_symbol)

        candles = self.store.candles_for_instrument(int(instrument["id"]))
        created = 0
        updated = 0
        generated_samples: list[dict[str, Any]] = []
        for sample_index in range(lookback_sessions - 1, len(candles)):
            input_window = candles[sample_index - lookback_sessions + 1 : sample_index + 1]
            future_window = candles[sample_index + 1 : sample_index + 1 + future_window_sessions]
            sample = build_sample(
                instrument=instrument,
                input_window=input_window,
                future_window=future_window,
                target_percent=target_percent,
                stop_percent=stop_percent,
                future_window_sessions=future_window_sessions,
            )
            if dry_run:
                exists = self.store.sample_exists(
                    model_name=sample["model_name"],
                    label_name=sample["label_name"],
                    instrument_id=sample["instrument_id"],
                    sample_date=sample["sample_date"],
                )
                action = "updated" if exists else "created"
            else:
                action = self.store.upsert_sample(sample)
            if action == "created":
                created += 1
            else:
                updated += 1
            generated_samples.append(sample)

        outcome_counts = Counter(sample["outcome"] for sample in generated_samples)
        trainable_count = sum(1 for sample in generated_samples if sample["trainable"])
        ambiguous_count = outcome_counts.get("AMBIGUOUS", 0)
        return {
            "symbol": normalized_symbol,
            "instrument_id": int(instrument["id"]),
            "candles_available": len(candles),
            "samples_created": created,
            "samples_updated": updated,
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "trainable_count": trainable_count,
            "ambiguous_count": ambiguous_count,
            "first_sample_date": generated_samples[0]["sample_date"] if generated_samples else None,
            "last_sample_date": generated_samples[-1]["sample_date"] if generated_samples else None,
        }

    def generate_batch(self, symbols: list[str], dry_run: bool = True) -> dict[str, Any]:
        if not symbols:
            raise ValueError("No symbols provided for batch generation.")
        if len(symbols) > 5:
            raise ValueError("Maximum of 5 symbols allowed per batch request.")

        unique_symbols = set()
        for symbol in symbols:
            normalized = symbol.strip().upper()
            if not normalized:
                raise ValueError("Blank or whitespace-only symbol found in request.")
            if normalized in unique_symbols:
                raise ValueError(f"Duplicate symbol found in request: {normalized}")
            unique_symbols.add(normalized)

        results = []
        errors = []

        created = 0
        updated = 0
        trainable = 0

        for symbol in symbols:
            try:
                res = self.generate_one(symbol=symbol, dry_run=dry_run)
                results.append(res)
                created += res["samples_created"]
                updated += res["samples_updated"]
                trainable += res["trainable_count"]
            except ValueError as e:
                errors.append({"symbol": symbol, "error": str(e)})

        return {
            "symbols_requested": len(symbols),
            "symbols_processed": len(results),
            "symbols_failed": len(errors),
            "total_samples_created": created,
            "total_samples_updated": updated,
            "total_trainable_count": trainable,
            "dry_run": dry_run,
            "results": results,
            "errors": errors,
        }


def build_sample(
    instrument: dict[str, Any],
    input_window: list[dict[str, Any]],
    future_window: list[dict[str, Any]],
    target_percent: float,
    stop_percent: float,
    future_window_sessions: int,
) -> dict[str, Any]:
    entry_candle = input_window[-1]
    entry_close = float(entry_candle["close"])
    target_price = entry_close * (1 + target_percent / 100.0)
    stop_price = entry_close * (1 - stop_percent / 100.0)
    outcome_data = classify_outcome(
        future_window=future_window,
        future_window_sessions=future_window_sessions,
        target_price=target_price,
        stop_price=stop_price,
    )
    future_window_start = future_window[0]["trading_date"] if future_window else None
    future_window_end = (
        future_window[min(len(future_window), future_window_sessions) - 1]["trading_date"] if future_window else None
    )
    outcome = outcome_data["outcome"]
    return {
        "model_name": ML_MODEL_NAME,
        "label_name": ML_LABEL_NAME,
        "instrument_id": int(instrument["id"]),
        "symbol": str(instrument["underlying_symbol"]).upper(),
        "sample_date": entry_candle["trading_date"],
        "input_window_start": input_window[0]["trading_date"],
        "input_window_end": entry_candle["trading_date"],
        "future_window_start": future_window_start,
        "future_window_end": future_window_end,
        "entry_close": entry_close,
        "target_price": target_price,
        "stop_price": stop_price,
        "outcome": outcome,
        "trainable": outcome in TRAINABLE_OUTCOMES,
        "exclude_reason": outcome_data["exclude_reason"],
        "barrier_hit_date": outcome_data["barrier_hit_date"],
        "barrier_hit_type": outcome_data["barrier_hit_type"],
        "days_to_outcome": outcome_data["days_to_outcome"],
        "feature": build_feature_snapshot(
            instrument=instrument,
            input_window=input_window,
            entry_close=entry_close,
            target_percent=target_percent,
            stop_percent=stop_percent,
            future_window_sessions=future_window_sessions,
        ),
    }


def classify_outcome(
    future_window: list[dict[str, Any]],
    future_window_sessions: int,
    target_price: float,
    stop_price: float,
) -> dict[str, Any]:
    if len(future_window) < future_window_sessions:
        return {
            "outcome": "INSUFFICIENT_FUTURE_DATA",
            "exclude_reason": INSUFFICIENT_FUTURE_EXCLUDE_REASON,
            "barrier_hit_date": None,
            "barrier_hit_type": "",
            "days_to_outcome": None,
        }

    for offset, candle in enumerate(future_window[:future_window_sessions], start=1):
        hit_target = float(candle["high"]) >= target_price
        hit_stop = float(candle["low"]) <= stop_price
        if hit_target and hit_stop:
            return {
                "outcome": "AMBIGUOUS",
                "exclude_reason": AMBIGUOUS_EXCLUDE_REASON,
                "barrier_hit_date": candle["trading_date"],
                "barrier_hit_type": "both",
                "days_to_outcome": offset,
            }
        if hit_target:
            return {
                "outcome": "WIN",
                "exclude_reason": "",
                "barrier_hit_date": candle["trading_date"],
                "barrier_hit_type": "target",
                "days_to_outcome": offset,
            }
        if hit_stop:
            return {
                "outcome": "LOSS",
                "exclude_reason": "",
                "barrier_hit_date": candle["trading_date"],
                "barrier_hit_type": "stop",
                "days_to_outcome": offset,
            }
    return {
        "outcome": "TIMEOUT",
        "exclude_reason": "",
        "barrier_hit_date": None,
        "barrier_hit_type": "",
        "days_to_outcome": future_window_sessions,
    }


def build_feature_snapshot(
    instrument: dict[str, Any],
    input_window: list[dict[str, Any]],
    entry_close: float,
    target_percent: float,
    stop_percent: float,
    future_window_sessions: int,
) -> dict[str, Any]:
    average_volume = sum(float(candle["volume"]) for candle in input_window) / len(input_window)
    candles = []
    for candle in input_window:
        volume = float(candle["volume"])
        candles.append(
            {
                "trading_date": candle["trading_date"],
                "open_rel": relative_price(float(candle["open"]), entry_close),
                "high_rel": relative_price(float(candle["high"]), entry_close),
                "low_rel": relative_price(float(candle["low"]), entry_close),
                "close_rel": relative_price(float(candle["close"]), entry_close),
                "volume_rel": 0.0 if average_volume == 0 else volume / average_volume - 1.0,
            }
        )
    return {
        "symbol": str(instrument["underlying_symbol"]).upper(),
        "instrument_id": int(instrument["id"]),
        "sample_date": input_window[-1]["trading_date"],
        "entry_close": entry_close,
        "input_window_sessions": len(input_window),
        "future_window_sessions": future_window_sessions,
        "target_percent": target_percent,
        "stop_percent": stop_percent,
        "candles": candles,
    }


def relative_price(value: float, entry_close: float) -> float:
    if entry_close == 0:
        return 0.0
    return value / entry_close - 1.0


def sample_row_to_dict(row) -> dict[str, Any]:
    data = dict(row)
    data["trainable"] = bool(data["trainable"])
    data["feature"] = json.loads(data.pop("feature_json") or "{}")
    return data
