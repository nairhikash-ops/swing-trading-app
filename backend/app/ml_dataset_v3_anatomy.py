import math
from typing import Mapping, Any

def calculate_candle_anatomy(candle: Mapping[str, Any]) -> dict[str, float]:
    required_keys = ["open_rel", "high_rel", "low_rel", "close_rel"]
    for k in required_keys:
        if k not in candle:
            raise ValueError(f"Missing required field: {k}")
        val = candle[k]
        # Allow ints and floats, but exclude booleans which are a subclass of int
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise ValueError(f"Value for {k} is not numeric")
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Value for {k} is NaN or infinite")

    open_rel = float(candle["open_rel"])
    high_rel = float(candle["high_rel"])
    low_rel = float(candle["low_rel"])
    close_rel = float(candle["close_rel"])

    range_value = high_rel - low_rel

    if range_value < 0:
        raise ValueError("Range value cannot be negative")

    if range_value == 0.0:
        return {
            "body_to_range": 0.0,
            "upper_wick_to_range": 0.0,
            "lower_wick_to_range": 0.0,
            "close_position_in_range": 0.5,
            "signed_body_to_range": 0.0,
        }

    body_to_range = abs(close_rel - open_rel) / range_value
    upper_wick_to_range = (high_rel - max(open_rel, close_rel)) / range_value
    lower_wick_to_range = (min(open_rel, close_rel) - low_rel) / range_value
    close_position_in_range = (close_rel - low_rel) / range_value
    signed_body_to_range = (close_rel - open_rel) / range_value

    return {
        "body_to_range": float(body_to_range),
        "upper_wick_to_range": float(upper_wick_to_range),
        "lower_wick_to_range": float(lower_wick_to_range),
        "close_position_in_range": float(close_position_in_range),
        "signed_body_to_range": float(signed_body_to_range),
    }

def add_candle_anatomy_features(candle: Mapping[str, Any]) -> dict[str, Any]:
    anatomy = calculate_candle_anatomy(candle)
    result = dict(candle)
    result.update(anatomy)
    return result
