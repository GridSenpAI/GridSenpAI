from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False, default=str)


def canonical_state_path(run_dir: Path) -> Path:
    return run_dir / "state" / "canonical_facility_state.json"


def pipeline_summary_path(run_dir: Path) -> Path:
    return run_dir / "pipeline_summary.json"


def load_canonical_state(run_dir: Path) -> dict[str, Any]:
    payload = read_json(canonical_state_path(run_dir), default={})
    if not isinstance(payload, dict):
        return {}
    return payload


def load_pipeline_summary(run_dir: Path) -> dict[str, Any]:
    payload = read_json(pipeline_summary_path(run_dir), default={})
    if not isinstance(payload, dict):
        return {}
    return payload


def value_fingerprint(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return repr(value)


def build_field_index(field_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in field_records:
        if not isinstance(record, dict):
            continue
        field_path = str(record.get("field_path", "")).strip()
        if not field_path:
            continue
        existing = index.get(field_path)
        if existing is None:
            index[field_path] = {
                "value": record.get("value"),
                "record_ids": [str(record.get("field_record_id", ""))],
                "records": [record],
            }
            continue

        existing["record_ids"].append(str(record.get("field_record_id", "")))
        existing["records"].append(record)

        current_value = existing.get("value")
        candidate_value = record.get("value")
        if value_fingerprint(candidate_value) > value_fingerprint(current_value):
            existing["value"] = candidate_value
    return index


def build_conflict_index(conflict_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in conflict_records:
        if not isinstance(record, dict):
            continue
        field_path = str(record.get("field_path", "")).strip()
        conflict_id = str(record.get("conflict_id", "")).strip()
        key = field_path or conflict_id
        if not key:
            continue
        index[key] = record
    return index


def build_review_flag_index(review_flags: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in review_flags:
        if not isinstance(record, dict):
            continue
        review_flag_id = str(record.get("review_flag_id", "")).strip()
        if not review_flag_id:
            continue
        index[review_flag_id] = record
    return index