from __future__ import annotations

from typing import Any, Callable


def coerce_dict_list(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def is_terminal_record(record: dict[str, Any]) -> bool:
    status = str(record.get("status", "")).strip().upper()
    return status in {"CONFIRMED", "ACCEPTED", "RESOLVED"}


def build_field_record_lookup(
    field_records: list[dict[str, Any]],
    normalize_field_path: Callable[[Any], str],
) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}
    for record in field_records:
        normalized = normalize_field_path(record.get("field_path"))
        if not normalized:
            continue
        lookup.setdefault(normalized, []).append(record)
    return lookup


def build_review_flag_lookup(
    review_flags: list[dict[str, Any]],
    normalize_field_path: Callable[[Any], str],
) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = {}
    for flag in review_flags:
        normalized = normalize_field_path(flag.get("field_path"))
        if not normalized:
            continue
        category = str(flag.get("category", "")).strip()
        if not category:
            continue
        lookup.setdefault(normalized, []).append(category)
    return lookup


def build_candidate_lookup(
    candidates: list[Any],
    normalize_field_path: Callable[[Any], str],
) -> dict[str, list[Any]]:
    lookup: dict[str, list[Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        normalized = normalize_field_path(candidate.get("field_path"))
        if not normalized:
            continue
        lookup.setdefault(normalized, []).append(candidate)
    return lookup


def determine_resolution_reason(
    *,
    field_path: str,
    record_lookup: dict[str, list[dict[str, Any]]],
    review_flag_lookup: dict[str, list[str]],
    candidate_lookup: dict[str, list[Any]],
) -> str | None:
    review_categories = {str(item).strip().lower() for item in review_flag_lookup.get(field_path, [])}
    if "conflicting" in review_categories:
        return "conflicting"
    if "review_required" in review_categories or "review-required" in review_categories:
        return "review_required"

    records = record_lookup.get(field_path, [])
    if records:
        if any(not is_terminal_record(record) for record in records):
            return "review_required"
        if any(str(record.get("confidence", "")).strip().upper() == "LOW" for record in records):
            return "low_confidence"
        return None

    candidates = candidate_lookup.get(field_path, [])
    if candidates:
        return "candidate_confirmation"

    return "missing"


def infer_triggering_status(
    field_path: str,
    record_lookup: dict[str, list[dict[str, Any]]],
) -> str:
    records = record_lookup.get(field_path, [])
    if not records:
        return "MISSING"
    if any(not is_terminal_record(record) for record in records):
        return "REVIEW_REQUIRED"
    if any(str(record.get("confidence", "")).strip().upper() == "LOW" for record in records):
        return "LOW_CONFIDENCE"
    return "CONFIRMED"


def collect_related_artifact_ids(
    field_path: str,
    record_lookup: dict[str, list[dict[str, Any]]],
    candidate_lookup: dict[str, list[Any]],
) -> list[str]:
    artifact_ids: list[str] = []
    for record in record_lookup.get(field_path, []):
        artifact_id = record.get("artifact_id") or record.get("source_artifact_id")
        if artifact_id is not None:
            artifact_ids.append(str(artifact_id))
    for candidate in candidate_lookup.get(field_path, []):
        artifact_id = candidate.get("source_artifact_id")
        if artifact_id is not None:
            artifact_ids.append(str(artifact_id))
    return artifact_ids
