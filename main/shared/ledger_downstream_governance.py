from __future__ import annotations

"""Downstream use-policy helpers for the planner field ledger.

Translation and scenario generation must not silently consume values that the
planner ledger has marked blocked, unresolved, adjudication-failed, or held for
review.  This module gives downstream services a compact, shared contract for
checking ledger rows before values are used in model outputs or scenario drivers.
"""

from typing import Any

ACCEPTED_LEDGER_STATUSES = {
    "ACCEPTED",
    "ACCEPTED_WITH_CONFLICT_NOTE",
    "INTERVIEW_CONFIRMED",
    "INTERVIEW_SUPPLIED",
    "INTERVIEW_CONFLICT_CONFIRMED",
}

PROVISIONAL_LEDGER_STATUSES = {"PROVISIONAL", "FUTURE_STUDY_REQUIRED", "NOT_APPLICABLE"}

BLOCKED_LEDGER_STATUSES = {
    "UNRESOLVED",
    "BLOCKED_BY_MISSING_SOURCE",
    "BLOCKED_BY_CONFLICT",
    "BLOCKED_BY_ADJUDICATION_FAILURE",
}

_HOLD_TRANSLATION_POLICIES = {
    "do_not_use",
    "hold_from_modeled_output",
    "hold_for_review",
    "hold",
}

_HOLD_SCENARIO_POLICIES = {
    "do_not_use",
    "hold_for_review_variant_only",
    "hold_from_modeled_output",
    "hold_for_review",
    "hold",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _planner_rows_from_state(canonical_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    state = canonical_state if isinstance(canonical_state, dict) else {}
    contract = state.get("planner_field_contract") if isinstance(state.get("planner_field_contract"), dict) else {}
    rows = contract.get("planner_field_ledger") if isinstance(contract.get("planner_field_ledger"), list) else None
    if rows is None:
        rows = state.get("planner_field_ledger") if isinstance(state.get("planner_field_ledger"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def planner_ledger_index(canonical_state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Index ledger rows by both registry id and field path."""
    index: dict[str, dict[str, Any]] = {}
    for row in _planner_rows_from_state(canonical_state):
        for key in (_clean(row.get("field_path")), _clean(row.get("field_id"))):
            if key and key not in index:
                index[key] = row
    return index


def source_reference_for_row(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return "No direct source found"
    source = _clean(row.get("source_document")) or "No direct source found"
    page = _clean(row.get("source_page"))
    section = _clean(row.get("source_section"))
    line = _clean(row.get("source_line"))
    if page:
        source = f"{source}, page {page}"
    if section:
        source = f"{source}, {section}"
    if line:
        source = f"{source}, line {line}"
    return source


def row_hold_reason(row: dict[str, Any], *, use_case: str = "translation") -> str:
    status = _clean(row.get("status")).upper()
    release_state = _clean(row.get("release_state")).upper()
    translation_policy = _clean(row.get("translation_use_policy")).lower()
    scenario_policy = _clean(row.get("scenario_use_policy")).lower()
    accepted_value = _clean(row.get("accepted_value"))
    source = source_reference_for_row(row)
    reasons: list[str] = []

    if status in BLOCKED_LEDGER_STATUSES:
        reasons.append(f"ledger status is {status}")
    if release_state.startswith("BLOCKED") or release_state == "BLOCKED":
        reasons.append(f"release state is {release_state or 'BLOCKED'}")
    if use_case == "translation" and translation_policy in _HOLD_TRANSLATION_POLICIES:
        reasons.append(f"translation use policy is {translation_policy}")
    if use_case == "scenario" and scenario_policy in _HOLD_SCENARIO_POLICIES:
        reasons.append(f"scenario use policy is {scenario_policy}")
    if not accepted_value or accepted_value.upper() == "UNRESOLVED":
        reasons.append("accepted value is unresolved")

    if not reasons and status in PROVISIONAL_LEDGER_STATUSES:
        reasons.append(f"ledger status is {status}; downstream use must stay review-tagged")

    if not reasons:
        return ""
    label = _clean(row.get("field_label")) or _clean(row.get("field_path")) or "planner field"
    return f"Planner ledger gates {label} from automatic {use_case} use because " + "; ".join(reasons) + f". Source: {source}."


def row_is_usable(row: dict[str, Any] | None, *, use_case: str = "translation") -> bool:
    if not isinstance(row, dict):
        return False
    status = _clean(row.get("status")).upper()
    if status not in ACCEPTED_LEDGER_STATUSES:
        return False
    if row_hold_reason(row, use_case=use_case):
        return False
    return True


def resolve_planner_ledger_value(
    canonical_state: dict[str, Any] | None,
    *field_keys: str,
    use_case: str = "translation",
) -> dict[str, Any] | None:
    """Return a field-resolution-shaped record from the closed planner ledger.

    The return shape intentionally mirrors the subset consumed by translation
    helpers so downstream code can move from legacy field-resolution rows to the
    final planner-ledger contract without duplicating branch logic.
    """
    index = planner_ledger_index(canonical_state)
    for raw_key in field_keys:
        key = _clean(raw_key)
        if not key:
            continue
        row = index.get(key)
        if not isinstance(row, dict):
            continue
        value = row.get("accepted_value")
        status = _clean(row.get("status")).upper()
        hold_reason = row_hold_reason(row, use_case=use_case)
        return {
            "value": None if _clean(value).upper() == "UNRESOLVED" else value,
            "status": "resolved" if status in ACCEPTED_LEDGER_STATUSES else "review_required" if status in PROVISIONAL_LEDGER_STATUSES else "unresolved",
            "confidence": _safe_float(row.get("confidence_score"), 0.0),
            "confidence_band": _clean(row.get("confidence_band")) or "UNRESOLVED",
            "why_accepted": [note for note in (
                _clean(row.get("manual_review_reason")),
                _clean(row.get("conflict_summary")),
                _clean(row.get("unresolved_reason")),
            ) if note],
            "source_anchors": [_clean(row.get("source_anchor")) or source_reference_for_row(row)],
            "planner_review_flag": bool(row.get("planner_critical", False)) and status not in ACCEPTED_LEDGER_STATUSES,
            "needs_applicant_confirmation": status in {"BLOCKED_BY_CONFLICT", "PROVISIONAL"} or _clean(row.get("interview_status")).lower() in {"needs_confirmation", "confirmation_required"},
            "decision_basis": "closed_planner_field_ledger",
            "accepted_status": "resolved" if status in ACCEPTED_LEDGER_STATUSES else "review_required" if status in PROVISIONAL_LEDGER_STATUSES else "unresolved",
            "accepted_value_kind": "planner_ledger",
            "planner_attention_tier": "critical_review_required" if bool(row.get("planner_critical", False)) and status not in ACCEPTED_LEDGER_STATUSES else "",
            "accepted_source_hierarchy": _clean(row.get("source_role")),
            "accepted_specificity": source_reference_for_row(row),
            "contradiction_summary": _clean(row.get("conflict_summary")),
            "field_release_profile": {
                "release_state": _clean(row.get("release_state")),
                "translation_use_policy": _clean(row.get("translation_use_policy")),
                "scenario_use_policy": _clean(row.get("scenario_use_policy")),
                "planner_packet_use_policy": _clean(row.get("planner_packet_use_policy")),
                "export_readiness_tier": _clean(row.get("export_readiness_tier")),
            },
            "supporting_sources": [{
                "source_document": _clean(row.get("source_document")),
                "source_page": _clean(row.get("source_page")),
                "source_section": _clean(row.get("source_section")),
                "source_role": _clean(row.get("source_role")),
                "evidence_snippet": _clean(row.get("evidence_snippet"))[:500],
            }],
            "alternatives": [],
            "label": _clean(row.get("field_label")),
            "field_path": _clean(row.get("field_path")),
            "field_id": _clean(row.get("field_id")),
            "used_field_resolution": True,
            "used_planner_field_ledger": True,
            "planner_ledger_status": status,
            "planner_ledger_hold_reason": hold_reason,
            "planner_ledger_row": row,
        }
    return None


def apply_ledger_governance_to_parameter(
    parameter: dict[str, Any],
    canonical_state: dict[str, Any] | None,
    *,
    use_case: str = "translation",
) -> dict[str, Any]:
    """Downgrade/hold a translated parameter when any driving ledger field is gated."""
    if not isinstance(parameter, dict):
        return parameter
    index = planner_ledger_index(canonical_state)
    paths: set[str] = set()
    for key in ("source_field_paths", "dependency_paths"):
        raw = parameter.get(key)
        if isinstance(raw, list):
            paths.update(_clean(item) for item in raw if _clean(item))
    field_key = _clean(parameter.get("field_resolution_field_key"))
    if field_key:
        paths.add(field_key)

    gated_rows: list[dict[str, Any]] = []
    for path in sorted(paths):
        row = index.get(path)
        if isinstance(row, dict) and row_hold_reason(row, use_case=use_case):
            gated_rows.append(row)

    if not gated_rows:
        return parameter

    reasons = [row_hold_reason(row, use_case=use_case) for row in gated_rows[:3]]
    note = " ".join(reason for reason in reasons if reason).strip()
    if note:
        existing_review = _clean(parameter.get("review_note"))
        existing_explanation = _clean(parameter.get("confidence_explanation"))
        parameter["review_note"] = f"{existing_review} {note}".strip() if existing_review else note
        parameter["confidence_explanation"] = f"{existing_explanation} {note}".strip() if existing_explanation else note
    parameter["confidence_tag"] = "LOW"
    parameter["confidence_score"] = min(_safe_float(parameter.get("confidence_score"), 1.0), 0.49)
    parameter["planner_review_flag"] = True
    parameter["ledger_downstream_gated"] = True
    parameter["ledger_downstream_gated_fields"] = [
        {
            "field_path": _clean(row.get("field_path")),
            "field_id": _clean(row.get("field_id")),
            "status": _clean(row.get("status")),
            "release_state": _clean(row.get("release_state")),
            "translation_use_policy": _clean(row.get("translation_use_policy")),
            "scenario_use_policy": _clean(row.get("scenario_use_policy")),
            "source_reference": source_reference_for_row(row),
        }
        for row in gated_rows[:10]
    ]
    if any(_clean(row.get("status")).upper() in BLOCKED_LEDGER_STATUSES for row in gated_rows):
        parameter["field_release_state"] = "BLOCKED"
    elif any(_clean(row.get("status")).upper() in PROVISIONAL_LEDGER_STATUSES for row in gated_rows):
        parameter["field_release_state"] = "PROVISIONAL"
    return parameter


def apply_ledger_governance_to_parameters(
    output_parameters: list[dict[str, Any]],
    canonical_state: dict[str, Any] | None,
    *,
    use_case: str = "translation",
) -> dict[str, Any]:
    gated = 0
    blocked = 0
    provisional = 0
    for parameter in output_parameters if isinstance(output_parameters, list) else []:
        before = bool(parameter.get("ledger_downstream_gated", False)) if isinstance(parameter, dict) else False
        apply_ledger_governance_to_parameter(parameter, canonical_state, use_case=use_case)
        after = bool(parameter.get("ledger_downstream_gated", False)) if isinstance(parameter, dict) else False
        if after and not before:
            gated += 1
        state = _clean(parameter.get("field_release_state")).upper() if isinstance(parameter, dict) else ""
        if state == "BLOCKED":
            blocked += 1
        elif state == "PROVISIONAL":
            provisional += 1
    return {
        "contract_version": "ledger_downstream_governance_v1",
        "use_case": use_case,
        "gated_parameter_count": gated,
        "blocked_parameter_count": blocked,
        "provisional_parameter_count": provisional,
    }
