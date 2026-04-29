# services/normalization_service/utils.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1", "present"}:
            return True
        if lowered in {"false", "no", "n", "0", "absent"}:
            return False

    if isinstance(value, (int, float)):
        return bool(value)

    return None


def build_followup_question(
    *,
    question_id: str,
    field_path: str,
    reason: str,
    suggested_sources: list[str],
    severity: str = "HIGH",
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "question_id": question_id,
        "field_path": field_path,
        "reason": reason,
        "suggested_sources": list(suggested_sources),
        "severity": severity,
    }
    if extra_fields:
        payload.update(extra_fields)
    return payload


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