import csv
import json
import math
import os
from collections import defaultdict
from typing import Any

from app.config import Settings
from app.ml_foundation import ML_LABEL_NAME, ML_MODEL_NAME
from app.store import TokenStore
from app.ml_dataset_v3_anatomy import calculate_candle_anatomy

REQUIRED_KEYS = {"open_rel", "high_rel", "low_rel", "close_rel", "volume_rel"}
ORDERED_REQUIRED_KEYS = ["open_rel", "high_rel", "low_rel", "close_rel", "volume_rel"]
ALLOWED_KEYS = frozenset(REQUIRED_KEYS.union({"trading_date"}))
DEFAULT_OUTPUT_PATH = "/app/data/exports/ml_dataset_ohlcv_v3.csv"

def export_ml_dataset_v3(output_path: str | None = None, settings: Settings | None = None) -> dict[str, Any]:
    if settings is None:
        settings = Settings()

    if output_path is None:
        output_path = DEFAULT_OUTPUT_PATH

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    temp_output_path = output_path + ".tmp"

    token_store = TokenStore(settings.database_path)

    total_rows = 0
    rows_by_symbol: dict[str, int] = defaultdict(int)
    rows_by_outcome: dict[str, int] = defaultdict(int)
    null_count = 0
    duplicate_sample_count = 0
    seen_samples: set[tuple[str, str]] = set()

    metadata_cols = ["symbol", "sample_date", "outcome"]
    feature_cols = []
    
    anatomy_keys = [
        "body_to_range",
        "upper_wick_to_range",
        "lower_wick_to_range",
        "close_position_in_range",
        "signed_body_to_range",
    ]
    
    for i in range(60):
        prefix = f"c{i:02d}_"
        feature_cols.extend([
            f"{prefix}open_rel",
            f"{prefix}high_rel",
            f"{prefix}low_rel",
            f"{prefix}close_rel",
            f"{prefix}volume_rel",
            f"{prefix}body_to_range",
            f"{prefix}upper_wick_to_range",
            f"{prefix}lower_wick_to_range",
            f"{prefix}close_position_in_range",
            f"{prefix}signed_body_to_range",
        ])

    all_cols = metadata_cols + feature_cols

    with token_store._connect() as conn:
        query = """
            SELECT symbol, sample_date, outcome, feature_json
            FROM ml_samples
            WHERE model_name = ?
              AND label_name = ?
              AND trainable = 1
              AND outcome NOT IN ('AMBIGUOUS', 'INSUFFICIENT_FUTURE_DATA')
            ORDER BY sample_date ASC
        """
        rows = conn.execute(query, (ML_MODEL_NAME, ML_LABEL_NAME)).fetchall()

        try:
            with open(temp_output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=all_cols)
                writer.writeheader()

                for row in rows:
                    symbol = row["symbol"]
                    sample_date = row["sample_date"]
                    outcome = row["outcome"]
                    feature_json_str = row["feature_json"]

                    if (symbol, sample_date) in seen_samples:
                        duplicate_sample_count += 1
                    seen_samples.add((symbol, sample_date))

                    try:
                        feature = json.loads(feature_json_str)
                    except Exception as e:
                        raise ValueError(f"Invalid JSON in row {symbol} {sample_date}: {e}")

                    if not isinstance(feature, dict):
                        raise ValueError(f"Feature JSON is not a dict for {symbol} {sample_date}")

                    candles = feature.get("candles")
                    if not isinstance(candles, list):
                        raise ValueError(f"Missing or invalid 'candles' array for {symbol} {sample_date}")

                    if len(candles) != 60:
                        raise ValueError(f"Invalid window length {len(candles)} (expected 60) for {symbol} {sample_date}")

                    csv_row = {
                        "symbol": symbol,
                        "sample_date": sample_date,
                        "outcome": outcome,
                    }

                    for i, candle in enumerate(candles):
                        if not isinstance(candle, dict):
                            raise ValueError(f"Candle {i} is not a dict for {symbol} {sample_date}")

                        keys = set(candle.keys())
                        if not REQUIRED_KEYS.issubset(keys):
                            raise ValueError(f"Missing required keys in candle {i} for {symbol} {sample_date}")

                        if not keys.issubset(ALLOWED_KEYS):
                            extra = keys - ALLOWED_KEYS
                            raise ValueError(f"Forbidden extra keys {extra} in candle {i} for {symbol} {sample_date}")

                        prefix = f"c{i:02d}_"
                        
                        # Add raw required keys
                        for rk in ORDERED_REQUIRED_KEYS:
                            val = candle[rk]
                            if val is None or not isinstance(val, (int, float)) or isinstance(val, bool):
                                raise ValueError(f"Non-numeric value for {rk} in candle {i} for {symbol} {sample_date}")
                            if math.isnan(val) or math.isinf(val):
                                null_count += 1
                                raise ValueError(f"Null/NaN/Inf value for {rk} in candle {i} for {symbol} {sample_date}")
                            csv_row[f"{prefix}{rk}"] = val
                            
                        # Add anatomy features
                        anatomy = calculate_candle_anatomy(candle)
                        for ak in anatomy_keys:
                            val = anatomy[ak]
                            if val is None or math.isnan(val) or math.isinf(val):
                                null_count += 1
                                raise ValueError(f"Null/NaN/Inf value for anatomy {ak} in candle {i} for {symbol} {sample_date}")
                            csv_row[f"{prefix}{ak}"] = val

                    writer.writerow(csv_row)

                    total_rows += 1
                    rows_by_symbol[symbol] += 1
                    rows_by_outcome[outcome] += 1

            # If we get here, everything is successful
            os.replace(temp_output_path, output_path)

        except Exception as e:
            if os.path.exists(temp_output_path):
                os.remove(temp_output_path)
            raise e

    result = {
        "output_path": output_path,
        "row_count": total_rows,
        "feature_column_count": len(feature_cols),
        "total_column_count": len(all_cols),
        "label_counts": dict(rows_by_outcome),
        "symbol_counts": dict(rows_by_symbol),
        "null_count": null_count,
        "duplicate_sample_count": duplicate_sample_count,
    }
    
    if result["feature_column_count"] != 600:
        raise ValueError(f"Expected feature count to be exactly 600, got {result['feature_column_count']}")
    if result["total_column_count"] != 603:
        raise ValueError(f"Expected total column count to be exactly 603, got {result['total_column_count']}")
        
    return result


if __name__ == "__main__":
    print("Starting ML dataset v3 export...")
    res = export_ml_dataset_v3()
    print("\n=== Export Summary ===")
    print(f"Output Path:          {res['output_path']}")
    print(f"Row Count:            {res['row_count']}")
    print(f"Feature Column Count: {res['feature_column_count']}")
    print(f"Total Column Count:   {res['total_column_count']}")
    print(f"Null Count:           {res['null_count']}")
    print(f"Duplicates:           {res['duplicate_sample_count']}")
    print("\nLabel Counts:")
    for k, v in res['label_counts'].items():
        print(f"  {k}: {v}")
    print("\nSymbol Counts:")
    for k, v in res['symbol_counts'].items():
        print(f"  {k}: {v}")
