from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _field_key(decision: dict[str, Any]) -> str:
    return (
        _clean_text(decision.get("field_path"))
        or _clean_text(decision.get("field_id"))
        or _clean_text(decision.get("master_field_path"))
    )


def _candidate_id(decision: dict[str, Any]) -> str:
    for key in (
        "accepted_candidate_id",
        "selected_candidate_id",
        "winning_candidate_id",
        "winner_candidate_id",
        "candidate_id",
    ):
        value = _clean_text(decision.get(key))
        if value:
            return value
    selected = decision.get("selected_candidate") or decision.get("winning_candidate") or decision.get("accepted_candidate")
    if isinstance(selected, dict):
        return _clean_text(selected.get("candidate_id"))
    return ""


def _decision_value(decision: dict[str, Any]) -> Any:
    for key in ("accepted_value", "selected_value", "winning_value", "value", "normalized_value"):
        if key in decision and decision.get(key) not in (None, ""):
            return decision.get(key)
    selected = decision.get("selected_candidate") or decision.get("winning_candidate") or decision.get("accepted_candidate")
    if isinstance(selected, dict):
        return selected.get("value", selected.get("accepted_value"))
    return None


def _compact_per_field_decision(raw: dict[str, Any], *, packet_index: int) -> dict[str, Any]:
    selected = raw.get("selected_candidate") or raw.get("winning_candidate") or raw.get("accepted_candidate")
    selected = selected if isinstance(selected, dict) else {}
    confidence = _safe_float(raw.get("confidence"))
    if confidence is None:
        confidence = _safe_float(raw.get("confidence_score"))
    if confidence is None:
        confidence = _safe_float(selected.get("confidence"))
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    return {
        "field_path": _field_key(raw),
        "field_id": _clean_text(raw.get("field_id")),
        "field_label": _clean_text(raw.get("field_label") or raw.get("label")),
        "accepted_candidate_id": _candidate_id(raw),
        "accepted_value": _decision_value(raw),
        "normalized_value": raw.get("normalized_value", _decision_value(raw)),
        "unit": _clean_text(raw.get("unit") or selected.get("unit")),
        "confidence_score": confidence,
        "confidence_band": _clean_text(raw.get("confidence_band") or selected.get("confidence_band")),
        "status": _clean_text(raw.get("status") or raw.get("decision_status") or raw.get("adjudication_status")),
        "rationale": _clean_text(raw.get("rationale") or raw.get("reasoning") or raw.get("stronger_candidate_reasoning")),
        "conflict_note": _clean_text(raw.get("conflict_note") or raw.get("runner_up_summary") or raw.get("source_quality_comparison")),
        "manual_review_reason": _clean_text(raw.get("manual_review_reason")),
        "source_document": _clean_text(raw.get("source_document") or source.get("source_document") or selected.get("source_document")),
        "source_page": _clean_text(raw.get("source_page") or source.get("source_page") or selected.get("source_page")),
        "source_section": _clean_text(raw.get("source_section") or source.get("source_section") or selected.get("source_section")),
        "source_line": _clean_text(raw.get("source_line") or source.get("source_line") or selected.get("source_line")),
        "source_anchor": _clean_text(raw.get("source_anchor") or source.get("source_anchor") or selected.get("source_anchor")),
        "evidence_snippet": _clean_text(raw.get("evidence_snippet") or raw.get("snippet") or selected.get("evidence_snippet")),
        "packet_index": packet_index,
    }


def _per_field_decisions_from_packet_results(packet_results: list[Any]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for packet_index, packet_result in enumerate(packet_results):
        if not isinstance(packet_result, dict):
            continue
        structured = packet_result.get("structured_output")
        if not isinstance(structured, dict):
            continue
        values = structured.get("per_field_adjudication")
        if not isinstance(values, list):
            values = structured.get("field_decisions") if isinstance(structured.get("field_decisions"), list) else []
        for raw in values:
            if not isinstance(raw, dict):
                continue
            compact = _compact_per_field_decision(raw, packet_index=packet_index)
            field_path = _clean_text(compact.get("field_path"))
            if not field_path:
                continue
            signature = (field_path, _clean_text(compact.get("accepted_candidate_id")), _clean_text(compact.get("accepted_value")))
            if signature in seen:
                continue
            seen.add(signature)
            decisions.append(compact)
    return decisions[:250]

def build_adjudication_result_from_canonical(
    *,
    run_id: str,
    canonical_state_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Extract field-resolution adjudication into a stable runtime/export artifact."""
    result_payload = canonical_state_result if isinstance(canonical_state_result, dict) else {}
    canonical_state = result_payload.get("canonical_state", {})
    if not isinstance(canonical_state, dict):
        canonical_state = {}

    field_resolution = canonical_state.get("field_resolution", {})
    if not isinstance(field_resolution, dict):
        field_resolution = {}

    packet_plan = field_resolution.get("adjudication_packet_plan", {})
    if not isinstance(packet_plan, dict):
        packet_plan = {}

    support = field_resolution.get("adjudication_support", {})
    if not isinstance(support, dict):
        support = {}

    summary = field_resolution.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}

    status = str(
        field_resolution.get("adjudication_status")
        or packet_plan.get("status")
        or "ADJUDICATION_SKIPPED_NO_CONFLICTS"
    ).strip() or "ADJUDICATION_SKIPPED_NO_CONFLICTS"

    packet_results = support.get("packet_results", [])
    if not isinstance(packet_results, list):
        packet_results = []

    failed_statuses = {
        "ADJUDICATION_PARTIAL",
        "ADJUDICATION_REQUIRED_BUT_FAILED",
        "ADJUDICATION_BLOCKED_PROMPT_TOO_LARGE",
    }
    planner_critical_failed = status in failed_statuses and int(summary.get("planner_review_count", 0) or 0) > 0

    packet_count = packet_plan.get("packet_count")
    if packet_count is None and isinstance(packet_plan.get("packets"), list):
        packet_count = len(packet_plan.get("packets", []))

    per_field_decisions = _per_field_decisions_from_packet_results(packet_results)

    return {
        "run_id": run_id,
        "status": status,
        "stage_name": "canonical_state",
        "substage_name": "adjudication",
        "created_at": utc_now_iso(),
        "required": int(packet_plan.get("target_count", 0) or 0) > 0,
        "packet_count": int(packet_count or 0),
        "target_count": int(packet_plan.get("target_count", 0) or 0),
        "completed_packet_count": int(support.get("completed_packet_count", 0) or 0),
        "blocked_packet_count": int(support.get("blocked_packet_count", 0) or 0),
        "error_packet_count": int(support.get("error_packet_count", 0) or 0),
        "planner_review_count": int(summary.get("planner_review_count", 0) or 0),
        "planner_critical_failed": planner_critical_failed,
        "release_impact": (
            "manual_review_required"
            if planner_critical_failed
            else "no_global_export_block"
        ),
        "packet_plan": packet_plan,
        "support_summary": field_resolution.get("adjudication_support_summary", {}),
        "per_field_decisions": per_field_decisions,
        "per_field_decision_count": len(per_field_decisions),
        "packet_result_statuses": [
            str(item.get("status", "UNKNOWN")).strip()
            for item in packet_results
            if isinstance(item, dict)
        ],
    }
