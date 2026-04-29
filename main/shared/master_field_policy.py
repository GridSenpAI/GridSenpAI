from __future__ import annotations

"""Master planner-field policy helpers.

This module turns the planner-required-fields registry into runtime policy that can be
shared by normalization, field resolution, adjudication, interview, and export.
It is intentionally deterministic: the LLM may advise, but these field contracts
remain the governing source for source authority and field-intent checks.
"""

from functools import lru_cache
import re
from typing import Any

from shared.planner_registry import (
    resolve_registry_field,
    field_path_for_registry_field_id,
    planner_registry_fields,
)


_RUNTIME_SOURCE_ROLE_BY_REGISTRY_SOURCE: dict[str, str] = {
    "validated_applicant_answer": "interview",
    "applicant_answer": "interview",
    "applicant_interview": "interview",
    "interview_answer": "interview",
    "human_applicant": "interview",
    "engineer_input": "interview",
    "utility_or_iso_required_form": "application_request_form",
    "interconnection_application": "application_request_form",
    "large_load_request_form": "application_request_form",
    "load_request_form": "application_request_form",
    "request_form": "application_request_form",
    "application_form": "application_request_form",
    "electrical_characteristics_form": "application_request_form",
    "applicant_cover_letter": "transmittal_cover_letter",
    "cover_letter": "transmittal_cover_letter",
    "transmittal": "transmittal_cover_letter",
    "project_contacts_package": "application_request_form",
    "project_summary": "project_summary_load_schedule",
    "summary_load_schedule": "project_summary_load_schedule",
    "load_schedule": "project_summary_load_schedule",
    "project_summary_and_load_schedule": "project_summary_load_schedule",
    "equipment_schedule": "equipment_schedule",
    "major_equipment_schedule": "equipment_schedule",
    "technical_particulars": "equipment_schedule",
    "equipment_technical_particulars": "equipment_schedule",
    "one_line": "one_line_diagram",
    "one-line": "one_line_diagram",
    "one line": "one_line_diagram",
    "one_line_diagram": "one_line_diagram",
    "single_line": "one_line_diagram",
    "single-line": "one_line_diagram",
    "single line": "one_line_diagram",
    "single_line_diagram": "one_line_diagram",
    "sld": "one_line_diagram",
    "site_plan": "site_plan",
    "civil_site_plan": "site_plan",
    "civil_electrical_site_plan": "site_plan",
    "site_control_package": "site_control",
    "site_control": "site_control",
    "parcel_exhibit": "site_control",
    "facilities_study": "facilities_interconnection_memo",
    "interconnection_facilities_study": "facilities_interconnection_memo",
    "interconnection_memo": "facilities_interconnection_memo",
    "facilities_memo": "facilities_interconnection_memo",
    "facilities_study_memo": "facilities_interconnection_memo",
    "phasing_plan": "phasing_energization_plan",
    "energization_plan": "phasing_energization_plan",
    "construction_schedule": "phasing_energization_plan",
    "construction_phasing": "phasing_energization_plan",
    "construction_phasing_plan": "phasing_energization_plan",
    "protection_settings": "protection_controls",
    "protection_controls": "protection_controls",
    "protection_controls_and_communications": "protection_controls",
    "relay_settings": "protection_controls",
    "relay_application": "protection_controls",
    "metering_package": "metering_scada",
    "metering_scada": "metering_scada",
    "metering_scada_and_telemetry": "metering_scada",
    "metering_scada_telemetry": "metering_scada",
    "scada_package": "metering_scada",
    "telemetry_package": "metering_scada",
    "manufacturer_cut_sheet": "oem_reference",
    "manufacturer_datasheet": "oem_reference",
    "vendor_datasheet": "oem_reference",
    "equipment_datasheet": "oem_reference",
    "oem_datasheet": "oem_reference",
    "oem_reference": "oem_reference",
    "datasheet": "oem_reference",
    "cut_sheet": "oem_reference",

    "generator_schedule": "equipment_schedule",
    "transformer_schedule": "equipment_schedule",
    "ups_schedule": "equipment_schedule",
    "battery_schedule": "equipment_schedule",
    "switchgear_schedule": "equipment_schedule",
    "motor_schedule": "equipment_schedule",
    "mechanical_schedule": "equipment_schedule",
    "load_information_form": "project_summary_load_schedule",
    "load_form": "project_summary_load_schedule",
    "commissioning_plan": "phasing_energization_plan",
    "project_schedule": "phasing_energization_plan",
    "load_commissioning_plan": "phasing_energization_plan",
    "site_electrical_narrative": "project_summary_load_schedule",
    "operating_narrative": "project_summary_load_schedule",
    "telemetry_requirements": "metering_scada",
    "scada_points_list": "metering_scada",
    "relay_settings_file": "protection_controls",
    "protection_narrative": "protection_controls",
    "controls_narrative": "protection_controls",
    "drawing_sheet": "drawing",
    "drawing": "drawing",
}

_DEFAULT_ROLE_SCORE: dict[str, int] = {
    "interview": 45,
    "application_request_form": 34,
    "project_summary_load_schedule": 28,
    "facilities_interconnection_memo": 27,
    "equipment_schedule": 24,
    "phasing_energization_plan": 23,
    "one_line_diagram": 18,
    "metering_scada": 18,
    "protection_controls": 18,
    "site_plan": 14,
    "site_control": 14,
    "transmittal_cover_letter": 12,
    "drawing": 6,
    "oem_reference": 5,
    "project_package": 2,
    "unknown": 0,
}



def canonical_source_role(source_role: Any) -> str:
    """Return the runtime source-role key used by field authority policies."""
    raw = _clean_token(source_role).replace("-", "_").replace("/", "_")
    raw = re.sub(r"[^a-z0-9_ ]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    compact = raw.replace(" ", "_")
    for key in (compact, raw):
        if key in _RUNTIME_SOURCE_ROLE_BY_REGISTRY_SOURCE:
            return _RUNTIME_SOURCE_ROLE_BY_REGISTRY_SOURCE[key]
    if compact in _DEFAULT_ROLE_SCORE:
        return compact
    if raw in _DEFAULT_ROLE_SCORE:
        return raw
    return compact or "unknown"


_FAMILY_ROLE_OVERRIDES: dict[str, dict[str, int]] = {
    "interconnection": {
        "application_request_form": 38,
        "facilities_interconnection_memo": 36,
        "one_line_diagram": 28,
        "project_summary_load_schedule": 22,
        "equipment_schedule": 8,
        "oem_reference": -10,
    },
    "load": {
        "project_summary_load_schedule": 38,
        "application_request_form": 34,
        "phasing_energization_plan": 20,
        "one_line_diagram": 4,
        "oem_reference": -15,
    },
    "generator": {
        "equipment_schedule": 36,
        "project_summary_load_schedule": 28,
        "application_request_form": 20,
        "one_line_diagram": 10,
        "oem_reference": 18,
    },
    "transformer": {
        "equipment_schedule": 38,
        "facilities_interconnection_memo": 28,
        "one_line_diagram": 22,
        "application_request_form": 18,
        "oem_reference": 14,
    },
    "ups": {
        "equipment_schedule": 36,
        "project_summary_load_schedule": 24,
        "one_line_diagram": 12,
        "oem_reference": 20,
    },
    "date": {
        "phasing_energization_plan": 38,
        "application_request_form": 34,
        "project_summary_load_schedule": 20,
        "one_line_diagram": -18,
        "drawing": -24,
        "oem_reference": -24,
    },
    "metering": {
        "metering_scada": 38,
        "one_line_diagram": 24,
        "facilities_interconnection_memo": 22,
        "application_request_form": 16,
    },
    "relay": {
        "protection_controls": 38,
        "one_line_diagram": 22,
        "facilities_interconnection_memo": 18,
        "application_request_form": 10,
    },
    "site": {
        "site_control": 36,
        "site_plan": 34,
        "application_request_form": 20,
        "one_line_diagram": 6,
    },
}

_ACCEPTED_CONTEXTS_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "interconnection": (
        "point of interconnection", "poi", "interconnection", "nominal service voltage",
        "service voltage", "utility terminal", "customer interconnection facilities",
    ),
    "load": (
        "load schedule", "campus load", "demand mw", "critical it load", "phased development",
        "phase", "ultimate", "initial phase", "forecast load",
    ),
    "generator": (
        "standby generation", "generator", "genset", "unit count", "campus quantity",
        "rated kw", "terminal voltage", "prime", "standby",
    ),
    "transformer": (
        "main transformer", "interconnection transformer", "mva", "hv", "lv", "unit count",
        "campus quantity", "technical particulars",
    ),
    "ups": (
        "ups", "battery", "runtime", "topology", "output voltage", "capacity kw",
        "technical particulars", "campus quantity",
    ),
    "date": (
        "requested in-service", "requested initial", "initial energization", "target energization",
        "commercial operation", "commissioning", "milestone", "phase date",
    ),
    "metering": (
        "revenue meter", "metering", "scada", "telemetry", "rtu", "point list", "control center",
    ),
    "relay": (
        "protection", "relay", "sel", "50/51", "87t", "50bf", "breaker failure", "communications",
    ),
    "site": (
        "parcel", "site control", "site plan", "property", "easement", "substation location",
    ),
}

_REJECTED_CONTEXTS_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "interconnection": (
        "ups voltage", "ups output", "generator terminal", "low voltage", "480 v",
        "campus medium voltage", "medium-voltage distribution", "switchgear voltage",
    ),
    "load": (
        "generator rating", "transformer rating", "mva", "revision", "drawing date", "title block",
    ),
    "generator": (
        "device number", "drawing label", "single line symbol", "typical", "sheet", "revision",
    ),
    "transformer": (
        "device number", "drawing label", "typical", "sheet", "revision",
    ),
    "ups": (
        "device number", "drawing label", "typical", "sheet", "revision",
    ),
    "date": (
        "drawing date", "title block", "revision date", "issued for", "sheet date", "plot date",
    ),
}


def _clean_token(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _field_blob(field: dict[str, Any] | None, field_path_or_id: str | None) -> str:
    if not isinstance(field, dict):
        return _clean_token(field_path_or_id)
    parts: list[str] = [
        field.get("field_id", ""),
        field.get("label", ""),
        field.get("group", ""),
        field.get("packet_section", ""),
        field.get("notes", ""),
        field_path_or_id or "",
    ]
    for key in ("search_keywords", "repo_aliases_or_related_fields", "preferred_sources", "used_in_studies"):
        value = field.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return _clean_token(" ".join(str(part) for part in parts if part is not None))


def infer_policy_family(field_path_or_id: str | None, field: dict[str, Any] | None = None) -> str:
    blob = _field_blob(field, field_path_or_id)
    field_id = _clean_token((field or {}).get("field_id") if isinstance(field, dict) else field_path_or_id)
    label = _clean_token((field or {}).get("label") if isinstance(field, dict) else "")

    date_markers = (
        "energization", "commercial operation", "commissioning date", "milestone date",
        "requested in-service", "in-service date", "as-of date", "as of date",
        "target date", "phase date", "revision date",
    )
    if (field_id.endswith("_date") or field_id.endswith("_year") or any(token in label for token in (" date", "year"))
            or any(token in blob for token in date_markers)):
        return "date"

    # Specific equipment/system families must win before broad words such as
    # interconnection, validation, or phase appear in registry descriptions.
    if any(token in blob for token in ("transformer", "xfmr")):
        return "transformer"
    if any(token in blob for token in ("generator", "genset", "standby generation")):
        return "generator"
    if any(token in blob for token in ("ups", "battery", "runtime")):
        return "ups"
    if any(token in blob for token in ("meter", "metering", "scada", "telemetry", "rtu", "revenue")):
        return "metering"
    if any(token in blob for token in ("relay", "protection", "trip", "breaker failure", "50/51", "87t", "50bf")):
        return "relay"
    if any(token in blob for token in ("parcel", "site control", "site plan", "easement", "property")):
        return "site"
    if any(token in blob for token in ("poi", "point_of_interconnection", "point of interconnection", "interconnection", "service voltage", "substation")):
        return "interconnection"
    if any(token in blob for token in ("load", "demand", "mw", "mvar", "ramp", "motor", "phase")):
        return "load"
    return "general"


def expected_unit_for_field(field_path_or_id: str | None, field: dict[str, Any] | None = None) -> str:
    blob = _field_blob(field, field_path_or_id)
    field_id = _clean_token((field or {}).get("field_id") if isinstance(field, dict) else field_path_or_id)
    if field_id.endswith("_kv") or ".kv" in field_id or "voltage kv" in blob:
        return "kV"
    if field_id.endswith("_v") or "output voltage" in blob or "input voltage" in blob:
        return "V"
    if field_id.endswith("_mw") or "demand mw" in blob or "load mw" in blob:
        return "MW"
    if field_id.endswith("_mva") or "mva" in blob:
        return "MVA"
    if field_id.endswith("_mvar") or "mvar" in blob:
        return "MVAR"
    if field_id.endswith("_kw") or "rated kw" in blob or "capacity kw" in blob:
        return "kW"
    if field_id.endswith("_hz") or "frequency" in blob:
        return "Hz"
    if field_id.endswith("_minutes") or "runtime" in blob:
        return "minutes"
    if "power factor" in blob or field_id.endswith("_pf"):
        return "pu"
    if field_id.endswith("_count") or "unit count" in blob or "count" in field_id:
        return "count"
    return ""




def _registry_values(field: dict[str, Any] | None, key: str) -> list[str]:
    if not isinstance(field, dict):
        return []
    raw = field.get(key, [])
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _tokenized_field_id_aliases(field_id: str) -> list[str]:
    cleaned = str(field_id or "").strip()
    if not cleaned:
        return []
    aliases = [cleaned, cleaned.replace("_", " ")]
    # Strip common equipment suffixes so labels like generator_unit_count can match
    # phrases such as "generator units" or "generator count" in tables.
    for suffix in ("_unit_count", "_installed_spares_count", "_equipment_name", "_tag_or_designator"):
        if cleaned.endswith(suffix):
            aliases.append(cleaned[: -len(suffix)].replace("_", " "))
    return aliases


def _aliases_for_field(field: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(field, dict):
        return ()
    values: list[str] = []
    field_id = str(field.get("field_id", "")).strip()
    label = str(field.get("label", "")).strip()
    values.extend(_tokenized_field_id_aliases(field_id))
    if label:
        values.extend([label, label.lower()])
    for key in ("search_keywords", "repo_aliases_or_related_fields"):
        values.extend(_registry_values(field, key))
    # Preferred source names often mirror field/table labels and help extraction
    # worklists without turning source names into accepted evidence contexts.
    for source in _registry_values(field, "preferred_sources")[:6]:
        values.append(source.replace("_", " "))
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _clean_token(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(value)
    return tuple(result[:24])


def _specific_policy_contexts(field: dict[str, Any] | None, family: str) -> tuple[list[str], list[str]]:
    field_id = _clean_token((field or {}).get("field_id") if isinstance(field, dict) else "")
    label = _clean_token((field or {}).get("label") if isinstance(field, dict) else "")
    data_type = _clean_token((field or {}).get("data_type") if isinstance(field, dict) else "")
    accepted: list[str] = []
    rejected: list[str] = []

    if field_id == "point_of_interconnection_voltage_kv":
        accepted.extend([
            "nominal service voltage", "poi voltage", "point of interconnection voltage",
            "interconnection voltage", "customer service voltage", "utility service voltage",
        ])
        rejected.extend([
            "campus medium voltage", "distribution voltage", "switchgear voltage",
            "ups input", "ups output", "generator terminal", "480 v", "low voltage",
        ])
    elif field_id in {"incoming_service_voltage_levels", "main_bus_nominal_voltage_kv"}:
        accepted.extend(["incoming service", "main bus", "service bus", "switchgear", "one-line"])
        rejected.extend(["ups output", "generator terminal", "low voltage receptacle"])
    elif field_id == "distribution_voltage_levels":
        accepted.extend(["campus medium-voltage distribution", "distribution voltage", "switchgear voltage", "feeder voltage"])
        rejected.extend(["point of interconnection", "poi", "utility service voltage"])
    elif field_id == "generator_terminal_voltage_kv":
        accepted.extend(["generator terminal", "genset terminal", "generator output", "standby generation"])
        rejected.extend(["point of interconnection", "poi", "ups output", "utility service voltage"])
    elif field_id in {"ups_input_voltage_kv_or_v", "ups_output_voltage_kv_or_v"}:
        accepted.extend(["ups input", "ups output", "ups voltage", "critical power", "load-side voltage"])
        rejected.extend(["point of interconnection", "poi", "utility service voltage", "generator terminal"])

    if field_id.endswith("_unit_count") or field_id.endswith("_installed_spares_count") or "unit count" in label:
        accepted.extend([
            "campus quantity", "units total", "unit count", "installed quantity",
            "equipment schedule", "technical particulars", "count",
        ])
        rejected.extend([
            "drawing label", "typical symbol", "device number", "repeated symbol",
            "sheet reference", "title block", "revision",
        ])
    if data_type == "date" or field_id.endswith("_date"):
        if field_id == "one_line_revision_date":
            accepted.extend(["one-line revision date", "drawing revision date", "sheet revision date"])
            rejected.extend(["requested in-service", "initial energization", "commercial operation", "target full buildout"])
        else:
            accepted.extend([
                "requested in-service", "target in-service", "earliest energization",
                "initial energization", "commercial operation", "commissioning milestone",
                "target full buildout",
            ])
            rejected.extend([
                "drawing date", "title block", "revision date", "issued for", "sheet date", "plot date",
            ])
    if field_id.endswith("_mw") or "mw" in label:
        accepted.extend(["load schedule", "phase demand", "peak demand", "normal operating demand", "critical it load"])
        rejected.extend(["generator rating", "transformer rating", "mva rating", "title block", "revision"])
    if "contact" in data_type or "contact" in field_id:
        accepted.extend(["primary contact", "engineering contact", "operations contact", "applicant", "owner", "email", "phone"])
    if not rejected:
        rejected.extend(["page footer", "copyright notice", "confidentiality notice", "unrelated adjacent row"])
    return accepted, rejected


def _preferred_roles(field: dict[str, Any] | None, family: str) -> dict[str, int]:
    role_scores: dict[str, int] = dict(_FAMILY_ROLE_OVERRIDES.get(family, {}))
    if isinstance(field, dict):
        field_id = _clean_token(field.get("field_id"))
        data_type = _clean_token(field.get("data_type"))
        for idx, source in enumerate(_registry_values(field, "preferred_sources")):
            role = canonical_source_role(source)
            if not role or role == "unknown":
                continue
            # Earlier preferred sources receive stronger credit. Interview remains highest.
            score = max(12, 38 - idx * 4)
            if role == "interview":
                score = 48
            role_scores[role] = max(role_scores.get(role, -999), score)
        if field_id.endswith("_unit_count") or field_id.endswith("_installed_spares_count"):
            role_scores["equipment_schedule"] = max(role_scores.get("equipment_schedule", 0), 40)
            role_scores["drawing"] = min(role_scores.get("drawing", 6), 4)
            role_scores["one_line_diagram"] = min(role_scores.get("one_line_diagram", 18), 14)
            role_scores["oem_reference"] = min(role_scores.get("oem_reference", 5), 2)
        if field_id in {"point_of_interconnection_voltage_kv", "requested_in_service_date", "earliest_energization_date", "target_full_buildout_date"}:
            role_scores["application_request_form"] = max(role_scores.get("application_request_form", 0), 40)
        if data_type == "date" and field_id != "one_line_revision_date":
            role_scores["drawing"] = min(role_scores.get("drawing", 0), -24)
            role_scores["one_line_diagram"] = min(role_scores.get("one_line_diagram", 0), -18)
            role_scores["oem_reference"] = min(role_scores.get("oem_reference", 0), -20)
        if any(token in field_id for token in ("manufacturer", "model", "catalog", "firmware", "datasheet")):
            role_scores["oem_reference"] = max(role_scores.get("oem_reference", 0), 34)
            role_scores["equipment_schedule"] = max(role_scores.get("equipment_schedule", 0), 32)
    if "interview" not in role_scores:
        role_scores["interview"] = 48
    return role_scores


def _expected_unit_from_registry(field: dict[str, Any] | None, field_path_or_id: str | None) -> str:
    unit = expected_unit_for_field(field_path_or_id, field)
    if unit:
        return unit
    data_type = _clean_token((field or {}).get("data_type") if isinstance(field, dict) else "")
    field_id = _clean_token((field or {}).get("field_id") if isinstance(field, dict) else field_path_or_id)
    label = _clean_token((field or {}).get("label") if isinstance(field, dict) else "")
    if data_type in {"number_list", "number"}:
        blob = f"{field_id} {label}"
        if "voltage" in blob:
            return "kV" if "kv" in blob else "V"
        if "count" in blob:
            return "count"
    return ""


def _conflict_behavior(field: dict[str, Any] | None, family: str) -> dict[str, Any]:
    field_id = _clean_token((field or {}).get("field_id") if isinstance(field, dict) else "")
    data_type = _clean_token((field or {}).get("data_type") if isinstance(field, dict) else "")
    behavior = {
        "candidate_strategy": "collect_score_then_select",
        "requires_compact_adjudication_on_conflict": True,
        "interview_authority": "interview_wins_unless_high_confidence_document_conflict",
        "idk_behavior": "fallback_to_best_document_candidate",
    }
    if data_type in {"number_list", "object_list", "contact_list"}:
        behavior["candidate_strategy"] = "merge_compatible_values_preserve_sources"
    if field_id.endswith("_unit_count") or field_id.endswith("_installed_spares_count"):
        behavior.update({
            "candidate_strategy": "prefer_explicit_quantity_source_not_drawing_frequency",
            "drawing_counts_are_confirmatory": True,
        })
    if data_type == "date" and field_id != "one_line_revision_date":
        behavior.update({
            "candidate_strategy": "reject_title_block_dates_for_project_milestones",
            "drawing_dates_are_rejected": True,
        })
    if family in {"metering", "relay"}:
        behavior["candidate_strategy"] = "prefer_specialized_package_or_one_line_topology"
    return behavior


def _interview_priority(field: dict[str, Any] | None) -> str:
    if not isinstance(field, dict):
        return "fallback"
    if bool(field.get("planner_critical")) and str(field.get("requiredness", "")).lower() == "required":
        return "high"
    if str(field.get("requiredness", "")).lower() == "required":
        return "medium"
    if "applicant_interview" in " ".join(_registry_values(field, "pipeline_touchpoints")).lower():
        return "medium"
    return "low"


def _export_criticality(field: dict[str, Any] | None) -> str:
    if not isinstance(field, dict):
        return "fallback"
    if bool(field.get("planner_critical")):
        return "planner_critical"
    if str(field.get("requiredness", "")).lower() == "required":
        return "required_noncritical"
    return "supporting"


def _policy_coverage(policy: dict[str, Any], field: dict[str, Any] | None) -> dict[str, Any]:
    registry_present = isinstance(field, dict)
    explicit_preferred_sources = bool(_registry_values(field, "preferred_sources"))
    explicit_aliases = bool(_registry_values(field, "search_keywords") or _registry_values(field, "repo_aliases_or_related_fields"))
    explicit_type = bool(_clean_token((field or {}).get("data_type") if registry_present else ""))
    explicit_unit = bool(_clean_token(policy.get("expected_unit")))
    explicit_contexts = bool(policy.get("accepted_contexts")) and bool(policy.get("rejected_contexts"))
    explicit_conflict = isinstance(policy.get("conflict_behavior"), dict) and bool(policy.get("conflict_behavior"))
    components = {
        "registry_present": registry_present,
        "explicit_data_type": explicit_type,
        "explicit_expected_unit": explicit_unit,
        "explicit_aliases": explicit_aliases,
        "explicit_preferred_sources": explicit_preferred_sources,
        "explicit_context_policy": explicit_contexts,
        "explicit_conflict_behavior": explicit_conflict,
    }
    score = sum(1 for value in components.values() if value)
    return {
        **components,
        "coverage_score": score,
        "coverage_level": "explicit" if registry_present and score >= 5 else "enriched_fallback" if registry_present else "fallback_only",
    }

@lru_cache(maxsize=2048)
def master_field_policy(field_path_or_id: str | None) -> dict[str, Any]:
    """Return the registry-first policy contract for one master planner field.

    The master registry is the governing source.  Heuristic family rules only
    enrich missing context/unit/source behavior so every field receives a usable
    policy object without losing registry intent.
    """
    field = resolve_registry_field(field_path_or_id)
    field_id = str((field or {}).get("field_id") or field_path_or_id or "").strip()
    legacy_path = field_path_for_registry_field_id(field_id) or (field_path_or_id or field_id)
    family = infer_policy_family(field_path_or_id, field)
    label = str((field or {}).get("label") or field_id).strip()
    definition = str((field or {}).get("notes") or label or field_id).strip()
    data_type = str((field or {}).get("data_type") or "").strip().lower()

    accepted = list(_ACCEPTED_CONTEXTS_BY_FAMILY.get(family, ()))
    rejected = list(_REJECTED_CONTEXTS_BY_FAMILY.get(family, ()))
    field_accepted, field_rejected = _specific_policy_contexts(field, family)
    accepted.extend(field_accepted)
    rejected.extend(field_rejected)
    aliases = list(_aliases_for_field(field))
    if label:
        accepted.append(label.lower())
    for keyword in _registry_values(field, "search_keywords")[:12]:
        accepted.append(keyword.lower())

    expected_unit = _expected_unit_from_registry(field, field_path_or_id)
    policy: dict[str, Any] = {
        "field_id": field_id,
        "field_path": legacy_path,
        "label": label,
        "definition": definition,
        "data_type": data_type,
        "expected_unit": expected_unit,
        "policy_family": family,
        "accepted_contexts": tuple(dict.fromkeys(_clean_token(v) for v in accepted if _clean_token(v))),
        "rejected_contexts": tuple(dict.fromkeys(_clean_token(v) for v in rejected if _clean_token(v))),
        "aliases": tuple(aliases),
        "preferred_source_roles": _preferred_roles(field, family),
        "preferred_sources": tuple(_registry_values(field, "preferred_sources")),
        "preferred_corpora": tuple(),
        "pipeline_touchpoints": tuple(_registry_values(field, "pipeline_touchpoints")),
        "used_in_studies": tuple(_registry_values(field, "used_in_studies")),
        "planner_critical": bool((field or {}).get("planner_critical", False)),
        "requiredness": str((field or {}).get("requiredness") or "").strip().lower(),
        "minimum_confidence_for_auto_accept": str((field or {}).get("minimum_confidence_for_auto_accept") or "").strip().lower(),
        "allow_low_confidence_accept": bool((field or {}).get("allow_low_confidence_accept", False)),
        "identity_role": (field or {}).get("identity_role") if isinstance(field, dict) else None,
        "conflict_behavior": _conflict_behavior(field, family),
        "interview_priority": _interview_priority(field),
        "export_criticality": _export_criticality(field),
        "policy_source": "registry_first_with_field_enrichment" if isinstance(field, dict) else "fallback_heuristic_only",
    }
    policy["policy_coverage"] = _policy_coverage(policy, field)
    return policy

def source_role_authority_score(field_path_or_id: str | None, source_role: str | None) -> int:
    policy = master_field_policy(field_path_or_id)
    role = canonical_source_role(source_role)
    roles = policy.get("preferred_source_roles") if isinstance(policy.get("preferred_source_roles"), dict) else {}
    if role in roles:
        return int(roles[role])
    return int(_DEFAULT_ROLE_SCORE.get(role, 0))


def field_policy_export(field_path_or_id: str | None) -> dict[str, Any]:
    policy = master_field_policy(field_path_or_id)
    return {
        "field_id": policy.get("field_id", ""),
        "field_path": policy.get("field_path", ""),
        "field_label": policy.get("label", ""),
        "definition": policy.get("definition", ""),
        "data_type": policy.get("data_type", ""),
        "expected_unit": policy.get("expected_unit", ""),
        "policy_family": policy.get("policy_family", "general"),
        "accepted_contexts": list(policy.get("accepted_contexts", ()))[:16],
        "rejected_contexts": list(policy.get("rejected_contexts", ()))[:16],
        "aliases": list(policy.get("aliases", ()))[:24],
        "preferred_sources": list(policy.get("preferred_sources", ()))[:12],
        "preferred_source_roles": dict(policy.get("preferred_source_roles", {})),
        "pipeline_touchpoints": list(policy.get("pipeline_touchpoints", ()))[:12],
        "used_in_studies": list(policy.get("used_in_studies", ()))[:12],
        "conflict_behavior": dict(policy.get("conflict_behavior", {})) if isinstance(policy.get("conflict_behavior"), dict) else {},
        "interview_priority": policy.get("interview_priority", ""),
        "export_criticality": policy.get("export_criticality", ""),
        "planner_critical": bool(policy.get("planner_critical", False)),
        "requiredness": policy.get("requiredness", ""),
        "minimum_confidence_for_auto_accept": policy.get("minimum_confidence_for_auto_accept", ""),
        "allow_low_confidence_accept": bool(policy.get("allow_low_confidence_accept", False)),
        "identity_role": policy.get("identity_role"),
        "policy_source": policy.get("policy_source", ""),
        "policy_coverage": dict(policy.get("policy_coverage", {})) if isinstance(policy.get("policy_coverage"), dict) else {},
    }


@lru_cache(maxsize=1)
def master_policy_coverage_audit() -> dict[str, Any]:
    """Return a registry-wide coverage audit for the field-policy bridge."""
    fields = planner_registry_fields()
    level_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    missing_expected_unit: list[str] = []
    missing_rejected_contexts: list[str] = []
    fallback_policy_fields: list[str] = []
    policies: list[dict[str, Any]] = []
    for field in fields:
        field_id = str(field.get("field_id", "")).strip()
        policy = master_field_policy(field_id)
        coverage = policy.get("policy_coverage") if isinstance(policy.get("policy_coverage"), dict) else {}
        level = str(coverage.get("coverage_level") or "unknown")
        family = str(policy.get("policy_family") or "general")
        level_counts[level] = level_counts.get(level, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1
        if not str(policy.get("expected_unit") or "").strip() and str(policy.get("data_type") or "") in {"number", "number_list"}:
            # Some numeric fields are unitless by design, so this is an audit flag rather than failure.
            missing_expected_unit.append(field_id)
        if not policy.get("rejected_contexts"):
            missing_rejected_contexts.append(field_id)
        if level != "explicit":
            fallback_policy_fields.append(field_id)
        policies.append({
            "field_id": field_id,
            "field_path": policy.get("field_path", ""),
            "policy_family": family,
            "data_type": policy.get("data_type", ""),
            "expected_unit": policy.get("expected_unit", ""),
            "coverage_level": level,
            "preferred_source_role_count": len(policy.get("preferred_source_roles", {}) if isinstance(policy.get("preferred_source_roles"), dict) else {}),
            "alias_count": len(policy.get("aliases", ()) if isinstance(policy.get("aliases"), tuple) else []),
            "accepted_context_count": len(policy.get("accepted_contexts", ()) if isinstance(policy.get("accepted_contexts"), tuple) else []),
            "rejected_context_count": len(policy.get("rejected_contexts", ()) if isinstance(policy.get("rejected_contexts"), tuple) else []),
        })
    return {
        "contract_version": "master_policy_coverage_audit_v1",
        "registry_field_count": len(fields),
        "policy_count": len(policies),
        "level_counts": dict(sorted(level_counts.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "explicit_policy_count": level_counts.get("explicit", 0),
        "fallback_policy_count": len(fallback_policy_fields),
        "numeric_fields_without_expected_unit_count": len(missing_expected_unit),
        "numeric_fields_without_expected_unit_sample": missing_expected_unit[:25],
        "fields_without_rejected_context_count": len(missing_rejected_contexts),
        "fields_without_rejected_context_sample": missing_rejected_contexts[:25],
        "fallback_policy_field_sample": fallback_policy_fields[:25],
        "policies": policies,
    }


def registry_policy_manifest(limit: int | None = None) -> list[dict[str, Any]]:
    """Return exported policy contracts for registry fields for QA/reporting."""
    policies = [field_policy_export(str(field.get("field_id", "")).strip()) for field in planner_registry_fields()]
    if limit is None:
        return policies
    return policies[: max(0, int(limit))]
