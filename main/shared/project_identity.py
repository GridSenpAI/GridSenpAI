from __future__ import annotations

"""Project identity resolution helpers for run/session metadata."""

import re
from typing import Any

_IDENTITY_KEY_HINTS = {
    "project_name": ("project_name", "project_title", "facility_name", "site_name", "project"),
    "project_number": ("project_number", "project_no", "application_number", "request_number", "queue_number"),
    "applicant": ("applicant", "applicant_name", "customer_name", "interconnection_customer", "project_sponsor", "developer", "legal_entity", "organization", "company"),
}
_BAD_IDENTITY_TOKENS = {"", "unknown", "unresolved", "n/a", "na", "none", "null", "gridsenpai"}
_ELECTRICAL_OWNERSHIP_TOKENS = (
    "owned high-side",
    "high-side",
    "low-side",
    "customer-owned",
    "utility-owned",
    "owner side",
    "ownership boundary",
    "owned transformer",
    "owned switchgear",
    "transformer",
    "breaker",
    "switchgear",
    "substation",
    "line side",
    "load side",
    "metering",
    "protection",
    "relay",
)


def clean_identity_text(value: Any) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).replace("\x00", " ").split())
    text = re.sub(r"\bPage\s+\d+\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+\s+of\s+\d+\b", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" -|,:;\t\r\n")[:160]


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_") or "unresolved_project"


def _looks_like_identity(value: str) -> bool:
    cleaned = clean_identity_text(value)
    if cleaned.casefold() in _BAD_IDENTITY_TOKENS or len(cleaned) < 3:
        return False
    if re.fullmatch(r"\d{1,3}", cleaned) or re.fullmatch(r"\d{1,2}/\d{4}", cleaned):
        return False
    if cleaned.casefold().startswith(("page ", "sheet ", "rev ", "revision ")):
        return False
    return True


def _looks_like_applicant_identity(value: str) -> bool:
    cleaned = clean_identity_text(value)
    if not _looks_like_identity(cleaned):
        return False
    lowered = cleaned.casefold()
    if any(token in lowered for token in _ELECTRICAL_OWNERSHIP_TOKENS):
        return False
    if re.search(r"\b(kv|mw|mva|amp|breaker|relay|transformer|switchgear|substation|feeder|meter)\b", lowered):
        return False
    return True


def _key_kind(key: str) -> str | None:
    normalized = key.replace("-", "_").replace(" ", "_").casefold()

    # Prefer exact matches across all identity families before attempting
    # substring matching.  Without this, broad hints such as "project" can
    # incorrectly classify "project_number" as a project name before the
    # project-number family is checked.
    exact_hints_by_kind: dict[str, set[str]] = {
        kind: {hint.replace(" ", "_").casefold() for hint in hints}
        for kind, hints in _IDENTITY_KEY_HINTS.items()
    }
    for kind, normalized_hints in exact_hints_by_kind.items():
        if normalized in normalized_hints:
            return kind

    # Substring matching is only for specific, non-generic hints.  Keep
    # generic labels such as "project" and "customer" from stealing more
    # precise fields like project_number or customer_project_number.
    generic_hints = {"project", "customer", "company", "owner"}
    for kind, normalized_hints in exact_hints_by_kind.items():
        for hint in normalized_hints:
            if hint in generic_hints or len(hint) < 8:
                continue
            if hint in normalized:
                return kind
    return None


def _walk(payload: Any, *, path: str = "") -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child_path = f"{path}.{key}" if path else str(key)
            kind = _key_kind(str(key))
            if kind and not isinstance(value, (dict, list)):
                cleaned = clean_identity_text(value)
                if kind == "applicant":
                    if _looks_like_applicant_identity(cleaned):
                        found.append((kind, cleaned, child_path))
                elif _looks_like_identity(cleaned):
                    found.append((kind, cleaned, child_path))
            found.extend(_walk(value, path=child_path))
    elif isinstance(payload, list):
        for index, item in enumerate(payload[:250]):
            found.extend(_walk(item, path=f"{path}[{index}]"))
    return found


def resolve_project_identity(
    *,
    run_id: str,
    replay_source_run_id: str | None = None,
    parent_run_id: str | None = None,
    existing_project_name: str | None = None,
    normalization_result: dict[str, Any] | None = None,
    canonical_state_result: dict[str, Any] | None = None,
    extraction_result: dict[str, Any] | None = None,
    previous_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_run_id = clean_identity_text(replay_source_run_id) or clean_identity_text(parent_run_id) or clean_identity_text(run_id)
    candidates: list[tuple[str, str, str]] = []
    for label, payload in (
        ("previous_identity", previous_identity),
        ("canonical_state_result", canonical_state_result),
        ("normalization_result", normalization_result),
        ("extraction_result", extraction_result),
    ):
        for kind, value, path in _walk(payload):
            candidates.append((kind, value, f"{label}:{path}"))

    selected: dict[str, tuple[str, str]] = {}
    for kind, value, source in candidates:
        if kind in selected:
            current, _ = selected[kind]
            if kind != "project_number" and len(value) > len(current):
                selected[kind] = (value, source)
        else:
            selected[kind] = (value, source)

    existing_name = clean_identity_text(existing_project_name)
    if "project_name" not in selected and _looks_like_identity(existing_name) and existing_name.casefold() != "gridsenpai":
        selected["project_name"] = (existing_name, "run_config:project_name")

    project_name = selected.get("project_name", ("", ""))[0]
    project_number = selected.get("project_number", ("", ""))[0]
    applicant = selected.get("applicant", ("", ""))[0]
    if project_number:
        project_id = f"PROJECT::{_slug(project_number)}"
        confidence = 0.9
    elif project_name:
        project_id = f"PROJECT::{_slug(project_name)}"
        confidence = 0.82
    else:
        project_id = f"UNRESOLVED_PROJECT::{source_run_id}" if source_run_id else "UNRESOLVED_PROJECT"
        confidence = 0.0
    return {
        "project_id": project_id,
        "project_name": project_name,
        "project_number": project_number,
        "applicant": applicant,
        "identity_confidence": confidence,
        "identity_source": "extracted_project_identity" if selected else "unresolved_run_fallback",
        "source_run_id": source_run_id,
        "source_anchors": [{"field": kind, "source": source} for kind, (_value, source) in selected.items() if source],
    }
