import json
from collections import defaultdict
from typing import Any

from app.config import Settings
from app.ml_foundation import ML_LABEL_NAME, ML_MODEL_NAME
from app.store import TokenStore

REQUIRED_KEYS = {"open_rel", "high_rel", "low_rel", "close_rel", "volume_rel"}
ALLOWED_KEYS = REQUIRED_KEYS.union({"trading_date"})


class MLDatasetService:
    def __init__(self, settings: Settings, token_store: TokenStore) -> None:
        self.settings = settings
        self.token_store = token_store

    def _connect(self):
        return self.token_store._connect()

    def inspect(self) -> dict[str, Any]:
        total_usable_rows = 0
        rows_by_symbol: dict[str, int] = defaultdict(int)
        rows_by_outcome: dict[str, int] = defaultdict(int)
        duplicate_sample_count = 0
        invalid_feature_json_count = 0
        invalid_window_length_count = 0
        missing_required_key_count = 0
        forbidden_feature_key_count = 0
        null_value_count = 0

        seen_samples: set[tuple[str, str]] = set()
        first_sample_date = None
        last_sample_date = None

        with self._connect() as conn:
            # Query all trainable samples avoiding AMBIGUOUS and INSUFFICIENT_FUTURE_DATA
            query = """
                SELECT symbol, sample_date, outcome, feature_json
                FROM ml_samples
                WHERE model_name = ?
                  AND label_name = ?
                  AND trainable = 1
                  AND outcome != 'AMBIGUOUS'
                  AND outcome != 'INSUFFICIENT_FUTURE_DATA'
                ORDER BY sample_date ASC
            """
            rows = conn.execute(query, (ML_MODEL_NAME, ML_LABEL_NAME)).fetchall()

            for row in rows:
                symbol = row["symbol"]
                sample_date = row["sample_date"]
                outcome = row["outcome"]
                feature_json_str = row["feature_json"]

                if (symbol, sample_date) in seen_samples:
                    duplicate_sample_count += 1
                seen_samples.add((symbol, sample_date))

                if first_sample_date is None or sample_date < first_sample_date:
                    first_sample_date = sample_date
                if last_sample_date is None or sample_date > last_sample_date:
                    last_sample_date = sample_date

                is_invalid_json = False
                is_invalid_length = False
                has_missing_keys = False
                has_forbidden_keys = False
                has_nulls = False

                candles = []
                try:
                    feature = json.loads(feature_json_str)
                    if isinstance(feature, dict):
                        candles = feature.get("candles")
                        if not isinstance(candles, list):
                            is_invalid_json = True
                    else:
                        is_invalid_json = True
                except Exception:
                    is_invalid_json = True

                if not is_invalid_json:
                    if len(candles) != 60:
                        is_invalid_length = True

                    for candle in candles:
                        if not isinstance(candle, dict):
                            is_invalid_json = True
                            break

                        keys = set(candle.keys())
                        if not REQUIRED_KEYS.issubset(keys):
                            has_missing_keys = True

                        if not keys.issubset(ALLOWED_KEYS):
                            has_forbidden_keys = True

                        for req_key in REQUIRED_KEYS:
                            if req_key in candle and candle[req_key] is None:
                                has_nulls = True
                            elif req_key not in candle:
                                # also covers null conceptually, though missing key flag handles it too
                                pass

                if is_invalid_json:
                    invalid_feature_json_count += 1
                if is_invalid_length:
                    invalid_window_length_count += 1
                if has_missing_keys:
                    missing_required_key_count += 1
                if has_forbidden_keys:
                    forbidden_feature_key_count += 1
                if has_nulls:
                    null_value_count += 1

                total_usable_rows += 1
                rows_by_symbol[symbol] += 1
                rows_by_outcome[outcome] += 1

        return {
            "total_usable_rows": total_usable_rows,
            "rows_by_symbol": dict(rows_by_symbol),
            "rows_by_outcome": dict(rows_by_outcome),
            "first_sample_date": first_sample_date,
            "last_sample_date": last_sample_date,
            "duplicate_sample_count": duplicate_sample_count,
            "invalid_feature_json_count": invalid_feature_json_count,
            "invalid_window_length_count": invalid_window_length_count,
            "missing_required_key_count": missing_required_key_count,
            "forbidden_feature_key_count": forbidden_feature_key_count,
            "null_value_count": null_value_count,
            "expected_feature_column_count": 300,
        }
