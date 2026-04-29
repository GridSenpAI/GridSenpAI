from __future__ import annotations

"""Planner-ledger governance helpers.

The planner field ledger is the backbone contract for release, interview, and
adjudication decisions.  This module derives compact downstream action plans
from ledger rows instead of asking later services to infer from raw documents or
large canonical-state blobs.
"""

from collections import Counter, defaultdict
from typing import Any

from shared.master_field_policy import field_policy_export

ACCEPTED_STATUSES = {
    "ACCEPTED",
    "ACCEPTED_WITH_CONFLICT_NOTE",
    "INTERVIEW_CONFIRMED",
    "INTERVIEW_SUPPLIED",
    "INTERVIEW_CONFLICT_CONFIRMED",
}

PROVISIONAL_STATUSES = {"PROVISIONAL", "FUTURE_STUDY_REQUIRED", "NOT_APPLICABLE"}

BLOCKED_STATUSES = {
    "UNRESOLVED",
    "BLOCKED_BY_MISSING_SOURCE",
    "BLOCKED_BY_CONFLICT",
    "BLOCKED_BY_ADJUDICATION_FAILURE",
}

_INTERVIEW_ELIGIBLE_BLOCKED = {
    "UNRESOLVED",
    "BLOCKED_BY_MISSING_SOURCE",
    "BLOCKED_BY_CONFLICT",
    "BLOCKED_BY_ADJUDICATION_FAILURE",
    "PROVISIONAL",
}

_ADJUDICATION_ELIGIBLE = {
    "BLOCKED_BY_CONFLICT",
    "BLOCKED_BY_ADJUDICATION_FAILURE",
    "PROVISIONAL",
    "ACCEPTED_WITH_CONFLICT_NOTE",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _priority(row: dict[str, Any]) -> int:
    status = _clean(row.get("status")).upper()
    materiality = _clean(row.get("conflict_materiality")).lower()
    score = 0
    if bool(row.get("planner_critical", False)):
        score += 500
    requiredness = _clean(row.get("requiredness")).lower()
    if requiredness == "required":
        score += 200
    elif requiredness == "conditional":
        score += 120
    if status == "BLOCKED_BY_CONFLICT" or materiality == "high":
        score += 180
    elif status in BLOCKED_STATUSES:
        score += 140
    elif status == "PROVISIONAL":
        score += 80
    candidate_count = int(row.get("candidate_count", 0) or 0)
    if candidate_count > 1:
        score += min(50, candidate_count * 8)
    confidence = _safe_float(row.get("confidence_score"), 0.0)
    if confidence < 0.6:
        score += 40
    elif confidence < 0.85:
        score += 20
    return score


def _question_for_row(row: dict[str, Any]) -> str:
    label = _clean(row.get("field_label")) or _clean(row.get("field_path")) or "this planner field"
    status = _clean(row.get("status")).upper()
    value = _clean(row.get("accepted_value"))
    source = _clean(row.get("source_document"))
    reason = _clean(row.get("conflict_summary")) or _clean(row.get("manual_review_reason")) or _clean(row.get("unresolved_reason"))
    if status == "BLOCKED_BY_CONFLICT":
        return f"Conflicting evidence exists for {label}. Please provide the correct value and note which source should govern."
    if status == "PROVISIONAL" and value and value != "UNRESOLVED":
        return f"Please confirm whether {label} is {value}."
    if source and source != "No direct source found" and value and value != "UNRESOLVED":
        return f"Please confirm or correct {label}; current evidence suggests {value} from {source}."
    if reason:
        return f"Please provide {label}. Reason: {reason}"
    return f"Please provide {label}."


def _source_reference(row: dict[str, Any]) -> str:
    source = _clean(row.get("source_document")) or "No direct source found"
    page = _clean(row.get("source_page"))
    section = _clean(row.get("source_section"))
    if page:
        source = f"{source}, page {page}"
    if section:
        source = f"{source}, {section}"
    return source


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    field_path = _clean(row.get("field_path"))
    policy = field_policy_export(field_path or _clean(row.get("field_id")))
    return {
        "field_path": field_path,
        "field_id": _clean(row.get("field_id")),
        "field_label": _clean(row.get("field_label")) or _clean(policy.get("field_label")),
        "status": _clean(row.get("status")) or "UNRESOLVED",
        "accepted_value": row.get("accepted_value", "UNRESOLVED"),
        "confidence_score": _safe_float(row.get("confidence_score"), 0.0),
        "confidence_band": _clean(row.get("confidence_band")) or "UNRESOLVED",
        "source_reference": _source_reference(row),
        "source_role": _clean(row.get("source_role")) or "unknown",
        "planner_critical": bool(row.get("planner_critical", False) or policy.get("planner_critical", False)),
        "requiredness": _clean(row.get("requiredness")) or _clean(policy.get("requiredness")) or "optional",
        "policy_family": _clean(row.get("policy_family")) or _clean(policy.get("policy_family")) or "general",
        "expected_unit": _clean(row.get("expected_unit")) or _clean(policy.get("expected_unit")),
        "expected_data_type": _clean(row.get("expected_data_type")) or _clean(policy.get("data_type")),
        "candidate_count": int(row.get("candidate_count", 0) or 0),
        "conflict_summary": _clean(row.get("conflict_summary")),
        "manual_review_reason": _clean(row.get("manual_review_reason")),
        "unresolved_reason": _clean(row.get("unresolved_reason")),
        "interview_status": _clean(row.get("interview_status")) or "not_used",
        "evidence_snippet": _clean(row.get("evidence_snippet"))[:300],
        # Compact adjudication must still receive the bounded candidate list.
        # Without this, deterministic fallback sees no viable options and turns
        # obvious document-supported values into BLOCKED_BY_ADJUDICATION_FAILURE.
        "candidate_options": [
            dict(item)
            for item in (row.get("candidate_options") if isinstance(row.get("candidate_options"), list) else [])[:8]
            if isinstance(item, dict)
        ],
        "priority_score": _priority(row),
    }


def _interview_needed(row: dict[str, Any]) -> bool:
    status = _clean(row.get("status")).upper()
    if status not in _INTERVIEW_ELIGIBLE_BLOCKED:
        return False
    if status in {"FUTURE_STUDY_REQUIRED", "NOT_APPLICABLE"}:
        return False
    if _clean(row.get("interview_status")).lower() in {"confirmed", "supplied", "document_confirmed", "conflict_confirmed"}:
        return False
    if not bool(row.get("planner_critical", False)) and _clean(row.get("requiredness")).lower() == "optional" and status == "PROVISIONAL":
        return False
    return True


def _adjudication_needed(row: dict[str, Any]) -> bool:
    status = _clean(row.get("status")).upper()
    materiality = _clean(row.get("conflict_materiality")).lower()
    conflict_summary = _clean(row.get("conflict_summary"))
    # Do not send low-materiality provisional/corroborated rows to adjudication
    # merely because they carry a planner note.  Adjudication is for material
    # conflicts, blocked posture, or weak multi-candidate uncertainty.
    if status in {"FUTURE_STUDY_REQUIRED", "NOT_APPLICABLE"}:
        return False
    if status in _ADJUDICATION_ELIGIBLE:
        if _clean(row.get("registry_backfilled")).lower() == "true" and _clean(row.get("accepted_value")) in {"", "UNRESOLVED"}:
            return False
        if status == "PROVISIONAL" and materiality not in {"high", "medium"} and _clean(row.get("accepted_value")) not in {"", "UNRESOLVED"}:
            return False
        if _clean(row.get("manual_review_reason")).lower() == "accepted value is provisional and should be reviewed before planner use." and materiality not in {"high", "medium"}:
            return False
        return True
    if materiality in {"high", "medium"}:
        return True
    if conflict_summary and materiality not in {"", "none", "low"}:
        return True
    if int(row.get("candidate_count", 0) or 0) > 1 and _safe_float(row.get("confidence_score"), 0.0) < 0.85:
        return True
    if status in ACCEPTED_STATUSES and (_clean(row.get("source_document")) in {"", "No direct source found"}):
        return True
    return False


def build_planner_field_governance(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    ledger_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    status_counts = Counter(_clean(row.get("status")) or "UNKNOWN" for row in ledger_rows)
    by_reason: dict[str, int] = Counter()
    by_family: dict[str, int] = Counter()
    interview_plan: list[dict[str, Any]] = []
    adjudication_plan: list[dict[str, Any]] = []
    manual_review_plan: list[dict[str, Any]] = []

    for row in ledger_rows:
        compact = _compact_row(row)
        family = compact.get("policy_family") or "general"
        by_family[family] += 1
        status = _clean(row.get("status")).upper()
        if status in BLOCKED_STATUSES:
            reason = compact.get("unresolved_reason") or compact.get("manual_review_reason") or compact.get("conflict_summary") or "Unspecified blocker"
            by_reason[str(reason)] += 1
        if _interview_needed(row):
            interview_plan.append({
                **compact,
                "question_id": f"LEDGER_FOLLOWUP::{compact['field_path'] or compact['field_id']}",
                "question": _question_for_row(row),
                "reason": compact.get("manual_review_reason") or compact.get("unresolved_reason") or compact.get("conflict_summary"),
                "action": "ASK_APPLICANT",
            })
        if _adjudication_needed(row):
            adjudication_plan.append({
                **compact,
                "action": "COMPACT_FIELD_ADJUDICATION",
                "adjudication_question": (
                    "Select the winning candidate or confirm that the field must remain blocked/manual-review. "
                    "Use field policy, source authority, conflicts, and interview status only."
                ),
            })
        if status in {"FUTURE_STUDY_REQUIRED", "NOT_APPLICABLE"}:
            continue
        if status in BLOCKED_STATUSES or status in PROVISIONAL_STATUSES or compact.get("conflict_summary"):
            manual_review_plan.append({
                **compact,
                "action": "PLANNER_REVIEW" if bool(compact.get("planner_critical")) else "REVIEW_IF_NEEDED",
            })

    sort_key = lambda item: (-int(item.get("priority_score", 0) or 0), str(item.get("field_path", "")))
    interview_plan.sort(key=sort_key)
    adjudication_plan.sort(key=sort_key)
    manual_review_plan.sort(key=sort_key)

    critical_blocked = [row for row in ledger_rows if bool(row.get("planner_critical", False)) and _clean(row.get("status")).upper() in BLOCKED_STATUSES]
    critical_provisional = [row for row in ledger_rows if bool(row.get("planner_critical", False)) and _clean(row.get("status")).upper() in PROVISIONAL_STATUSES]
    critical_adjudication = [row for row in adjudication_plan if bool(row.get("planner_critical", False))]

    if critical_blocked:
        release_state = "BLOCKED_PENDING_APPLICANT_OR_ENGINEERING_REVIEW"
    elif critical_adjudication:
        release_state = "MANUAL_REVIEW_REQUIRED_PENDING_ADJUDICATION"
    elif critical_provisional:
        release_state = "PROVISIONAL_PENDING_PLANNER_REVIEW"
    else:
        release_state = "READY_WITH_NOTED_LIMITATIONS" if manual_review_plan else "READY"

    grouped_review: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in manual_review_plan[:100]:
        reason = item.get("unresolved_reason") or item.get("manual_review_reason") or item.get("conflict_summary") or item.get("status") or "review_required"
        grouped_review[str(reason)[:160]].append(item)

    return {
        "contract_version": "planner_field_governance_v1",
        "release_state": release_state,
        "field_count": len(ledger_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "blocked_reason_counts": dict(by_reason.most_common()),
        "policy_family_counts": dict(sorted(by_family.items())),
        "applicant_followup_plan": interview_plan[:75],
        "applicant_followup_count": len(interview_plan),
        "adjudication_plan": adjudication_plan[:75],
        "adjudication_required_count": len(adjudication_plan),
        "manual_review_plan": manual_review_plan[:100],
        "manual_review_count": len(manual_review_plan),
        "planner_critical_blocked_count": len(critical_blocked),
        "planner_critical_provisional_count": len(critical_provisional),
        "planner_critical_adjudication_count": len(critical_adjudication),
        "grouped_manual_review": {
            reason: group[:10] for reason, group in grouped_review.items()
        },
    }
