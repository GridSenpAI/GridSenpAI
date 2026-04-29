from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_run_id(context: Any) -> str:
    run_id = getattr(context, "run_id", None)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("context.run_id must be a non-empty string.")
    return run_id.strip()


def _find_parameter(
    output_parameters: list[dict[str, Any]],
    parameter_path: str,
) -> dict[str, Any] | None:
    for parameter in output_parameters:
        if not isinstance(parameter, dict):
            continue
        if str(parameter.get("parameter_path", "")).strip() == parameter_path:
            return parameter
    return None


def _get_assumption_ids(assumptions: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in assumptions:
        if not isinstance(item, dict):
            continue
        assumption_id = str(item.get("assumption_id", "")).strip()
        if assumption_id:
            result.append(assumption_id)
    return result


def _coerce_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _governance_alerts(translation_result: dict[str, Any] | None) -> dict[str, Any]:
    payload = translation_result if isinstance(translation_result, dict) else {}
    alerts = payload.get("governance_alerts") if isinstance(payload.get("governance_alerts"), dict) else {}
    result = dict(alerts) if isinstance(alerts, dict) else {}
    ledger_translation = payload.get("ledger_downstream_governance") if isinstance(payload.get("ledger_downstream_governance"), dict) else {}
    ledger_scenario = payload.get("ledger_scenario_governance") if isinstance(payload.get("ledger_scenario_governance"), dict) else {}
    if ledger_translation:
        result["ledger_downstream_governance"] = dict(ledger_translation)
    if ledger_scenario:
        result["ledger_scenario_governance"] = dict(ledger_scenario)
        result["scenario_ledger_gated_parameter_count"] = int(ledger_scenario.get("gated_parameter_count", 0) or 0)
        result["scenario_ledger_blocked_parameter_count"] = int(ledger_scenario.get("blocked_parameter_count", 0) or 0)
    return result


def _translation_support_note(translation_result: dict[str, Any] | None) -> str:
    if not isinstance(translation_result, dict):
        return ""

    translation_support = translation_result.get("translation_support", {})
    if not isinstance(translation_support, dict):
        return ""

    review_notes = translation_support.get("review_notes", [])
    if not isinstance(review_notes, list):
        review_notes = []

    planner_note = str(translation_support.get("planner_note", "")).strip()
    missing_info_summary = str(translation_support.get("missing_info_summary", "")).strip()

    notes: list[str] = []
    if planner_note:
        notes.append(planner_note)
    if missing_info_summary:
        notes.append(missing_info_summary)

    for item in review_notes:
        if isinstance(item, str) and item.strip():
            notes.append(item.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for note in notes:
        if note in seen:
            continue
        seen.add(note)
        deduped.append(note)

    return " ".join(deduped).strip()


def _translation_resolution_summary(output_parameters: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "parameter_count": 0,
        "field_resolution_backed_parameter_count": 0,
        "needs_review_parameter_count": 0,
        "planner_review_flag_count": 0,
        "needs_applicant_confirmation_count": 0,
        "assumption_backed_parameter_count": 0,
        "blocked_parameter_count": 0,
        "provisional_parameter_count": 0,
        "confidence_tag_counts": {},
        "provenance_type_counts": {},
    }
    for parameter in output_parameters:
        if not isinstance(parameter, dict):
            continue
        summary["parameter_count"] += 1
        provenance_type = str(parameter.get("provenance_type", "")).strip() or "unknown"
        summary["provenance_type_counts"][provenance_type] = summary["provenance_type_counts"].get(provenance_type, 0) + 1
        confidence_tag = str(parameter.get("confidence_tag", "")).strip().upper() or "UNKNOWN"
        summary["confidence_tag_counts"][confidence_tag] = summary["confidence_tag_counts"].get(confidence_tag, 0) + 1
        if provenance_type == "field_resolution":
            summary["field_resolution_backed_parameter_count"] += 1
        field_release_state = str(parameter.get("field_release_state", "")).strip().upper()
        if bool(parameter.get("planner_review_flag", False)):
            summary["planner_review_flag_count"] += 1
        if bool(parameter.get("needs_applicant_confirmation", False)):
            summary["needs_applicant_confirmation_count"] += 1
        if field_release_state == "BLOCKED":
            summary["blocked_parameter_count"] += 1
        elif field_release_state == "PROVISIONAL":
            summary["provisional_parameter_count"] += 1
        if confidence_tag in {"LOW", "UNRESOLVED"} or str(parameter.get("review_note", "")).strip() or field_release_state in {"BLOCKED", "PROVISIONAL"}:
            summary["needs_review_parameter_count"] += 1
        if provenance_type == "assumption":
            summary["assumption_backed_parameter_count"] += 1
    return summary


def _changed_parameter(
    *,
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    parameter_path: str,
    baseline_value: Any,
    new_value: Any,
    units: str,
    change_reason: str,
) -> dict[str, Any]:
    parameter = _find_parameter(output_parameters, parameter_path)
    dependency_paths: list[str] = []
    source_field_paths: list[str] = []
    supporting_snippet_ids: list[str] = []
    planner_note = ""
    review_note = ""
    confidence_explanation = ""

    if isinstance(parameter, dict):
        dependency_paths = list(parameter.get("dependency_paths", []))
        source_field_paths = list(parameter.get("source_field_paths", []))
        supporting_snippet_ids = list(parameter.get("supporting_snippet_ids", []))
        planner_note = str(parameter.get("planner_note", "")).strip()
        review_note = str(parameter.get("review_note", "")).strip()
        confidence_explanation = str(parameter.get("confidence_explanation", "")).strip()

    delta: float | None = None
    try:
        delta = round(float(new_value) - float(baseline_value), 6)
    except (TypeError, ValueError):
        delta = None

    changed = {
        "parameter_path": parameter_path,
        "baseline_parameter_path": parameter_path,
        "baseline_value": baseline_value,
        "new_value": new_value,
        "delta": delta,
        "units": units,
        "change_reason": change_reason,
        "dependency_paths": dependency_paths,
        "source_field_paths": source_field_paths,
        "supporting_snippet_ids": supporting_snippet_ids,
        "assumption_ids": _get_assumption_ids(assumptions),
        "planner_note": planner_note,
        "review_note": review_note,
        "confidence_explanation": confidence_explanation,
    }
    if isinstance(parameter, dict):
        for source_key, target_key in (
            ("provenance_type", "baseline_provenance_type"),
            ("provenance_ref", "baseline_provenance_ref"),
            ("confidence_tag", "baseline_confidence_tag"),
            ("confidence_score", "baseline_confidence_score"),
            ("planner_review_flag", "planner_review_flag"),
            ("needs_applicant_confirmation", "needs_applicant_confirmation"),
            ("decision_basis", "decision_basis"),
            ("accepted_value_kind", "accepted_value_kind"),
            ("planner_attention_tier", "planner_attention_tier"),
            ("field_resolution_field_key", "field_resolution_field_key"),
            ("field_release_state", "field_release_state"),
            ("translation_use_policy", "translation_use_policy"),
            ("scenario_use_policy", "scenario_use_policy"),
            ("planner_packet_use_policy", "planner_packet_use_policy"),
            ("export_readiness_tier", "export_readiness_tier"),
            ("contradiction_summary", "contradiction_summary"),
        ):
            value = parameter.get(source_key)
            if value not in (None, "", [], {}):
                changed[target_key] = value
        for source_key, target_key in (
            ("why_accepted", "why_accepted"),
            ("source_anchors", "source_anchors"),
        ):
            value = parameter.get(source_key)
            if isinstance(value, list):
                cleaned = [str(item).strip() for item in value if str(item).strip()]
                if cleaned:
                    changed[target_key] = cleaned
        for source_key, target_key in (
            ("alternatives_count", "alternatives_count"),
            ("supporting_sources_count", "supporting_sources_count"),
        ):
            value = parameter.get(source_key)
            if isinstance(value, int) and value >= 0:
                changed[target_key] = value
    return changed


def _coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _round_output(value: float) -> float:
    return round(value, 6)


def _get_output_number(outputs: dict[str, Any], section: str, key: str, fallback: float) -> float:
    section_payload = outputs.get(section, {})
    if not isinstance(section_payload, dict):
        return fallback
    value = _to_float(section_payload.get(key), fallback)
    if value is None:
        return fallback
    return value


def _set_output_number(outputs: dict[str, Any], section: str, key: str, value: float) -> None:
    if section not in outputs or not isinstance(outputs.get(section), dict):
        outputs[section] = {}
    outputs[section][key] = _round_output(value)


def _append_changed_parameter(
    changed_parameters: list[dict[str, Any]],
    *,
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    parameter_path: str,
    baseline_value: Any,
    new_value: Any,
    units: str,
    change_reason: str,
) -> None:
    if baseline_value == new_value:
        return
    changed_parameters.append(
        _changed_parameter(
            output_parameters=output_parameters,
            assumptions=assumptions,
            parameter_path=parameter_path,
            baseline_value=baseline_value,
            new_value=new_value,
            units=units,
            change_reason=change_reason,
        )
    )


def _baseline_metrics(outputs: dict[str, Any]) -> dict[str, float]:
    return {
        "p_mw": _get_output_number(outputs, "steady_state", "p_mw", 0.0),
        "cp": _get_output_number(outputs, "zip_model", "constant_power_fraction", 0.8),
        "cc": _get_output_number(outputs, "zip_model", "constant_current_fraction", 0.1),
        "cz": _get_output_number(outputs, "zip_model", "constant_impedance_fraction", 0.1),
        "ramp_up": _get_output_number(outputs, "ramping", "max_ramp_up_mw_per_min", 1.0),
        "ramp_down": _get_output_number(outputs, "ramping", "max_ramp_down_mw_per_min", 1.0),
        "power_factor": _get_output_number(outputs, "steady_state", "power_factor", 0.98),
    }


def _driver_text(driver_context: dict[str, Any], key: str) -> str:
    value = driver_context.get(key)
    return str(value).strip() if value is not None else ""


def _driver_float(driver_context: dict[str, Any], key: str, default: float | None = None) -> float | None:
    return _to_float(driver_context.get(key), default)


def _driver_bool(driver_context: dict[str, Any], key: str) -> bool | None:
    value = driver_context.get(key)
    return value if isinstance(value, bool) else None


def _driver_review_required(driver_context: dict[str, Any]) -> bool:
    telemetry_present = _driver_bool(driver_context, "telemetry_present")
    telemetry_points_count = int(_driver_float(driver_context, "telemetry_points_count", 0.0) or 0)
    protection_summary = _driver_text(driver_context, "protection_summary")
    return (telemetry_present is True and telemetry_points_count <= 0) or not protection_summary


def _normalize_zip_triplet(cp: float, cc: float, cz: float) -> tuple[float, float, float]:
    total = cp + cc + cz
    if total <= 0:
        return 0.8, 0.1, 0.1
    return (
        _round_output(cp / total),
        _round_output(cc / total),
        _round_output(cz / total),
    )


def _scenario_confidence(
    confidence_summary: dict[str, Any],
    changed_parameters: list[dict[str, Any]],
    driver_context: dict[str, Any] | None = None,
    governance_alerts: dict[str, Any] | None = None,
) -> str:
    alerts = governance_alerts if isinstance(governance_alerts, dict) else {}
    if isinstance(driver_context, dict) and _driver_review_required(driver_context):
        return "LOW"
    if any(str(item.get("field_release_state", "")).strip().upper() == "BLOCKED" or str(item.get("scenario_use_policy", "")).strip().lower() == "hold_for_review_variant_only" for item in changed_parameters if isinstance(item, dict)):
        return "LOW"
    if any(bool(item.get("planner_review_flag", False)) or bool(item.get("needs_applicant_confirmation", False)) for item in changed_parameters if isinstance(item, dict)):
        return "LOW"
    if int(alerts.get("scenario_ledger_blocked_parameter_count", 0) or 0) > 0:
        return "LOW"
    if int(alerts.get("manual_review_conflict_count", 0) or 0) > 0:
        return "LOW"
    if int(alerts.get("manual_review_interview_dependency_count", 0) or 0) > 0 and int(alerts.get("manual_review_planner_critical_count", 0) or 0) > 0:
        return "LOW"

    heavy_change_count = len(changed_parameters)
    low_count = int(confidence_summary.get("LOW", 0)) + int(confidence_summary.get("UNRESOLVED", 0))
    moderate_count = int(confidence_summary.get("MODERATE", 0))

    if low_count > 0 or heavy_change_count >= 6:
        return "LOW"
    if any(str(item.get("field_release_state", "")).strip().upper() == "PROVISIONAL" for item in changed_parameters if isinstance(item, dict)):
        return "MODERATE"
    if moderate_count > 0 or heavy_change_count >= 3 or int(alerts.get("manual_review_total_count", 0) or 0) > 0:
        return "MODERATE"
    return "HIGH"


def _build_variant(
    *,
    label: str,
    description: str,
    outputs: dict[str, Any],
    changed_parameters: list[dict[str, Any]],
    confidence_summary: dict[str, Any],
    translation_support_note: str,
    scenario_family: str,
    scenario_dimensions: dict[str, Any],
    translation_resolution_summary: dict[str, Any],
    scenario_driver_context: dict[str, Any] | None = None,
    governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assumption_heavy_change_count = sum(
        1 for item in changed_parameters if item.get("assumption_ids")
    )

    review_required_change_count = sum(
        1 for item in changed_parameters if isinstance(item, dict) and (
            bool(item.get("planner_review_flag", False))
            or bool(item.get("needs_applicant_confirmation", False))
            or str(item.get("baseline_confidence_tag", "")).strip().upper() in {"LOW", "UNRESOLVED"}
            or str(item.get("review_note", "")).strip()
        )
    )
    field_resolution_changed_count = sum(
        1 for item in changed_parameters if isinstance(item, dict) and str(item.get("baseline_provenance_type", "")).strip() == "field_resolution"
    )
    governance_alerts = governance_alerts if isinstance(governance_alerts, dict) else {}
    metadata = {
        "source_confidence_summary": dict(confidence_summary),
        "parameter_count": 7,
        "changed_parameter_count": len(changed_parameters),
        "assumption_heavy_change_count": assumption_heavy_change_count,
        "review_required_change_count": review_required_change_count,
        "field_resolution_changed_count": field_resolution_changed_count,
        "scenario_method": "bounded_deterministic_variation_v3",
        "scenario_family": scenario_family,
        "scenario_dimensions": dict(scenario_dimensions),
        "translation_resolution_summary": dict(translation_resolution_summary),
        "governance_alerts": dict(governance_alerts),
        "manual_review_queue_summary": dict(governance_alerts.get("manual_review_queue_summary", {})) if isinstance(governance_alerts.get("manual_review_queue_summary"), dict) else {},
        "field_governance_summary": dict(governance_alerts.get("field_governance_summary", {})) if isinstance(governance_alerts.get("field_governance_summary"), dict) else {},
        "stage_transition_summary": dict(governance_alerts.get("stage_transition_summary", {})) if isinstance(governance_alerts.get("stage_transition_summary"), dict) else {},
    }
    if translation_support_note:
        metadata["translation_support_note"] = translation_support_note

    return {
        "label": label,
        "description": description,
        "outputs": outputs,
        "confidence": _scenario_confidence(confidence_summary, changed_parameters, scenario_driver_context, governance_alerts),
        "changed_parameters": changed_parameters,
        "metadata": metadata,
    }


def _make_typical_variant(
    *,
    baseline_outputs: dict[str, Any],
    confidence_summary: dict[str, Any],
    translation_support_note: str,
    translation_resolution_summary: dict[str, Any],
    scenario_driver_context: dict[str, Any] | None = None,
    governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _build_variant(
        label="Typical",
        description="Baseline planner-facing case carried forward from translated outputs.",
        outputs=deepcopy(baseline_outputs),
        changed_parameters=[],
        confidence_summary=confidence_summary,
        translation_support_note=translation_support_note,
        scenario_family="baseline",
        scenario_dimensions={
            "buildout_phase": "baseline",
            "redundancy_state": "baseline",
            "cooling_condition": "baseline",
            "operating_assumption": "baseline",
            "ramping_profile": "baseline",
        },
        translation_resolution_summary=translation_resolution_summary,
        scenario_driver_context=scenario_driver_context,
        governance_alerts=governance_alerts,
    )


def _make_conservative_variant(
    *,
    baseline_outputs: dict[str, Any],
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    confidence_summary: dict[str, Any],
    translation_support_note: str,
    translation_resolution_summary: dict[str, Any],
    scenario_driver_context: dict[str, Any] | None = None,
    governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outputs = deepcopy(baseline_outputs)
    baseline = _baseline_metrics(baseline_outputs)
    changed_parameters: list[dict[str, Any]] = []

    new_cp = _clamp(baseline["cp"] + 0.05, 0.0, 1.0)
    new_cc = _clamp(baseline["cc"] - 0.025, 0.0, 1.0)
    new_cz = _clamp(baseline["cz"] - 0.025, 0.0, 1.0)
    new_cp, new_cc, new_cz = _normalize_zip_triplet(new_cp, new_cc, new_cz)

    _set_output_number(outputs, "zip_model", "constant_power_fraction", new_cp)
    _set_output_number(outputs, "zip_model", "constant_current_fraction", new_cc)
    _set_output_number(outputs, "zip_model", "constant_impedance_fraction", new_cz)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_power_fraction",
        baseline_value=baseline["cp"],
        new_value=new_cp,
        units="fraction",
        change_reason="bounded_conservative_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_current_fraction",
        baseline_value=baseline["cc"],
        new_value=new_cc,
        units="fraction",
        change_reason="bounded_conservative_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_impedance_fraction",
        baseline_value=baseline["cz"],
        new_value=new_cz,
        units="fraction",
        change_reason="bounded_conservative_adjustment",
    )

    new_ramp_up = _round_output(_clamp(baseline["ramp_up"] * 0.5, 0.1, baseline["ramp_up"]))
    new_ramp_down = _round_output(_clamp(baseline["ramp_down"] * 0.5, 0.1, baseline["ramp_down"]))
    _set_output_number(outputs, "ramping", "max_ramp_up_mw_per_min", new_ramp_up)
    _set_output_number(outputs, "ramping", "max_ramp_down_mw_per_min", new_ramp_down)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_up_mw_per_min",
        baseline_value=baseline["ramp_up"],
        new_value=new_ramp_up,
        units="MW/min",
        change_reason="bounded_conservative_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_down_mw_per_min",
        baseline_value=baseline["ramp_down"],
        new_value=new_ramp_down,
        units="MW/min",
        change_reason="bounded_conservative_adjustment",
    )

    return _build_variant(
        label="Conservative",
        description="Risk-sensitive bounded case with tighter ramp and higher constant-power loading.",
        outputs=outputs,
        changed_parameters=changed_parameters,
        confidence_summary=confidence_summary,
        translation_support_note=translation_support_note,
        scenario_family="core_bounds",
        scenario_dimensions={
            "buildout_phase": "baseline",
            "redundancy_state": "baseline",
            "cooling_condition": "baseline",
            "operating_assumption": "risk_sensitive",
            "ramping_profile": "tightened",
        },
        translation_resolution_summary=translation_resolution_summary,
        scenario_driver_context=scenario_driver_context,
        governance_alerts=governance_alerts,
    )


def _make_best_case_variant(
    *,
    baseline_outputs: dict[str, Any],
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    confidence_summary: dict[str, Any],
    translation_support_note: str,
    translation_resolution_summary: dict[str, Any],
    scenario_driver_context: dict[str, Any] | None = None,
    governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outputs = deepcopy(baseline_outputs)
    baseline = _baseline_metrics(baseline_outputs)
    changed_parameters: list[dict[str, Any]] = []

    new_cp = _clamp(baseline["cp"] - 0.05, 0.0, 1.0)
    new_cc = _clamp(baseline["cc"] + 0.025, 0.0, 1.0)
    new_cz = _clamp(baseline["cz"] + 0.025, 0.0, 1.0)
    new_cp, new_cc, new_cz = _normalize_zip_triplet(new_cp, new_cc, new_cz)

    _set_output_number(outputs, "zip_model", "constant_power_fraction", new_cp)
    _set_output_number(outputs, "zip_model", "constant_current_fraction", new_cc)
    _set_output_number(outputs, "zip_model", "constant_impedance_fraction", new_cz)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_power_fraction",
        baseline_value=baseline["cp"],
        new_value=new_cp,
        units="fraction",
        change_reason="bounded_best_case_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_current_fraction",
        baseline_value=baseline["cc"],
        new_value=new_cc,
        units="fraction",
        change_reason="bounded_best_case_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_impedance_fraction",
        baseline_value=baseline["cz"],
        new_value=new_cz,
        units="fraction",
        change_reason="bounded_best_case_adjustment",
    )

    new_ramp_up = _round_output(_clamp(baseline["ramp_up"] * 1.5, baseline["ramp_up"], baseline["ramp_up"] * 2.0))
    new_ramp_down = _round_output(_clamp(baseline["ramp_down"] * 1.5, baseline["ramp_down"], baseline["ramp_down"] * 2.0))
    _set_output_number(outputs, "ramping", "max_ramp_up_mw_per_min", new_ramp_up)
    _set_output_number(outputs, "ramping", "max_ramp_down_mw_per_min", new_ramp_down)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_up_mw_per_min",
        baseline_value=baseline["ramp_up"],
        new_value=new_ramp_up,
        units="MW/min",
        change_reason="bounded_best_case_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_down_mw_per_min",
        baseline_value=baseline["ramp_down"],
        new_value=new_ramp_down,
        units="MW/min",
        change_reason="bounded_best_case_adjustment",
    )

    return _build_variant(
        label="Best-case",
        description="Optimistic bounded case with looser ramp and slightly reduced constant-power loading.",
        outputs=outputs,
        changed_parameters=changed_parameters,
        confidence_summary=confidence_summary,
        translation_support_note=translation_support_note,
        scenario_family="core_bounds",
        scenario_dimensions={
            "buildout_phase": "baseline",
            "redundancy_state": "baseline",
            "cooling_condition": "baseline",
            "operating_assumption": "optimistic",
            "ramping_profile": "relaxed",
        },
        translation_resolution_summary=translation_resolution_summary,
        scenario_driver_context=scenario_driver_context,
        governance_alerts=governance_alerts,
    )


def _make_buildout_phase_variant(
    *,
    baseline_outputs: dict[str, Any],
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    confidence_summary: dict[str, Any],
    translation_support_note: str,
    translation_resolution_summary: dict[str, Any],
    scenario_driver_context: dict[str, Any] | None = None,
    governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outputs = deepcopy(baseline_outputs)
    baseline = _baseline_metrics(baseline_outputs)
    changed_parameters: list[dict[str, Any]] = []

    operating_modes = _driver_text(scenario_driver_context or {}, "planned_operating_modes_summary").lower()
    maintenance_modes = _driver_text(scenario_driver_context or {}, "maintenance_or_outage_operating_modes").lower()
    transfer_summary = _driver_text(scenario_driver_context or {}, "transfer_summary").lower()
    generator_transfer = _driver_text(scenario_driver_context or {}, "generator_transfer_sequence_summary").lower()

    scale_factor = 0.75
    if any(token in operating_modes for token in ("staged", "phase", "phased")):
        scale_factor = 0.65
    if any(token in maintenance_modes for token in ("maintenance", "outage", "reduced")):
        scale_factor = min(scale_factor, 0.6)
    if any(token in transfer_summary for token in ("manual", "delayed")) or any(token in generator_transfer for token in ("manual", "sequence", "staged")):
        scale_factor = min(scale_factor, 0.55)

    new_ramp_up = _round_output(_clamp(baseline["ramp_up"] * scale_factor, 0.1, baseline["ramp_up"]))
    new_ramp_down = _round_output(_clamp(baseline["ramp_down"] * scale_factor, 0.1, baseline["ramp_down"]))
    _set_output_number(outputs, "ramping", "max_ramp_up_mw_per_min", new_ramp_up)
    _set_output_number(outputs, "ramping", "max_ramp_down_mw_per_min", new_ramp_down)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_up_mw_per_min",
        baseline_value=baseline["ramp_up"],
        new_value=new_ramp_up,
        units="MW/min",
        change_reason="buildout_phase_partial_load_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_down_mw_per_min",
        baseline_value=baseline["ramp_down"],
        new_value=new_ramp_down,
        units="MW/min",
        change_reason="buildout_phase_partial_load_adjustment",
    )

    buildout_p_scale = 0.9 if scale_factor <= 0.65 else 0.95
    new_p_mw = _round_output(_clamp(baseline["p_mw"] * buildout_p_scale, 0.0, baseline["p_mw"]))
    _set_output_number(outputs, "steady_state", "p_mw", new_p_mw)
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="steady_state.p_mw",
        baseline_value=baseline["p_mw"],
        new_value=new_p_mw,
        units="MW",
        change_reason="buildout_phase_partial_load_adjustment",
    )

    new_cp = _clamp(baseline["cp"] - 0.02, 0.0, 1.0)
    new_cc = _clamp(baseline["cc"] + 0.01, 0.0, 1.0)
    new_cz = _clamp(baseline["cz"] + 0.01, 0.0, 1.0)
    new_cp, new_cc, new_cz = _normalize_zip_triplet(new_cp, new_cc, new_cz)

    _set_output_number(outputs, "zip_model", "constant_power_fraction", new_cp)
    _set_output_number(outputs, "zip_model", "constant_current_fraction", new_cc)
    _set_output_number(outputs, "zip_model", "constant_impedance_fraction", new_cz)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_power_fraction",
        baseline_value=baseline["cp"],
        new_value=new_cp,
        units="fraction",
        change_reason="buildout_phase_partial_load_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_current_fraction",
        baseline_value=baseline["cc"],
        new_value=new_cc,
        units="fraction",
        change_reason="buildout_phase_partial_load_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_impedance_fraction",
        baseline_value=baseline["cz"],
        new_value=new_cz,
        units="fraction",
        change_reason="buildout_phase_partial_load_adjustment",
    )

    return _build_variant(
        label="Buildout Phase",
        description="Bounded partial buildout case representing an earlier energization phase with moderated ramp behavior.",
        outputs=outputs,
        changed_parameters=changed_parameters,
        confidence_summary=confidence_summary,
        translation_support_note=translation_support_note,
        scenario_family="buildout_phase",
        scenario_dimensions={
            "buildout_phase": "phase_limited",
            "redundancy_state": "baseline",
            "cooling_condition": "baseline",
            "operating_assumption": "staged_energization",
            "ramping_profile": "moderated",
        },
        translation_resolution_summary=translation_resolution_summary,
        scenario_driver_context=scenario_driver_context,
        governance_alerts=governance_alerts,
    )


def _make_redundancy_degraded_variant(
    *,
    baseline_outputs: dict[str, Any],
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    confidence_summary: dict[str, Any],
    translation_support_note: str,
    translation_resolution_summary: dict[str, Any],
    scenario_driver_context: dict[str, Any] | None = None,
    governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outputs = deepcopy(baseline_outputs)
    baseline = _baseline_metrics(baseline_outputs)
    changed_parameters: list[dict[str, Any]] = []

    redundancy_text = _driver_text(scenario_driver_context or {}, "redundancy_architecture").upper()
    generator_unit_count = int(_driver_float(scenario_driver_context or {}, "generator_unit_count", 0.0) or 0)
    cp_shift = 0.03 + (0.02 if redundancy_text in {"2N", "N+2", "N+1"} or generator_unit_count >= 2 else 0.0)
    new_cp = _clamp(baseline["cp"] + cp_shift, 0.0, 1.0)
    new_cc = _clamp(baseline["cc"] - (cp_shift / 2.0), 0.0, 1.0)
    new_cz = _clamp(baseline["cz"] - (cp_shift / 2.0), 0.0, 1.0)
    new_cp, new_cc, new_cz = _normalize_zip_triplet(new_cp, new_cc, new_cz)

    _set_output_number(outputs, "zip_model", "constant_power_fraction", new_cp)
    _set_output_number(outputs, "zip_model", "constant_current_fraction", new_cc)
    _set_output_number(outputs, "zip_model", "constant_impedance_fraction", new_cz)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_power_fraction",
        baseline_value=baseline["cp"],
        new_value=new_cp,
        units="fraction",
        change_reason="redundancy_degraded_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_current_fraction",
        baseline_value=baseline["cc"],
        new_value=new_cc,
        units="fraction",
        change_reason="redundancy_degraded_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_impedance_fraction",
        baseline_value=baseline["cz"],
        new_value=new_cz,
        units="fraction",
        change_reason="redundancy_degraded_adjustment",
    )

    new_ramp_up = _round_output(_clamp(baseline["ramp_up"] * 0.8, 0.1, baseline["ramp_up"]))
    new_ramp_down = _round_output(_clamp(baseline["ramp_down"] * 0.8, 0.1, baseline["ramp_down"]))
    _set_output_number(outputs, "ramping", "max_ramp_up_mw_per_min", new_ramp_up)
    _set_output_number(outputs, "ramping", "max_ramp_down_mw_per_min", new_ramp_down)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_up_mw_per_min",
        baseline_value=baseline["ramp_up"],
        new_value=new_ramp_up,
        units="MW/min",
        change_reason="redundancy_degraded_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_down_mw_per_min",
        baseline_value=baseline["ramp_down"],
        new_value=new_ramp_down,
        units="MW/min",
        change_reason="redundancy_degraded_adjustment",
    )

    transfer_summary = _driver_text(scenario_driver_context or {}, "transfer_summary").lower()
    generator_transfer = _driver_text(scenario_driver_context or {}, "generator_transfer_sequence_summary").lower()
    p_scale = 0.98
    if generator_unit_count <= 1 or any(token in redundancy_text for token in ("n", "single")):
        p_scale = 0.94
    if any(token in transfer_summary for token in ("manual", "delayed")) or any(token in generator_transfer for token in ("manual", "staged")):
        p_scale = min(p_scale, 0.92)
    new_p_mw = _round_output(_clamp(baseline["p_mw"] * p_scale, 0.0, baseline["p_mw"]))
    _set_output_number(outputs, "steady_state", "p_mw", new_p_mw)
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="steady_state.p_mw",
        baseline_value=baseline["p_mw"],
        new_value=new_p_mw,
        units="MW",
        change_reason="redundancy_degraded_adjustment",
    )

    return _build_variant(
        label="Redundancy Degraded",
        description="Bounded reduced-redundancy case reflecting a less resilient operating posture.",
        outputs=outputs,
        changed_parameters=changed_parameters,
        confidence_summary=confidence_summary,
        translation_support_note=translation_support_note,
        scenario_family="redundancy_state",
        scenario_dimensions={
            "buildout_phase": "baseline",
            "redundancy_state": "degraded",
            "cooling_condition": "baseline",
            "operating_assumption": "reduced_resilience",
            "ramping_profile": "moderately_tightened",
        },
        translation_resolution_summary=translation_resolution_summary,
        scenario_driver_context=scenario_driver_context,
        governance_alerts=governance_alerts,
    )


def _make_high_cooling_demand_variant(
    *,
    baseline_outputs: dict[str, Any],
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    confidence_summary: dict[str, Any],
    translation_support_note: str,
    translation_resolution_summary: dict[str, Any],
    scenario_driver_context: dict[str, Any] | None = None,
    governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outputs = deepcopy(baseline_outputs)
    baseline = _baseline_metrics(baseline_outputs)
    changed_parameters: list[dict[str, Any]] = []

    cooling_share = _driver_float(scenario_driver_context or {}, "cooling_load_share", 0.0) or 0.0
    cp_shift = 0.04 + (0.03 if cooling_share >= 0.4 else 0.0)
    cc_shift = 0.02 + (0.01 if cooling_share >= 0.4 else 0.0)
    new_cp = _clamp(baseline["cp"] + cp_shift, 0.0, 1.0)
    new_cc = _clamp(baseline["cc"] - cc_shift, 0.0, 1.0)
    new_cz = _clamp(baseline["cz"] - (cp_shift - cc_shift), 0.0, 1.0)
    new_cp, new_cc, new_cz = _normalize_zip_triplet(new_cp, new_cc, new_cz)

    _set_output_number(outputs, "zip_model", "constant_power_fraction", new_cp)
    _set_output_number(outputs, "zip_model", "constant_current_fraction", new_cc)
    _set_output_number(outputs, "zip_model", "constant_impedance_fraction", new_cz)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_power_fraction",
        baseline_value=baseline["cp"],
        new_value=new_cp,
        units="fraction",
        change_reason="high_cooling_demand_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_current_fraction",
        baseline_value=baseline["cc"],
        new_value=new_cc,
        units="fraction",
        change_reason="high_cooling_demand_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="zip_model.constant_impedance_fraction",
        baseline_value=baseline["cz"],
        new_value=new_cz,
        units="fraction",
        change_reason="high_cooling_demand_adjustment",
    )

    cooling_arch = _driver_text(scenario_driver_context or {}, "cooling_architecture_summary").lower()
    pf_drop = 0.015 if cooling_share >= 0.4 else 0.01
    if any(token in cooling_arch for token in ("chiller", "compressor", "mechanical")):
        pf_drop += 0.005
    new_pf = _round_output(_clamp(baseline["power_factor"] - pf_drop, 0.85, 1.0))
    _set_output_number(outputs, "steady_state", "power_factor", new_pf)
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="steady_state.power_factor",
        baseline_value=baseline["power_factor"],
        new_value=new_pf,
        units="fraction",
        change_reason="high_cooling_demand_adjustment",
    )

    p_scale = 1.03 if cooling_share >= 0.4 else 1.01
    if any(token in cooling_arch for token in ("chiller", "compressor", "mechanical")):
        p_scale += 0.01
    new_p_mw = _round_output(_clamp(baseline["p_mw"] * p_scale, baseline["p_mw"], baseline["p_mw"] * 1.08))
    _set_output_number(outputs, "steady_state", "p_mw", new_p_mw)
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="steady_state.p_mw",
        baseline_value=baseline["p_mw"],
        new_value=new_p_mw,
        units="MW",
        change_reason="high_cooling_demand_adjustment",
    )

    new_ramp_up = _round_output(_clamp(baseline["ramp_up"] * 1.1, baseline["ramp_up"], baseline["ramp_up"] * 1.25))
    new_ramp_down = _round_output(_clamp(baseline["ramp_down"] * 1.1, baseline["ramp_down"], baseline["ramp_down"] * 1.25))
    _set_output_number(outputs, "ramping", "max_ramp_up_mw_per_min", new_ramp_up)
    _set_output_number(outputs, "ramping", "max_ramp_down_mw_per_min", new_ramp_down)
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_up_mw_per_min",
        baseline_value=baseline["ramp_up"],
        new_value=new_ramp_up,
        units="MW/min",
        change_reason="high_cooling_demand_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_down_mw_per_min",
        baseline_value=baseline["ramp_down"],
        new_value=new_ramp_down,
        units="MW/min",
        change_reason="high_cooling_demand_adjustment",
    )

    return _build_variant(
        label="High Cooling Demand",
        description="Bounded high-demand thermal support case with greater constant-power behavior and slightly reduced power factor.",
        outputs=outputs,
        changed_parameters=changed_parameters,
        confidence_summary=confidence_summary,
        translation_support_note=translation_support_note,
        scenario_family="cooling_condition",
        scenario_dimensions={
            "buildout_phase": "baseline",
            "redundancy_state": "baseline",
            "cooling_condition": "peak",
            "operating_assumption": "thermal_peak",
            "ramping_profile": "baseline",
        },
        translation_resolution_summary=translation_resolution_summary,
        scenario_driver_context=scenario_driver_context,
        governance_alerts=governance_alerts,
    )


def _make_fast_ramping_variant(
    *,
    baseline_outputs: dict[str, Any],
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    confidence_summary: dict[str, Any],
    translation_support_note: str,
    translation_resolution_summary: dict[str, Any],
    scenario_driver_context: dict[str, Any] | None = None,
    governance_alerts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outputs = deepcopy(baseline_outputs)
    baseline = _baseline_metrics(baseline_outputs)
    changed_parameters: list[dict[str, Any]] = []

    ramp_summary = _driver_text(scenario_driver_context or {}, "load_ramp_profile_summary").lower()
    transfer_summary = _driver_text(scenario_driver_context or {}, "transfer_summary").lower()
    emergency_modes = _driver_text(scenario_driver_context or {}, "emergency_operating_mode_summary").lower()
    generator_transfer = _driver_text(scenario_driver_context or {}, "generator_transfer_sequence_summary").lower()
    ramp_factor = 1.35
    if any(token in ramp_summary for token in ("fast", "aggressive")) or any(token in transfer_summary for token in ("step", "instant", "fast")):
        ramp_factor = 1.6
    if any(token in emergency_modes for token in ("load shed", "black start", "emergency")) or any(token in generator_transfer for token in ("instant", "fast")):
        ramp_factor = max(ramp_factor, 1.75)
    new_ramp_up = _round_output(_clamp(baseline["ramp_up"] * ramp_factor, baseline["ramp_up"], baseline["ramp_up"] * 2.0))
    new_ramp_down = _round_output(_clamp(baseline["ramp_down"] * ramp_factor, baseline["ramp_down"], baseline["ramp_down"] * 2.0))
    _set_output_number(outputs, "ramping", "max_ramp_up_mw_per_min", new_ramp_up)
    _set_output_number(outputs, "ramping", "max_ramp_down_mw_per_min", new_ramp_down)

    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_up_mw_per_min",
        baseline_value=baseline["ramp_up"],
        new_value=new_ramp_up,
        units="MW/min",
        change_reason="fast_ramping_adjustment",
    )
    _append_changed_parameter(
        changed_parameters,
        output_parameters=output_parameters,
        assumptions=assumptions,
        parameter_path="ramping.max_ramp_down_mw_per_min",
        baseline_value=baseline["ramp_down"],
        new_value=new_ramp_down,
        units="MW/min",
        change_reason="fast_ramping_adjustment",
    )

    p_scale = 1.02 if ramp_factor >= 1.6 else 1.0
    if p_scale > 1.0:
        new_p_mw = _round_output(_clamp(baseline["p_mw"] * p_scale, baseline["p_mw"], baseline["p_mw"] * 1.05))
        _set_output_number(outputs, "steady_state", "p_mw", new_p_mw)
        _append_changed_parameter(
            changed_parameters,
            output_parameters=output_parameters,
            assumptions=assumptions,
            parameter_path="steady_state.p_mw",
            baseline_value=baseline["p_mw"],
            new_value=new_p_mw,
            units="MW",
            change_reason="fast_ramping_adjustment",
        )

    return _build_variant(
        label="Fast Ramping",
        description="Bounded operating case for more aggressive ramp behavior during load transition windows.",
        outputs=outputs,
        changed_parameters=changed_parameters,
        confidence_summary=confidence_summary,
        translation_support_note=translation_support_note,
        scenario_family="ramping_behavior",
        scenario_dimensions={
            "buildout_phase": "baseline",
            "redundancy_state": "baseline",
            "cooling_condition": "baseline",
            "operating_assumption": "aggressive_transition",
            "ramping_profile": "accelerated",
        },
        translation_resolution_summary=translation_resolution_summary,
        scenario_driver_context=scenario_driver_context,
        governance_alerts=governance_alerts,
    )


def generate_scenarios(
    context: Any,
    translation_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = _require_run_id(context)

    if translation_result is None or not isinstance(translation_result, dict):
        raise ValueError("translation_result is required.")

    ledger_native_contract = translation_result.get("ledger_native_translation") if isinstance(translation_result.get("ledger_native_translation"), dict) else {}
    ledger_native_outputs = translation_result.get("ledger_native_model_outputs")
    if isinstance(ledger_native_outputs, dict) and ledger_native_outputs:
        baseline_outputs = ledger_native_outputs
        baseline_output_source = "ledger_native_model_outputs"
    else:
        return {
            "run_id": run_id,
            "scenarios": {},
            "scenario_variants": [],
            "scenario_families": {},
            "scenario_input_contract": {
                "contract_version": "ledger_native_scenario_input_v1",
                "baseline_output_source": "blocked_no_ledger_native_model_outputs",
                "blocked_reason": "LEDGER_NATIVE_TRANSLATION_REQUIRED",
            },
            "ledger_native_translation": dict(ledger_native_contract),
            "ledger_scenario_governance": dict(translation_result.get("ledger_scenario_governance", {})) if isinstance(translation_result.get("ledger_scenario_governance"), dict) else {},
            "status": "SCENARIOS_BLOCKED_LEDGER_FIRST_REQUIRED",
            "generated_at": utc_now_iso(),
        }

    output_parameters = translation_result.get("output_parameters", [])
    assumptions = translation_result.get("assumptions", [])
    confidence_summary = translation_result.get("confidence_summary", {})

    if not isinstance(output_parameters, list):
        output_parameters = []
    if not isinstance(assumptions, list):
        assumptions = []
    if not isinstance(confidence_summary, dict):
        confidence_summary = {}

    translation_support_note = _translation_support_note(translation_result)
    translation_resolution_summary = _translation_resolution_summary(output_parameters)
    scenario_driver_context = _coerce_dict(translation_result.get("scenario_driver_context"))
    governance_alerts = _governance_alerts(translation_result)

    variants = [
        _make_typical_variant(
            baseline_outputs=baseline_outputs,
            confidence_summary=confidence_summary,
            translation_support_note=translation_support_note,
            translation_resolution_summary=translation_resolution_summary,
            scenario_driver_context=scenario_driver_context,
            governance_alerts=governance_alerts,
        ),
        _make_conservative_variant(
            baseline_outputs=baseline_outputs,
            output_parameters=output_parameters,
            assumptions=assumptions,
            confidence_summary=confidence_summary,
            translation_support_note=translation_support_note,
            translation_resolution_summary=translation_resolution_summary,
            scenario_driver_context=scenario_driver_context,
            governance_alerts=governance_alerts,
        ),
        _make_best_case_variant(
            baseline_outputs=baseline_outputs,
            output_parameters=output_parameters,
            assumptions=assumptions,
            confidence_summary=confidence_summary,
            translation_support_note=translation_support_note,
            translation_resolution_summary=translation_resolution_summary,
            scenario_driver_context=scenario_driver_context,
            governance_alerts=governance_alerts,
        ),
        _make_buildout_phase_variant(
            baseline_outputs=baseline_outputs,
            output_parameters=output_parameters,
            assumptions=assumptions,
            confidence_summary=confidence_summary,
            translation_support_note=translation_support_note,
            translation_resolution_summary=translation_resolution_summary,
            scenario_driver_context=scenario_driver_context,
            governance_alerts=governance_alerts,
        ),
        _make_redundancy_degraded_variant(
            baseline_outputs=baseline_outputs,
            output_parameters=output_parameters,
            assumptions=assumptions,
            confidence_summary=confidence_summary,
            translation_support_note=translation_support_note,
            translation_resolution_summary=translation_resolution_summary,
            scenario_driver_context=scenario_driver_context,
            governance_alerts=governance_alerts,
        ),
        _make_high_cooling_demand_variant(
            baseline_outputs=baseline_outputs,
            output_parameters=output_parameters,
            assumptions=assumptions,
            confidence_summary=confidence_summary,
            translation_support_note=translation_support_note,
            translation_resolution_summary=translation_resolution_summary,
            scenario_driver_context=scenario_driver_context,
            governance_alerts=governance_alerts,
        ),
        _make_fast_ramping_variant(
            baseline_outputs=baseline_outputs,
            output_parameters=output_parameters,
            assumptions=assumptions,
            confidence_summary=confidence_summary,
            translation_support_note=translation_support_note,
            translation_resolution_summary=translation_resolution_summary,
            scenario_driver_context=scenario_driver_context,
            governance_alerts=governance_alerts,
        ),
    ]

    scenarios = {variant["label"]: dict(variant) for variant in variants}
    scenario_families: dict[str, list[str]] = {}
    for variant in variants:
        metadata = _coerce_dict(variant.get("metadata"))
        family = str(metadata.get("scenario_family", "uncategorized")).strip() or "uncategorized"
        scenario_families.setdefault(family, []).append(str(variant.get("label", "")).strip())

    return {
        "run_id": run_id,
        "scenarios": scenarios,
        "scenario_variants": variants,
        "scenario_families": scenario_families,
        "scenario_driver_context": scenario_driver_context,
        "governed_truth_summary": dict(translation_result.get("governed_truth_summary", {})) if isinstance(translation_result, dict) and isinstance(translation_result.get("governed_truth_summary"), dict) else {},
        "governance_alerts": governance_alerts,
        "ledger_scenario_governance": dict(translation_result.get("ledger_scenario_governance", {})) if isinstance(translation_result.get("ledger_scenario_governance"), dict) else {},
        "ledger_native_translation": dict(ledger_native_contract),
        "scenario_input_contract": {
            "contract_version": "ledger_native_scenario_input_v1",
            "baseline_output_source": baseline_output_source,
            "blocked_parameter_count": int(ledger_native_contract.get("blocked_parameter_count", 0) or 0),
            "provisional_parameter_count": int(ledger_native_contract.get("provisional_parameter_count", 0) or 0),
            "scenario_use_policy": str(ledger_native_contract.get("scenario_use_policy", "")).strip(),
        },
        "status": "SCENARIOS_GENERATED",
        "generated_at": utc_now_iso(),
    }


def run_service(
    context: Any,
    translation_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return generate_scenarios(
        context=context,
        translation_result=translation_result,
    )