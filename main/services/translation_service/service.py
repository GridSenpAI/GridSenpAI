from __future__ import annotations

from typing import Any

from shared.gap_resolution_utils import resolve_gap_resolution_stage_inputs
from shared.governed_summary import build_governed_summary
from shared.ledger_downstream_governance import (
    apply_ledger_governance_to_parameters,
    resolve_planner_ledger_value,
)
from shared.ledger_native_translation import (
    build_ledger_first_translation_inputs,
    build_ledger_native_translation_contract,
)
from shared.review_priority import build_field_governance_core
from shared.planner_registry import (
    build_translation_runtime_schema_validation,
    planner_translation_output_defaults,
    resolve_registry_field_value,
    translation_parameter_config,
)

from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent
from services.translation_service.utils import (
    build_confidence_factors,
    compute_confidence_score,
    get_dependency_paths,
    get_nested_value,
    get_source_field_paths,
    get_supporting_snippet_ids,
    map_confidence_tag,
    safe_float,
    set_nested_value,
    utc_now_iso,
)



def _require_run_id(context: Any) -> str:
    run_id = getattr(context, "run_id", None)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("context.run_id must be a non-empty string.")
    return run_id.strip()


def _build_canonical_state_from_stage_inputs(
    normalization_result: dict[str, Any] | None,
    retrieval_result: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_input: dict[str, Any] = {}
    validation_report: dict[str, Any] = {}
    evidence_snippets: list[dict[str, Any]] = []

    if isinstance(normalization_result, dict):
        normalized_input = normalization_result.get("normalized_input", {})
        validation_report = normalization_result.get("validation_report", {})

    if isinstance(retrieval_result, dict):
        evidence_snippets = retrieval_result.get("snippets", [])

    if not isinstance(normalized_input, dict):
        normalized_input = {}
    if not isinstance(validation_report, dict):
        validation_report = {}
    if not isinstance(evidence_snippets, list):
        evidence_snippets = []

    return {
        "normalized_input": normalized_input,
        "validation_report": validation_report,
        "evidence_snippets": evidence_snippets,
        "engineering_model": None,
    }


def _governed_truth_summary(canonical_state: dict[str, Any], validation_report: dict[str, Any] | None) -> dict[str, Any]:
    summary = canonical_state.get("governed_truth_summary") if isinstance(canonical_state.get("governed_truth_summary"), dict) else {}
    if isinstance(summary, dict) and summary:
        return dict(summary)
    return build_governed_summary(
        canonical_state,
        {"validation_report": validation_report} if isinstance(validation_report, dict) else None,
    )


def _governance_alerts_from_summary(summary: dict[str, Any], manual_review_queue: dict[str, Any] | None = None, field_governance_core: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = summary if isinstance(summary, dict) else {}
    review_queue = manual_review_queue if isinstance(manual_review_queue, dict) else {}
    review_summary = review_queue.get("summary") if isinstance(review_queue.get("summary"), dict) else {}
    planner_review_count = int(payload.get("planner_review_count", 0) or 0)
    applicant_confirmation_needed_count = int(payload.get("applicant_confirmation_needed_count", 0) or 0)
    high_materiality_conflict_count = int(payload.get("high_materiality_conflict_count", 0) or 0)
    conflicting_count = int(payload.get("conflicting_count", 0) or 0)
    review_required_count = int(payload.get("review_required_count", 0) or 0)
    manual_review_total_count = int(review_summary.get("total_count", 0) or 0)
    manual_review_planner_critical_count = int(review_summary.get("planner_critical_count", 0) or 0)
    manual_review_conflict_count = int(review_summary.get("conflict_count", 0) or 0)
    manual_review_interview_dependency_count = int(review_summary.get("interview_dependency_count", 0) or 0)
    manual_review_deterministic_override_count = int(review_summary.get("deterministic_override_count", 0) or 0)
    governance_core = field_governance_core if isinstance(field_governance_core, dict) else {}
    escalation_summary = governance_core.get("escalation_registry", {}).get("summary", {}) if isinstance(governance_core.get("escalation_registry", {}), dict) else {}
    transition_summary = governance_core.get("stage_transition_decisions", {}).get("summary", {}) if isinstance(governance_core.get("stage_transition_decisions", {}), dict) else {}
    field_governance_summary = governance_core.get("field_governance_registry", {}).get("summary", {}) if isinstance(governance_core.get("field_governance_registry", {}), dict) else {}
    release_summary = governance_core.get("governed_release_decision", {}).get("summary", {}) if isinstance(governance_core.get("governed_release_decision", {}), dict) else {}
    high_priority_manual_review_count = (
        manual_review_conflict_count
        + manual_review_interview_dependency_count
        + manual_review_deterministic_override_count
    )
    return {
        "planner_review_count": planner_review_count,
        "applicant_confirmation_needed_count": applicant_confirmation_needed_count,
        "high_materiality_conflict_count": high_materiality_conflict_count,
        "conflicting_count": conflicting_count,
        "review_required_count": review_required_count,
        "manual_review_queue_summary": dict(review_summary),
        "manual_review_total_count": manual_review_total_count,
        "manual_review_planner_critical_count": manual_review_planner_critical_count,
        "manual_review_conflict_count": manual_review_conflict_count,
        "manual_review_interview_dependency_count": manual_review_interview_dependency_count,
        "manual_review_deterministic_override_count": manual_review_deterministic_override_count,
        "high_priority_manual_review_count": high_priority_manual_review_count,
        "top_backlog_field_ids": list(payload.get("top_backlog_field_ids", []))[:10] if isinstance(payload.get("top_backlog_field_ids", []), list) else [],
        "escalation_registry_summary": dict(escalation_summary),
        "stage_transition_summary": dict(transition_summary),
        "field_governance_summary": dict(field_governance_summary),
        "governed_release_summary": dict(release_summary),
        "has_governance_attention": any(
            count > 0
            for count in (
                planner_review_count,
                applicant_confirmation_needed_count,
                high_materiality_conflict_count,
                conflicting_count,
                review_required_count,
                manual_review_total_count,
            )
        ),
    }




def _apply_shared_review_priority_gating(
    output_parameters: list[dict[str, Any]],
    manual_review_queue: dict[str, Any] | None,
) -> None:
    review_queue = manual_review_queue if isinstance(manual_review_queue, dict) else {}
    groups = review_queue.get("groups") if isinstance(review_queue.get("groups"), dict) else {}
    field_priority: dict[str, tuple[str, str, bool]] = {}
    for bucket, items in groups.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            bucket_value = str(bucket).strip() or "manual_review"
            reason_value = str(item.get("reason", "")).strip() or "Manual review queue requires planner attention."
            critical_value = bool(item.get("planner_critical", False))
            for key in (str(item.get("field_path", "")).strip(), str(item.get("field_id", "")).strip()):
                if not key or key in field_priority:
                    continue
                field_priority[key] = (bucket_value, reason_value, critical_value)

    for parameter in output_parameters:
        if not isinstance(parameter, dict):
            continue
        source_paths = {str(v).strip() for v in parameter.get("source_field_paths", []) if str(v).strip()}
        source_paths.update(str(v).strip() for v in parameter.get("dependency_paths", []) if str(v).strip())
        field_resolution_key = str(parameter.get("field_resolution_field_key", "")).strip()
        if field_resolution_key:
            source_paths.add(field_resolution_key)
        matches = [field_priority[path] for path in source_paths if path in field_priority]
        if not matches:
            continue
        bucket, reason, planner_critical = matches[0]
        note = f"Shared review priority ({bucket}) affects source field support. {reason}".strip()
        parameter["review_note"] = _merge_notes(parameter.get("review_note", ""), note)
        parameter["confidence_explanation"] = _merge_notes(parameter.get("confidence_explanation", ""), note)
        parameter["confidence_tag"] = "LOW"
        parameter["confidence_score"] = min(float(parameter.get("confidence_score", 1.0) or 1.0), 0.49)
        parameter["planner_review_flag"] = True
        if bucket in {"interview_dependency", "conflict"}:
            parameter["needs_applicant_confirmation"] = True
        parameter["shared_review_priority_bucket"] = bucket
        if planner_critical:
            parameter["planner_attention_tier"] = str(parameter.get("planner_attention_tier", "")).strip() or "critical_review_required"

def _resolve_canonical_state(
    *,
    canonical_state_result: dict[str, Any] | None = None,
    validation_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    gap_resolution_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(validation_result, dict):
        payload = validation_result.get("canonical_state")
        if isinstance(payload, dict) and payload:
            return payload

    if isinstance(canonical_state_result, dict):
        payload = canonical_state_result.get("canonical_state")
        if isinstance(payload, dict) and payload:
            return payload

    retrieval_result, _ = resolve_gap_resolution_stage_inputs(
        retrieval_result=retrieval_result,
        interview_result=None,
        gap_resolution_result=gap_resolution_result,
    )

    return _build_canonical_state_from_stage_inputs(
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )


def _resolve_field_resolution_value(
    canonical_state: dict[str, Any],
    *field_keys: str,
) -> tuple[Any, dict[str, Any] | None, str]:
    ledger_resolved = resolve_planner_ledger_value(
        canonical_state,
        *field_keys,
        use_case="translation",
    )
    if isinstance(ledger_resolved, dict):
        key = str(ledger_resolved.get("field_path") or ledger_resolved.get("field_id") or "").strip()
        value = ledger_resolved.get("value")
        hold_reason = str(ledger_resolved.get("planner_ledger_hold_reason", "")).strip()
        if value is not None or hold_reason:
            return value, ledger_resolved, key

    for raw_key in field_keys:
        key = str(raw_key or "").strip()
        if not key:
            continue
        resolved = resolve_registry_field_value(canonical_state, key, None)
        if not isinstance(resolved, dict):
            continue
        if not bool(resolved.get("used_field_resolution", False)):
            continue
        status = str(resolved.get("status", "unresolved")).strip().lower() or "unresolved"
        value = resolved.get("value")
        if value is None or status in {"missing", "unresolved"}:
            continue
        return value, resolved, key
    return None, None, ""

def _field_resolution_confidence_override(resolved: dict[str, Any] | None) -> tuple[float | None, str | None]:
    if not isinstance(resolved, dict):
        return None, None
    score = safe_float(resolved.get("confidence"))
    band = str(resolved.get("confidence_band", "")).strip().upper() or None
    if bool(resolved.get("planner_review_flag", False)):
        return score, "LOW"
    if band in {"HIGH", "MODERATE", "LOW", "UNRESOLVED"}:
        return score, band
    return score, None


def _field_resolution_provenance_ref(field_key: str, resolved: dict[str, Any] | None) -> str | list[str]:
    if not isinstance(resolved, dict):
        return f"FIELD_RESOLUTION.{field_key}" if field_key else "FIELD_RESOLUTION"
    anchors = resolved.get("source_anchors")
    if isinstance(anchors, list):
        clean = [str(item).strip() for item in anchors if str(item).strip()]
        if clean:
            return clean
    return f"FIELD_RESOLUTION.{field_key}" if field_key else "FIELD_RESOLUTION"


def _field_resolution_note(resolved: dict[str, Any] | None) -> str:
    if not isinstance(resolved, dict):
        return ""
    notes: list[str] = []
    decision_basis = str(resolved.get("decision_basis", "")).strip()
    if decision_basis:
        notes.append(f"Field resolution basis: {decision_basis}.")
    why_accepted = resolved.get("why_accepted")
    if isinstance(why_accepted, list):
        reasons = [str(item).strip() for item in why_accepted if str(item).strip()]
        if reasons:
            notes.append("Why accepted: " + "; ".join(reasons[:3]) + ".")
    contradiction_summary = str(resolved.get("contradiction_summary", "")).strip()
    if contradiction_summary:
        notes.append(f"Conflict context: {contradiction_summary}.")
    if bool(resolved.get("needs_applicant_confirmation", False)):
        notes.append("Applicant confirmation still recommended.")
    ledger_hold_reason = str(resolved.get("planner_ledger_hold_reason", "")).strip()
    if ledger_hold_reason:
        notes.append(ledger_hold_reason)
    if bool(resolved.get("planner_review_flag", False)):
        notes.append("Planner review required.")
    return " ".join(notes).strip()


def _field_resolution_metadata(field_key: str | None, resolved: dict[str, Any] | None) -> dict[str, Any]:
    key = str(field_key or "").strip()
    if not isinstance(resolved, dict):
        return {}

    metadata: dict[str, Any] = {}
    if key:
        metadata["field_resolution_field_key"] = key

    for source_key, target_key in (
        ("planner_review_flag", "planner_review_flag"),
        ("needs_applicant_confirmation", "needs_applicant_confirmation"),
        ("decision_basis", "decision_basis"),
        ("accepted_status", "accepted_status"),
        ("accepted_value_kind", "accepted_value_kind"),
        ("planner_attention_tier", "planner_attention_tier"),
        ("accepted_source_hierarchy", "accepted_source_hierarchy"),
        ("accepted_specificity", "accepted_specificity"),
        ("contradiction_summary", "contradiction_summary"),
        ("confidence_band", "field_resolution_confidence_band"),
        ("used_planner_field_ledger", "used_planner_field_ledger"),
        ("planner_ledger_status", "planner_ledger_status"),
        ("planner_ledger_hold_reason", "planner_ledger_hold_reason"),
        ("field_path", "planner_ledger_field_path"),
        ("field_id", "planner_ledger_field_id"),
    ):
        value = resolved.get(source_key)
        if isinstance(value, str):
            value = value.strip()
        if value not in (None, "", [], {}):
            metadata[target_key] = value

    why_accepted = resolved.get("why_accepted")
    if isinstance(why_accepted, list):
        cleaned = [str(item).strip() for item in why_accepted if str(item).strip()]
        if cleaned:
            metadata["why_accepted"] = cleaned

    source_anchors = resolved.get("source_anchors")
    if isinstance(source_anchors, list):
        cleaned = [str(item).strip() for item in source_anchors if str(item).strip()]
        if cleaned:
            metadata["source_anchors"] = cleaned

    alternatives = resolved.get("alternatives")
    if isinstance(alternatives, list):
        metadata["alternatives_count"] = len([item for item in alternatives if isinstance(item, dict)])

    supporting_sources = resolved.get("supporting_sources")
    if isinstance(supporting_sources, list):
        metadata["supporting_sources_count"] = len([item for item in supporting_sources if isinstance(item, dict)])

    release_profile = _field_resolution_release_profile(resolved)
    if release_profile:
        for source_key, target_key in (
            ("release_state", "field_release_state"),
            ("translation_use_policy", "translation_use_policy"),
            ("scenario_use_policy", "scenario_use_policy"),
            ("planner_packet_use_policy", "planner_packet_use_policy"),
            ("export_readiness_tier", "export_readiness_tier"),
        ):
            value = release_profile.get(source_key)
            if isinstance(value, str):
                value = value.strip()
            if value not in (None, "", [], {}):
                metadata[target_key] = value

    return metadata




def _field_resolution_release_profile(resolved: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(resolved, dict):
        return {}
    profile = resolved.get("field_release_profile")
    return dict(profile) if isinstance(profile, dict) else {}


def _field_resolution_translation_hold_context(field_key: str | None, resolved: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(resolved, dict):
        return None
    release_profile = _field_resolution_release_profile(resolved)
    release_state = str(release_profile.get("release_state", "")).strip().upper()
    translation_policy = str(release_profile.get("translation_use_policy", "")).strip().lower()
    if release_state != "BLOCKED" and translation_policy != "hold_from_modeled_output":
        return None
    label = str(resolved.get("label") or field_key or "field resolution").strip()
    note = (
        f"Governed field resolution for {label} was held from modeled output "
        f"because release state is BLOCKED."
    )
    detail = _field_resolution_note(resolved)
    if detail:
        note = f"{note} {detail}"
    metadata = _field_resolution_metadata(field_key, resolved)
    metadata["field_release_state"] = release_state or "BLOCKED"
    if translation_policy:
        metadata["translation_use_policy"] = translation_policy
    scenario_policy = str(release_profile.get("scenario_use_policy", "")).strip()
    if scenario_policy:
        metadata["scenario_use_policy"] = scenario_policy
    packet_policy = str(release_profile.get("planner_packet_use_policy", "")).strip()
    if packet_policy:
        metadata["planner_packet_use_policy"] = packet_policy
    export_tier = str(release_profile.get("export_readiness_tier", "")).strip()
    if export_tier:
        metadata["export_readiness_tier"] = export_tier
    metadata["held_from_modeled_output"] = True
    metadata["held_field_resolution_value"] = resolved.get("value")
    return {"note": note.strip(), "metadata": metadata}


def _apply_field_resolution_hold(parameter: dict[str, Any], hold_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(parameter, dict) or not isinstance(hold_context, dict):
        return parameter
    note = str(hold_context.get("note", "")).strip()
    if note:
        parameter["review_note"] = _merge_notes(parameter.get("review_note", ""), note)
        parameter["confidence_explanation"] = _merge_notes(parameter.get("confidence_explanation", ""), note)
    parameter["confidence_tag"] = "LOW"
    parameter["confidence_score"] = min(float(parameter.get("confidence_score", 1.0) or 1.0), 0.49)
    parameter["planner_review_flag"] = True
    metadata = hold_context.get("metadata") if isinstance(hold_context.get("metadata"), dict) else {}
    if bool(metadata.get("needs_applicant_confirmation", False)):
        parameter["needs_applicant_confirmation"] = True
    for key, value in metadata.items():
        if value not in (None, "", [], {}):
            parameter[key] = value
    return parameter

def _normalized_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _merge_notes(*parts: str) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    for part in parts:
        note = str(part or "").strip()
        if not note or note in seen:
            continue
        seen.add(note)
        ordered.append(note)
    return " ".join(ordered).strip()


def _driver_context_notes(driver_context: dict[str, Any]) -> dict[str, str]:
    has_telemetry_context = "telemetry_present" in driver_context
    telemetry_present = driver_context.get("telemetry_present")
    telemetry_points_count = int((safe_float(driver_context.get("telemetry_points_count")) or 0.0))
    has_protection_context = "protection_summary" in driver_context
    protection_summary = _normalized_text(driver_context.get("protection_summary"))
    transfer_summary = _normalized_text(driver_context.get("transfer_summary"))
    redundancy_text = _normalized_text(driver_context.get("redundancy_architecture"))
    operating_modes = _normalized_text(driver_context.get("planned_operating_modes_summary"))
    emergency_modes = _normalized_text(driver_context.get("emergency_operating_mode_summary"))
    maintenance_modes = _normalized_text(driver_context.get("maintenance_or_outage_operating_modes"))
    generator_transfer = _normalized_text(driver_context.get("generator_transfer_sequence_summary"))
    cooling_arch = _normalized_text(driver_context.get("cooling_architecture_summary"))
    cooling_share = safe_float(driver_context.get("cooling_load_share"))
    gen_count = int((safe_float(driver_context.get("generator_unit_count")) or 0.0))
    ramp_summary = _normalized_text(driver_context.get("load_ramp_profile_summary"))

    p_note_bits: list[str] = []
    if gen_count > 0:
        p_note_bits.append(f"Resolved generator unit count: {gen_count}.")
    if redundancy_text:
        p_note_bits.append(f"Resolved redundancy architecture: {redundancy_text}.")
    if operating_modes:
        p_note_bits.append(f"Planned operating modes: {operating_modes}.")
    if maintenance_modes:
        p_note_bits.append(f"Maintenance/outage modes: {maintenance_modes}.")

    q_note_bits: list[str] = []
    if cooling_arch:
        q_note_bits.append(f"Cooling architecture context: {cooling_arch}.")
    if cooling_share is not None:
        q_note_bits.append(f"Cooling load share context: {round(cooling_share * 100.0 if cooling_share <= 1.0 else cooling_share, 2)}% of total load.")
    if transfer_summary:
        q_note_bits.append(f"Transfer behavior context: {transfer_summary}.")

    ramp_note_bits: list[str] = []
    if ramp_summary:
        ramp_note_bits.append(f"Resolved ramp profile summary: {ramp_summary}.")
    if transfer_summary:
        ramp_note_bits.append(f"Transfer scheme context: {transfer_summary}.")
    if generator_transfer:
        ramp_note_bits.append(f"Generator transfer sequence context: {generator_transfer}.")
    if emergency_modes:
        ramp_note_bits.append(f"Emergency operating modes: {emergency_modes}.")

    review_bits: list[str] = []
    if has_telemetry_context and telemetry_present is True and telemetry_points_count <= 0:
        review_bits.append("Telemetry is present but no telemetry points list was resolved.")
    elif has_telemetry_context and telemetry_present is False:
        review_bits.append("Telemetry support remains unresolved or unavailable.")
    if has_protection_context and not protection_summary:
        review_bits.append("Protection scheme summary remains unresolved.")

    return {
        "p_note": " ".join(p_note_bits).strip(),
        "q_note": " ".join(q_note_bits).strip(),
        "ramp_note": " ".join(ramp_note_bits).strip(),
        "review_note": " ".join(review_bits).strip(),
    }


def _extract_scenario_driver_context(
    canonical_state: dict[str, Any],
    normalized_input: dict[str, Any],
) -> dict[str, Any]:
    context: dict[str, Any] = {}

    resolved_pf_value, _, _ = _resolve_field_resolution_value(canonical_state, "net_power_factor_at_poi")
    pf_value = safe_float(resolved_pf_value)
    if pf_value is not None:
        context["power_factor_at_poi"] = round(pf_value, 6)

    gen_count, _, _ = _resolve_field_resolution_value(canonical_state, "generator_unit_count")
    gen_count_num = safe_float(gen_count)
    if gen_count_num is not None:
        context["generator_unit_count"] = int(gen_count_num)

    cooling_share, _, _ = _resolve_field_resolution_value(canonical_state, "cooling_load_share_percent_of_total")
    cooling_share_num = safe_float(cooling_share)
    if cooling_share_num is not None:
        if cooling_share_num > 1.0:
            cooling_share_num = cooling_share_num / 100.0
        context["cooling_load_share"] = round(max(0.0, min(cooling_share_num, 1.0)), 6)

    redundancy_value, _, _ = _resolve_field_resolution_value(canonical_state, "redundancy_architecture")
    redundancy_text = _normalized_text(redundancy_value)
    if redundancy_text:
        context["redundancy_architecture"] = redundancy_text

    ramp_summary, _, _ = _resolve_field_resolution_value(canonical_state, "load_ramp_profile_summary")
    ramp_text = _normalized_text(ramp_summary)
    if ramp_text:
        context["load_ramp_profile_summary"] = ramp_text

    cooling_architecture, _, _ = _resolve_field_resolution_value(canonical_state, "cooling_architecture_summary")
    cooling_architecture_text = _normalized_text(cooling_architecture)
    if cooling_architecture_text:
        context["cooling_architecture_summary"] = cooling_architecture_text

    planned_operating_modes, _, _ = _resolve_field_resolution_value(canonical_state, "planned_operating_modes_summary")
    planned_operating_modes_text = _normalized_text(planned_operating_modes)
    if planned_operating_modes_text:
        context["planned_operating_modes_summary"] = planned_operating_modes_text

    emergency_modes, _, _ = _resolve_field_resolution_value(canonical_state, "emergency_operating_mode_summary")
    emergency_modes_text = _normalized_text(emergency_modes)
    if emergency_modes_text:
        context["emergency_operating_mode_summary"] = emergency_modes_text

    maintenance_modes, _, _ = _resolve_field_resolution_value(canonical_state, "maintenance_or_outage_operating_modes")
    maintenance_modes_text = _normalized_text(maintenance_modes)
    if maintenance_modes_text:
        context["maintenance_or_outage_operating_modes"] = maintenance_modes_text

    generator_transfer_sequence, _, _ = _resolve_field_resolution_value(canonical_state, "generator_transfer_sequence_summary")
    generator_transfer_sequence_text = _normalized_text(generator_transfer_sequence)
    if generator_transfer_sequence_text:
        context["generator_transfer_sequence_summary"] = generator_transfer_sequence_text

    telemetry_present = get_nested_value(normalized_input, "interconnection.telemetry.present")
    if isinstance(telemetry_present, bool):
        context["telemetry_present"] = telemetry_present

    telemetry_points = get_nested_value(normalized_input, "interconnection.telemetry.points_list")
    if isinstance(telemetry_points, list):
        context["telemetry_points_count"] = len([item for item in telemetry_points if item not in (None, "")])

    protection_summary = get_nested_value(normalized_input, "interconnection.protection.protection_summary")
    protection_text = _normalized_text(protection_summary)
    if protection_text:
        context["protection_summary"] = protection_text

    transfer_summary = get_nested_value(normalized_input, "facility.load.transfer_summary")
    transfer_text = _normalized_text(transfer_summary)
    if not transfer_text:
        resolved_transfer_summary, _, _ = _resolve_field_resolution_value(canonical_state, "source_transfer_scheme_summary", "transfer_scheme_logic_summary", "ups_transfer_behavior_summary")
        transfer_text = _normalized_text(resolved_transfer_summary)
    if transfer_text:
        context["transfer_summary"] = transfer_text

    resolved_protection_summary, _, _ = _resolve_field_resolution_value(canonical_state, "protection_scheme_summary")
    if not protection_text:
        protection_text = _normalized_text(resolved_protection_summary)
    if protection_text:
        context["protection_summary"] = protection_text

    return context


def _build_output_schema(context: Any) -> dict[str, Any]:
    schema_version = getattr(getattr(context, "config", None), "schema_version_output", "1.0.0")
    payload = {
        "run_id": context.run_id,
        "schema_version": schema_version,
    }
    payload.update(planner_translation_output_defaults())
    if "steady_state" not in payload:
        payload["steady_state"] = {"p_mw": 0.0, "q_mvar": 0.0}
    if "zip_model" not in payload:
        payload["zip_model"] = {
            "constant_power_fraction": 0.80,
            "constant_current_fraction": 0.10,
            "constant_impedance_fraction": 0.10,
        }
    if "ramping" not in payload:
        payload["ramping"] = {"max_ramp_up_mw_per_min": 1.0, "max_ramp_down_mw_per_min": 1.0}
    return payload


def _assumption_record(
    *,
    assumption_id: str,
    parameter_path: str,
    nominal_value: Any,
    bounds: dict[str, Any],
    rationale: str,
    created_by: str = "translation",
    source_field_paths: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    assumption_type: str = "DERIVED_PARAMETER_DEFAULT",
    status: str = "ACTIVE",
) -> dict[str, Any]:
    normalized_source_field_paths = [
        str(value).strip()
        for value in (source_field_paths or [])
        if isinstance(value, str) and value.strip()
    ]
    normalized_evidence_refs = [
        str(value).strip()
        for value in (evidence_refs or [])
        if isinstance(value, str) and value.strip()
    ]

    return {
        "assumption_id": assumption_id,
        "parameter_path": parameter_path,
        "field_path": parameter_path,
        "nominal_value": nominal_value,
        "assumption_value": nominal_value,
        "bounds": bounds,
        "rationale": rationale,
        "created_by": created_by,
        "created_by_stage": created_by,
        "status": status,
        "evidence_refs": normalized_evidence_refs,
        "metadata": {
            "assumption_type": assumption_type,
            "source_field_paths": normalized_source_field_paths,
        },
    }


def _parameter_record(
    *,
    parameter_path: str,
    value: Any,
    units: str,
    provenance_type: str,
    provenance_ref: str | list[str],
    validation_report: dict[str, Any],
    snippets: list[dict[str, Any]],
    assumption_used: bool,
    derived_from_rule: bool,
    dependency_paths: list[str] | None = None,
    source_field_paths: list[str] | None = None,
    confidence_score_override: float | None = None,
    confidence_tag_override: str | None = None,
    planner_note: str = "",
    review_note: str = "",
    confidence_explanation: str = "",
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    supporting_snippet_ids = get_supporting_snippet_ids(
        parameter_path=parameter_path,
        snippets=snippets,
    )
    factors = build_confidence_factors(
        parameter_path=parameter_path,
        provenance_type=provenance_type,
        provenance_ref=provenance_ref,
        validation_report=validation_report,
        snippets=snippets,
        assumption_used=assumption_used,
        derived_from_rule=derived_from_rule,
    )
    score = compute_confidence_score(
        provenance_type=provenance_type,
        factors=factors,
    )

    resolved_dependency_paths = [
        str(item).strip()
        for item in (
            dependency_paths
            if dependency_paths is not None
            else get_dependency_paths(parameter_path)
        )
        if isinstance(item, str) and item.strip()
    ]
    resolved_source_field_paths = [
        str(item).strip()
        for item in (
            source_field_paths
            if source_field_paths is not None
            else get_source_field_paths(parameter_path)
        )
        if isinstance(item, str) and item.strip()
    ]

    parameter_config = translation_parameter_config(parameter_path)
    resolved_units = units or str(parameter_config.get("units", "")).strip()
    resolved_score = score if confidence_score_override is None else float(confidence_score_override)
    resolved_tag = confidence_tag_override or map_confidence_tag(resolved_score)
    payload = {
        "parameter_path": parameter_path,
        "value": value,
        "units": resolved_units,
        "provenance_type": provenance_type,
        "provenance_ref": provenance_ref,
        "dependency_paths": resolved_dependency_paths,
        "source_field_paths": resolved_source_field_paths,
        "supporting_snippet_ids": supporting_snippet_ids,
        "confidence_score": round(max(0.0, min(1.0, resolved_score)), 2),
        "confidence_tag": resolved_tag,
        "confidence_factors": factors,
        "planner_note": planner_note,
        "review_note": review_note,
        "confidence_explanation": confidence_explanation,
    }
    if isinstance(extra_metadata, dict):
        for key, value in extra_metadata.items():
            if key not in payload and value not in (None, "", [], {}):
                payload[key] = value
    return payload


def _unwrap_engineering_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _get_engineering_model_value(
    engineering_model: dict[str, Any],
    field_path: str,
) -> Any:
    current: Any = engineering_model

    for token in field_path.split("."):
        if not isinstance(current, dict) or token not in current:
            return None
        current = current[token]

    return _unwrap_engineering_value(current)


def _resolve_steady_state_p_mw(
    engineering_model: dict[str, Any],
    normalized_input: dict[str, Any],
) -> tuple[float | None, list[str], str]:
    has_engineering_model = bool(engineering_model)

    engineering_peak = safe_float(
        _get_engineering_model_value(
            engineering_model,
            "load_system.peak_demand_mw",
        )
    )
    if engineering_peak is not None:
        return (
            engineering_peak,
            ["engineering_model.load_system.peak_demand_mw"],
            "engineering_model",
        )

    engineering_block = safe_float(
        _get_engineering_model_value(
            engineering_model,
            "buildout_and_ramping.ramp_characteristics.block_load_step_mw",
        )
    )
    if engineering_block is not None:
        return (
            engineering_block,
            ["engineering_model.buildout_and_ramping.ramp_characteristics.block_load_step_mw"],
            "engineering_model",
        )

    phase_1_mw = safe_float(
        get_nested_value(normalized_input, "facility.load_schedule.phase_1_mw")
    )
    if phase_1_mw is not None:
        return (
            phase_1_mw,
            ["facility.load_schedule.phase_1_mw"],
            "normalized_input",
        )

    if has_engineering_model:
        return (
            None,
            [
                "engineering_model.load_system.peak_demand_mw",
                "engineering_model.buildout_and_ramping.ramp_characteristics.block_load_step_mw",
                "facility.load_schedule.phase_1_mw",
            ],
            "missing",
        )

    return (
        None,
        ["facility.load_schedule.phase_1_mw"],
        "missing",
    )


def _resolve_ramp_rate_mw_per_min(
    engineering_model: dict[str, Any],
) -> tuple[float | None, list[str], str]:
    ramp_rate = safe_float(
        _get_engineering_model_value(
            engineering_model,
            "buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min",
        )
    )
    if ramp_rate is not None:
        return (
            ramp_rate,
            ["engineering_model.buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min"],
            "engineering_model",
        )

    return (None, ["facility.load_schedule.phase_1_mw"], "default_rule")


def _resolve_zip_dependency_paths(
    engineering_model: dict[str, Any],
    normalized_input: dict[str, Any],
) -> list[str]:
    ups_topology = _get_engineering_model_value(
        engineering_model,
        "power_conversion_and_ups.ups_systems",
    )
    if isinstance(ups_topology, list) and ups_topology:
        first_ups = ups_topology[0]
        if isinstance(first_ups, dict):
            topology_value = _unwrap_engineering_value(first_ups.get("topology"))
            if topology_value is not None:
                return ["engineering_model.power_conversion_and_ups.ups_systems.0.topology"]

    normalized_ups_topology = get_nested_value(normalized_input, "facility.ups.topology")
    if normalized_ups_topology is not None:
        return ["facility.ups.topology"]

    return ["facility.ups.topology"]


def _append_unique_note(existing_text: str, note: str) -> str:
    normalized_existing = str(existing_text).strip()
    normalized_note = str(note).strip()

    if not normalized_note:
        return normalized_existing
    if not normalized_existing:
        return normalized_note
    if normalized_note in normalized_existing:
        return normalized_existing
    return f"{normalized_existing} {normalized_note}".strip()


def _build_translation_support_summary(
    *,
    structured_output: dict[str, Any],
) -> dict[str, Any]:
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return sorted(
            {
                str(item).strip()
                for item in value
                if isinstance(item, str) and item.strip()
            }
        )

    review_notes = structured_output.get("review_notes", [])
    if not isinstance(review_notes, list):
        review_notes = []

    return {
        "review_notes": [
            str(item).strip()
            for item in review_notes
            if isinstance(item, str) and item.strip()
        ],
        "low_confidence_parameters": _string_list(structured_output.get("low_confidence_parameters", [])),
        "assumption_backed_parameters": _string_list(structured_output.get("assumption_backed_parameters", [])),
        "missing_dependency_parameters": _string_list(structured_output.get("missing_dependency_parameters", [])),
        "parameter_explanation": str(structured_output.get("parameter_explanation", "")).strip(),
        "planner_note": str(structured_output.get("planner_note", "")).strip(),
        "review_note": str(structured_output.get("review_note", "")).strip(),
        "assumption_summary": str(structured_output.get("assumption_summary", "")).strip(),
        "missing_info_summary": str(structured_output.get("missing_info_summary", "")).strip(),
        "confidence_explanation": str(structured_output.get("confidence_explanation", "")).strip(),
        "rationale": str(structured_output.get("rationale", "")).strip(),
        "confidence": str(structured_output.get("confidence", "")).strip(),
    }


def _can_run_agent(context: Any | None) -> bool:
    if context is None:
        return False
    run_id = getattr(context, "run_id", None)
    return isinstance(run_id, str) and bool(run_id.strip())




def _compact_translation_agent_inputs(
    *,
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    validation_report: dict[str, Any],
) -> dict[str, Any]:
    safe_parameters = [item for item in output_parameters if isinstance(item, dict)]
    critical_parameters = [
        item for item in safe_parameters
        if str(item.get("confidence", item.get("confidence_band", ""))).strip().upper() in {"LOW", "UNRESOLVED"}
        or item.get("value") in (None, "", [])
        or bool(item.get("review_required", False))
    ]
    if not critical_parameters:
        critical_parameters = safe_parameters[:25]

    safe_validation = validation_report if isinstance(validation_report, dict) else {}
    missing_fields = safe_validation.get("missing_fields") if isinstance(safe_validation.get("missing_fields"), list) else []
    conflicts = safe_validation.get("conflicts") if isinstance(safe_validation.get("conflicts"), list) else []
    return {
        "translation_parameters": safe_parameters[:80],
        "critical_translation_review_items": critical_parameters[:40],
        "assumptions": [item for item in assumptions if isinstance(item, dict)][:40],
        "validation_summary": {
            "schema_valid": safe_validation.get("schema_valid"),
            "missing_field_count": len(missing_fields),
            "missing_fields": missing_fields[:40],
            "conflict_count": len(conflicts),
            "conflicts": conflicts[:20],
        },
        "chunking_domains": [
            "steady_state_power",
            "reactive_power_and_pf",
            "voltage_and_poi",
            "load_model_zip",
            "dynamic_behavior",
            "backup_generation",
            "energization_schedule",
            "missing_or_blocked_model_inputs",
        ],
    }

def _run_translation_support_agent(
    *,
    context: Any,
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    validation_report: dict[str, Any],
) -> dict[str, Any]:
    result = run_agent(
        context=context,
        request=AgentRequest(
            agent_id="translation_support_agent",
            stage_name="translation",
            task_name="parameter_review",
            inputs=_compact_translation_agent_inputs(
                output_parameters=output_parameters,
                assumptions=assumptions,
                validation_report=validation_report,
            ),
            metadata={
                "service": "translation_service",
            },
            trigger_reason="planner_facing_translation_support_requested",
            associated_field_paths=[
                str(parameter.get("parameter_path", "")).strip()
                for parameter in output_parameters
                if isinstance(parameter, dict) and str(parameter.get("parameter_path", "")).strip()
            ],
            evidence_anchors=[],
            suggested_output_fields=[
                "parameter_explanation",
                "planner_note",
                "review_note",
                "assumption_summary",
                "missing_info_summary",
                "confidence_explanation",
                "rationale",
                "confidence",
            ],
        ),
    )
    return result


def _apply_translation_support(
    *,
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(agent_result, dict):
        return {
            "review_notes": [],
            "low_confidence_parameters": [],
            "assumption_backed_parameters": [],
            "missing_dependency_parameters": [],
            "parameter_explanation": "",
            "planner_note": "",
            "review_note": "",
            "assumption_summary": "",
            "missing_info_summary": "",
            "confidence_explanation": "",
            "rationale": "",
            "confidence": "",
            "agent_id": "",
            "agent_status": "",
            "agent_audit_path": "",
            "agent_policy": {},
        }

    structured_output = agent_result.get("structured_output", {})
    if not isinstance(structured_output, dict):
        structured_output = {}

    support_summary = _build_translation_support_summary(
        structured_output=structured_output,
    )

    low_confidence_parameters = set(support_summary["low_confidence_parameters"])
    assumption_backed_parameters = set(support_summary["assumption_backed_parameters"])
    missing_dependency_parameters = set(support_summary["missing_dependency_parameters"])

    global_planner_note = support_summary["planner_note"]
    global_review_note = support_summary["review_note"]
    global_confidence_explanation = support_summary["confidence_explanation"]

    for parameter in output_parameters:
        parameter_path = str(parameter.get("parameter_path", "")).strip()
        if not parameter_path:
            continue

        if parameter_path in low_confidence_parameters:
            parameter["review_note"] = _append_unique_note(
                str(parameter.get("review_note", "")),
                "Translation Support Agent flagged this parameter as low-confidence.",
            )

        if parameter_path in assumption_backed_parameters:
            parameter["planner_note"] = _append_unique_note(
                str(parameter.get("planner_note", "")),
                "This parameter is supported by an explicit assumption record.",
            )

        if parameter_path in missing_dependency_parameters:
            parameter["confidence_explanation"] = _append_unique_note(
                str(parameter.get("confidence_explanation", "")),
                "Confidence is reduced because one or more dependency fields remain unresolved.",
            )

        if global_planner_note:
            parameter["planner_note"] = _append_unique_note(
                str(parameter.get("planner_note", "")),
                global_planner_note,
            )

        if global_review_note:
            parameter["review_note"] = _append_unique_note(
                str(parameter.get("review_note", "")),
                global_review_note,
            )

        if global_confidence_explanation:
            parameter["confidence_explanation"] = _append_unique_note(
                str(parameter.get("confidence_explanation", "")),
                global_confidence_explanation,
            )

    assumption_parameter_paths = {
        str(assumption.get("parameter_path", "")).strip()
        for assumption in assumptions
        if isinstance(assumption, dict)
    }

    for assumption in assumptions:
        parameter_path = str(assumption.get("parameter_path", "")).strip()
        if not parameter_path:
            continue

        if parameter_path in assumption_backed_parameters or parameter_path in assumption_parameter_paths:
            assumption["planner_note"] = _append_unique_note(
                str(assumption.get("planner_note", "")),
                "Translation Support Agent confirmed this assumption remains planner-visible.",
            )

        if support_summary["assumption_summary"]:
            assumption["planner_note"] = _append_unique_note(
                str(assumption.get("planner_note", "")),
                support_summary["assumption_summary"],
            )

    support_summary["agent_id"] = str(agent_result.get("agent_id", "")).strip()
    support_summary["agent_status"] = str(agent_result.get("status", "")).strip()
    support_summary["agent_audit_path"] = str(agent_result.get("audit_path", "")).strip()
    support_summary["agent_policy"] = dict(agent_result.get("policy", {})) if isinstance(agent_result.get("policy", {}), dict) else {}
    return support_summary


def _finalize_ledger_native_translation_result(
    *,
    context: Any,
    run_id: str,
    canonical_state: dict[str, Any],
    validation_report: dict[str, Any],
    ledger_first_contract: dict[str, Any],
) -> dict[str, Any]:
    """Return the Patch 27 ledger-first translation result.

    This path is intentionally separate from the legacy derivation body below so
    the active service can prove that modeled values originate from final planner
    ledger rows when a planner ledger exists.
    """
    model_outputs = dict(ledger_first_contract.get("model_outputs", {})) if isinstance(ledger_first_contract.get("model_outputs"), dict) else {}
    output_parameters = [
        dict(item)
        for item in ledger_first_contract.get("output_parameters", [])
        if isinstance(item, dict)
    ] if isinstance(ledger_first_contract.get("output_parameters", []), list) else []
    assumptions: list[dict[str, Any]] = []

    if _can_run_agent(context):
        agent_result = _run_translation_support_agent(
            context=context,
            output_parameters=output_parameters,
            assumptions=assumptions,
            validation_report=validation_report,
        )
    else:
        agent_result = {
            "run_id": run_id,
            "agent_id": "",
            "status": "SKIPPED",
            "policy": {},
            "audit_path": "",
            "structured_output": {},
        }

    translation_support = _apply_translation_support(
        output_parameters=output_parameters,
        assumptions=assumptions,
        agent_result=agent_result,
    )

    scenario_driver_context = _extract_scenario_driver_context(
        canonical_state=canonical_state,
        normalized_input=canonical_state.get("normalized_input", {}) if isinstance(canonical_state.get("normalized_input", {}), dict) else {},
    )
    scenario_driver_context["source"] = "planner_field_ledger"
    scenario_driver_context["legacy_driver_context_used"] = False
    driver_notes = _driver_context_notes(scenario_driver_context)
    for parameter in output_parameters:
        if not isinstance(parameter, dict):
            continue
        path = str(parameter.get("parameter_path", "")).strip()
        if path == "steady_state.p_mw":
            parameter["planner_note"] = _merge_notes(parameter.get("planner_note", ""), driver_notes.get("p_note", ""))
        elif path in {"steady_state.q_mvar", "steady_state.power_factor"}:
            parameter["planner_note"] = _merge_notes(parameter.get("planner_note", ""), driver_notes.get("q_note", ""))
        elif path in {"ramping.max_ramp_up_mw_per_min", "ramping.max_ramp_down_mw_per_min"}:
            parameter["planner_note"] = _merge_notes(parameter.get("planner_note", ""), driver_notes.get("ramp_note", ""))
        if path in {"steady_state.p_mw", "steady_state.q_mvar", "steady_state.power_factor", "ramping.max_ramp_up_mw_per_min", "ramping.max_ramp_down_mw_per_min"}:
            review_note = driver_notes.get("review_note", "")
            if review_note:
                parameter["review_note"] = _merge_notes(parameter.get("review_note", ""), review_note)
                parameter["confidence_tag"] = "LOW"
                parameter["confidence_score"] = min(float(parameter.get("confidence_score", 1.0) or 1.0), 0.49)
                parameter["confidence_explanation"] = _merge_notes(parameter.get("confidence_explanation", ""), review_note)
            parameter["scenario_driver_context_used"] = True

    llm_assistance = {
        "run_id": run_id,
        "stage_name": "translation",
        "task_name": "parameter_review",
        "status": str(agent_result.get("status", "")).strip() or "SKIPPED",
        "policy": dict(agent_result.get("policy", {})) if isinstance(agent_result.get("policy", {}), dict) else {},
        "audit_path": str(agent_result.get("audit_path", "")).strip(),
        "bounded_response": dict(agent_result.get("structured_output", {})) if isinstance(agent_result.get("structured_output", {}), dict) else {},
        "agent_id": str(agent_result.get("agent_id", "")).strip() or "translation_support_agent",
    }

    field_governance_core = build_field_governance_core(canonical_state=canonical_state)
    manual_review_queue = field_governance_core.get("manual_review_queue", {}) if isinstance(field_governance_core.get("manual_review_queue", {}), dict) else {}
    _apply_shared_review_priority_gating(output_parameters, manual_review_queue)
    ledger_downstream_governance = apply_ledger_governance_to_parameters(
        output_parameters,
        canonical_state,
        use_case="translation",
    )
    ledger_scenario_governance = apply_ledger_governance_to_parameters(
        output_parameters,
        canonical_state,
        use_case="scenario",
    )
    ledger_native_translation = build_ledger_native_translation_contract(
        output_parameters,
        model_outputs,
    )
    ledger_native_translation["primary_translation_contract"] = dict(ledger_first_contract)
    ledger_native_model_outputs = ledger_native_translation.get("ledger_native_model_outputs")
    if isinstance(ledger_native_model_outputs, dict):
        model_outputs = ledger_native_model_outputs

    confidence_summary = {
        "HIGH": 0,
        "MODERATE": 0,
        "LOW": 0,
        "UNRESOLVED": 0,
    }
    for parameter in output_parameters:
        confidence_tag = str(parameter.get("confidence_tag", "LOW"))
        if confidence_tag not in confidence_summary:
            confidence_summary[confidence_tag] = 0
        confidence_summary[confidence_tag] += 1

    schema_validation = build_translation_runtime_schema_validation(
        model_outputs,
        output_parameters,
    )
    governed_truth_summary = _governed_truth_summary(canonical_state, validation_report)
    governance_alerts = _governance_alerts_from_summary(governed_truth_summary, manual_review_queue, field_governance_core)

    return {
        "run_id": run_id,
        "model_outputs": model_outputs,
        "output_parameters": output_parameters,
        "assumptions": assumptions,
        "confidence_summary": confidence_summary,
        "schema_validation": schema_validation,
        "translation_support": translation_support,
        "llm_assistance": llm_assistance,
        "scenario_driver_context": scenario_driver_context,
        "governed_truth_summary": governed_truth_summary,
        "governance_alerts": governance_alerts,
        "ledger_downstream_governance": ledger_downstream_governance,
        "ledger_scenario_governance": ledger_scenario_governance,
        "ledger_native_translation": ledger_native_translation,
        "ledger_native_model_outputs": ledger_native_model_outputs if isinstance(ledger_native_model_outputs, dict) else model_outputs,
        "ledger_first_translation_contract": ledger_first_contract,
        "translation_source_contract": {
            "primary_source": "planner_field_ledger",
            "legacy_translation_fallback_used": False,
            "legacy_translation_fallback_allowed": False,
            "planner_ledger_row_count": ledger_first_contract.get("planner_ledger_row_count", 0),
            "output_parameters_source": "planner_field_ledger",
            "model_outputs_source": "planner_field_ledger",
            "blocked_rows_excluded_from_model_outputs": ledger_first_contract.get("blocked_rows_excluded_from_model_outputs", 0),
            "provisional_parameter_count": ledger_first_contract.get("provisional_parameter_count", 0),
            "fallback_rows_used": ledger_first_contract.get("fallback_rows_used", 0),
        },
        "manual_review_queue": manual_review_queue,
        "field_governance_core": field_governance_core,
        "status": "TRANSLATED",
        "translated_at": utc_now_iso(),
    }


def translate_parameters(
    context: Any,
    canonical_state_result: dict[str, Any] | None = None,
    validation_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    gap_resolution_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = _require_run_id(context)

    canonical_state = _resolve_canonical_state(
        canonical_state_result=canonical_state_result,
        validation_result=validation_result,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
        gap_resolution_result=gap_resolution_result,
    )

    normalized_input = canonical_state.get("normalized_input", {})
    validation_report = canonical_state.get("validation_report", {})
    snippets = canonical_state.get("evidence_snippets", [])
    engineering_model = canonical_state.get("engineering_model", {})

    if not isinstance(normalized_input, dict):
        normalized_input = {}
    if not isinstance(validation_report, dict):
        validation_report = {}
    if not isinstance(snippets, list):
        snippets = []
    if not isinstance(engineering_model, dict):
        engineering_model = {}

    ledger_first_translation_contract = build_ledger_first_translation_inputs(canonical_state)
    if bool(ledger_first_translation_contract.get("used_ledger_native_primary", False)):
        return _finalize_ledger_native_translation_result(
            context=context,
            run_id=run_id,
            canonical_state=canonical_state,
            validation_report=validation_report,
            ledger_first_contract=ledger_first_translation_contract,
        )

    # Final modeling outputs must not be synthesized from legacy fallback paths
    # when the final planner ledger is missing or unresolved.  Return a blocked
    # diagnostic contract instead; export/pre-export gating will keep planner
    # artifacts from being generated from unbacked model outputs. Keep the same
    # top-level shape as successful translation so downstream governance/status
    # code can reason about the block without KeyErrors.
    field_governance_core = build_field_governance_core(canonical_state=canonical_state)
    manual_review_queue = field_governance_core.get("manual_review_queue", {}) if isinstance(field_governance_core.get("manual_review_queue", {}), dict) else {}
    governed_truth_summary = _governed_truth_summary(canonical_state, validation_report)
    governance_alerts = _governance_alerts_from_summary(governed_truth_summary, manual_review_queue, field_governance_core)
    schema_validation = build_translation_runtime_schema_validation({}, [])
    schema_validation["status"] = "SKIPPED_TRANSLATION_BLOCKED"
    schema_validation["blocked_reason"] = "LEDGER_FIRST_TRANSLATION_REQUIRED"
    return {
        "run_id": run_id,
        "model_outputs": {},
        "ledger_native_model_outputs": {},
        "output_parameters": [],
        "assumptions": [],
        "confidence_summary": {"HIGH": 0, "MODERATE": 0, "LOW": 0, "UNRESOLVED": 0},
        "schema_validation": schema_validation,
        "translation_support": {
            "review_notes": ["Ledger-first translation was blocked because no final planner-ledger-native inputs were available."],
            "low_confidence_parameters": [],
            "assumption_backed_parameters": [],
            "missing_dependency_parameters": [],
            "parameter_explanation": "",
            "planner_note": "Final translated parameters require accepted/provisional planner ledger rows.",
            "review_note": "Translation blocked before model-output synthesis because the final planner ledger is absent.",
            "assumption_summary": "",
            "missing_info_summary": "",
            "confidence_explanation": "Ledger-first translation is mandatory for final planner outputs.",
            "rationale": "No planner-field-ledger-native source rows were available.",
            "confidence": "LOW",
            "agent_id": "",
            "agent_status": "SKIPPED_TRANSLATION_BLOCKED",
            "agent_audit_path": "",
            "agent_policy": {},
        },
        "llm_assistance": {
            "run_id": run_id,
            "stage_name": "translation",
            "task_name": "parameter_review",
            "status": "SKIPPED_TRANSLATION_BLOCKED",
            "policy": {},
            "audit_path": "",
            "bounded_response": {},
            "agent_id": "translation_support_agent",
        },
        "scenario_driver_context": {
            "source": "blocked_no_final_planner_ledger",
            "legacy_driver_context_used": False,
            "note": "Scenario drivers were not produced because ledger-first translation inputs were unavailable.",
        },
        "governed_truth_summary": governed_truth_summary,
        "governance_alerts": governance_alerts,
        "ledger_downstream_governance": {
            "checked_parameter_count": 0,
            "gated_parameter_count": 0,
            "status": "BLOCKED_NO_OUTPUT_PARAMETERS",
        },
        "ledger_scenario_governance": {
            "checked_parameter_count": 0,
            "gated_parameter_count": 0,
            "status": "BLOCKED_NO_OUTPUT_PARAMETERS",
        },
        "ledger_native_translation": build_ledger_native_translation_contract([], {}),
        "ledger_first_translation_contract": ledger_first_translation_contract,
        "translation_source_contract": {
            "primary_source": "planner_field_ledger",
            "legacy_translation_fallback_used": False,
            "legacy_translation_fallback_allowed": False,
            "planner_ledger_row_count": ledger_first_translation_contract.get("planner_ledger_row_count", 0),
            "output_parameters_source": "blocked_no_final_planner_ledger",
            "model_outputs_source": "blocked_no_final_planner_ledger",
            "blocked_reason": "LEDGER_FIRST_TRANSLATION_REQUIRED",
        },
        "manual_review_queue": manual_review_queue,
        "field_governance_core": field_governance_core,
        "status": "TRANSLATION_BLOCKED_LEDGER_FIRST_REQUIRED",
        "translated_at": utc_now_iso(),
    }

    model_outputs = _build_output_schema(context)
    output_parameters: list[dict[str, Any]] = []
    assumptions: list[dict[str, Any]] = []

    p_mw_value, p_mw_source_field_paths, p_mw_input_source = _resolve_steady_state_p_mw(
        engineering_model=engineering_model,
        normalized_input=normalized_input,
    )
    phase_1_mw_supporting_snippet_ids = get_supporting_snippet_ids(
        parameter_path="steady_state.p_mw",
        snippets=snippets,
    )

    p_mw: dict[str, Any] | None = None
    p_resolution_note = ""
    p_hold_context: dict[str, Any] | None = None
    if p_mw_input_source != "engineering_model":
        resolved_p_value, resolved_p_entry, resolved_p_key = _resolve_field_resolution_value(
            canonical_state,
            "accepted_peak_demand_mw",
            "peak_demand_mw",
            "facility.load_schedule.phase_1_mw",
        )
        numeric_resolved_p = safe_float(resolved_p_value)
        if numeric_resolved_p is not None:
            p_hold_context = _field_resolution_translation_hold_context(resolved_p_key, resolved_p_entry)
            if p_hold_context is None:
                p_mw_value = numeric_resolved_p
                p_mw_source_field_paths = [resolved_p_key]
                p_mw_input_source = "field_resolution"
                p_resolution_note = _field_resolution_note(resolved_p_entry)
                p_confidence_override, p_tag_override = _field_resolution_confidence_override(resolved_p_entry)
                planner_review = bool(resolved_p_entry.get("planner_review_flag", False)) if isinstance(resolved_p_entry, dict) else False
                p_mw = _parameter_record(
                parameter_path="steady_state.p_mw",
                value=p_mw_value,
                units="MW",
                provenance_type="field_resolution",
                provenance_ref=_field_resolution_provenance_ref(resolved_p_key, resolved_p_entry),
                validation_report=validation_report,
                snippets=snippets,
                assumption_used=False,
                derived_from_rule=False,
                dependency_paths=p_mw_source_field_paths,
                source_field_paths=p_mw_source_field_paths,
                confidence_score_override=p_confidence_override,
                confidence_tag_override=p_tag_override,
                planner_note=p_resolution_note if not planner_review else "",
                review_note=p_resolution_note if planner_review else "",
                confidence_explanation=p_resolution_note or "Resolved from governed field-resolution ledger.",
                    extra_metadata=_field_resolution_metadata(resolved_p_key, resolved_p_entry),
                )

    if p_mw is None and p_mw_value is None:
        p_mw_value = 0.0
        assumption_id = "assumption_steady_state_load"
        assumptions.append(
            _assumption_record(
                assumption_id=assumption_id,
                parameter_path="steady_state.p_mw",
                nominal_value=0.0,
                bounds={"min": 0.0, "max": 5.0},
                rationale=(
                    "No engineering-model demand value or Phase 1 MW schedule was available, "
                    "so steady-state real power was assumed."
                ),
                created_by="translation",
                source_field_paths=p_mw_source_field_paths,
                evidence_refs=phase_1_mw_supporting_snippet_ids,
                assumption_type="MISSING_INPUT_DEFAULT",
                status="ACTIVE",
            )
        )
        p_mw = _parameter_record(
            parameter_path="steady_state.p_mw",
            value=p_mw_value,
            units="MW",
            provenance_type="assumption",
            provenance_ref=assumption_id,
            validation_report=validation_report,
            snippets=snippets,
            assumption_used=True,
            derived_from_rule=False,
            dependency_paths=p_mw_source_field_paths,
            source_field_paths=p_mw_source_field_paths,
        )
    elif p_mw is None:
        if p_mw_input_source == "engineering_model":
            provenance_ref = "RULE.ENGINEERING_MODEL_TO_STEADY_STATE_P.v1"
        else:
            provenance_ref = "RULE.NORMALIZED_LOAD_TO_STEADY_STATE_P.v1"

        p_mw = _parameter_record(
            parameter_path="steady_state.p_mw",
            value=p_mw_value,
            units="MW",
            provenance_type="rule",
            provenance_ref=provenance_ref,
            validation_report=validation_report,
            snippets=snippets,
            assumption_used=False,
            derived_from_rule=True,
            dependency_paths=p_mw_source_field_paths,
            source_field_paths=p_mw_source_field_paths,
        )
    output_parameters.append(p_mw)
    if p_hold_context is not None:
        _apply_field_resolution_hold(p_mw, p_hold_context)

    resolved_pf_value, resolved_pf_entry, resolved_pf_key = _resolve_field_resolution_value(
        canonical_state,
        "net_power_factor_at_poi",
    )
    q_dependency_paths = list(p_mw_source_field_paths)
    q_provenance_type = "rule"
    q_provenance_ref = (
        "RULE.ENGINEERING_MODEL_DEFAULT_Q_FACTOR"
        if p_mw_input_source == "engineering_model"
        else "RULE.DEFAULT_Q_FACTOR"
    )
    q_confidence_override = None
    q_tag_override = None
    q_planner_note = p_resolution_note if p_mw_input_source == "field_resolution" else ""
    q_review_note = ""
    q_confidence_explanation = ""
    q_hold_context: dict[str, Any] | None = None
    pf_value = safe_float(resolved_pf_value)
    if pf_value is not None and 0 < abs(pf_value) <= 1.0 and p_mw_value is not None:
        q_hold_context = _field_resolution_translation_hold_context(resolved_pf_key, resolved_pf_entry)
        if q_hold_context is None:
            apparent_power = abs(float(p_mw_value)) / abs(pf_value) if abs(pf_value) > 0 else None
            q_term = None if apparent_power is None else max((apparent_power ** 2) - (float(p_mw_value) ** 2), 0.0)
            q_value = round((q_term ** 0.5) if q_term is not None else 0.0, 3)
            q_dependency_paths = [resolved_pf_key] + [path for path in p_mw_source_field_paths if path not in {resolved_pf_key}]
            q_provenance_type = "field_resolution"
            q_provenance_ref = _field_resolution_provenance_ref(resolved_pf_key, resolved_pf_entry)
            q_confidence_override, q_tag_override = _field_resolution_confidence_override(resolved_pf_entry)
            q_note = _field_resolution_note(resolved_pf_entry)
            planner_review = bool(resolved_pf_entry.get("planner_review_flag", False)) if isinstance(resolved_pf_entry, dict) else False
            q_planner_note = q_note if not planner_review else ""
            q_review_note = q_note if planner_review else ""
            q_confidence_explanation = q_note or "Derived from governed power-factor field resolution."
        else:
            q_value = round(float(p_mw_value) * 0.10, 3)
    else:
        q_value = round(float(p_mw_value) * 0.10, 3)
    q_mvar = _parameter_record(
        parameter_path="steady_state.q_mvar",
        value=q_value,
        units="MVAR",
        provenance_type=q_provenance_type,
        provenance_ref=q_provenance_ref,
        validation_report=validation_report,
        snippets=snippets,
        assumption_used=(p_mw["provenance_type"] == "assumption"),
        derived_from_rule=(q_provenance_type == "rule"),
        dependency_paths=q_dependency_paths,
        source_field_paths=q_dependency_paths,
        confidence_score_override=q_confidence_override,
        confidence_tag_override=q_tag_override,
        planner_note=q_planner_note,
        review_note=q_review_note,
        confidence_explanation=q_confidence_explanation,
        extra_metadata=_field_resolution_metadata(resolved_pf_key, resolved_pf_entry) if q_provenance_type == "field_resolution" else None,
    )
    output_parameters.append(q_mvar)
    if q_hold_context is not None:
        _apply_field_resolution_hold(q_mvar, q_hold_context)

    if pf_value is not None and 0 < abs(pf_value) <= 1.0 and q_hold_context is None:
        output_parameters.append(
            _parameter_record(
                parameter_path="steady_state.power_factor",
                value=round(abs(pf_value), 6),
                units="fraction",
                provenance_type="field_resolution",
                provenance_ref=_field_resolution_provenance_ref(resolved_pf_key, resolved_pf_entry),
                validation_report=validation_report,
                snippets=snippets,
                assumption_used=False,
                derived_from_rule=False,
                dependency_paths=[resolved_pf_key],
                source_field_paths=[resolved_pf_key],
                confidence_score_override=q_confidence_override,
                confidence_tag_override=q_tag_override,
                planner_note=q_planner_note,
                review_note=q_review_note,
                confidence_explanation=q_confidence_explanation or "Resolved from governed power-factor field resolution.",
                extra_metadata=_field_resolution_metadata(resolved_pf_key, resolved_pf_entry),
            )
        )
        set_nested_value(model_outputs, "steady_state.power_factor", round(abs(pf_value), 6))

    zip_dependency_paths = _resolve_zip_dependency_paths(
        engineering_model=engineering_model,
        normalized_input=normalized_input,
    )
    zip_p_value, zip_p_entry, zip_p_key = _resolve_field_resolution_value(canonical_state, "steady_state_zip_fraction_p")
    zip_i_value, zip_i_entry, zip_i_key = _resolve_field_resolution_value(canonical_state, "steady_state_zip_fraction_i")
    zip_z_value, zip_z_entry, zip_z_key = _resolve_field_resolution_value(canonical_state, "steady_state_zip_fraction_z")
    zip_hold_contexts = [
        ctx for ctx in (
            _field_resolution_translation_hold_context(zip_p_key, zip_p_entry),
            _field_resolution_translation_hold_context(zip_i_key, zip_i_entry),
            _field_resolution_translation_hold_context(zip_z_key, zip_z_entry),
        )
        if isinstance(ctx, dict)
    ]
    zip_p = None if _field_resolution_translation_hold_context(zip_p_key, zip_p_entry) else safe_float(zip_p_value)
    zip_i = None if _field_resolution_translation_hold_context(zip_i_key, zip_i_entry) else safe_float(zip_i_value)
    zip_z = None if _field_resolution_translation_hold_context(zip_z_key, zip_z_entry) else safe_float(zip_z_value)
    if zip_p is None:
        zip_p = 0.80
    if zip_i is None:
        zip_i = 0.10
    if zip_z is None:
        zip_z = 0.10
    zip_total = zip_p + zip_i + zip_z
    if zip_total > 0:
        zip_p = round(zip_p / zip_total, 6)
        zip_i = round(zip_i / zip_total, 6)
        zip_z = round(zip_z / zip_total, 6)
    zip_resolution_used = any(entry is not None for entry in (zip_p_entry, zip_i_entry, zip_z_entry))
    zip_resolution_note_bits: list[str] = []
    for entry in (zip_p_entry, zip_i_entry, zip_z_entry):
        note = _field_resolution_note(entry)
        if note and note not in zip_resolution_note_bits:
            zip_resolution_note_bits.append(note)
    zip_resolution_note = " ".join(zip_resolution_note_bits)
    zip_confidence_override = None
    zip_tag_override = None
    zip_planner_review = False
    if zip_resolution_used:
        scores = []
        for entry in (zip_p_entry, zip_i_entry, zip_z_entry):
            if isinstance(entry, dict):
                score = safe_float(entry.get("confidence"))
                if score is not None:
                    scores.append(score)
                if bool(entry.get("planner_review_flag", False)):
                    zip_planner_review = True
        if scores:
            zip_confidence_override = round(sum(scores) / len(scores), 2)
        if zip_planner_review:
            zip_tag_override = "LOW"
        zip_dependency_paths = [key for key in [zip_p_key, zip_i_key, zip_z_key] if key]

    output_parameters.append(
        _parameter_record(
            parameter_path="zip_model.constant_power_fraction",
            value=zip_p,
            units="fraction",
            provenance_type="field_resolution" if zip_resolution_used else "rule",
            provenance_ref=_field_resolution_provenance_ref(zip_p_key or "steady_state_zip_fraction_p", zip_p_entry) if zip_resolution_used else "RULE.ZIP.DEFAULTS.v1",
            validation_report=validation_report,
            snippets=snippets,
            assumption_used=False,
            derived_from_rule=not zip_resolution_used,
            dependency_paths=zip_dependency_paths,
            source_field_paths=zip_dependency_paths,
            confidence_score_override=zip_confidence_override,
            confidence_tag_override=zip_tag_override,
            planner_note=zip_resolution_note if zip_resolution_used and not zip_planner_review else "",
            review_note=zip_resolution_note if zip_resolution_used and zip_planner_review else "",
            confidence_explanation=(zip_resolution_note or "Resolved from governed ZIP field-resolution inputs.") if zip_resolution_used else "",
            extra_metadata=_field_resolution_metadata(zip_p_key or "steady_state_zip_fraction_p", zip_p_entry) if zip_resolution_used else None,
        )
    )
    output_parameters.append(
        _parameter_record(
            parameter_path="zip_model.constant_current_fraction",
            value=zip_i,
            units="fraction",
            provenance_type="field_resolution" if zip_resolution_used else "rule",
            provenance_ref=_field_resolution_provenance_ref(zip_i_key or "steady_state_zip_fraction_i", zip_i_entry) if zip_resolution_used else "RULE.ZIP.DEFAULTS.v1",
            validation_report=validation_report,
            snippets=snippets,
            assumption_used=False,
            derived_from_rule=not zip_resolution_used,
            dependency_paths=zip_dependency_paths,
            source_field_paths=zip_dependency_paths,
            confidence_score_override=zip_confidence_override,
            confidence_tag_override=zip_tag_override,
            planner_note=zip_resolution_note if zip_resolution_used and not zip_planner_review else "",
            review_note=zip_resolution_note if zip_resolution_used and zip_planner_review else "",
            confidence_explanation=(zip_resolution_note or "Resolved from governed ZIP field-resolution inputs.") if zip_resolution_used else "",
            extra_metadata=_field_resolution_metadata(zip_i_key or "steady_state_zip_fraction_i", zip_i_entry) if zip_resolution_used else None,
        )
    )
    output_parameters.append(
        _parameter_record(
            parameter_path="zip_model.constant_impedance_fraction",
            value=zip_z,
            units="fraction",
            provenance_type="field_resolution" if zip_resolution_used else "rule",
            provenance_ref=_field_resolution_provenance_ref(zip_z_key or "steady_state_zip_fraction_z", zip_z_entry) if zip_resolution_used else "RULE.ZIP.DEFAULTS.v1",
            validation_report=validation_report,
            snippets=snippets,
            assumption_used=False,
            derived_from_rule=not zip_resolution_used,
            dependency_paths=zip_dependency_paths,
            source_field_paths=zip_dependency_paths,
            confidence_score_override=zip_confidence_override,
            confidence_tag_override=zip_tag_override,
            planner_note=zip_resolution_note if zip_resolution_used and not zip_planner_review else "",
            review_note=zip_resolution_note if zip_resolution_used and zip_planner_review else "",
            confidence_explanation=(zip_resolution_note or "Resolved from governed ZIP field-resolution inputs.") if zip_resolution_used else "",
            extra_metadata=_field_resolution_metadata(zip_z_key or "steady_state_zip_fraction_z", zip_z_entry) if zip_resolution_used else None,
        )
    )
    if zip_hold_contexts:
        merged_zip_hold = {"note": " ".join(ctx.get("note", "").strip() for ctx in zip_hold_contexts if ctx.get("note")), "metadata": {}}
        for ctx in zip_hold_contexts:
            for key, value in (ctx.get("metadata") or {}).items():
                if value not in (None, "", [], {}):
                    merged_zip_hold["metadata"][key] = value
        for parameter in output_parameters[-3:]:
            _apply_field_resolution_hold(parameter, merged_zip_hold)

    ramp_rate_value, ramp_dependency_paths, ramp_source = _resolve_ramp_rate_mw_per_min(
        engineering_model=engineering_model,
    )
    resolved_ramp_summary, resolved_ramp_entry, resolved_ramp_key = _resolve_field_resolution_value(
        canonical_state,
        "load_ramp_profile_summary",
    )
    ramp_summary_text = _normalized_text(resolved_ramp_summary).lower()
    ramp_hold_context: dict[str, Any] | None = _field_resolution_translation_hold_context(resolved_ramp_key, resolved_ramp_entry)
    if ramp_hold_context is not None:
        resolved_ramp_summary = None
        ramp_summary_text = ""
    if ramp_rate_value is None and ramp_summary_text:
        if any(token in ramp_summary_text for token in ("fast", "aggressive", "step", "instant")):
            ramp_rate_value = 1.5
        elif any(token in ramp_summary_text for token in ("slow", "gradual", "staged")):
            ramp_rate_value = 0.75
        else:
            ramp_rate_value = 1.0
        ramp_dependency_paths = [resolved_ramp_key]
        ramp_source = "field_resolution"
    if ramp_rate_value is None:
        ramp_rate_value = 1.0
        ramp_provenance_ref = "RULE.RAMP.DEFAULTS.v1"
        ramp_provenance_type = "rule"
        ramp_confidence_override = None
        ramp_tag_override = None
        ramp_note = ""
    else:
        if ramp_source == "engineering_model":
            ramp_provenance_ref = "RULE.ENGINEERING_MODEL_RAMP_RATE.v1"
            ramp_provenance_type = "rule"
            ramp_confidence_override = None
            ramp_tag_override = None
            ramp_note = ""
        elif ramp_source == "field_resolution" and ramp_hold_context is None:
            ramp_provenance_ref = _field_resolution_provenance_ref(resolved_ramp_key, resolved_ramp_entry)
            ramp_provenance_type = "field_resolution"
            ramp_confidence_override, ramp_tag_override = _field_resolution_confidence_override(resolved_ramp_entry)
            ramp_note = _field_resolution_note(resolved_ramp_entry)
        else:
            ramp_provenance_ref = "RULE.RAMP.DEFAULTS.v1"
            ramp_provenance_type = "rule"
            ramp_confidence_override = None
            ramp_tag_override = None
            ramp_note = ""

    output_parameters.append(
        _parameter_record(
            parameter_path="ramping.max_ramp_up_mw_per_min",
            value=ramp_rate_value,
            units="MW/min",
            provenance_type=ramp_provenance_type,
            provenance_ref=ramp_provenance_ref,
            validation_report=validation_report,
            snippets=snippets,
            assumption_used=False,
            derived_from_rule=(ramp_provenance_type == "rule"),
            dependency_paths=ramp_dependency_paths,
            source_field_paths=ramp_dependency_paths,
            confidence_score_override=ramp_confidence_override,
            confidence_tag_override=ramp_tag_override,
            planner_note=ramp_note,
            confidence_explanation=ramp_note,
            extra_metadata=_field_resolution_metadata(resolved_ramp_key, resolved_ramp_entry) if ramp_provenance_type == "field_resolution" else None,
        )
    )
    output_parameters.append(
        _parameter_record(
            parameter_path="ramping.max_ramp_down_mw_per_min",
            value=ramp_rate_value,
            units="MW/min",
            provenance_type=ramp_provenance_type,
            provenance_ref=ramp_provenance_ref,
            validation_report=validation_report,
            snippets=snippets,
            assumption_used=False,
            derived_from_rule=(ramp_provenance_type == "rule"),
            dependency_paths=ramp_dependency_paths,
            source_field_paths=ramp_dependency_paths,
            confidence_score_override=ramp_confidence_override,
            confidence_tag_override=ramp_tag_override,
            planner_note=ramp_note,
            confidence_explanation=ramp_note,
            extra_metadata=_field_resolution_metadata(resolved_ramp_key, resolved_ramp_entry) if ramp_provenance_type == "field_resolution" else None,
        )
    )
    if ramp_hold_context is not None:
        for parameter in output_parameters[-2:]:
            _apply_field_resolution_hold(parameter, ramp_hold_context)

    for parameter in output_parameters:
        set_nested_value(model_outputs, parameter["parameter_path"], parameter["value"])

    if _can_run_agent(context):
        agent_result = _run_translation_support_agent(
            context=context,
            output_parameters=output_parameters,
            assumptions=assumptions,
            validation_report=validation_report,
        )
    else:
        agent_result = {
            "run_id": run_id,
            "agent_id": "",
            "status": "SKIPPED",
            "policy": {},
            "audit_path": "",
            "structured_output": {},
        }

    translation_support = _apply_translation_support(
        output_parameters=output_parameters,
        assumptions=assumptions,
        agent_result=agent_result,
    )

    llm_assistance = {
        "run_id": run_id,
        "stage_name": "translation",
        "task_name": "parameter_review",
        "status": str(agent_result.get("status", "")).strip() or "SKIPPED",
        "policy": dict(agent_result.get("policy", {})) if isinstance(agent_result.get("policy", {}), dict) else {},
        "audit_path": str(agent_result.get("audit_path", "")).strip(),
        "bounded_response": dict(agent_result.get("structured_output", {})) if isinstance(agent_result.get("structured_output", {}), dict) else {},
        "agent_id": str(agent_result.get("agent_id", "")).strip() or "translation_support_agent",
    }

    scenario_driver_context = _extract_scenario_driver_context(
        canonical_state=canonical_state,
        normalized_input=normalized_input,
    )
    driver_notes = _driver_context_notes(scenario_driver_context)
    for parameter in output_parameters:
        if not isinstance(parameter, dict):
            continue
        path = str(parameter.get("parameter_path", "")).strip()
        if path == "steady_state.p_mw":
            parameter["planner_note"] = _merge_notes(parameter.get("planner_note", ""), driver_notes.get("p_note", ""))
        elif path in {"steady_state.q_mvar", "steady_state.power_factor"}:
            parameter["planner_note"] = _merge_notes(parameter.get("planner_note", ""), driver_notes.get("q_note", ""))
        elif path in {"ramping.max_ramp_up_mw_per_min", "ramping.max_ramp_down_mw_per_min"}:
            parameter["planner_note"] = _merge_notes(parameter.get("planner_note", ""), driver_notes.get("ramp_note", ""))
        if path in {"steady_state.p_mw", "steady_state.q_mvar", "steady_state.power_factor", "ramping.max_ramp_up_mw_per_min", "ramping.max_ramp_down_mw_per_min"}:
            review_note = driver_notes.get("review_note", "")
            if review_note:
                parameter["review_note"] = _merge_notes(parameter.get("review_note", ""), review_note)
                parameter["confidence_tag"] = "LOW"
                parameter["confidence_score"] = min(float(parameter.get("confidence_score", 1.0) or 1.0), 0.49)
                parameter["confidence_explanation"] = _merge_notes(parameter.get("confidence_explanation", ""), review_note)
            parameter["scenario_driver_context_used"] = True

    confidence_summary = {
        "HIGH": 0,
        "MODERATE": 0,
        "LOW": 0,
        "UNRESOLVED": 0,
    }
    for parameter in output_parameters:
        confidence_tag = str(parameter["confidence_tag"])
        if confidence_tag not in confidence_summary:
            confidence_summary[confidence_tag] = 0
        confidence_summary[confidence_tag] += 1

    field_governance_core = build_field_governance_core(canonical_state=canonical_state)
    manual_review_queue = field_governance_core.get("manual_review_queue", {}) if isinstance(field_governance_core.get("manual_review_queue", {}), dict) else {}
    _apply_shared_review_priority_gating(output_parameters, manual_review_queue)
    ledger_downstream_governance = apply_ledger_governance_to_parameters(
        output_parameters,
        canonical_state,
        use_case="translation",
    )
    ledger_scenario_governance = apply_ledger_governance_to_parameters(
        output_parameters,
        canonical_state,
        use_case="scenario",
    )
    ledger_native_translation = build_ledger_native_translation_contract(
        output_parameters,
        model_outputs,
    )
    ledger_native_model_outputs = ledger_native_translation.get("ledger_native_model_outputs")
    if isinstance(ledger_native_model_outputs, dict) and ledger_native_model_outputs:
        model_outputs = ledger_native_model_outputs

    confidence_summary = {
        "HIGH": 0,
        "MODERATE": 0,
        "LOW": 0,
        "UNRESOLVED": 0,
    }
    for parameter in output_parameters:
        confidence_tag = str(parameter["confidence_tag"])
        if confidence_tag not in confidence_summary:
            confidence_summary[confidence_tag] = 0
        confidence_summary[confidence_tag] += 1

    schema_validation = build_translation_runtime_schema_validation(
        model_outputs,
        output_parameters,
    )
    governed_truth_summary = _governed_truth_summary(canonical_state, validation_report)
    governance_alerts = _governance_alerts_from_summary(governed_truth_summary, manual_review_queue, field_governance_core)

    return {
        "run_id": run_id,
        "model_outputs": model_outputs,
        "output_parameters": output_parameters,
        "assumptions": assumptions,
        "confidence_summary": confidence_summary,
        "schema_validation": schema_validation,
        "translation_support": translation_support,
        "llm_assistance": llm_assistance,
        "scenario_driver_context": scenario_driver_context,
        "governed_truth_summary": governed_truth_summary,
        "governance_alerts": governance_alerts,
        "ledger_downstream_governance": ledger_downstream_governance,
        "ledger_scenario_governance": ledger_scenario_governance,
        "ledger_native_translation": ledger_native_translation,
        "ledger_native_model_outputs": ledger_native_model_outputs if isinstance(ledger_native_model_outputs, dict) else model_outputs,
        "manual_review_queue": manual_review_queue,
        "field_governance_core": field_governance_core,
        "status": "TRANSLATED",
        "translated_at": utc_now_iso(),
    }


def run_service(
    context: Any,
    canonical_state_result: dict[str, Any] | None = None,
    validation_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    gap_resolution_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return translate_parameters(
        context=context,
        canonical_state_result=canonical_state_result,
        validation_result=validation_result,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
        gap_resolution_result=gap_resolution_result,
    )
