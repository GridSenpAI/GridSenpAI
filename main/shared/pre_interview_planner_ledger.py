from __future__ import annotations

"""Pre-interview planner ledger helpers.

The final planner field ledger is built after canonical state and field
resolution.  The interview stage runs earlier, so it needs a working ledger that
is still registry-complete and candidate-aware.  This module builds that working
contract directly from the normalization candidate ledger so applicant questions
are driven by master planner fields instead of loose extraction/retrieval
backlogs.
"""

from typing import Any

from shared.master_field_policy import field_policy_export
from shared.planner_candidate_bridge import planner_candidate_rows_from_normalization_result
from shared.planner_field_governance import build_planner_field_governance
from shared.planner_field_ledger import build_source_index_from_planner_ledger, planner_field_ledger_summary
from shared.planner_field_workflow import registry_completion_audit, registry_field_work_items


CONTRACT_VERSION = "pre_interview_planner_field_ledger_v1"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return _clean(value).lower() in {"1", "true", "yes", "y", "required", "critical"}


def _confidence(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        score = float(value)
        if score > 1.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))
    text = _clean(value).lower()
    if text in {"high", "accepted", "accepted_by_normalization"}:
        return 0.9
    if text in {"moderate", "medium", "provisional"}:
        return 0.65
    if text in {"low", "weak"}:
        return 0.35
    return default


def _first_candidate(row: dict[str, Any]) -> dict[str, Any]:
    candidates = row.get("candidates") if isinstance(row.get("candidates"), list) else []
    usable = [item for item in candidates if isinstance(item, dict) and not bool(item.get("rejected_by_field_policy", False))]
    if not usable:
        usable = [item for item in candidates if isinstance(item, dict)]
    usable.sort(
        key=lambda item: (
            int(bool(item.get("rejected_by_field_policy", False))) * -1,
            _confidence(item.get("confidence_score"), 0.0),
            int(item.get("authority_score", 0) or 0),
        ),
        reverse=True,
    )
    return dict(usable[0]) if usable else {}


def _source_from_candidate(candidate: dict[str, Any], accepted_source: dict[str, Any]) -> dict[str, str]:
    document = (
        _clean(candidate.get("source_document"))
        or _clean(accepted_source.get("source_name"))
        or _clean(accepted_source.get("source_document"))
        or "No direct source found"
    )
    page = _clean(candidate.get("source_page")) or _clean(accepted_source.get("source_page"))
    section = _clean(candidate.get("source_section")) or _clean(accepted_source.get("source_section"))
    anchor = _clean(candidate.get("source_anchor_id")) or _clean(accepted_source.get("source_anchor_id"))
    role = _clean(candidate.get("source_role")) or _clean(accepted_source.get("source_type")) or "unknown"
    return {
        "source_document": document,
        "source_page": page,
        "source_section": section,
        "source_line": "",
        "source_anchor": anchor,
        "source_role": role,
    }


def _status_for_candidate_row(row: dict[str, Any], *, requiredness: str, planner_critical: bool) -> tuple[str, str, str, str]:
    accepted_value = row.get("accepted_value")
    conflict_count = int(row.get("conflict_count", 0) or 0)
    candidate_count = int(row.get("candidate_count", 0) or 0)
    rejected_count = int(row.get("rejected_candidate_count", 0) or 0)
    if conflict_count > 0:
        return (
            "BLOCKED_BY_CONFLICT",
            "BLOCKED",
            "do_not_use",
            "Conflicting candidate evidence requires applicant confirmation before final planner acceptance.",
        )
    if accepted_value not in (None, "", [], {}):
        return ("ACCEPTED", "READY", "use", "")
    if candidate_count > 0 and rejected_count < candidate_count:
        if planner_critical or requiredness in {"required", "conditional"}:
            return (
                "PROVISIONAL",
                "PROVISIONAL",
                "use_with_warning",
                "Candidate evidence exists, but no accepted value has been promoted before interview.",
            )
        return (
            "PROVISIONAL",
            "PROVISIONAL",
            "show_as_provisional",
            "Candidate evidence exists, but this optional field has not been accepted yet.",
        )
    if planner_critical or requiredness in {"required", "conditional"}:
        return (
            "BLOCKED_BY_MISSING_SOURCE",
            "BLOCKED",
            "do_not_use",
            "No candidate value was found before interview for this required/planner-critical field.",
        )
    return (
        "UNRESOLVED",
        "PROVISIONAL",
        "show_as_unresolved",
        "No candidate value was found before interview for this optional field.",
    )


def _row_from_work_item(work_item: dict[str, Any], candidate_row: dict[str, Any] | None) -> dict[str, Any]:
    field_id = _clean(work_item.get("field_id"))
    field_path = _clean(work_item.get("field_path")) or field_id
    policy = field_policy_export(field_path or field_id)
    candidate_payload = dict(candidate_row) if isinstance(candidate_row, dict) else {}
    best_candidate = _first_candidate(candidate_payload)
    accepted_source = candidate_payload.get("accepted_source") if isinstance(candidate_payload.get("accepted_source"), dict) else {}
    source = _source_from_candidate(best_candidate, accepted_source)
    requiredness = _clean(candidate_payload.get("requiredness")) or _clean(work_item.get("requiredness")) or "optional"
    planner_critical = _truthy(candidate_payload.get("planner_critical")) or _truthy(work_item.get("planner_critical"))
    status, release_state, use_policy, reason = _status_for_candidate_row(
        candidate_payload,
        requiredness=requiredness.lower(),
        planner_critical=planner_critical,
    )
    accepted_value = candidate_payload.get("accepted_value")
    normalized_value = best_candidate.get("normalized_value") if best_candidate.get("normalized_value") not in (None, "", [], {}) else best_candidate.get("value")
    confidence = _confidence(accepted_source.get("confidence"), 0.0)
    if confidence <= 0.0 and best_candidate:
        confidence = _confidence(best_candidate.get("confidence_score"), 0.5)
    if accepted_value in (None, "", [], {}) and status not in {"PROVISIONAL"}:
        confidence = 0.0
    manual_review_reason = reason
    if _clean(best_candidate.get("field_policy_reason")) and bool(best_candidate.get("rejected_by_field_policy", False)):
        manual_review_reason = (manual_review_reason + "; " if manual_review_reason else "") + _clean(best_candidate.get("field_policy_reason"))
    return {
        "ledger_contract_version": CONTRACT_VERSION,
        "field_path": field_path,
        "field_id": field_id,
        "field_label": _clean(candidate_payload.get("field_label")) or _clean(work_item.get("field_label")) or _clean(policy.get("field_label")) or field_id,
        "field_definition": _clean(policy.get("definition")) or _clean(work_item.get("field_definition")),
        "expected_data_type": _clean(candidate_payload.get("expected_data_type")) or _clean(work_item.get("expected_data_type")) or _clean(policy.get("data_type")),
        "expected_unit": _clean(candidate_payload.get("expected_unit")) or _clean(work_item.get("expected_unit")) or _clean(policy.get("expected_unit")),
        "policy_family": _clean(candidate_payload.get("policy_family")) or _clean(work_item.get("policy_family")) or _clean(policy.get("policy_family")) or "general",
        "preferred_source_roles": dict(policy.get("preferred_source_roles", {})) if isinstance(policy.get("preferred_source_roles"), dict) else {},
        "accepted_value": accepted_value if accepted_value not in (None, "", [], {}) else "UNRESOLVED",
        "normalized_value": normalized_value if normalized_value not in (None, "", [], {}) else "UNRESOLVED",
        "unit": _clean(work_item.get("expected_unit")) or _clean(policy.get("expected_unit")),
        "confidence_score": confidence,
        "confidence_band": "HIGH" if confidence >= 0.85 else "MODERATE" if confidence >= 0.6 else "LOW" if confidence > 0 else "UNRESOLVED",
        "status": status,
        "release_state": release_state,
        "export_readiness_tier": "ready" if release_state == "READY" else "blocked" if release_state == "BLOCKED" else "warning",
        "translation_use_policy": use_policy,
        "scenario_use_policy": use_policy,
        "planner_packet_use_policy": "show_value" if status == "ACCEPTED" else "show_as_provisional" if status == "PROVISIONAL" else "show_as_unresolved",
        **source,
        "evidence_snippet": _clean(best_candidate.get("evidence_snippet"))[:500] if best_candidate else "No direct evidence preserved before interview.",
        "candidate_count": int(candidate_payload.get("candidate_count", 0) or 0),
        "rejected_candidate_count": int(candidate_payload.get("rejected_candidate_count", 0) or 0),
        "conflict_summary": "Candidate ledger reports conflicting pre-interview evidence." if int(candidate_payload.get("conflict_count", 0) or 0) > 0 else "",
        "conflict_materiality": "high" if int(candidate_payload.get("conflict_count", 0) or 0) > 0 and planner_critical else "moderate" if int(candidate_payload.get("conflict_count", 0) or 0) > 0 else "none",
        "interview_status": "not_used",
        "manual_review_reason": manual_review_reason,
        "unresolved_reason": reason if status in {"UNRESOLVED", "BLOCKED_BY_MISSING_SOURCE", "BLOCKED_BY_CONFLICT"} else "",
        "planner_critical": planner_critical,
        "requiredness": requiredness,
        "packet_section": _clean(work_item.get("packet_section")),
        "packet_section_label": _clean(work_item.get("packet_section")),
        "accepted_candidate_id": _clean(best_candidate.get("candidate_id")) if status in {"ACCEPTED", "PROVISIONAL"} else "",
        "acceptance_policy_outcome": _clean(candidate_payload.get("status")) or status,
        "acceptance_policy_next_action": "applicant_confirmation" if status != "ACCEPTED" else "none",
        "adjudication_trace": {},
        "registry_backfilled": not bool(candidate_payload),
        "pre_interview_working_row": True,
    }


def build_pre_interview_planner_field_contract(
    normalization_result: dict[str, Any] | None,
    *,
    include_optional: bool = True,
) -> dict[str, Any]:
    """Build a registry-complete working planner ledger for interview triage."""
    candidate_rows = planner_candidate_rows_from_normalization_result(normalization_result)
    candidate_by_id: dict[str, dict[str, Any]] = {}
    candidate_by_path: dict[str, dict[str, Any]] = {}
    for row in candidate_rows:
        if not isinstance(row, dict):
            continue
        field_id = _clean(row.get("field_id"))
        field_path = _clean(row.get("field_path"))
        if field_id and field_id not in candidate_by_id:
            candidate_by_id[field_id] = row
        if field_path and field_path not in candidate_by_path:
            candidate_by_path[field_path] = row

    rows: list[dict[str, Any]] = []
    for work_item in registry_field_work_items(include_optional=include_optional):
        if not isinstance(work_item, dict):
            continue
        field_id = _clean(work_item.get("field_id"))
        field_path = _clean(work_item.get("field_path")) or field_id
        if not field_id:
            continue
        rows.append(_row_from_work_item(work_item, candidate_by_id.get(field_id) or candidate_by_path.get(field_path)))

    rows.sort(key=lambda row: (0 if _truthy(row.get("planner_critical")) else 1, _clean(row.get("packet_section")), _clean(row.get("field_path"))))
    summary = planner_field_ledger_summary(rows)
    summary.update(
        {
            "contract_version": CONTRACT_VERSION,
            "pre_interview_working_ledger": True,
            "candidate_ledger_row_count": len(candidate_rows),
            "registry_completion_audit": registry_completion_audit(rows),
        }
    )
    governance = build_planner_field_governance(rows)
    return {
        "contract_version": CONTRACT_VERSION,
        "planner_field_ledger": rows,
        "planner_field_ledger_summary": summary,
        "planner_field_governance": governance,
        "source_index": build_source_index_from_planner_ledger(rows),
    }
