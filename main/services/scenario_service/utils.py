# services/scenario_service/utils.py

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_nested_value(payload: dict[str, Any], field_path: str) -> Any:
    current: Any = payload
    for token in field_path.split("."):
        if not isinstance(current, dict) or token not in current:
            return None
        current = current[token]
    return current


def set_nested_value(payload: dict[str, Any], field_path: str, value: Any) -> None:
    tokens = field_path.split(".")
    current = payload

    for token in tokens[:-1]:
        next_value = current.get(token)
        if not isinstance(next_value, dict):
            next_value = {}
            current[token] = next_value
        current = next_value

    current[tokens[-1]] = value


def clone_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(payload)


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_scenario_key(label: str) -> str:
    return label.strip().lower().replace("-", "_").replace(" ", "_")