from __future__ import annotations

"""Registry-driven planner-field workflow helpers.

The planner_required_fields registry is the backbone of GridSenpAI.  This module
turns that registry plus the planner ledger into compact, deterministic work
queues that can be shared by interview, adjudication, translation, and export.
"""

from typing import Any

from shared.master_field_policy import field_policy_export
from shared.planner_registry import (
    field_path_for_registry_field_id,
    planner_registry_fields,
)

ACCEPTED_WORKFLOW_STATUSES: set[str] = {
    "ACCEPTED",
    "ACCEPTED_WITH_CONFLICT_NOTE",
    "INTERVIEW_CONFIRMED",
    "INTERVIEW_SUPPLIED",
    "INTERVIEW_CONFLICT_CONFIRMED",
    "NOT_APPLICABLE",
    "FUTURE_STUDY_REQUIRED",
}

BLOCKING_WORKFLOW_STATUSES: set[str] = {
    "UNRESOLVED",
    "BLOCKED_BY_MISSING_SOURCE",
    "BLOCKED_BY_CONFLICT",
    "BLOCKED_BY_ADJUDICATION_FAILURE",
}

PROVISIONAL_WORKFLOW_STATUSES: set[str] = {
    "PROVISIONAL",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _clean(value).lower()
    return text in {"1", "true", "yes", "y", "required", "critical"}


def registry_field_work_items(*, include_optional: bool = True) -> list[dict[str, Any]]:
    """Return one deterministic workflow item for every master planner field."""
    items: list[dict[str, Any]] = []
    for field in planner_registry_fields():
        field_id = _clean(field.get("field_id"))
        if not field_id:
            continue
        requiredness = _clean(field.get("requiredness")).lower() or "optional"
        planner_critical = _truthy(field.get("planner_critical"))
        if not include_optional and requiredness == "optional" and not planner_critical:
            continue
        field_path = field_path_for_registry_field_id(field_id) or field_id
        policy = field_policy_export(field_path or field_id)
        items.append(
            {
                "field_id": field_id,
                "field_path": field_path,
                "field_label": _clean(field.get("label")) or _clean(policy.get("field_label")) or field_id,
                "field_definition": _clean(policy.get("definition")),
                "expected_data_type": _clean(policy.get("data_type")),
                "expected_unit": _clean(policy.get("expected_unit")),
                "policy_family": _clean(policy.get("policy_family")) or "general",
                "accepted_contexts": list(policy.get("accepted_contexts", [])) if isinstance(policy.get("accepted_contexts"), list) else [],
                "rejected_contexts": list(policy.get("rejected_contexts", [])) if isinstance(policy.get("rejected_contexts"), list) else [],
                "preferred_source_roles": dict(policy.get("preferred_source_roles", {})) if isinstance(policy.get("preferred_source_roles"), dict) else {},
                "requiredness": requiredness,
                "planner_critical": planner_critical,
                "packet_section": _clean(field.get("packet_section")),
                "group": _clean(field.get("group")),
                "search_keywords": list(field.get("search_keywords", [])) if isinstance(field.get("search_keywords"), list) else [],
                "minimum_confidence_for_auto_accept": _clean(policy.get("minimum_confidence_for_auto_accept")),
            }
        )
    return items


def ledger_row_status(row: dict[str, Any]) -> str:
    return _clean(row.get("status")).upper() or "UNRESOLVED"


def ledger_row_requires_interview(row: dict[str, Any]) -> bool:
    """Return True when applicant input is useful and not just noise."""
    if not isinstance(row, dict):
        return False
    status = ledger_row_status(row)
    requiredness = _clean(row.get("requiredness")).lower()
    planner_critical = _truthy(row.get("planner_critical"))
    interview_status = _clean(row.get("interview_status")).lower()
    if interview_status in {"answered", "confirmed", "interview_confirmed", "interview_supplied"}:
        return False
    if status in ACCEPTED_WORKFLOW_STATUSES:
        return False
    if status in BLOCKING_WORKFLOW_STATUSES:
        return True
    if status in PROVISIONAL_WORKFLOW_STATUSES and (planner_critical or requiredness in {"required", "conditional"}):
        return True
    if _clean(row.get("manual_review_reason")) and (planner_critical or requiredness in {"required", "conditional"}):
        return True
    return False


def _priority_tuple(row: dict[str, Any]) -> tuple[int, int, int, str]:
    status = ledger_row_status(row)
    planner_critical = _truthy(row.get("planner_critical"))
    requiredness = _clean(row.get("requiredness")).lower()
    status_rank = {
        "BLOCKED_BY_CONFLICT": 0,
        "BLOCKED_BY_ADJUDICATION_FAILURE": 1,
        "BLOCKED_BY_MISSING_SOURCE": 2,
        "UNRESOLVED": 3,
        "PROVISIONAL": 4,
    }.get(status, 6)
    required_rank = 0 if planner_critical else 1 if requiredness == "required" else 2 if requiredness == "conditional" else 3
    family = _clean(row.get("policy_family"))
    family_rank = 0 if family in {"interconnection", "load", "date", "transformer", "generator", "ups"} else 1
    return (required_rank, status_rank, family_rank, _clean(row.get("field_path") or row.get("field_id")))


def build_interview_question_records_from_ledger(
    rows: list[dict[str, Any]] | None,
    *,
    answered_field_paths: set[str] | None = None,
    max_questions: int = 75,
) -> list[dict[str, Any]]:
    """Build compact applicant-question records directly from the planner ledger."""
    answered = {_clean(item) for item in (answered_field_paths or set()) if _clean(item)}
    candidates = [row for row in rows if isinstance(row, dict) and ledger_row_requires_interview(row)]
    candidates = [row for row in candidates if _clean(row.get("field_path")) not in answered and _clean(row.get("field_id")) not in answered]
    candidates.sort(key=_priority_tuple)
    if max_questions > 0:
        candidates = candidates[:max_questions]

    questions: list[dict[str, Any]] = []
    for index, row in enumerate(candidates, start=1):
        field_path = _clean(row.get("field_path")) or _clean(row.get("field_id"))
        field_id = _clean(row.get("field_id")) or field_path
        label = _clean(row.get("field_label")) or field_id.replace("_", " ")
        status = ledger_row_status(row)
        accepted_value = _clean(row.get("accepted_value"))
        source_document = _clean(row.get("source_document"))
        source_page = _clean(row.get("source_page"))
        reason_bits = []
        if status in BLOCKING_WORKFLOW_STATUSES:
            reason_bits.append(f"planner ledger status is {status}")
        elif status == "PROVISIONAL":
            reason_bits.append("planner ledger value is provisional")
        if _clean(row.get("unresolved_reason")):
            reason_bits.append(_clean(row.get("unresolved_reason")))
        if _clean(row.get("manual_review_reason")):
            reason_bits.append(_clean(row.get("manual_review_reason")))
        if accepted_value and accepted_value.upper() != "UNRESOLVED":
            prompt = f"Please confirm or correct {label}: current best value is {accepted_value}."
        else:
            prompt = f"Please provide {label}."
        if source_document and source_document != "No direct source found":
            prompt += f" Current evidence source: {source_document}"
            if source_page:
                prompt += f", page {source_page}"
            prompt += "."
        policy = field_policy_export(field_path or field_id)
        questions.append(
            {
                "question_id": f"PLANNER_LEDGER_FIELD_{index:03d}::{field_id}",
                "field_path": field_path,
                "question": prompt,
                "category": "planner_field_ledger_followup",
                "priority": "HIGH" if _truthy(row.get("planner_critical")) or _clean(row.get("requiredness")).lower() == "required" else "MODERATE",
                "source": "planner_field_ledger",
                "reason": "; ".join(reason_bits) or "Planner field ledger requires applicant confirmation.",
                "suggested_sources": list(policy.get("preferred_source_roles", {}).keys())[:5] if isinstance(policy.get("preferred_source_roles"), dict) else [],
                "metadata": {
                    "field_id": field_id,
                    "planner_critical": _truthy(row.get("planner_critical")),
                    "requiredness": _clean(row.get("requiredness")) or "optional",
                    "ledger_status": status,
                    "accepted_value": row.get("accepted_value"),
                    "accepted_confidence": row.get("confidence_score"),
                    "source_document": source_document,
                    "source_page": source_page,
                    "expected_data_type": _clean(row.get("expected_data_type")) or _clean(policy.get("data_type")),
                    "expected_unit": _clean(row.get("expected_unit")) or _clean(policy.get("expected_unit")),
                    "field_policy": policy,
                },
            }
        )
    return questions


def registry_completion_audit(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    registry_items = registry_field_work_items(include_optional=True)
    registry_ids = {_clean(item.get("field_id")) for item in registry_items if _clean(item.get("field_id"))}
    row_ids = {_clean(row.get("field_id")) for row in rows if _clean(row.get("field_id"))}
    missing = sorted(registry_ids - row_ids)
    extra = sorted(row_ids - registry_ids)
    blocking = [row for row in rows if ledger_row_status(row) in BLOCKING_WORKFLOW_STATUSES]
    provisional = [row for row in rows if ledger_row_status(row) in PROVISIONAL_WORKFLOW_STATUSES]
    accepted = [row for row in rows if ledger_row_status(row) in ACCEPTED_WORKFLOW_STATUSES]
    return {
        "registry_field_count": len(registry_ids),
        "ledger_row_count": len(rows),
        "registry_complete": not missing,
        "missing_registry_field_ids": missing,
        "extra_ledger_field_ids": extra,
        "accepted_count": len(accepted),
        "provisional_count": len(provisional),
        "blocking_count": len(blocking),
        "blocking_planner_critical_count": len([row for row in blocking if _truthy(row.get("planner_critical"))]),
        "release_blocked": any(_truthy(row.get("planner_critical")) for row in blocking),
    }
