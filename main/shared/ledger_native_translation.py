from __future__ import annotations

"""Ledger-native translation/scenario projection helpers.

Patch 27 makes translation genuinely ledger-first: when a closed planner field
ledger is present, translated model parameters are projected from ledger rows
before any legacy translation derivation is considered.  Legacy translation may
still exist as a fallback for incomplete historical runs, but active GridSenpAI
runs should use the planner ledger as the source of modeled truth.
"""

from copy import deepcopy
import math
import re
from typing import Any

from shared.planner_registry import translation_parameter_map

PARAMETER_OUTPUT_PATHS: dict[str, str] = {
    "steady_state.p_mw": "steady_state.p_mw",
    "steady_state.q_mvar": "steady_state.q_mvar",
    "steady_state.power_factor": "steady_state.power_factor",
    "zip_model.constant_power_fraction": "zip_model.constant_power_fraction",
    "zip_model.constant_current_fraction": "zip_model.constant_current_fraction",
    "zip_model.constant_impedance_fraction": "zip_model.constant_impedance_fraction",
    "ramping.max_ramp_up_mw_per_min": "ramping.max_ramp_up_mw_per_min",
    "ramping.max_ramp_down_mw_per_min": "ramping.max_ramp_down_mw_per_min",
    "network.poi_voltage_kv": "network.poi_voltage_kv",
    "network.internal_voltage_levels": "network.internal_voltage_levels",
    "network.interconnection_configuration": "network.interconnection_configuration",
    "equipment.ups_count": "equipment.ups_count",
    "equipment.generator_count": "equipment.generator_count",
    "equipment.transformer_count": "equipment.transformer_count",
    "equipment.transformer_ratings_mva": "equipment.transformer_ratings_mva",
    "schedule.requested_in_service_date": "schedule.requested_in_service_date",
    "schedule.commercial_operation_date": "schedule.commercial_operation_date",
}

EXTRA_LEDGER_NATIVE_PARAMETERS: dict[str, dict[str, Any]] = {
    "steady_state.power_factor": {
        "parameter_path": "steady_state.power_factor",
        "label": "Steady-state power factor at POI",
        "units": "per_unit",
        "accepted_field_id": "net_power_factor_at_poi",
        "dependency_paths": ["net_power_factor_at_poi"],
        "source_field_paths": ["net_power_factor_at_poi"],
        "topics": ["power factor", "steady state"],
    },
    "network.poi_voltage_kv": {
        "parameter_path": "network.poi_voltage_kv",
        "label": "POI voltage",
        "units": "kV",
        "accepted_field_id": "point_of_interconnection_voltage_kv",
        "dependency_paths": ["point_of_interconnection_voltage_kv", "facility.poi_voltage_kv"],
        "source_field_paths": ["point_of_interconnection_voltage_kv", "facility.poi_voltage_kv"],
        "topics": ["voltage", "poi"],
    },
    "network.internal_voltage_levels": {
        "parameter_path": "network.internal_voltage_levels",
        "label": "Internal voltage levels",
        "units": "kV",
        "accepted_field_id": "distribution_voltage_levels",
        "dependency_paths": ["distribution_voltage_levels", "facility.electrical_configuration.internal_voltage_levels"],
        "source_field_paths": ["distribution_voltage_levels", "facility.electrical_configuration.internal_voltage_levels"],
        "topics": ["voltage"],
    },
    "network.interconnection_configuration": {
        "parameter_path": "network.interconnection_configuration",
        "label": "Interconnection configuration",
        "units": "",
        "accepted_field_id": "interconnection_configuration",
        "dependency_paths": ["interconnection_configuration"],
        "source_field_paths": ["interconnection_configuration"],
        "topics": ["topology", "configuration"],
    },
    "equipment.ups_count": {
        "parameter_path": "equipment.ups_count",
        "label": "UPS count",
        "units": "count",
        "accepted_field_id": "facility.ups.count",
        "dependency_paths": ["facility.ups.count", "ups_unit_count"],
        "source_field_paths": ["facility.ups.count", "ups_unit_count"],
        "topics": ["ups", "equipment"],
    },
    "equipment.generator_count": {
        "parameter_path": "equipment.generator_count",
        "label": "Generator count",
        "units": "count",
        "accepted_field_id": "facility.generators.count",
        "dependency_paths": ["facility.generators.count", "generator_unit_count"],
        "source_field_paths": ["facility.generators.count", "generator_unit_count"],
        "topics": ["generator", "equipment"],
    },
    "equipment.transformer_count": {
        "parameter_path": "equipment.transformer_count",
        "label": "Transformer count",
        "units": "count",
        "accepted_field_id": "facility.transformers.count",
        "dependency_paths": ["facility.transformers.count", "interconnection_transformer_unit_count"],
        "source_field_paths": ["facility.transformers.count", "interconnection_transformer_unit_count"],
        "topics": ["transformer", "equipment"],
    },
    "equipment.transformer_ratings_mva": {
        "parameter_path": "equipment.transformer_ratings_mva",
        "label": "Transformer ratings",
        "units": "MVA",
        "accepted_field_id": "interconnection_transformer_rating_mva",
        "dependency_paths": ["interconnection_transformer_rating_mva", "facility.transformers.ratings_mva"],
        "source_field_paths": ["interconnection_transformer_rating_mva", "facility.transformers.ratings_mva"],
        "topics": ["transformer", "rating"],
    },
    "schedule.requested_in_service_date": {
        "parameter_path": "schedule.requested_in_service_date",
        "label": "Requested in-service date",
        "units": "",
        "accepted_field_id": "requested_in_service_date",
        "dependency_paths": ["requested_in_service_date"],
        "source_field_paths": ["requested_in_service_date"],
        "topics": ["schedule"],
    },
    "schedule.commercial_operation_date": {
        "parameter_path": "schedule.commercial_operation_date",
        "label": "Commercial operation date",
        "units": "",
        "accepted_field_id": "ultimate_commercial_operation_date",
        "dependency_paths": ["ultimate_commercial_operation_date"],
        "source_field_paths": ["ultimate_commercial_operation_date"],
        "topics": ["schedule"],
    },
}

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
_BLOCKED_STATES = {"BLOCKED", "BLOCKED_BY_ADJUDICATION_FAILURE"}
_REVIEW_TAGS = {"LOW", "UNRESOLVED"}
_HOLD_TRANSLATION_POLICIES = {"do_not_use", "hold_from_modeled_output", "hold_for_review", "hold"}
_HOLD_SCENARIO_POLICIES = {"do_not_use", "hold_for_review_variant_only", "hold_from_modeled_output", "hold_for_review", "hold"}


def _clean(value: Any) -> str:
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


def _coerce_number_from_text(value: Any) -> float | None:
    numeric = _safe_float(value)
    if numeric is not None:
        return numeric
    text = _clean(value).replace(",", "")
    if not text or text.upper() == "UNRESOLVED":
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return _safe_float(match.group(0))


def _set_nested_value(payload: dict[str, Any], path: str, value: Any) -> None:
    current = payload
    tokens = [token for token in path.split(".") if token]
    for token in tokens[:-1]:
        child = current.get(token)
        if not isinstance(child, dict):
            child = {}
            current[token] = child
        current = child
    if tokens:
        current[tokens[-1]] = value


def _status_from_field_resolution(row: dict[str, Any]) -> str:
    release_profile = row.get("field_release_profile") if isinstance(row.get("field_release_profile"), dict) else {}
    release_state = _clean(release_profile.get("release_state")).upper()
    translation_policy = _clean(release_profile.get("translation_use_policy")).lower()
    status = _clean(row.get("accepted_status") or row.get("status")).lower()
    band = _clean(row.get("confidence_band")).upper()
    if release_state.startswith("BLOCKED") or translation_policy in _HOLD_TRANSLATION_POLICIES:
        return "BLOCKED_BY_CONFLICT"
    if status in {"confirmed", "resolved", "accepted", "interview_confirmed", "interview_supplied"}:
        return "ACCEPTED"
    if status in {"provisional", "future_study_required", "not_applicable"}:
        return "PROVISIONAL"
    if status in {"conflicting", "conflict", "blocked", "review_required"} or band in {"LOW", "UNRESOLVED"}:
        return "BLOCKED_BY_CONFLICT"
    return "UNRESOLVED"


def _row_from_field_resolution_entry(field_key: str, entry: dict[str, Any]) -> dict[str, Any]:
    source_anchors = entry.get("source_anchors") if isinstance(entry.get("source_anchors"), list) else []
    source_anchor = _clean(source_anchors[0]) if source_anchors else _clean(entry.get("source_anchor"))
    release_profile = entry.get("field_release_profile") if isinstance(entry.get("field_release_profile"), dict) else {}
    field_id = _clean(entry.get("field_id")) or _clean(field_key)
    field_path = _clean(entry.get("field_path")) or _clean(field_key)
    confidence = _safe_float(entry.get("accepted_confidence"))
    if confidence is None:
        confidence = _safe_float(entry.get("confidence"))
    return {
        "field_id": field_id,
        "field_path": field_path,
        "field_label": _clean(entry.get("label")) or field_id or field_path,
        "accepted_value": entry.get("accepted_value", entry.get("value")),
        "normalized_value": entry.get("normalized_value", entry.get("accepted_value", entry.get("value"))),
        "status": _status_from_field_resolution(entry),
        "confidence_score": confidence if confidence is not None else 0.0,
        "confidence_band": _clean(entry.get("confidence_band")) or "UNRESOLVED",
        "source_anchor": source_anchor,
        "source_document": source_anchor or "FIELD_RESOLUTION",
        "source_section": _clean(entry.get("decision_basis")) or "field_resolution",
        "source_role": _clean(entry.get("accepted_source_hierarchy")) or "field_resolution",
        "evidence_snippet": "; ".join(_clean(item) for item in entry.get("why_accepted", []) if _clean(item)) if isinstance(entry.get("why_accepted"), list) else _clean(entry.get("why_accepted")),
        "conflict_summary": _clean(entry.get("contradiction_summary")),
        "manual_review_reason": _clean(entry.get("decision_basis")),
        "planner_critical": bool(entry.get("planner_critical", entry.get("planner_review_flag", False))),
        "release_state": _clean(release_profile.get("release_state")) or ("BLOCKED" if bool(entry.get("planner_review_flag", False)) else "ACCEPTED"),
        "translation_use_policy": _clean(release_profile.get("translation_use_policy")) or ("hold_from_modeled_output" if bool(entry.get("planner_review_flag", False)) else "use_for_modeling"),
        "scenario_use_policy": _clean(release_profile.get("scenario_use_policy")) or ("hold_for_review_variant_only" if bool(entry.get("planner_review_flag", False)) else "use_for_scenarios"),
        "planner_packet_use_policy": _clean(release_profile.get("planner_packet_use_policy")) or ("show_as_provisional_with_blocker" if bool(entry.get("planner_review_flag", False)) else "show_as_accepted"),
        "export_readiness_tier": _clean(release_profile.get("export_readiness_tier")) or ("blocked" if bool(entry.get("planner_review_flag", False)) else "ready"),
        "ledger_source_kind": "field_resolution",
    }


def _field_resolution_rows_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    field_resolution = state.get("field_resolution") if isinstance(state.get("field_resolution"), dict) else {}
    rows: list[dict[str, Any]] = []
    legacy_ledger = field_resolution.get("ledger") if isinstance(field_resolution.get("ledger"), list) else []
    for item in legacy_ledger:
        if isinstance(item, dict):
            key = _clean(item.get("field_path")) or _clean(item.get("field_id"))
            if key:
                rows.append(_row_from_field_resolution_entry(key, item))
    accepted_index = field_resolution.get("accepted_field_index") if isinstance(field_resolution.get("accepted_field_index"), dict) else {}
    for key, item in accepted_index.items():
        if isinstance(item, dict):
            rows.append(_row_from_field_resolution_entry(_clean(key), item))
    return rows


def _planner_rows_from_state(canonical_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    state = canonical_state if isinstance(canonical_state, dict) else {}
    contract = state.get("planner_field_contract") if isinstance(state.get("planner_field_contract"), dict) else {}
    rows = contract.get("planner_field_ledger") if isinstance(contract.get("planner_field_ledger"), list) else None
    if rows is None:
        rows = state.get("planner_field_ledger") if isinstance(state.get("planner_field_ledger"), list) else None
    if rows is not None:
        clean_rows = [row for row in rows if isinstance(row, dict)]
        if clean_rows:
            return clean_rows
    return _field_resolution_rows_from_state(state)


def _ledger_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in (_clean(row.get("field_path")), _clean(row.get("field_id"))):
            if key and key not in index:
                index[key] = row
    return index


def _row_source_reference(row: dict[str, Any] | None) -> str:
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


def _row_hold_reason(row: dict[str, Any] | None, *, use_case: str = "translation") -> str:
    if not isinstance(row, dict):
        return "Planner ledger row is missing."
    status = _clean(row.get("status")).upper()
    release_state = _clean(row.get("release_state")).upper()
    translation_policy = _clean(row.get("translation_use_policy")).lower()
    scenario_policy = _clean(row.get("scenario_use_policy")).lower()
    accepted_value = _clean(row.get("accepted_value"))
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
    if not reasons:
        return ""
    label = _clean(row.get("field_label")) or _clean(row.get("field_path")) or "planner field"
    return f"Planner ledger gates {label} from automatic {use_case} use because " + "; ".join(reasons) + f". Source: {_row_source_reference(row)}."


def _row_status_class(row: dict[str, Any] | None, *, use_case: str = "translation") -> str:
    if not isinstance(row, dict):
        return "missing"
    status = _clean(row.get("status")).upper()
    if _row_hold_reason(row, use_case=use_case):
        return "blocked" if status in BLOCKED_LEDGER_STATUSES else "provisional"
    if status in ACCEPTED_LEDGER_STATUSES:
        return "accepted"
    if status in PROVISIONAL_LEDGER_STATUSES:
        return "provisional"
    return "blocked"


def _confidence_tag(score: float | None, *, status_class: str) -> str:
    if status_class == "blocked":
        return "LOW"
    value = 0.0 if score is None else max(0.0, min(1.0, float(score)))
    if value >= 0.85:
        return "HIGH"
    if value >= 0.60:
        return "MODERATE"
    return "LOW"


def _confidence_score(row: dict[str, Any] | None, *, status_class: str) -> float:
    if not isinstance(row, dict):
        return 0.0
    score = _safe_float(row.get("confidence_score"))
    if score is None:
        score = _safe_float(row.get("confidence"))
    score = 0.0 if score is None else max(0.0, min(1.0, float(score)))
    if status_class == "blocked":
        return min(score, 0.49)
    if status_class == "provisional":
        return min(score if score else 0.59, 0.74)
    return score


def _parameter_configs() -> dict[str, dict[str, Any]]:
    configs = {path: dict(config) for path, config in translation_parameter_map().items()}
    for path, config in EXTRA_LEDGER_NATIVE_PARAMETERS.items():
        configs.setdefault(path, dict(config))
    return {path: config for path, config in configs.items() if path in PARAMETER_OUTPUT_PATHS}


def _candidate_keys_for_config(parameter_path: str, config: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    if parameter_path == "steady_state.p_mw":
        # Keep public registry dependency helpers stable while allowing the
        # ledger-native translator to consume registry-first peak/ultimate aliases
        # that appear in the final planner ledger.
        for alias in (
            "peak_demand_mw",
            "accepted_peak_demand_mw",
            "facility.load_schedule.maximum_coincident_demand_mw",
            "facility.load_schedule.ultimate_mw",
            "facility.load_schedule.phase_3_mw",
        ):
            if alias not in keys:
                keys.append(alias)
    for key in (config.get("accepted_field_id"),):
        cleaned = _clean(key)
        if cleaned:
            keys.append(cleaned)
    for collection_key in ("source_field_paths", "dependency_paths"):
        values = config.get(collection_key)
        if not isinstance(values, list):
            continue
        for value in values:
            cleaned = _clean(value)
            if not cleaned or cleaned.startswith("engineering_model."):
                continue
            if parameter_path == "steady_state.q_mvar" and cleaned in {"facility.load_schedule.phase_1_mw", "facility.load_schedule.phase_3_mw", "peak_demand_mw", "accepted_peak_demand_mw", "net_power_factor_at_poi"}:
                # Active/reactive power should be derived from P and PF unless a
                # direct reactive-power ledger field exists.  Do not treat the
                # active MW dependency itself as Q.
                continue
            if parameter_path in {"ramping.max_ramp_up_mw_per_min", "ramping.max_ramp_down_mw_per_min"} and cleaned in {"facility.load_schedule.phase_1_mw", "facility.load_schedule.phase_3_mw", "peak_demand_mw", "accepted_peak_demand_mw"}:
                # Phase MW can support ramp review but is not itself a ramp rate.
                continue
            if cleaned not in keys:
                keys.append(cleaned)
    return keys


def _best_row_for_config(index: dict[str, dict[str, Any]], config: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    candidates: list[tuple[int, int, dict[str, Any], str]] = []
    for order, key in enumerate(_candidate_keys_for_config(_clean(config.get("parameter_path")) or "", config)):
        row = index.get(key)
        if not isinstance(row, dict):
            continue
        status_class = _row_status_class(row, use_case="translation")
        rank = {"accepted": 0, "provisional": 1, "blocked": 2, "missing": 3}.get(status_class, 3)
        candidates.append((rank, order, row, key))
    if not candidates:
        return None, ""
    candidates.sort(key=lambda item: item[:2])
    _, _, row, key = candidates[0]
    return row, key


def _parameter_payload(
    *,
    parameter_path: str,
    config: dict[str, Any],
    value: Any,
    row: dict[str, Any] | None,
    source_key: str,
    status_class: str,
    derived_from: list[str] | None = None,
    derivation_note: str = "",
) -> dict[str, Any]:
    confidence = _confidence_score(row, status_class=status_class)
    hold_reason = _row_hold_reason(row, use_case="translation") if isinstance(row, dict) else "Planner ledger source row is missing."
    if derivation_note:
        hold_reason = f"{derivation_note} {hold_reason}".strip()
    source_paths = [source_key] if source_key else []
    if derived_from:
        for item in derived_from:
            cleaned = _clean(item)
            if cleaned and cleaned not in source_paths:
                source_paths.append(cleaned)
    source_ref = _row_source_reference(row)
    field_path = _clean(row.get("field_path")) if isinstance(row, dict) else source_key
    field_id = _clean(row.get("field_id")) if isinstance(row, dict) else source_key
    provenance_type = "field_resolution" if isinstance(row, dict) and _clean(row.get("ledger_source_kind")) == "field_resolution" else "planner_field_ledger"
    planner_note = _clean(row.get("conflict_summary")) if isinstance(row, dict) else ""
    if isinstance(row, dict) and provenance_type == "field_resolution" and not planner_note:
        basis = _clean(row.get("manual_review_reason"))
        evidence = _clean(row.get("evidence_snippet"))
        bits = []
        if basis:
            bits.append(f"Field resolution basis: {basis}.")
        if evidence:
            bits.append(f"Why accepted: {evidence}.")
        planner_note = " ".join(bits).strip()

    if hold_reason:
        confidence_explanation = hold_reason
        if planner_note and planner_note not in confidence_explanation:
            confidence_explanation = f"{confidence_explanation} {planner_note}".strip()
    elif planner_note:
        confidence_explanation = planner_note
    else:
        confidence_explanation = f"Ledger-native translation used {_clean(row.get('field_label')) or field_path} from {source_ref}."

    payload = {
        "parameter_path": parameter_path,
        "value": value,
        "units": _clean(config.get("units")),
        "provenance_type": provenance_type,
        "provenance_ref": source_ref,
        "dependency_paths": source_paths,
        "source_field_paths": source_paths,
        "supporting_snippet_ids": [],
        "confidence_score": round(confidence, 2),
        "confidence_tag": _confidence_tag(confidence, status_class=status_class),
        "confidence_factors": {
            "engineer_confirmed": status_class == "accepted" and _clean(row.get("interview_status")).lower() in {"confirmed", "supplied", "answered"} if isinstance(row, dict) else False,
            "direct_evidence_count": 1 if isinstance(row, dict) and _clean(row.get("source_document")) and _clean(row.get("source_document")) != "No direct source found" else 0,
            "derived_from_rule": bool(derived_from),
            "assumption_used": False,
            "conflict_present": bool(isinstance(row, dict) and _clean(row.get("conflict_summary"))),
            "missing_dependency": status_class == "blocked",
            "uses_default_rule": False,
        },
        "planner_note": planner_note,
        "review_note": hold_reason if status_class != "accepted" else "",
        "confidence_explanation": confidence_explanation,
        "field_resolution_field_key": source_key or field_path or field_id,
        "planner_ledger_field_path": field_path,
        "planner_ledger_field_id": field_id,
        "used_planner_field_ledger": provenance_type == "planner_field_ledger",
        "used_field_resolution": provenance_type == "field_resolution",
        "planner_ledger_status": _clean(row.get("status")).upper() if isinstance(row, dict) else "MISSING",
        "planner_ledger_hold_reason": hold_reason,
        "field_release_state": "BLOCKED" if status_class == "blocked" else "PROVISIONAL" if status_class == "provisional" else "ACCEPTED",
        "translation_use_policy": _clean(row.get("translation_use_policy")) if isinstance(row, dict) else "do_not_use",
        "scenario_use_policy": _clean(row.get("scenario_use_policy")) if isinstance(row, dict) else "do_not_use",
        "planner_packet_use_policy": _clean(row.get("planner_packet_use_policy")) if isinstance(row, dict) else "review_required",
        "planner_review_flag": status_class != "accepted",
        "ledger_downstream_gated": status_class == "blocked",
        "ledger_native_primary": True,
        "ledger_native_status_class": status_class,
    }
    if isinstance(row, dict):
        payload["source_document"] = _clean(row.get("source_document"))
        payload["source_page"] = _clean(row.get("source_page"))
        payload["source_section"] = _clean(row.get("source_section"))
        payload["source_role"] = _clean(row.get("source_role"))
        payload["evidence_snippet"] = _clean(row.get("evidence_snippet"))[:500]
    return payload


def _value_for_direct_parameter(parameter_path: str, config: dict[str, Any], row: dict[str, Any] | None) -> Any:
    if not isinstance(row, dict):
        return None
    value = row.get("normalized_value", row.get("accepted_value"))
    if _clean(value).upper() == "UNRESOLVED":
        return None
    if parameter_path in {"steady_state.p_mw", "steady_state.q_mvar", "steady_state.power_factor", "ramping.max_ramp_up_mw_per_min", "ramping.max_ramp_down_mw_per_min", "zip_model.constant_power_fraction", "zip_model.constant_current_fraction", "zip_model.constant_impedance_fraction"}:
        numeric_value = _coerce_number_from_text(value)
        if parameter_path == "steady_state.power_factor" and numeric_value is not None and not (0.0 < abs(numeric_value) <= 1.0):
            return None
        return numeric_value
    return value


_ZIP_PARAMETER_PATHS = (
    "zip_model.constant_power_fraction",
    "zip_model.constant_current_fraction",
    "zip_model.constant_impedance_fraction",
)


def _remove_nested_value(payload: dict[str, Any], path: str) -> None:
    current: Any = payload
    tokens = [token for token in path.split(".") if token]
    for token in tokens[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(token)
    if isinstance(current, dict) and tokens:
        current.pop(tokens[-1], None)


def _append_parameter_note(parameter: dict[str, Any], field_name: str, note: str) -> None:
    existing = _clean(parameter.get(field_name))
    if existing and note in existing:
        return
    parameter[field_name] = f"{existing} {note}".strip() if existing else note


def _block_parameter_for_model_safety(parameter: dict[str, Any], reason: str) -> None:
    parameter["value"] = None
    parameter["field_release_state"] = "BLOCKED"
    parameter["translation_use_policy"] = "do_not_use"
    parameter["scenario_use_policy"] = "do_not_use"
    parameter["planner_packet_use_policy"] = "show_as_blocked"
    parameter["planner_review_flag"] = True
    parameter["ledger_downstream_gated"] = True
    parameter["ledger_native_status_class"] = "blocked"
    parameter["confidence_score"] = min(float(parameter.get("confidence_score", 0.49) or 0.49), 0.49)
    parameter["confidence_tag"] = "LOW"
    _append_parameter_note(parameter, "review_note", reason)
    _append_parameter_note(parameter, "confidence_explanation", reason)


def _enforce_zip_model_safety(parameters_by_path: dict[str, dict[str, Any]], model_outputs: dict[str, Any]) -> dict[str, Any]:
    zip_parameters = {path: parameters_by_path.get(path) for path in _ZIP_PARAMETER_PATHS}
    present_parameters = [parameter for parameter in zip_parameters.values() if isinstance(parameter, dict)]
    if not present_parameters:
        return {
            "zip_model_status": "NO_LEDGER_ZIP_PARAMETERS",
            "zip_model_safe": False,
            "zip_model_note": "No ledger-backed ZIP parameters were available for model output.",
        }

    raw_values: dict[str, float | None] = {}
    for path, parameter in zip_parameters.items():
        raw_values[path] = _safe_float(parameter.get("value")) if isinstance(parameter, dict) else None

    missing_paths = [path for path, value in raw_values.items() if value is None]
    out_of_range_paths = [path for path, value in raw_values.items() if value is not None and not (0.0 <= value <= 1.0)]
    total = sum(value for value in raw_values.values() if value is not None)
    total_invalid = not missing_paths and not math.isclose(total, 1.0, rel_tol=0.01, abs_tol=0.01)

    if missing_paths or out_of_range_paths or total <= 0 or total_invalid:
        reason_bits = ["ZIP model fractions are not safe for modeling output."]
        if missing_paths:
            reason_bits.append("Missing fractions: " + ", ".join(missing_paths) + ".")
        if out_of_range_paths:
            reason_bits.append("Fractions outside 0.0-1.0: " + ", ".join(out_of_range_paths) + ".")
        if total <= 0:
            reason_bits.append("ZIP fraction total is not positive.")
        elif total_invalid:
            reason_bits.append(f"ZIP fraction total is {round(total, 6)}, not approximately 1.0.")
        reason = " ".join(reason_bits)
        for parameter in present_parameters:
            _block_parameter_for_model_safety(parameter, reason)
        for path in _ZIP_PARAMETER_PATHS:
            _remove_nested_value(model_outputs, PARAMETER_OUTPUT_PATHS[path])
        return {
            "zip_model_status": "BLOCKED_UNSAFE_ZIP_FRACTIONS",
            "zip_model_safe": False,
            "zip_model_note": reason,
            "zip_model_raw_values": dict(raw_values),
        }

    rounded_values = {path: round(float(value), 6) for path, value in raw_values.items() if value is not None}
    for path, value in rounded_values.items():
        parameter = parameters_by_path.get(path)
        if isinstance(parameter, dict):
            parameter["value"] = value
        _set_nested_value(model_outputs, PARAMETER_OUTPUT_PATHS[path], value)
    return {
        "zip_model_status": "SAFE",
        "zip_model_safe": True,
        "zip_model_note": "ZIP model fractions are bounded and sum to approximately 1.0.",
        "zip_model_raw_values": dict(raw_values),
        "zip_model_projected_values": rounded_values,
    }


def _derive_q_from_p_and_pf(parameters_by_path: dict[str, dict[str, Any]], index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    p = parameters_by_path.get("steady_state.p_mw")
    pf = parameters_by_path.get("steady_state.power_factor")
    if not isinstance(p, dict) or not isinstance(pf, dict):
        return None
    p_value = _safe_float(p.get("value"))
    pf_value = _safe_float(pf.get("value"))
    if p_value is None or pf_value is None or pf_value <= 0 or pf_value > 1.0:
        return None
    q_value = abs(p_value) * math.tan(math.acos(max(0.0, min(1.0, abs(pf_value)))))
    config = _parameter_configs().get("steady_state.q_mvar", {
        "parameter_path": "steady_state.q_mvar",
        "units": "MVAR",
        "source_field_paths": ["peak_demand_mw", "accepted_peak_demand_mw", "facility.load_schedule.phase_3_mw", "net_power_factor_at_poi"],
    })
    source_row = index.get(_clean(pf.get("planner_ledger_field_path"))) or index.get(_clean(pf.get("planner_ledger_field_id")))
    source_key = _clean(pf.get("planner_ledger_field_path")) or _clean(pf.get("planner_ledger_field_id"))
    status_class = "provisional" if p.get("planner_review_flag") or pf.get("planner_review_flag") else "accepted"
    return _parameter_payload(
        parameter_path="steady_state.q_mvar",
        config=config,
        value=round(q_value, 6),
        row=source_row,
        source_key=source_key,
        status_class=status_class,
        derived_from=[_clean(pf.get("planner_ledger_field_path")), _clean(p.get("planner_ledger_field_path"))],
        derivation_note="Derived from ledger-native active power and ledger-native power factor.",
    )


def build_ledger_first_translation_inputs(
    canonical_state: dict[str, Any] | None,
    *,
    include_blocked_parameters: bool = True,
) -> dict[str, Any]:
    """Build translated parameters directly from the closed planner ledger.

    This is the Patch 27 primary translation contract.  If planner ledger rows are
    present, callers should use this output as the main translation source and
    treat legacy translation as fallback/diagnostic only.
    """
    rows = _planner_rows_from_state(canonical_state)
    index = _ledger_index(rows)
    if not rows:
        return {
            "contract_version": "ledger_native_translation_primary_v1",
            "used_ledger_native_primary": False,
            "fallback_allowed": True,
            "fallback_reason": "No planner field ledger rows were available.",
            "planner_ledger_row_count": 0,
            "output_parameters": [],
            "model_outputs": {},
            "excluded_parameters": [],
            "blocked_parameter_count": 0,
            "provisional_parameter_count": 0,
            "accepted_parameter_count": 0,
        }

    parameters: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    model_outputs: dict[str, Any] = {}
    parameters_by_path: dict[str, dict[str, Any]] = {}

    for parameter_path, config in _parameter_configs().items():
        config = dict(config)
        config["parameter_path"] = parameter_path
        row, source_key = _best_row_for_config(index, config)
        status_class = _row_status_class(row, use_case="translation")
        value = _value_for_direct_parameter(parameter_path, config, row)
        if status_class == "blocked" or value is None:
            # Reactive power is commonly not provided as a direct ledger row.
            # When P and PF are available, let the governed derivation below
            # create q_mvar instead of emitting a leading blocked q_mvar record.
            if parameter_path == "steady_state.q_mvar":
                exclusion = {
                    "parameter_path": parameter_path,
                    "reason": _row_hold_reason(row, use_case="translation") if isinstance(row, dict) else "No direct reactive-power ledger source row; derivation from P and PF will be attempted.",
                    "source_field_key": source_key,
                    "ledger_status": _clean(row.get("status")).upper() if isinstance(row, dict) else "MISSING",
                    "derivation_attempted": True,
                }
                excluded.append(exclusion)
                continue
            exclusion = {
                "parameter_path": parameter_path,
                "reason": _row_hold_reason(row, use_case="translation") if isinstance(row, dict) else "No matching planner ledger source row.",
                "source_field_key": source_key,
                "ledger_status": _clean(row.get("status")).upper() if isinstance(row, dict) else "MISSING",
            }
            excluded.append(exclusion)
            if include_blocked_parameters:
                parameters.append(_parameter_payload(
                    parameter_path=parameter_path,
                    config=config,
                    value=None,
                    row=row,
                    source_key=source_key,
                    status_class="blocked",
                ))
            continue
        parameter = _parameter_payload(
            parameter_path=parameter_path,
            config=config,
            value=value,
            row=row,
            source_key=source_key,
            status_class=status_class,
        )
        parameters.append(parameter)
        parameters_by_path[parameter_path] = parameter
        _set_nested_value(model_outputs, PARAMETER_OUTPUT_PATHS[parameter_path], value)

    if "steady_state.q_mvar" not in parameters_by_path:
        derived_q = _derive_q_from_p_and_pf(parameters_by_path, index)
        if isinstance(derived_q, dict):
            parameters.append(derived_q)
            parameters_by_path["steady_state.q_mvar"] = derived_q
            if derived_q.get("value") is not None and derived_q.get("ledger_native_status_class") != "blocked":
                _set_nested_value(model_outputs, PARAMETER_OUTPUT_PATHS["steady_state.q_mvar"], derived_q.get("value"))

    translation_model_safety = _enforce_zip_model_safety(parameters_by_path, model_outputs)

    accepted_count = sum(1 for parameter in parameters if parameter.get("ledger_native_status_class") == "accepted")
    provisional_count = sum(1 for parameter in parameters if parameter.get("ledger_native_status_class") == "provisional")
    blocked_count = sum(1 for parameter in parameters if parameter.get("ledger_native_status_class") == "blocked")
    return {
        "contract_version": "ledger_native_translation_primary_v1",
        "used_ledger_native_primary": True,
        "fallback_allowed": False,
        "fallback_reason": "Planner field ledger rows are available; legacy translation is diagnostic only.",
        "model_outputs_source": "planner_field_ledger",
        "output_parameters_source": "planner_field_ledger",
        "planner_ledger_row_count": len(rows),
        "parameter_config_count": len(_parameter_configs()),
        "output_parameters": parameters,
        "model_outputs": model_outputs,
        "excluded_parameters": excluded,
        "accepted_parameter_count": accepted_count,
        "provisional_parameter_count": provisional_count,
        "blocked_parameter_count": blocked_count,
        "blocked_rows_excluded_from_model_outputs": len(excluded),
        "fallback_rows_used": 0,
        "translation_model_safety": translation_model_safety,
    }


def _parameter_value(parameter: dict[str, Any]) -> Any:
    value = parameter.get("value")
    numeric = _safe_float(value)
    return numeric if numeric is not None else value


def _parameter_status(parameter: dict[str, Any]) -> str:
    field_state = _clean(parameter.get("field_release_state")).upper()
    if field_state in _BLOCKED_STATES:
        return "BLOCKED"
    if bool(parameter.get("ledger_downstream_gated", False)):
        return "BLOCKED" if field_state == "BLOCKED" else "PROVISIONAL"
    if bool(parameter.get("planner_review_flag", False)) or _clean(parameter.get("confidence_tag")).upper() in _REVIEW_TAGS:
        return "PROVISIONAL"
    if _clean(parameter.get("provenance_type")) in {"field_resolution", "planner_field_ledger"} or bool(parameter.get("used_planner_field_ledger", False)):
        return "LEDGER_ACCEPTED"
    return "DERIVED"


def build_ledger_native_translation_contract(
    output_parameters: list[dict[str, Any]] | Any,
    model_outputs: dict[str, Any] | Any,
) -> dict[str, Any]:
    """Project final model outputs from governed output parameters.

    ``model_outputs`` should already come from ledger-native projection in the
    Patch 27 runtime path.  This contract still replays allowed values from the
    governed parameter records and excludes blocked values from scenario-driving
    outputs.
    """
    native_outputs = deepcopy(model_outputs) if isinstance(model_outputs, dict) else {}
    parameters = [item for item in output_parameters if isinstance(item, dict)] if isinstance(output_parameters, list) else []
    projected: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    provisional: list[dict[str, Any]] = []
    ledger_backed = 0

    for parameter in parameters:
        parameter_path = _clean(parameter.get("parameter_path"))
        output_path = PARAMETER_OUTPUT_PATHS.get(parameter_path)
        if not output_path:
            continue
        status = _parameter_status(parameter)
        value = _parameter_value(parameter)
        if status != "BLOCKED" and value is not None:
            _set_nested_value(native_outputs, output_path, value)
        if bool(parameter.get("used_planner_field_ledger", False)) or _clean(parameter.get("provenance_type")) in {"field_resolution", "planner_field_ledger"}:
            ledger_backed += 1
        row = {
            "parameter_path": parameter_path,
            "output_path": output_path,
            "value": value,
            "units": _clean(parameter.get("units")),
            "status": status,
            "provenance_type": _clean(parameter.get("provenance_type")),
            "field_resolution_field_key": _clean(parameter.get("field_resolution_field_key")),
            "ledger_field_path": _clean(parameter.get("planner_ledger_field_path")) or _clean(parameter.get("field_resolution_field_key")),
            "confidence_score": parameter.get("confidence_score"),
            "confidence_tag": _clean(parameter.get("confidence_tag")),
            "field_release_state": _clean(parameter.get("field_release_state")),
            "translation_use_policy": _clean(parameter.get("translation_use_policy")),
            "scenario_use_policy": _clean(parameter.get("scenario_use_policy")),
            "planner_review_flag": bool(parameter.get("planner_review_flag", False)),
            "ledger_downstream_gated": bool(parameter.get("ledger_downstream_gated", False)),
            "review_note": _clean(parameter.get("review_note")),
        }
        projected.append(row)
        if status == "BLOCKED":
            blocked.append(row)
        elif status == "PROVISIONAL":
            provisional.append(row)

    return {
        "contract_version": "ledger_native_translation_v2",
        "model_outputs_source": "planner_field_ledger" if any(bool(parameter.get("ledger_native_primary", False)) for parameter in parameters) else "governed_output_parameters",
        "ledger_native_model_outputs": native_outputs,
        "projected_parameter_count": len(projected),
        "ledger_backed_parameter_count": ledger_backed,
        "blocked_parameter_count": len(blocked),
        "provisional_parameter_count": len(provisional),
        "projected_parameters": projected,
        "blocked_parameters": blocked,
        "provisional_parameters": provisional,
        "scenario_use_policy": "review_required" if blocked or provisional else "accepted_for_scenario_generation",
    }
