from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VirtualDemoSignal:
    symbol: str
    security_id: str
    sample_date: str
    kurma_probability: float
    varaha_probability: float
    close_price: float | None = None
    source_report_path: str = ""
    model_versions: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_virtual_demo_signals(path: str | Path) -> list[VirtualDemoSignal]:
    source_path = Path(path)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid virtual demo signal JSON: {exc.msg}") from exc
    records = payload.get("signals") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Virtual demo signal payload must be a JSON list or an object with a signals list")
    return [parse_virtual_demo_signal(record, default_source_path=str(source_path)) for record in records]


def parse_virtual_demo_signal(record: dict[str, Any], *, default_source_path: str = "") -> VirtualDemoSignal:
    if not isinstance(record, dict):
        raise ValueError("Virtual demo signal must be a JSON object")
    symbol = _required_text(record, "symbol")
    security_id = _required_text(record, "security_id")
    sample_date = _required_text(record, "sample_date")
    try:
        date.fromisoformat(sample_date)
    except ValueError as exc:
        raise ValueError("sample_date must be an ISO date") from exc

    close_price = record.get("close_price")
    parsed_close_price = None if close_price is None else _finite_positive_number(close_price, "close_price")
    model_versions = record.get("model_versions")
    if model_versions is not None:
        if not isinstance(model_versions, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in model_versions.items()
        ):
            raise ValueError("model_versions must be an object with string keys and values")

    return VirtualDemoSignal(
        symbol=symbol,
        security_id=security_id,
        sample_date=sample_date,
        kurma_probability=_probability(record.get("kurma_probability"), "kurma_probability"),
        varaha_probability=_probability(record.get("varaha_probability"), "varaha_probability"),
        close_price=parsed_close_price,
        source_report_path=str(record.get("source_report_path") or default_source_path),
        model_versions=model_versions,
    )


def _required_text(record: dict[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _probability(value: Any, field_name: str) -> float:
    if not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    probability = float(value)
    if probability < 0 or probability > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return probability


def _finite_positive_number(value: Any, field_name: str) -> float:
    if not isinstance(value, (int, float)) or not isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"{field_name} must be a finite positive number")
    return float(value)
