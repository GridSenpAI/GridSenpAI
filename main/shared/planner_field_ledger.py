from __future__ import annotations

"""Planner field ledger contract helpers.

The field-resolution ledger remains the detailed audit trail.  This module turns
that audit trail into the governing planner-facing contract used by canonical
state, export, TLDR, release decisions, and regression checks.

Every master field row must answer the planner questions:
- what value won,
- how confident the system is,
- where the value came from,
- whether the value is accepted, provisional, blocked, or interview supplied,
- and what follow-up is required.
"""

from collections import Counter
import json
from typing import Any

from shared.master_field_policy import field_policy_export
from shared.planner_field_governance import build_planner_field_governance
from shared.planner_registry import field_path_for_registry_field_id, planner_registry_fields
from shared.value_quality import contamination_reasons

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


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(str(value).split())


def clean_source_text(value: Any) -> str:
    cleaned = clean_text(value)
    return "" if cleaned.lower() in {"none", "null", "n/a", "na", "unknown", "no direct source found"} else cleaned


def _is_truthy_presence_value(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str):
        return clean_text(value).lower() not in {"false", "no", "none", "null", "unresolved", "not provided"}
    return True


def stringify_export_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return "[]"
        return ", ".join(stringify_export_value(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return "UNRESOLVED"
    return str(value)


def _accepted_candidate_for_entry(entry: dict[str, Any]) -> dict[str, Any]:
    candidates = entry.get("candidates") if isinstance(entry.get("candidates"), list) else []
    accepted_candidate_id = clean_text(entry.get("accepted_candidate_id"))
    if accepted_candidate_id:
        for candidate in candidates:
            if isinstance(candidate, dict) and clean_text(candidate.get("candidate_id")) == accepted_candidate_id:
                return candidate
    accepted_value = entry.get("accepted_value")
    if accepted_value is not None:
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("value") == accepted_value:
                return candidate
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("value") is not None:
            return candidate
    return {}


def _source_location_from_candidate(candidate: dict[str, Any], entry: dict[str, Any]) -> dict[str, str]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    source_refs = candidate.get("source_ref") if isinstance(candidate.get("source_ref"), list) else []
    source_anchor = clean_text(candidate.get("source_anchor")) or clean_text(entry.get("source_anchor"))
    document = (
        clean_source_text(candidate.get("source_document"))
        or clean_source_text(candidate.get("document_name"))
        or clean_source_text(candidate.get("filename"))
        or clean_source_text(candidate.get("artifact_name"))
        or clean_source_text(entry.get("source_document"))
        or clean_source_text(metadata.get("source_document"))
        or clean_source_text(metadata.get("source_document_name"))
        or clean_source_text(metadata.get("document_name"))
        or clean_source_text(metadata.get("filename"))
        or clean_source_text(metadata.get("file_name"))
        or clean_source_text(metadata.get("artifact_filename"))
        or clean_source_text(metadata.get("artifact_name"))
        or clean_source_text(metadata.get("source_artifact_id"))
        or (clean_source_text(source_refs[0]) if source_refs else "")
    )
    page = clean_text(candidate.get("source_page")) or clean_text(entry.get("source_page")) or clean_text(metadata.get("page_number")) or clean_text(metadata.get("page")) or clean_text(metadata.get("source_page"))
    section = (
        clean_text(candidate.get("source_section"))
        or clean_text(entry.get("source_section"))
        or clean_text(metadata.get("section_label"))
        or clean_text(metadata.get("section"))
        or clean_text(metadata.get("table_name"))
        or clean_text(metadata.get("table_label"))
        or clean_text(metadata.get("row_label"))
        or clean_text(metadata.get("line_label"))
    )
    line = clean_text(candidate.get("source_line")) or clean_text(entry.get("source_line")) or clean_text(metadata.get("line_number")) or clean_text(metadata.get("line")) or clean_text(metadata.get("row_number")) or clean_text(metadata.get("row"))
    if source_anchor:
        lower_anchor = source_anchor.lower()
        if not document:
            document = source_anchor.split("/")[0].strip()
        if not page and "page " in lower_anchor:
            tail = lower_anchor.split("page ", 1)[1].strip()
            page = tail.split("/", 1)[0].strip()
        if not section and "/" in source_anchor:
            parts = [part.strip() for part in source_anchor.split("/") if part.strip()]
            if len(parts) >= 3:
                section = parts[2]
    return {
        "source_document": document or "No direct source found",
        "source_page": page,
        "source_section": section,
        "source_line": line,
        "source_anchor": source_anchor,
    }



def _candidate_option_for_ledger(candidate: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Return a compact candidate option that can later be selected by adjudication."""
    location = _source_location_from_candidate(candidate, entry)
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    source_role = (
        clean_text(candidate.get("source_role"))
        or clean_text(entry.get("source_role"))
        or clean_text(metadata.get("source_role"))
        or clean_text(metadata.get("document_role"))
        or clean_text(candidate.get("source_hierarchy"))
        or clean_text(candidate.get("source_type"))
        or "unknown"
    )
    return {
        "candidate_id": clean_text(candidate.get("candidate_id")),
        "value": candidate.get("value"),
        "normalized_value": candidate.get("normalized_value", candidate.get("value")),
        "unit": clean_text(candidate.get("unit")),
        "confidence_score": candidate.get("confidence") if isinstance(candidate.get("confidence"), (int, float)) else candidate.get("score"),
        "confidence_band": clean_text(candidate.get("confidence_band")),
        "score": candidate.get("score") if isinstance(candidate.get("score"), (int, float)) else candidate.get("confidence"),
        "source_role": source_role,
            "semantic_role": "",
        "source_stage": clean_text(candidate.get("source_stage")),
        "source_stream": clean_text(candidate.get("source_stream")),
        "source_document": location["source_document"],
        "source_page": location["source_page"],
        "source_section": location["source_section"],
        "source_line": location["source_line"],
        "source_anchor": location["source_anchor"],
        "evidence_snippet": _evidence_snippet_for_entry(entry, candidate),
    }


def _candidate_options_for_entry(entry: dict[str, Any], *, max_options: int = 8) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for key in ("candidates", "alternatives", "candidate_evidence_appendix", "supporting_sources"):
        values = entry.get(key)
        if isinstance(values, list):
            raw.extend(item for item in values if isinstance(item, dict))
    seen: set[str] = set()
    options: list[dict[str, Any]] = []
    for candidate in raw:
        option = _candidate_option_for_ledger(candidate, entry)
        signature = json.dumps(
            [option.get("candidate_id"), option.get("value"), option.get("source_anchor")],
            sort_keys=True,
            default=str,
        )
        if signature in seen:
            continue
        seen.add(signature)
        options.append(option)
        if len(options) >= max_options:
            break
    return options

def _winner_reference_summary(entry: dict[str, Any]) -> str:
    trust_row = entry.get("planner_trust_row") if isinstance(entry.get("planner_trust_row"), dict) else {}
    evidence_route = entry.get("evidence_route_record") if isinstance(entry.get("evidence_route_record"), dict) else {}
    adjudication_notes = entry.get("adjudication_notes", []) if isinstance(entry.get("adjudication_notes"), list) else []
    candidates = [
        clean_text(trust_row.get("support_summary")),
        clean_text(entry.get("acceptance_rationale")),
        clean_text(entry.get("winner_summary")),
        clean_text(evidence_route.get("best_source_hierarchy")),
        clean_text(evidence_route.get("best_specificity")),
    ]
    candidates.extend(clean_text(item) for item in adjudication_notes[:2])
    for item in candidates:
        if item:
            return item
    return "Governed field-resolution ledger accepted this winner from the strongest available evidence path."


def _evidence_snippet_for_entry(entry: dict[str, Any], candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for value in (
        metadata.get("evidence_snippet"),
        metadata.get("snippet"),
        metadata.get("source_excerpt"),
        metadata.get("excerpt"),
        metadata.get("text"),
        candidate.get("evidence_snippet"),
        candidate.get("snippet"),
        candidate.get("source_anchor"),
        _winner_reference_summary(entry),
    ):
        cleaned = clean_text(value)
        if cleaned:
            return cleaned[:500]
    return "No direct evidence snippet preserved."


def _planner_field_status(entry: dict[str, Any], candidate: dict[str, Any]) -> str:
    status = (
        clean_text(entry.get("accepted_status"))
        or clean_text(entry.get("status"))
        or clean_text(entry.get("resolution_status"))
    ).lower() or "unresolved"
    applicant_state = clean_text(entry.get("applicant_answer_state")).lower()
    source_stream = clean_text(candidate.get("source_stream")).lower()
    conflict_materiality = clean_text(entry.get("conflict_materiality")).lower()
    release_profile = entry.get("field_release_profile") if isinstance(entry.get("field_release_profile"), dict) else {}
    release_state = clean_text(release_profile.get("release_state")).upper()
    release_tier = clean_text(release_profile.get("export_readiness_tier")).lower()
    future_study = clean_text(entry.get("field_policy_class")).lower() == "future_study" or clean_text(entry.get("accepted_value_kind")).lower() == "future_study"
    if future_study and status in {"missing", "unresolved"}:
        return "FUTURE_STUDY_REQUIRED"
    if status in {"missing", "unresolved"}:
        return "UNRESOLVED"
    if status == "not_applicable":
        return "NOT_APPLICABLE"
    if status == "conflicting" or conflict_materiality == "high":
        if source_stream == "interview" or applicant_state in {"confirmed", "supplied", "answered", "conflict_confirmed"}:
            return "INTERVIEW_CONFLICT_CONFIRMED"
        return "BLOCKED_BY_CONFLICT" if release_state == "BLOCKED" else "ACCEPTED_WITH_CONFLICT_NOTE"
    if release_tier == "blocked" or release_state == "BLOCKED":
        if status == "review_required":
            return "PROVISIONAL"
        return "BLOCKED_BY_MISSING_SOURCE"
    if source_stream == "interview":
        return "INTERVIEW_SUPPLIED"
    if applicant_state in {"confirmed", "document_confirmed", "confirmed_document_value"}:
        return "INTERVIEW_CONFIRMED"
    if status in {"resolved", "accepted"}:
        return "ACCEPTED" if not bool(entry.get("planner_review_flag", False)) else "PROVISIONAL"
    if status == "review_required":
        return "PROVISIONAL"
    return "PROVISIONAL"


def _manual_review_reason_for_entry(entry: dict[str, Any]) -> str:
    reasons: list[str] = []
    if bool(entry.get("planner_review_flag", False)):
        reasons.append("planner review flag set")
    if bool(entry.get("needs_applicant_confirmation", False)):
        reasons.append("applicant confirmation needed")
    conflict_profile = entry.get("conflict_profile") if isinstance(entry.get("conflict_profile"), dict) else {}
    conflict = clean_text(entry.get("contradiction_summary")) or clean_text(conflict_profile.get("summary")) or clean_text(conflict_profile.get("conflict_summary"))
    if conflict:
        reasons.append(conflict)
    unresolved = clean_text(entry.get("unresolved_reason"))
    if unresolved:
        reasons.append(unresolved)
    policy = entry.get("acceptance_policy_result") if isinstance(entry.get("acceptance_policy_result"), dict) else {}
    for item in policy.get("reasons", []) if isinstance(policy.get("reasons"), list) else []:
        cleaned = clean_text(item)
        if cleaned and cleaned not in reasons:
            reasons.append(cleaned)
    return "; ".join(reasons[:3])


def _ledger_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        0 if row.get("planner_critical") else 1,
        clean_text(row.get("packet_section_label")) or clean_text(row.get("packet_section")),
        clean_text(row.get("field_label")),
        clean_text(row.get("field_id")) or clean_text(row.get("field_path")),
    )



def _registry_missing_posture(field: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """Classify registry-backfilled missing rows without overblocking intake.

    The complete 524-field ledger is intentionally registry-complete, but not
    every absent field is an application defect.  Fields tied to detailed
    design, later studies, relay setting finalization, commissioning, or utility
    review should stay visible as future-study/provisional items instead of
    becoming applicant-blocking questions.
    """
    field_id = clean_text(field.get("field_id")).lower()
    label = clean_text(field.get("label")).lower()
    notes = clean_text(field.get("notes")).lower()
    requiredness = clean_text(policy.get("requiredness") or field.get("requiredness")).lower() or "optional"
    used_in = " ".join(clean_text(item).lower() for item in field.get("used_in_studies", []) if isinstance(item, str)) if isinstance(field.get("used_in_studies"), list) else ""
    touchpoints = " ".join(clean_text(item).lower() for item in field.get("pipeline_touchpoints", []) if isinstance(item, str)) if isinstance(field.get("pipeline_touchpoints"), list) else ""
    blob = " ".join([field_id, label, notes, used_in, touchpoints])

    later_stage_tokens = {
        "detailed", "final", "relay setting", "relay-settings", "short-circuit",
        "short circuit", "harmonic", "grounding", "commissioning", "as-left",
        "as left", "ct ratio", "pt ratio", "fault", "dynamic model", "study",
        "utility review", "to review", "telemetry point list", "rtu database",
    }
    if requiredness == "optional":
        return {
            "status": "NOT_APPLICABLE",
            "release_state": "PROVISIONAL",
            "export_readiness_tier": "warning",
            "planner_packet_use_policy": "show_as_not_applicable_or_not_provided",
            "reason": "Optional registry field was not found in the intake package; preserve as not provided rather than applicant-blocking.",
            "next_action": "none",
        }
    if requiredness == "conditional_required" and any(token in blob for token in later_stage_tokens):
        return {
            "status": "FUTURE_STUDY_REQUIRED",
            "release_state": "PROVISIONAL",
            "export_readiness_tier": "warning",
            "planner_packet_use_policy": "show_as_future_study_or_detailed_design_item",
            "reason": "Conditional registry field appears to belong to later study, detailed design, utility review, or commissioning deliverables.",
            "next_action": "future_study_or_detailed_design",
        }
    if requiredness == "conditional_required" and "application_completeness" not in used_in:
        return {
            "status": "FUTURE_STUDY_REQUIRED",
            "release_state": "PROVISIONAL",
            "export_readiness_tier": "warning",
            "planner_packet_use_policy": "show_as_conditional_not_yet_resolved",
            "reason": "Conditional registry field was not found and is not explicitly required for application-completeness at intake.",
            "next_action": "conditional_followup_if_applicable",
        }
    return {
        "status": "UNRESOLVED",
        "release_state": "BLOCKED",
        "export_readiness_tier": "blocked",
        "planner_packet_use_policy": "show_as_unresolved",
        "reason": "Required intake/application field has no resolved candidate.",
        "next_action": "applicant_or_engineering_followup",
    }

def _registry_unresolved_row(field: dict[str, Any]) -> dict[str, Any]:
    field_id = clean_text(field.get("field_id"))
    field_path = clean_text(field_path_for_registry_field_id(field_id)) or field_id
    policy = field_policy_export(field_path or field_id)
    posture = _registry_missing_posture(field, policy)
    is_critical = bool(policy.get("planner_critical", False))
    return {
        "ledger_contract_version": "planner_field_ledger_v2",
        "field_path": field_path,
        "field_id": field_id,
        "field_label": clean_text(field.get("label")) or clean_text(policy.get("field_label")) or field_id,
        "field_definition": clean_text(policy.get("definition")),
        "expected_data_type": clean_text(policy.get("data_type")),
        "expected_unit": clean_text(policy.get("expected_unit")),
        "policy_family": clean_text(policy.get("policy_family")) or "general",
        "preferred_source_roles": policy.get("preferred_source_roles", {}) if isinstance(policy.get("preferred_source_roles"), dict) else {},
        "accepted_value": "UNRESOLVED",
        "normalized_value": "UNRESOLVED",
        "unit": clean_text(policy.get("expected_unit")),
        "confidence_score": 0.0,
        "confidence_band": "UNRESOLVED",
        "status": posture["status"],
        "release_state": posture["release_state"],
        "export_readiness_tier": posture["export_readiness_tier"],
        "translation_use_policy": "do_not_use",
        "scenario_use_policy": "do_not_use",
        "planner_packet_use_policy": posture["planner_packet_use_policy"],
        "source_document": "No direct source found",
        "source_page": "",
        "source_section": "",
        "source_line": "",
        "source_anchor": "",
        "evidence_snippet": "No direct evidence preserved for this master planner field.",
        "source_role": "none",
        "candidate_count": 0,
        "conflict_summary": "",
        "conflict_materiality": "none",
        "interview_status": "not_used",
        "manual_review_reason": posture["reason"],
        "unresolved_reason": posture["reason"],
        "planner_critical": is_critical,
        "requiredness": clean_text(policy.get("requiredness")) or "optional",
        "packet_section": clean_text(field.get("packet_section")),
        "packet_section_label": clean_text(field.get("packet_section")),
        "accepted_candidate_id": "",
        "acceptance_policy_outcome": posture["status"].lower(),
        "acceptance_policy_next_action": posture["next_action"],
        "adjudication_trace": {},
        "registry_backfilled": True,
    }


def _presence_candidate_for_entry(field_id: str, entry: dict[str, Any], current_candidate: dict[str, Any]) -> dict[str, Any]:
    """Select a source-appropriate candidate for *_present boolean fields.

    Presence fields should export a compact boolean, not raw parsed rows.  This
    also keeps unrelated phasing/milestone tables from being promoted as an
    equipment or motor schedule merely because they were table-shaped.
    """
    expected_role_tokens: tuple[str, ...]
    if field_id == "equipment_schedule_present":
        expected_role_tokens = ("equipment_schedule", "technical_particulars", "major_equipment")
    elif field_id == "motor_schedule_present":
        expected_role_tokens = ("motor_schedule", "motor")
    else:
        return current_candidate

    candidates = entry.get("candidates") if isinstance(entry.get("candidates"), list) else []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        role_blob = " ".join(
            clean_text(value).lower()
            for value in (
                candidate.get("source_role"),
                candidate.get("source_hierarchy"),
                candidate.get("source_type"),
                candidate.get("source_document"),
                metadata.get("source_role"),
                metadata.get("document_role"),
                metadata.get("source_document"),
            )
        )
        if any(token in role_blob for token in expected_role_tokens) and _is_truthy_presence_value(candidate.get("value")):
            return candidate
    return current_candidate


def _planner_export_value(field_id: str, expected_data_type: str, value: Any) -> Any:
    if expected_data_type == "boolean" and field_id.endswith("_present"):
        return bool(_is_truthy_presence_value(value))
    return stringify_export_value(value) if value is not None else "UNRESOLVED"


def _is_rejected_titleblock_date(row: dict[str, Any]) -> bool:
    field_id = clean_text(row.get("field_id")).lower()
    if not any(token in field_id for token in ("date", "in_service", "energization", "cod", "operation")):
        return False
    source_role = clean_text(row.get("source_role")).lower()
    blob = " ".join(
        clean_text(row.get(key)).lower()
        for key in ("source_section", "source_anchor", "evidence_snippet", "manual_review_reason", "conflict_summary")
    )
    date_text = clean_text(row.get("accepted_value")).lower()
    milestone_context = any(token in blob for token in ("energization", "in-service", "in service", "commercial operation", "operation date", "target date", "milestone"))
    title_context = any(token in blob for token in ("rev", "revision", "drawn", "chk", "checked", "sheet", "title block", "issued for", "date description"))
    return bool((source_role in {"drawing", "one_line_diagram", "site_plan"} or title_context) and title_context and not milestone_context and date_text)


def _infer_semantic_role_for_row(row: dict[str, Any]) -> str:
    field_id = clean_text(row.get("field_id")).lower()
    field_path = clean_text(row.get("field_path")).lower()
    blob = " ".join(clean_text(row.get(key)).lower() for key in ("field_label", "source_section", "source_anchor", "evidence_snippet", "source_role"))
    target = f"{field_id} {field_path} {blob}"
    if any(token in target for token in ("poi", "point of interconnection", "service voltage", "utility service", "transmission")):
        return "poi_or_service_voltage"
    if any(token in target for token in ("high side", "primary", "transformer primary")):
        return "transformer_high_side_voltage"
    if any(token in target for token in ("low side", "secondary", "transformer secondary", "13.8")):
        return "transformer_low_side_or_campus_mv"
    if any(token in target for token in ("generator terminal", "genset terminal")):
        return "generator_terminal_voltage"
    if any(token in target for token in ("ups", "pdu", "480", "output voltage", "load distribution")):
        return "load_distribution_voltage"
    if any(token in target for token in ("ultimate", "coincident", "maximum demand")):
        return "ultimate_or_coincident_demand"
    if any(token in target for token in ("phase 1", "phase_1")):
        return "phase_1_demand"
    if any(token in target for token in ("phase 2", "phase_2")):
        return "phase_2_demand"
    if any(token in target for token in ("phase 3", "phase_3")):
        return "phase_3_demand"
    return ""


def _is_semantic_role_mismatch(row: dict[str, Any]) -> bool:
    field_id = clean_text(row.get("field_id")).lower()
    field_path = clean_text(row.get("field_path")).lower()
    role = clean_text(row.get("semantic_role")).lower() or _infer_semantic_role_for_row(row)
    if "poi_voltage" in f"{field_id} {field_path}" and role in {"load_distribution_voltage", "generator_terminal_voltage"}:
        return True
    if "phase_1" in f"{field_id} {field_path}" and role in {"phase_2_demand", "phase_3_demand", "ultimate_or_coincident_demand"}:
        return True
    if "phase_2" in f"{field_id} {field_path}" and role in {"phase_1_demand", "phase_3_demand", "ultimate_or_coincident_demand"}:
        return True
    if "phase_3" in f"{field_id} {field_path}" and role in {"phase_1_demand", "phase_2_demand", "ultimate_or_coincident_demand"}:
        return True
    return False

def _is_rejected_source_region_for_load_phase(row: dict[str, Any]) -> bool:
    field_id = clean_text(row.get("field_id")).lower()
    field_path = clean_text(row.get("field_path")).lower()
    if not any(token in f"{field_id} {field_path}" for token in ("phase_1_mw", "phase_2_mw", "phase_3_mw", "phase_", "demand_mw")):
        return False
    source_role = clean_text(row.get("source_role")).lower()
    blob = " ".join(
        clean_text(row.get(key)).lower()
        for key in ("source_section", "source_anchor", "evidence_snippet", "manual_review_reason", "conflict_summary")
    )
    value = row.get("accepted_value")
    try:
        numeric = float(str(value).replace(",", ""))
    except Exception:
        numeric = None
    forbidden_context = any(token in f"{source_role} {blob}" for token in ("title_block", "revision", "rev table", "drawing index", "sheet index", "page number", "row id", "equipment id"))
    load_context = any(token in blob for token in ("mw", "mva", "load", "demand", "phase demand", "buildout", "coincident")) or source_role in {"load_schedule", "project_summary_load_schedule", "application_request_form"}
    tiny_uncontexted = numeric is not None and numeric <= 3.0 and not load_context
    return bool(forbidden_context or tiny_uncontexted)


def _apply_final_row_guards(row: dict[str, Any]) -> None:
    if _is_rejected_titleblock_date(row):
        row["status"] = "UNRESOLVED"
        row["release_state"] = "BLOCKED" if bool(row.get("planner_critical")) else "PROVISIONAL"
        row["export_readiness_tier"] = "blocked" if bool(row.get("planner_critical")) else "warning"
        row["translation_use_policy"] = "do_not_use"
        row["scenario_use_policy"] = "do_not_use"
        row["planner_packet_use_policy"] = "show_as_unresolved_titleblock_date_rejected"
        row["manual_review_reason"] = (clean_text(row.get("manual_review_reason")) + "; " if clean_text(row.get("manual_review_reason")) else "") + "Rejected drawing/title-block date for project milestone field."
        row["unresolved_reason"] = "Drawing/title-block/revision date cannot satisfy project milestone date field."
    if _is_rejected_source_region_for_load_phase(row):
        row["status"] = "UNRESOLVED"
        row["release_state"] = "BLOCKED" if bool(row.get("planner_critical")) else "PROVISIONAL"
        row["export_readiness_tier"] = "blocked" if bool(row.get("planner_critical")) else "warning"
        row["translation_use_policy"] = "do_not_use"
        row["scenario_use_policy"] = "do_not_use"
        row["planner_packet_use_policy"] = "show_as_unresolved_source_region_rejected"
        row["manual_review_reason"] = (clean_text(row.get("manual_review_reason")) + "; " if clean_text(row.get("manual_review_reason")) else "") + "Rejected non-load/revision/title-block source region for phase MW field."
        row["unresolved_reason"] = "Phase MW value requires load/demand context and cannot be sourced from drawing indexes, revision/title blocks, or uncontexted tiny numeric labels."
    if _is_semantic_role_mismatch(row):
        row["status"] = "UNRESOLVED"
        row["release_state"] = "BLOCKED" if bool(row.get("planner_critical")) else "PROVISIONAL"
        row["export_readiness_tier"] = "blocked" if bool(row.get("planner_critical")) else "warning"
        row["translation_use_policy"] = "do_not_use"
        row["scenario_use_policy"] = "do_not_use"
        row["planner_packet_use_policy"] = "show_as_unresolved_semantic_role_mismatch"
        row["manual_review_reason"] = (clean_text(row.get("manual_review_reason")) + "; " if clean_text(row.get("manual_review_reason")) else "") + "Rejected candidate whose semantic voltage/load role does not match the target planner field."
        row["unresolved_reason"] = "Candidate semantic role does not match target planner field role."




def _normalize_planner_confidence_score(value: object, band: str = "") -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = {"HIGH": 0.9, "MODERATE": 0.65, "LOW": 0.35, "UNRESOLVED": 0.0}.get(clean_text(band).upper(), 0.0)
    if score > 1.0:
        # Internal rank/support scores can be larger than 1.0. Planner-facing confidence is probability-like.
        score = score / 100.0 if score <= 100.0 else 1.0
    if score < 0.0:
        score = 0.0
    if score > 1.0:
        score = 1.0
    return round(score, 3)


def _confidence_band_from_score(score: float, fallback: str = "") -> str:
    normalized_fallback = clean_text(fallback).upper()
    if normalized_fallback == "UNRESOLVED" and score <= 0.0:
        return "UNRESOLVED"
    if score >= 0.85:
        return "HIGH"
    if score >= 0.60:
        return "MODERATE"
    if score > 0.0:
        return "LOW"
    return normalized_fallback or "UNRESOLVED"



def _apply_contamination_guard(row: dict[str, Any]) -> None:
    reasons = contamination_reasons(
        str(row.get("field_path") or row.get("field_id") or ""),
        row.get("accepted_value"),
        {
            "source_role": row.get("source_role"),
            "source_method": row.get("source_method"),
            "document_role": row.get("source_role"),
        },
    )
    if not reasons:
        return

    existing_reason = clean_text(row.get("manual_review_reason"))
    contamination_reason = "Rejected contaminated candidate: " + "; ".join(reasons)
    row["status"] = "UNRESOLVED"
    row["release_state"] = "BLOCKED" if bool(row.get("planner_critical")) else "PROVISIONAL"
    row["export_readiness_tier"] = "blocked" if bool(row.get("planner_critical")) else "warning"
    row["translation_use_policy"] = "do_not_use"
    row["scenario_use_policy"] = "do_not_use"
    row["planner_packet_use_policy"] = "show_as_rejected_contaminated"
    row["manual_review_reason"] = (
        f"{existing_reason}; {contamination_reason}" if existing_reason else contamination_reason
    )
    row["unresolved_reason"] = contamination_reason
    row["contamination_reasons"] = reasons
    row["accepted_value"] = "UNRESOLVED"
    row["normalized_value"] = "UNRESOLVED"



def _repair_adjudication_trace_value(row: dict[str, object]) -> None:
    trace = row.get("adjudication_trace")
    if not isinstance(trace, dict):
        return
    accepted_text = clean_text(row.get("accepted_value"))
    unit = clean_text(row.get("unit"))
    if not accepted_text or accepted_text.upper() == "UNRESOLVED":
        return
    accepted_with_unit = f"{accepted_text} {unit}".strip()
    trace["accepted_value_text"] = accepted_with_unit
    narrative = clean_text(trace.get("planner_narrative"))
    label = clean_text(row.get("field_label")) or clean_text(row.get("field_path")) or "Field"
    status = clean_text(row.get("status")).lower() or "accepted"
    band = clean_text(row.get("confidence_band")) or "UNRESOLVED"
    prefix = f"{label} accepted {accepted_with_unit} with status {status} and confidence {band}."
    if narrative:
        # Replace only the first sentence, which is generated from accepted value.
        rest = narrative.split(".", 1)[1].strip() if "." in narrative else ""
        trace["planner_narrative"] = f"{prefix} {rest}".strip()
    else:
        trace["planner_narrative"] = prefix


def build_planner_field_ledger(field_resolution_ledger: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    covered_field_ids: set[str] = set()
    covered_field_paths: set[str] = set()
    for entry in field_resolution_ledger if isinstance(field_resolution_ledger, list) else []:
        if not isinstance(entry, dict):
            continue
        candidate = _accepted_candidate_for_entry(entry)
        location = _source_location_from_candidate(candidate, entry)
        status = _planner_field_status(entry, candidate)
        candidate_summary = entry.get("candidate_summary") if isinstance(entry.get("candidate_summary"), dict) else {}
        conflict_profile = entry.get("conflict_profile") if isinstance(entry.get("conflict_profile"), dict) else {}
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        policy = field_policy_export(entry.get("field_id") or entry.get("field_path"))
        field_path = clean_text(entry.get("field_path")) or clean_text(policy.get("field_path")) or clean_text(entry.get("field_id"))
        field_id = clean_text(policy.get("field_id")) or clean_text(entry.get("field_id")) or field_path
        candidate = _presence_candidate_for_entry(field_id, entry, candidate)
        normalized_value = candidate.get("value") if candidate else entry.get("accepted_value")
        accepted_value = True if clean_text(policy.get("data_type")) == "boolean" and field_id.endswith("_present") and _is_truthy_presence_value(normalized_value) else entry.get("accepted_value")
        unresolved_reason = clean_text(entry.get("unresolved_reason"))
        if status in BLOCKED_LEDGER_STATUSES and not unresolved_reason:
            unresolved_reason = "No accepted candidate met source/confidence requirements."
        source_role = (
            clean_text(metadata.get("source_role"))
            or clean_text(metadata.get("document_role"))
            or clean_text(candidate.get("source_hierarchy"))
            or clean_text(entry.get("accepted_source_hierarchy"))
            or "unknown"
        )
        release_profile = entry.get("field_release_profile") if isinstance(entry.get("field_release_profile"), dict) else {}
        acceptance_policy = entry.get("acceptance_policy_result") if isinstance(entry.get("acceptance_policy_result"), dict) else {}
        row = {
            "ledger_contract_version": "planner_field_ledger_v2",
            "field_path": field_path,
            "field_id": field_id,
            "field_label": clean_text(entry.get("label")) or clean_text(policy.get("field_label")) or field_id,
            "field_definition": clean_text(policy.get("definition")),
            "expected_data_type": clean_text(policy.get("data_type")),
            "expected_unit": clean_text(policy.get("expected_unit")),
            "policy_family": clean_text(policy.get("policy_family")) or "general",
            "preferred_source_roles": policy.get("preferred_source_roles", {}) if isinstance(policy.get("preferred_source_roles"), dict) else {},
            "accepted_value": _planner_export_value(field_id, clean_text(policy.get("data_type")), accepted_value),
            "normalized_value": _planner_export_value(field_id, clean_text(policy.get("data_type")), normalized_value),
            "unit": clean_text(entry.get("accepted_unit")) or clean_text(candidate.get("unit")) or clean_text(policy.get("expected_unit")),
                        "confidence_score": _normalize_planner_confidence_score(
                entry.get("accepted_confidence") if isinstance(entry.get("accepted_confidence"), (int, float)) else entry.get("confidence_score"),
                clean_text(entry.get("confidence_band")) or clean_text(candidate.get("confidence_band")),
            ),
            "confidence_band": _confidence_band_from_score(
                _normalize_planner_confidence_score(
                    entry.get("accepted_confidence") if isinstance(entry.get("accepted_confidence"), (int, float)) else entry.get("confidence_score"),
                    clean_text(entry.get("confidence_band")) or clean_text(candidate.get("confidence_band")),
                ),
                clean_text(entry.get("confidence_band")) or clean_text(candidate.get("confidence_band")),
            ),
            "status": status,
            "release_state": clean_text(release_profile.get("release_state")) or ("READY" if status in ACCEPTED_LEDGER_STATUSES else "BLOCKED" if status in BLOCKED_LEDGER_STATUSES else "PROVISIONAL"),
            "export_readiness_tier": clean_text(release_profile.get("export_readiness_tier")),
            "translation_use_policy": clean_text(release_profile.get("translation_use_policy")),
            "scenario_use_policy": clean_text(release_profile.get("scenario_use_policy")),
            "planner_packet_use_policy": clean_text(release_profile.get("planner_packet_use_policy")),
            "source_document": location["source_document"],
            "source_page": location["source_page"],
            "source_section": location["source_section"],
            "source_line": location["source_line"],
            "source_anchor": location["source_anchor"],
            "evidence_snippet": _evidence_snippet_for_entry(entry, candidate),
            "source_role": source_role,
            "semantic_role": "",
            "candidate_count": int(candidate_summary.get("candidate_count", len(entry.get("candidates", [])) if isinstance(entry.get("candidates"), list) else 0) or 0),
            "conflict_summary": clean_text(entry.get("contradiction_summary")) or clean_text(conflict_profile.get("summary")) or clean_text(conflict_profile.get("conflict_summary")),
            "conflict_materiality": clean_text(entry.get("conflict_materiality")) or clean_text(conflict_profile.get("conflict_materiality")) or "none",
            "interview_status": clean_text(entry.get("applicant_answer_state")) or "not_used",
            "manual_review_reason": _manual_review_reason_for_entry(entry),
            "unresolved_reason": unresolved_reason,
            "planner_critical": bool(entry.get("planner_critical", False) or policy.get("planner_critical", False)),
            "requiredness": clean_text(entry.get("requiredness")) or clean_text(policy.get("requiredness")) or "optional",
            "packet_section": clean_text(entry.get("packet_section")),
            "packet_section_label": clean_text(entry.get("packet_section_label")),
            "accepted_candidate_id": clean_text(entry.get("accepted_candidate_id")),
            "candidate_options": _candidate_options_for_entry(entry),
            "acceptance_policy_outcome": clean_text(acceptance_policy.get("outcome")),
            "acceptance_policy_next_action": clean_text(acceptance_policy.get("required_next_action")),
            "adjudication_trace": entry.get("adjudication_trace", {}) if isinstance(entry.get("adjudication_trace"), dict) else {},
            "registry_backfilled": False,
        }
        if row["status"] in ACCEPTED_LEDGER_STATUSES and row["source_document"] == "No direct source found":
            row["status"] = "PROVISIONAL"
            row["manual_review_reason"] = (row["manual_review_reason"] + "; " if row["manual_review_reason"] else "") + "accepted value lacks source location"
            row["release_state"] = "PROVISIONAL"
            row["planner_packet_use_policy"] = row["planner_packet_use_policy"] or "show_as_provisional"
        row["semantic_role"] = _infer_semantic_role_for_row(row)
        _apply_contamination_guard(row)
        _apply_final_row_guards(row)
        _repair_adjudication_trace_value(row)
        rows.append(row)
        if field_id:
            covered_field_ids.add(field_id)
        if field_path:
            covered_field_paths.add(field_path)

    for field in planner_registry_fields():
        field_id = clean_text(field.get("field_id"))
        if not field_id:
            continue
        field_path = clean_text(field_path_for_registry_field_id(field_id)) or field_id
        if field_id in covered_field_ids or field_path in covered_field_paths:
            continue
        row = _registry_unresolved_row(field)
        rows.append(row)
        covered_field_ids.add(field_id)
        covered_field_paths.add(field_path)

    rows.sort(key=_ledger_sort_key)
    return rows
def planner_field_ledger_summary(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = rows if isinstance(rows, list) else []
    status_counts = Counter(clean_text(row.get("status")) or "UNKNOWN" for row in rows if isinstance(row, dict))
    unresolved_reason_counts = Counter(
        clean_text(row.get("unresolved_reason")) or clean_text(row.get("manual_review_reason")) or "Unspecified"
        for row in rows
        if isinstance(row, dict) and clean_text(row.get("status")) in BLOCKED_LEDGER_STATUSES
    )
    planner_critical_rows = [row for row in rows if isinstance(row, dict) and bool(row.get("planner_critical", False))]
    critical_blocked = [row for row in planner_critical_rows if clean_text(row.get("status")) in BLOCKED_LEDGER_STATUSES]
    critical_provisional = [row for row in planner_critical_rows if clean_text(row.get("status")) in PROVISIONAL_LEDGER_STATUSES or clean_text(row.get("release_state")).upper() == "PROVISIONAL"]
    registry_fields = planner_registry_fields()
    registry_ids = {clean_text(field.get("field_id")) for field in registry_fields if isinstance(field, dict) and clean_text(field.get("field_id"))}
    row_ids = {clean_text(row.get("field_id")) for row in rows if isinstance(row, dict) and clean_text(row.get("field_id"))}
    registry_complete = registry_ids.issubset(row_ids)
    return {
        "contract_version": "planner_field_ledger_v2",
        "field_count": len(rows),
        "registry_complete": registry_complete,
        "registry_field_count": len(registry_ids),
        "missing_registry_field_count": len(registry_ids - row_ids),
        "registry_completion": {
            "registry_field_count": len(registry_ids),
            "ledger_field_count": len(rows),
            "missing_registry_field_count": len(registry_ids - row_ids),
            "registry_complete": registry_complete,
        },
        "registry_completion_audit": {
            "registry_field_count": len(registry_ids),
            "ledger_field_count": len(rows),
            "missing_registry_field_count": len(registry_ids - row_ids),
            "registry_complete": registry_complete,
        },
        "planner_critical_count": len(planner_critical_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "accepted_count": sum(status_counts.get(key, 0) for key in ACCEPTED_LEDGER_STATUSES),
        "provisional_count": status_counts.get("PROVISIONAL", 0),
        "unresolved_or_blocked_count": sum(count for status, count in status_counts.items() if status.startswith("BLOCKED") or status == "UNRESOLVED"),
        "planner_critical_blocked_count": len(critical_blocked),
        "planner_critical_provisional_count": len(critical_provisional),
        "unresolved_reason_counts": dict(unresolved_reason_counts.most_common()),
        "release_blocked": bool(critical_blocked),
        "release_requires_manual_review": bool(critical_blocked or critical_provisional),
    }


def build_source_index_from_planner_ledger(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        document = clean_text(row.get("source_document")) or "No direct source found"
        role = clean_text(row.get("source_role")) or "unknown"
        key = (document, role)
        bucket = grouped.setdefault(key, {"source_document": document, "source_role": role, "field_count": 0, "pages": set()})
        bucket["field_count"] += 1
        page = clean_text(row.get("source_page"))
        if page:
            bucket["pages"].add(page)
    result = []
    for bucket in grouped.values():
        result.append({
            "source_document": bucket["source_document"],
            "source_role": bucket["source_role"],
            "field_count": bucket["field_count"],
            "pages": sorted(bucket["pages"]),
        })
    result.sort(key=lambda item: (1 if item.get("source_document", "") == "No direct source found" else 0, -int(item.get("field_count", 0)), item.get("source_document", "")))
    return result


def planner_field_contract_from_canonical(canonical_state_result: dict[str, Any] | None) -> dict[str, Any]:
    payload = canonical_state_result if isinstance(canonical_state_result, dict) else {}
    canonical_state = payload.get("canonical_state") if isinstance(payload.get("canonical_state"), dict) else payload
    field_resolution = canonical_state.get("field_resolution", {}) if isinstance(canonical_state, dict) else {}
    ledger = field_resolution.get("ledger", []) if isinstance(field_resolution, dict) and isinstance(field_resolution.get("ledger"), list) else []
    rows = build_planner_field_ledger(ledger)
    governance = build_planner_field_governance(rows)
    return {
        "contract_version": "planner_field_ledger_v2",
        "planner_field_ledger": rows,
        "planner_field_ledger_summary": planner_field_ledger_summary(rows),
        "planner_field_governance": governance,
        "source_index": build_source_index_from_planner_ledger(rows),
    }
