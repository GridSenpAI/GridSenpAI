from __future__ import annotations

import re
from typing import Any

from shared.master_field_policy import canonical_source_role, master_field_policy, source_role_authority_score


def _text_blob(*parts: Any) -> str:
    values: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, dict):
            values.extend(f"{k} {v}" for k, v in part.items() if v is not None)
        elif isinstance(part, (list, tuple, set)):
            values.extend(str(v) for v in part if v is not None)
        else:
            values.append(str(part))
    return " ".join(values).lower()


def numeric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = re.search(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def candidate_context_blob(candidate_or_record: dict[str, Any] | None) -> str:
    item = candidate_or_record if isinstance(candidate_or_record, dict) else {}
    evidence = item.get("evidence")
    evidence_bits: list[Any] = []
    if isinstance(evidence, list):
        evidence_bits.extend(evidence)
    elif isinstance(evidence, dict):
        evidence_bits.append(evidence)
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return _text_blob(
        item.get("field_path"),
        item.get("field_id"),
        item.get("label"),
        item.get("method"),
        item.get("source_method"),
        item.get("source_type"),
        item.get("source_stage"),
        item.get("source_anchor"),
        item.get("source_ref"),
        item.get("source_name"),
        item.get("document_role"),
        item.get("document_type"),
        item.get("source_role"),
        item.get("source_hierarchy"),
        item.get("value"),
        item.get("unit"),
        metadata,
        evidence_bits,
    )




def _iter_nested_dicts(value: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 4:
        return []
    results: list[dict[str, Any]] = []
    if isinstance(value, dict):
        results.append(value)
        for child in value.values():
            results.extend(_iter_nested_dicts(child, depth=depth + 1))
    elif isinstance(value, list):
        for child in value[:20]:
            results.extend(_iter_nested_dicts(child, depth=depth + 1))
    return results


def _explicit_source_role_from_payload(payload: dict[str, Any]) -> str:
    for key in (
        "source_role",
        "document_role",
        "document_type",
        "artifact_role",
        "artifact_type",
        "source_type",
        "source_method",
        "source_hierarchy",
    ):
        value = payload.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            role = canonical_source_role(value)
            if role not in {"unknown", "project_package"}:
                return role
    return ""


def source_role_from_candidate(candidate_or_record: dict[str, Any] | None) -> str:
    item = candidate_or_record if isinstance(candidate_or_record, dict) else {}
    for payload in _iter_nested_dicts(item):
        explicit = _explicit_source_role_from_payload(payload)
        if explicit:
            return explicit
    blob = candidate_context_blob(candidate_or_record)
    if any(token in blob for token in ("revision table", "revision log", "rev description", "drawing revisions")):
        return "revision_table"
    if any(token in blob for token in ("title block", "sheet title", "drawn by", "checked by", "approved by", "sheet date", "plot date")):
        return "title_block"
    if any(token in blob for token in ("interview", "engineer_input", "applicant_confirmed", "validated_applicant_answer")):
        return "interview"
    if any(token in blob for token in ("large_load_request_form", "large load request", "application_request_form", "interconnection_application", "interconnection request", "load request", "electrical characteristics", "primary contacts", "project identification")):
        return "application_request_form"
    if any(token in blob for token in ("project_summary", "load_schedule", "campus load breakdown", "phased development", "critical it load", "demand mw")):
        return "project_summary_load_schedule"
    if any(token in blob for token in ("equipment_schedule", "major equipment schedule", "technical particulars", "campus quantity", "units total")):
        return "equipment_schedule"
    if any(token in blob for token in ("facilities_study", "facilities_study_memo", "facilities study", "facility study", "study memo", "interconnection memo", "customer interconnection facilities")):
        return "facilities_interconnection_memo"
    if any(token in blob for token in ("phasing_energization", "construction_phasing_plan", "energization plan", "energization schedule", "construction phasing", "milestone schedule", "commissioning deliverables", "target date")):
        return "phasing_energization_plan"
    if any(token in blob for token in ("metering_scada", "metering_scada_telemetry", "revenue meter", "telemetry", "scada", "rtu", "point list")):
        return "metering_scada"
    if any(token in blob for token in ("protection", "relay", "sel-", "50/51", "87t", "50bf")):
        return "protection_controls"
    if any(token in blob for token in ("one_line", "single line", "one-line", "device 52", " ct ", " pt ", " breaker", " bus ", " feeder")):
        return "one_line_diagram"
    if any(token in blob for token in ("site_control", "site control", "parcel exhibit", "easement")):
        return "site_control"
    if any(token in blob for token in ("site_plan", "site_civil_plan", "site plan", "civil plan", "parcel", "civil electrical")):
        return "site_plan"
    if any(token in blob for token in ("manufacturer", "datasheet", "catalog", "oem", "vendor", "spec sheet", "cut sheet")):
        return "oem_reference"
    if any(token in blob for token in ("drawing", "sheet", "title block")):
        return "drawing"
    return "project_package"


_FIELD_POLICY: dict[str, dict[str, Any]] = {
    "poi_voltage": {
        "paths": ("facility.poi_voltage_kv", "point_of_interconnection_voltage_kv", "nominal_poi_voltage_kv"),
        "accepted": ("point of interconnection", "poi", "nominal service voltage", "service voltage", "interconnection voltage", "utility terminal", "transmission service"),
        "rejected": ("campus medium voltage", "medium-voltage distribution", "distribution voltage", "main switchgear", "switchgear voltage", "ups voltage", "ups output", "generator terminal", "low voltage", "480 v", "13.8 kv distribution"),
        "expected_min": 34.5,
        "expected_max": 765.0,
    },
    "internal_voltage": {
        "paths": ("facility.electrical_configuration.internal_voltage_levels", "distribution_voltage_levels", "main_bus_nominal_voltage_kv"),
        "accepted": ("campus medium voltage", "medium-voltage distribution", "distribution voltage", "main switchgear", "generator terminal", "ups output", "480 v", "13.8 kv"),
        "rejected": (),
    },
    "equipment_count": {
        "paths": ("generator_unit_count", "facility.generators.count", "interconnection_transformer_unit_count", "facility.transformers.count", "ups_unit_count", "facility.ups.count"),
        "accepted": ("campus quantity", "units total", "total units", "quantity", "count", "six plants", "three main transformers"),
        "rejected": ("drawing label", "device number", "sheet", "revision", "typical", "typ"),
    },
    "phase_load": {
        "paths": ("facility.load_schedule.phase_1_mw", "peak_demand_mw", "facility.load_schedule.phase_2_mw", "facility.load_schedule.phase_3_mw"),
        "accepted": ("phase", "phased development", "load schedule", "campus load", "demand mw", "critical it load", "initial phase"),
        "rejected": ("generator rating", "transformer rating", "mva", "drawing date", "revision"),
    },
    "energization_date": {
        "paths": ("facility.energization.initial_energization_date", "facility.requested_in_service_date", "requested_in_service_date"),
        "accepted": ("requested in-service", "requested in service", "requested initial", "initial energization", "target energization", "commercial operation", "energization basis", "commissioning", "backfeed", "cod"),
        "rejected": ("drawing date", "title block", "revision date", "issued for", "sheet date", "plot date", "cad-style detailing", "normalized data"),
    },
    "motor_start": {
        "paths": ("largest_motor_start_mw", "facility.motor_schedule.largest_motor_start_mw", "motor_start_mw", "largest_motor_starting_load_mw"),
        "accepted": ("motor start", "motor starting", "largest motor", "inrush", "locked rotor", "starting kva", "starting mw"),
        "rejected": ("revision", "rev date", "title block", "issued for", "cad-style detailing", "drawn by", "checked by"),
    },
}


def field_policy_key(field_path_or_id: str) -> str:
    value = str(field_path_or_id or "").strip().lower()
    for key, policy in _FIELD_POLICY.items():
        if any(path.lower() in value or value in path.lower() for path in policy.get("paths", ())):
            return key
    if any(token in value for token in ("voltage", "kv", "_v")) and "poi" in value:
        return "poi_voltage"
    if any(token in value for token in ("unit_count", ".count", "count")):
        return "equipment_count"
    if any(token in value for token in ("motor_start", "motor start", "locked_rotor", "starting")):
        return "motor_start"
    if any(token in value for token in ("date", "energization", "service")):
        return "energization_date"
    if any(token in value for token in ("mw", "load", "demand", "phase")):
        return "phase_load"
    return ""


def _unit_mismatch_penalty(field_path_or_id: str, candidate_or_record: dict[str, Any] | None) -> tuple[float, str]:
    item = candidate_or_record if isinstance(candidate_or_record, dict) else {}
    policy = master_field_policy(field_path_or_id)
    expected = str(policy.get("expected_unit", "") or "").strip().lower()
    if not expected or expected == "count":
        return 0.0, ""
    observed = str(item.get("unit", "") or (item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}).get("unit", "") or "").strip().lower()
    value_text = str(item.get("value", "") or "").lower()
    if not observed:
        for unit in ("kv", "mw", "mva", "mvar", "kw", "v", "hz"):
            if re.search(rf"\b{unit}\b", value_text):
                observed = unit
                break
    if not observed:
        return 0.0, ""
    expected_aliases = {expected, expected.replace("mvar", "mvar"), expected.replace("minutes", "min")}
    compatible = observed in expected_aliases or expected in observed
    if expected == "kv" and observed == "v":
        return -6.0, "Candidate unit is volts while field expects kV; unit conversion is required before acceptance."
    if expected == "v" and observed == "kv":
        return -6.0, "Candidate unit is kV while field expects volts; unit conversion is required before acceptance."
    if compatible:
        return 4.0, f"Candidate unit matches expected field unit {policy.get('expected_unit')}."
    electrical_units = {"kv", "v", "mw", "mva", "mvar", "kw", "hz"}
    if observed in electrical_units and expected in electrical_units:
        return -18.0, f"Candidate unit {observed} does not match expected field unit {expected}."
    return 0.0, ""


def context_adjustment(field_path_or_id: str, candidate_or_record: dict[str, Any] | None) -> tuple[float, list[str], bool]:
    policy_key = field_policy_key(field_path_or_id)
    overlay = _FIELD_POLICY.get(policy_key, {})
    master = master_field_policy(field_path_or_id)
    blob = candidate_context_blob(candidate_or_record)
    role = source_role_from_candidate(candidate_or_record)
    adjustment = float(source_role_authority_score(field_path_or_id, role))
    notes: list[str] = []
    rejected = False

    if adjustment > 0:
        notes.append(f"Source role {role} has governed authority for {master.get('policy_family', 'general')} fields.")
    elif adjustment < 0:
        notes.append(f"Source role {role} is weak or rejected for {master.get('policy_family', 'general')} fields.")

    accepted_contexts = tuple(master.get("accepted_contexts", ())) + tuple(overlay.get("accepted", ()))
    rejected_contexts = tuple(master.get("rejected_contexts", ())) + tuple(overlay.get("rejected", ()))
    accepted_terms = [term for term in dict.fromkeys(accepted_contexts) if term and term in blob]
    rejected_terms = [term for term in dict.fromkeys(rejected_contexts) if term and term in blob]
    if accepted_terms:
        adjustment += min(22.0, 5.5 * len(accepted_terms))
        notes.append("Context contains accepted field-intent terms: " + ", ".join(accepted_terms[:3]) + ".")
    if rejected_terms:
        adjustment -= min(70.0, 18.0 * len(rejected_terms))
        rejected = True
        notes.append("Context contains rejected field-intent terms: " + ", ".join(rejected_terms[:3]) + ".")

    unit_adjustment, unit_note = _unit_mismatch_penalty(field_path_or_id, candidate_or_record)
    if unit_adjustment:
        adjustment += unit_adjustment
        notes.append(unit_note)

    raw_value = (candidate_or_record or {}).get("value") if isinstance(candidate_or_record, dict) else None
    numeric = numeric_value(raw_value)
    scalar_policy = policy_key in {"energization_date", "phase_load", "poi_voltage", "internal_voltage", "equipment_count", "motor_start"} or bool(master.get("expected_unit"))
    if scalar_policy and isinstance(raw_value, (dict, list, tuple, set)):
        adjustment -= 100.0
        rejected = True
        notes.append("Structured/list payload rejected for scalar planner field; likely extraction role contamination.")

    if policy_key == "poi_voltage" and numeric is not None:
        expected_min = float(overlay.get("expected_min", 0.0) or 0.0)
        expected_max = float(overlay.get("expected_max", 10_000.0) or 10_000.0)
        if expected_min <= numeric <= expected_max:
            adjustment += 12.0
            notes.append("POI voltage candidate is in transmission/service-voltage range.")
        else:
            adjustment -= 30.0
            rejected = True
            notes.append("POI voltage candidate is outside expected transmission/service-voltage range.")

    # Counts from drawings are confirmatory only unless no project-primary or schedule value exists.
    if master.get("expected_unit") == "count" and role in {"drawing", "one_line_diagram", "title_block", "revision_table"}:
        adjustment -= 18.0
        notes.append("Drawing-derived counts are treated as confirmatory and down-ranked against explicit schedule/form quantities.")

    # Title-block and revision contexts must not satisfy project milestone/date/load/equipment fields.
    admin_region = role in {"title_block", "revision_table"} or any(term in blob for term in ("title block", "revision", "issued for", "sheet date", "plot date", "rev description", "issued for interconnection review", "cad-style detailing", "normalized data"))
    if admin_region and (str(master.get("policy_family")) == "date" or policy_key in {"energization_date", "phase_load", "equipment_count"}):
        adjustment -= 80.0
        rejected = True
        notes.append("Title-block/revision-table context is rejected for planner milestone, load, and equipment fields.")

    if policy_key == "energization_date" and re.search(r"\d{1,2}/\d{4}", blob) and any(term in blob for term in ("issued for", "revision", "rev", "drawing", "title block", "sheet", "cad-style", "normalized data")):
        adjustment -= 90.0
        rejected = True
        notes.append("Month/year drawing or revision date is rejected for requested energization/in-service fields.")

    if policy_key == "phase_load" and numeric is not None and numeric <= 3.0:
        strong_load_context = any(term in blob for term in ("load schedule", "campus load", "demand mw", "critical it load", "phased development", "mw by phase", "gross campus mw", "maximum coincident demand"))
        weak_or_admin_context = admin_region or any(term in blob for term in ("row number", "row id", "drawing marker", "sheet", "revision", "rev", "phase label", "table artifact"))
        if not strong_load_context or weak_or_admin_context:
            adjustment -= 85.0
            rejected = True
            notes.append("Tiny phase MW candidate lacks strong load-schedule context and is treated as likely row/phase-label contamination.")

    if policy_key == "motor_start":
        strong_motor_context = any(term in blob for term in ("motor start", "motor starting", "largest motor", "inrush", "locked rotor", "starting kva", "starting mw"))
        if not strong_motor_context or admin_region:
            adjustment -= 95.0
            rejected = True
            notes.append("Motor-start candidate lacks motor-start context or came from admin/title-block content.")

    return adjustment, notes, rejected


def candidate_is_rejected_for_field(field_path_or_id: str, candidate_or_record: dict[str, Any] | None) -> bool:
    adjustment, _notes, rejected = context_adjustment(field_path_or_id, candidate_or_record)
    return rejected and adjustment <= -20.0


def normalization_authority_score(field_path_or_id: str, candidate: dict[str, Any]) -> tuple[int, int, int, int, int]:
    role = source_role_from_candidate(candidate)
    adjustment, _notes, rejected = context_adjustment(field_path_or_id, candidate)
    if rejected:
        adjustment -= 100.0
    method = str(candidate.get("method", "")).strip().lower()
    confidence = candidate.get("confidence", "")
    try:
        confidence_numeric = float(confidence)
    except (TypeError, ValueError):
        confidence_numeric = {"HIGH": 0.9, "MODERATE": 0.65, "LOW": 0.35}.get(str(confidence).strip().upper(), 0.35)
    method_rank = 5 if any(token in method for token in ("table", "row", "key_value", "project_primary", "schedule")) else 3 if "drawing" in method else 1
    role_rank = {
        "interview": 12,
        "application_request_form": 10,
        "project_summary_load_schedule": 9,
        "equipment_schedule": 8,
        "facilities_interconnection_memo": 8,
        "phasing_energization_plan": 8,
        "metering_scada": 7,
        "protection_controls": 7,
        "site_control": 7,
        "site_plan": 6,
        "one_line_diagram": 5,
        "drawing": 3,
        "oem_reference": 2,
        "project_package": 1,
    }.get(role, 1)
    value_len_penalty = -len(str(candidate.get("value", "")))
    return (int(adjustment), role_rank, method_rank, int(confidence_numeric * 100), value_len_penalty)
