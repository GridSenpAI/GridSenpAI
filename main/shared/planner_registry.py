from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parent / "schemas" / "planner_required_fields.json"

_DEFAULT_LEGACY_FIELD_PATH_MAP: dict[str, str] = {
    "facility.project_name": "project_name",
    "facility.poi_voltage_kv": "point_of_interconnection_voltage_kv",
    "facility.energization.initial_energization_date": "requested_in_service_date",
    # Preserve the public legacy contract: phase_1_mw is the intake alias for
    # peak demand in the current registry/question catalog. Row-bound phase
    # extraction still emits phase-specific candidates; downstream translation
    # prefers explicit peak/ultimate aliases before using this compatibility path.
    "facility.load_schedule.phase_1_mw": "peak_demand_mw",
    "facility.load_schedule.phase_2_mw": "buildout_phases_summary",
    "facility.load_schedule.phase_3_mw": "buildout_phases_summary",
    "facility.load_schedule.ultimate_mw": "peak_demand_mw",
    "facility.load_schedule.maximum_coincident_demand_mw": "peak_demand_mw",
    "facility.dynamic_behavior.max_ramp_up_mw_per_min": "load_ramp_profile_summary",
    "facility.dynamic_behavior.max_ramp_down_mw_per_min": "maximum_daily_weekly_monthly_ramp_summary",
    "facility.ups.topology": "ups_topology",
    "facility.ups.count": "ups_unit_count",
    "facility.generators.count": "generator_unit_count",
    "facility.generators.operation_mode": "generator_paralleling_capability",
    "facility.electrical_configuration.internal_voltage_levels": "distribution_voltage_levels",
    "facility.transformers.count": "interconnection_transformer_unit_count",
    "facility.frequency_hz": "generator_frequency_hz",
    "facility.transformers.ratings_mva": "interconnection_transformer_mva_per_unit",
    "facility.generators.ratings": "generator_rated_kw_per_unit",
    "facility.substation.configuration": "interconnection_configuration",
    "facility.motor_schedule": "largest_motor_start_mw",
    "facility.relay_settings": "relay_model_and_firmware_summary",
    "facility.equipment_schedule": "equipment_schedule_present",
    "facility.modeling.dynamic_model_available": "accepted_dynamic_representation",
}

_DEFAULT_WORKER_ROUTING: dict[str, tuple[str, ...]] = {}

_DEFAULT_PIPELINE_REQUESTED_FIELD_PATHS: tuple[str, ...] = ()

_DEFAULT_NORMALIZATION_REQUIRED_FIELD_IDS: tuple[str, ...] = ()

_DEFAULT_INTERVIEW_PRIORITY_FIELD_IDS: tuple[str, ...] = ()


_DEFAULT_TRANSLATION_PARAMETER_MAP: dict[str, dict[str, Any]] = {
    "steady_state.p_mw": {
        "label": "Steady-state active power at POI",
        "units": "MW",
        "default_value": 0.0,
        "accepted_field_id": "accepted_peak_demand_mw",
        "dependency_paths": [
            "peak_demand_mw",
            "accepted_peak_demand_mw",
            "facility.load_schedule.phase_3_mw",
            "engineering_model.load_system.peak_demand_mw",
            "engineering_model.buildout_and_ramping.ramp_characteristics.block_load_step_mw",
        ],
        "source_field_paths": [
            "peak_demand_mw",
            "accepted_peak_demand_mw",
            "facility.load_schedule.phase_3_mw",
            "engineering_model.load_system.peak_demand_mw",
            "engineering_model.buildout_and_ramping.ramp_characteristics.block_load_step_mw",
        ],
        "topics": ["load schedule", "peak demand", "steady state"],
    },
    "steady_state.q_mvar": {
        "label": "Steady-state reactive power at POI",
        "units": "MVAR",
        "default_value": 0.0,
        "accepted_field_id": "reactive_power_capability_or_requirement",
        "dependency_paths": [
            "peak_demand_mw",
            "accepted_peak_demand_mw",
            "facility.load_schedule.phase_3_mw",
            "net_power_factor_at_poi",
            "reactive_power_capability_or_requirement",
        ],
        "source_field_paths": [
            "peak_demand_mw",
            "accepted_peak_demand_mw",
            "facility.load_schedule.phase_3_mw",
            "net_power_factor_at_poi",
            "reactive_power_capability_or_requirement",
        ],
        "topics": ["load schedule", "reactive power", "power factor"],
    },
    "zip_model.constant_power_fraction": {
        "label": "ZIP constant-power fraction",
        "units": "per_unit",
        "default_value": 0.8,
        "accepted_field_id": "accepted_zip_representation",
        "dependency_paths": ["steady_state_zip_fraction_p", "facility.ups.topology"],
        "source_field_paths": ["steady_state_zip_fraction_p", "facility.ups.topology"],
        "topics": ["ups topology", "zip", "steady state"],
    },
    "zip_model.constant_current_fraction": {
        "label": "ZIP constant-current fraction",
        "units": "per_unit",
        "default_value": 0.1,
        "accepted_field_id": "accepted_zip_representation",
        "dependency_paths": ["steady_state_zip_fraction_i", "facility.ups.topology"],
        "source_field_paths": ["steady_state_zip_fraction_i", "facility.ups.topology"],
        "topics": ["ups topology", "zip", "steady state"],
    },
    "zip_model.constant_impedance_fraction": {
        "label": "ZIP constant-impedance fraction",
        "units": "per_unit",
        "default_value": 0.1,
        "accepted_field_id": "accepted_zip_representation",
        "dependency_paths": ["steady_state_zip_fraction_z", "facility.ups.topology"],
        "source_field_paths": ["steady_state_zip_fraction_z", "facility.ups.topology"],
        "topics": ["ups topology", "zip", "steady state"],
    },
    "ramping.max_ramp_up_mw_per_min": {
        "label": "Maximum ramp-up MW per minute",
        "units": "MW_per_min",
        "default_value": 1.0,
        "accepted_field_id": "load_ramp_profile_summary",
        "dependency_paths": [
            "facility.dynamic_behavior.max_ramp_up_mw_per_min",
            "facility.load_schedule.phase_1_mw",
            "load_ramp_profile_summary",
        ],
        "source_field_paths": [
            "facility.dynamic_behavior.max_ramp_up_mw_per_min",
            "facility.load_schedule.phase_1_mw",
            "load_ramp_profile_summary",
        ],
        "topics": ["load schedule", "ramping"],
    },
    "ramping.max_ramp_down_mw_per_min": {
        "label": "Maximum ramp-down MW per minute",
        "units": "MW_per_min",
        "default_value": 1.0,
        "accepted_field_id": "load_ramp_profile_summary",
        "dependency_paths": [
            "facility.dynamic_behavior.max_ramp_down_mw_per_min",
            "facility.load_schedule.phase_1_mw",
            "load_ramp_profile_summary",
        ],
        "source_field_paths": [
            "facility.dynamic_behavior.max_ramp_down_mw_per_min",
            "facility.load_schedule.phase_1_mw",
            "load_ramp_profile_summary",
        ],
        "topics": ["load schedule", "ramping"],
    },
}



_DEFAULT_FIELD_RESOLUTION_FAMILY_POLICIES: dict[str, dict[str, Any]] = {
    "generator": {
        "source_hierarchy_boosts": {
            "manufacturer_model_specific_spec": 18,
            "manufacturer_family_spec": 10,
            "official_interconnection_source": 4,
        },
        "identity_fields": [
            "generator_manufacturer",
            "generator_model",
            "generator_model_family",
            "generator_unit_count",
            "generator_prime_or_standby_rating_basis",
            "generator_terminal_voltage_kv",
        ],
        "voltage_reference_fields": [
            "generator_terminal_voltage_kv",
            "distribution_voltage_levels",
        ],
        "field_type_hierarchy_boosts": {
            "rating_basis": {
                "applicant_direct_document": 14,
                "applicant_confirmed_answer": 12,
                "manufacturer_model_specific_spec": 8,
            },
            "capacity": {
                "manufacturer_model_specific_spec": 16,
                "manufacturer_family_spec": 8,
                "applicant_direct_document": 6,
            },
            "identity": {
                "applicant_direct_document": 10,
                "manufacturer_model_specific_spec": 8,
            },
            "voltage": {
                "applicant_direct_document": 10,
                "official_interconnection_source": 10,
            },
        },
        "field_type_hierarchy_penalties": {
            "rating_basis": {
                "secondary_web": -10,
                "llm_uncited": -18,
            },
        },
    },
    "transformer": {
        "source_hierarchy_boosts": {
            "manufacturer_model_specific_spec": 16,
            "manufacturer_family_spec": 10,
        },
        "identity_fields": [
            "interconnection_transformer_manufacturer",
            "interconnection_transformer_model",
            "interconnection_transformer_model_family",
            "interconnection_transformer_unit_count",
        ],
        "voltage_reference_fields": [
            "point_of_interconnection_voltage_kv",
            "interconnection_transformer_hv_kv",
            "interconnection_transformer_lv_kv",
            "main_bus_nominal_voltage_kv",
        ],
        "capacity_fields": [
            "interconnection_transformer_mva_per_unit",
            "interconnection_transformer_unit_count",
        ],
        "peak_demand_fields": ["peak_demand_mw"],
        "field_type_hierarchy_boosts": {
            "voltage": {
                "official_interconnection_source": 18,
                "applicant_direct_document": 12,
                "manufacturer_model_specific_spec": 4,
            },
            "capacity": {
                "manufacturer_model_specific_spec": 14,
                "applicant_direct_document": 10,
                "official_interconnection_source": 6,
            },
            "identity": {
                "manufacturer_model_specific_spec": 10,
                "applicant_direct_document": 8,
            },
        },
        "field_type_hierarchy_penalties": {
            "voltage": {
                "vendor_pdf": -6,
                "secondary_web": -12,
                "llm_uncited": -20,
            },
        },
    },
    "ups": {
        "source_hierarchy_boosts": {
            "manufacturer_model_specific_spec": 16,
            "manufacturer_family_spec": 10,
        },
        "identity_fields": [
            "ups_manufacturer",
            "ups_model",
            "ups_model_family",
            "ups_unit_count",
            "ups_topology",
        ],
        "voltage_reference_fields": [
            "ups_input_voltage_kv_or_v",
            "ups_output_voltage_kv_or_v",
            "distribution_voltage_levels",
        ],
        "capacity_fields": [
            "ups_capacity_kw_per_unit",
            "ups_unit_count",
        ],
        "runtime_fields": ["ups_battery_runtime_minutes"],
        "peak_demand_fields": ["peak_demand_mw"],
        "field_type_hierarchy_boosts": {
            "runtime": {
                "manufacturer_model_specific_spec": 18,
                "manufacturer_family_spec": 10,
                "applicant_direct_document": 8,
            },
            "capacity": {
                "manufacturer_model_specific_spec": 14,
                "applicant_direct_document": 8,
            },
            "identity": {
                "applicant_direct_document": 8,
                "manufacturer_model_specific_spec": 8,
            },
        },
    },
    "relay": {
        "source_hierarchy_boosts": {
            "manufacturer_model_specific_spec": 12,
            "manufacturer_family_spec": 8,
            "official_interconnection_source": 6,
        },
        "identity_fields": [
            "relay_model_and_firmware_summary",
        ],
        "field_type_hierarchy_boosts": {
            "protection": {
                "official_interconnection_source": 16,
                "applicant_direct_document": 10,
            },
        },
    },
    "interconnection": {
        "source_hierarchy_boosts": {
            "official_interconnection_source": 18,
            "applicant_direct_document": 12,
        },
        "voltage_reference_fields": [
            "point_of_interconnection_voltage_kv",
            "incoming_service_voltage_levels",
            "main_bus_nominal_voltage_kv",
            "interconnection_transformer_hv_kv",
            "interconnection_transformer_lv_kv",
        ],
        "field_type_hierarchy_boosts": {
            "voltage": {
                "official_interconnection_source": 22,
                "applicant_direct_document": 10,
            },
            "topology": {
                "official_interconnection_source": 16,
                "applicant_direct_document": 10,
            },
            "telemetry": {
                "official_interconnection_source": 14,
                "applicant_direct_document": 8,
            },
        },
        "field_type_hierarchy_penalties": {
            "voltage": {
                "manufacturer_model_specific_spec": -8,
                "vendor_pdf": -10,
                "secondary_web": -16,
                "llm_uncited": -24,
            },
        },
    },
    "metering": {
        "source_hierarchy_boosts": {
            "official_interconnection_source": 10,
            "applicant_direct_document": 8,
        },
        "field_type_hierarchy_boosts": {
            "telemetry": {
                "official_interconnection_source": 16,
                "applicant_direct_document": 8,
            },
        },
    },
    "load": {
        "source_hierarchy_boosts": {
            "applicant_direct_document": 12,
            "applicant_confirmed_answer": 6,
        },
        "peak_demand_fields": ["peak_demand_mw"],
        "field_type_hierarchy_boosts": {
            "capacity": {
                "applicant_direct_document": 10,
                "official_interconnection_source": 6,
            },
            "topology": {
                "applicant_direct_document": 8,
            },
        },
    },
    "ramping": {
        "source_hierarchy_boosts": {
            "applicant_direct_document": 10,
            "applicant_confirmed_answer": 8,
            "official_interconnection_source": 4,
        },
        "peak_demand_fields": ["peak_demand_mw"],
        "ramp_fields": [
            "load_ramp_profile_summary",
            "maximum_daily_weekly_monthly_ramp_summary",
        ],
        "field_type_hierarchy_boosts": {
            "ramp": {
                "applicant_direct_document": 10,
                "official_interconnection_source": 6,
            },
        },
    },
}


_SOURCE_TO_CORPORA_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("manufacturer", ("equipment_catalog", "vendor_documents")),
    ("vendor", ("equipment_catalog", "vendor_documents")),
    ("datasheet", ("equipment_catalog", "vendor_documents")),
    ("spec", ("equipment_catalog", "vendor_documents")),
    ("catalog", ("equipment_catalog",)),
    ("model", ("equipment_catalog",)),
    ("utility", ("interconnection_guidance",)),
    ("iso", ("interconnection_guidance",)),
    ("ercot", ("interconnection_guidance",)),
    ("interconnection", ("interconnection_guidance",)),
    ("poi", ("interconnection_guidance",)),
    ("substation", ("interconnection_guidance",)),
    ("planning", ("modeling_references", "interconnection_guidance")),
    ("modeling", ("modeling_references",)),
    ("zip", ("modeling_references",)),
    ("dynamic", ("modeling_references",)),
)




_DEFAULT_SOURCE_STREAM_POLICY: dict[str, dict[str, int]] = {
    "general": {
        "ocr_extraction": 4,
        "knowledge_library": 6,
        "vendor_pdf": 6,
        "official_web": 4,
        "applicant_interview": 5,
        "normalized_record": 2,
        "record": 0,
    },
    "interconnection": {
        "official_web": 12,
        "vendor_pdf": 4,
        "knowledge_library": 3,
        "applicant_interview": 5,
        "ocr_extraction": 4,
    },
    "transformer": {
        "vendor_pdf": 10,
        "knowledge_library": 8,
        "official_web": 5,
        "applicant_interview": 6,
        "ocr_extraction": 4,
    },
    "ups": {
        "vendor_pdf": 10,
        "knowledge_library": 8,
        "official_web": 4,
        "applicant_interview": 6,
        "ocr_extraction": 4,
    },
    "generator": {
        "vendor_pdf": 9,
        "knowledge_library": 8,
        "official_web": 5,
        "applicant_interview": 7,
        "ocr_extraction": 4,
    },
}
@lru_cache(maxsize=1)
def load_planner_registry() -> dict[str, Any]:
    try:
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def planner_registry_fields() -> list[dict[str, Any]]:
    payload = load_planner_registry()
    fields = payload.get("fields", [])
    return [item for item in fields if isinstance(item, dict)] if isinstance(fields, list) else []


@lru_cache(maxsize=1)
def planner_registry_field_map() -> dict[str, dict[str, Any]]:
    return {
        str(item.get("field_id", "")).strip(): item
        for item in planner_registry_fields()
        if isinstance(item, dict) and str(item.get("field_id", "")).strip()
    }


def _runtime_compatibility() -> dict[str, Any]:
    payload = load_planner_registry()
    compatibility = payload.get("runtime_compatibility", {})
    return compatibility if isinstance(compatibility, dict) else {}


@lru_cache(maxsize=1)
def legacy_field_path_to_registry_field_id() -> dict[str, str]:
    compatibility = _runtime_compatibility()
    raw = compatibility.get("legacy_field_path_to_registry_field_id", {})
    result = dict(_DEFAULT_LEGACY_FIELD_PATH_MAP)
    valid_field_ids = set(planner_registry_field_map().keys())
    if isinstance(raw, dict):
        for key, value in raw.items():
            k = str(key).strip()
            v = str(value).strip()
            if not k or not v:
                continue
            if k in {"facility.load_schedule.phase_2_mw", "facility.load_schedule.phase_3_mw"} and v == "peak_demand_mw":
                # Preserve later phase rows as buildout schedule support if older
                # compatibility metadata maps them to peak demand. Phase 1 remains
                # the established public alias for peak_demand_mw.
                continue
            if v not in valid_field_ids and result.get(k) in valid_field_ids:
                continue
            result[k] = v
    return result


@lru_cache(maxsize=1)
def registry_field_id_to_legacy_paths() -> dict[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {}
    for legacy_path, field_id in legacy_field_path_to_registry_field_id().items():
        mapping.setdefault(field_id, []).append(legacy_path)
    return {key: tuple(value) for key, value in mapping.items()}


def field_path_for_registry_field_id(field_id: str | None) -> str | None:
    value = str(field_id or "").strip()
    if not value:
        return None
    paths = registry_field_id_to_legacy_paths().get(value, ())
    return paths[0] if paths else None


def resolve_registry_field(field_path_or_id: str | None) -> dict[str, Any] | None:
    value = str(field_path_or_id or "").strip()
    if not value:
        return None
    field_map = planner_registry_field_map()
    if value in field_map:
        return field_map[value]
    field_id = legacy_field_path_to_registry_field_id().get(value, "")
    return field_map.get(field_id) if field_id else None


def field_label_for_path(field_path_or_id: str | None) -> str:
    field = resolve_registry_field(field_path_or_id)
    if not isinstance(field, dict):
        value = str(field_path_or_id or "").strip()
        return value
    return str(field.get("label", "")).strip() or str(field_path_or_id or "").strip()


def field_family_for_path(field_path_or_id: str | None) -> str:
    field = resolve_registry_field(field_path_or_id)
    if isinstance(field, dict):
        explicit_family = str(field.get("field_family", "")).strip().lower()
        if explicit_family:
            return explicit_family
        group = str(field.get("group", "")).strip().lower()
        packet_section = str(field.get("packet_section", "")).strip().lower()
        field_id = str(field.get("field_id", "")).strip().lower()
        blob = " ".join(part for part in (group, packet_section, field_id) if part)
    else:
        blob = str(field_path_or_id or "").strip().lower()

    family_rules = (
        ("interconnection", ("poi", "interconnection", "substation", "utility", "point_of_interconnection", "electrical_configuration")),
        ("transformer", ("transformer", "xfmr")),
        ("generator", ("generator", "genset", "gen")),
        ("ups", ("ups", "battery", "runtime", "switchgear", "switchboard", "breaker", "bus", "distribution")),
        ("relay", ("relay", "protection", "trip", "breaker", "recloser", "firmware", "settings")),
        ("metering", ("meter", "metering", "telemetry", "scada", "rtu", "ct", "pt")),
        ("ramping", ("ramp", "load_step", "dynamic_behavior")),
        ("load", ("load", "demand", "motor", "schedule")),
    )
    for family, needles in family_rules:
        if any(token in blob for token in needles):
            return family
    return "general"


def field_group_for_path(field_path_or_id: str | None) -> str:
    field = resolve_registry_field(field_path_or_id)
    return str(field.get("group", "")).strip() if isinstance(field, dict) else ""


def field_data_type_for_path(field_path_or_id: str | None) -> str:
    field = resolve_registry_field(field_path_or_id)
    return str(field.get("data_type", "")).strip().lower() if isinstance(field, dict) else ""


def field_requiredness_for_path(field_path_or_id: str | None) -> str:
    field = resolve_registry_field(field_path_or_id)
    return str(field.get("requiredness", "")).strip().lower() if isinstance(field, dict) else ""


def field_minimum_confidence_for_auto_accept(field_path_or_id: str | None) -> str:
    field = resolve_registry_field(field_path_or_id)
    return str(field.get("minimum_confidence_for_auto_accept", "")).strip().lower() if isinstance(field, dict) else ""


def planner_critical_for_path(field_path_or_id: str | None) -> bool:
    field = resolve_registry_field(field_path_or_id)
    return bool(field.get("planner_critical", False)) if isinstance(field, dict) else False


def normalization_seed_field_paths() -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for field_id in normalization_required_field_ids():
        field_path = field_path_for_registry_field_id(field_id)
        if isinstance(field_path, str) and field_path.strip() and field_path not in seen:
            paths.append(field_path)
            seen.add(field_path)
    for field_path in pipeline_requested_field_paths():
        if isinstance(field_path, str) and field_path.strip() and field_path not in seen:
            paths.append(field_path.strip())
            seen.add(field_path.strip())
    return paths


def registry_field_id_for_path(field_path_or_id: str | None) -> str:
    value = str(field_path_or_id or "").strip()
    if not value:
        return ""
    if value in planner_registry_field_map():
        return value
    return legacy_field_path_to_registry_field_id().get(value, "")


def preferred_sources_for_field(field_path_or_id: str | None) -> list[str]:
    field = resolve_registry_field(field_path_or_id)
    preferred = field.get("preferred_sources", []) if isinstance(field, dict) else []
    return [str(item).strip() for item in preferred if isinstance(item, str) and str(item).strip()] if isinstance(preferred, list) else []


def preferred_corpora_for_field(field_path_or_id: str | None) -> list[str]:
    preferred_sources = preferred_sources_for_field(field_path_or_id)
    corpora: list[str] = []
    lowered_blob = " ".join(preferred_sources).lower()
    for needle, family_names in _SOURCE_TO_CORPORA_HINTS:
        if needle in lowered_blob:
            for family_name in family_names:
                if family_name not in corpora:
                    corpora.append(family_name)
    if not corpora:
        if "ups" in lowered_blob or "generator" in lowered_blob or "transformer" in lowered_blob:
            corpora.extend(["equipment_catalog", "vendor_documents"])
        elif preferred_sources:
            corpora.append("interconnection_guidance")
    return corpora


def search_keywords_for_field(field_path_or_id: str | None) -> list[str]:
    field = resolve_registry_field(field_path_or_id)
    keywords: list[str] = []
    if isinstance(field, dict):
        raw = field.get("search_keywords", [])
        if isinstance(raw, list):
            keywords.extend(str(item).strip() for item in raw if isinstance(item, str) and str(item).strip())
        label = str(field.get("label", "")).strip()
        if label:
            keywords.append(label)
        for alias in field.get("repo_aliases_or_related_fields", []) if isinstance(field.get("repo_aliases_or_related_fields"), list) else []:
            if isinstance(alias, str) and alias.strip():
                keywords.append(alias.strip())
    field_id = registry_field_id_for_path(field_path_or_id)
    if field_id:
        keywords.extend(part for part in field_id.replace("_", " ").split() if part)
    seen: set[str] = set()
    deduped: list[str] = []
    for keyword in keywords:
        lowered = keyword.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(keyword)
    return deduped


def pipeline_touchpoints_for_field(field_path_or_id: str | None) -> list[str]:
    field = resolve_registry_field(field_path_or_id)
    raw = field.get("pipeline_touchpoints", []) if isinstance(field, dict) else []
    return [str(item).strip() for item in raw if isinstance(item, str) and str(item).strip()] if isinstance(raw, list) else []


def _clean_runtime_path_list(name: str) -> list[str]:
    compatibility = _runtime_compatibility()
    raw = compatibility.get(name, [])
    values = [
        str(item).strip()
        for item in raw
        if isinstance(item, str) and str(item).strip()
    ] if isinstance(raw, list) else []
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _derive_pipeline_requested_field_paths() -> list[str]:
    requested: list[str] = []
    seen: set[str] = set()
    for field in planner_registry_fields():
        field_id = str(field.get("field_id", "")).strip()
        if not field_id:
            continue
        field_path = field_path_for_registry_field_id(field_id)
        if not field_path:
            continue
        if field_path in seen:
            continue
        touchpoints = set(pipeline_touchpoints_for_field(field_id))
        if not touchpoints.intersection({"entity_extraction", "ocr_layout_parsing", "document_classification", "ontology_mapping", "normalization"}):
            continue
        seen.add(field_path)
        requested.append(field_path)
    return requested


def pipeline_requested_field_paths() -> list[str]:
    values = _clean_runtime_path_list("pipeline_requested_field_paths")
    if values:
        return values
    derived = _derive_pipeline_requested_field_paths()
    return derived or list(_DEFAULT_PIPELINE_REQUESTED_FIELD_PATHS)


def _derive_worker_routing_table() -> dict[str, tuple[str, ...]]:
    requested = pipeline_requested_field_paths()
    result: dict[str, list[str]] = {
        "drawing_worker": [],
        "table_worker": [],
        "spec_worker": [],
        "retrieval_worker": [],
    }
    drawing_groups = {"site_and_interconnection_context", "electrical_topology"}
    table_groups = {"project_and_process_context", "load_profile_and_behavior", "protection_controls_and_relaying", "operations_and_commissioning"}
    spec_groups = {"generator_system", "ups_and_power_electronics", "transformers_and_switchgear", "metering_telemetry_and_scada", "mechanical_and_cooling_loads"}
    for field_path in requested:
        field = resolve_registry_field(field_path)
        group = str(field.get("group", "")).strip() if isinstance(field, dict) else ""
        field_id = registry_field_id_for_path(field_path)
        if field_id == "accepted_dynamic_representation":
            worker_name = "retrieval_worker"
        elif group in drawing_groups:
            worker_name = "drawing_worker"
        elif group in table_groups:
            worker_name = "table_worker"
        elif group in spec_groups:
            worker_name = "spec_worker"
        elif set(pipeline_touchpoints_for_field(field_path)).intersection({"internal_knowledge_retrieval", "vendor_pdf_retrieval", "official_web_retrieval"}):
            worker_name = "retrieval_worker"
        else:
            worker_name = "spec_worker"
        bucket = result.setdefault(worker_name, [])
        if field_path not in bucket:
            bucket.append(field_path)
    return {worker_name: tuple(paths) for worker_name, paths in result.items() if paths}


def _postprocess_worker_routing_table(result: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, list[str]] = {
        worker_name: list(field_paths)
        for worker_name, field_paths in result.items()
    }

    drawing_paths = normalized.setdefault("drawing_worker", [])
    if "facility.equipment_schedule" in drawing_paths:
        normalized["drawing_worker"] = [item for item in drawing_paths if item != "facility.equipment_schedule"]
        table_paths = normalized.setdefault("table_worker", [])
        if "facility.equipment_schedule" not in table_paths:
            table_paths.append("facility.equipment_schedule")

    return {
        worker_name: tuple(field_paths)
        for worker_name, field_paths in normalized.items()
        if field_paths
    }


def worker_routing_table() -> dict[str, tuple[str, ...]]:
    compatibility = _runtime_compatibility()
    raw = compatibility.get("worker_routing", {})
    if isinstance(raw, dict):
        result: dict[str, tuple[str, ...]] = {}
        for worker_name, field_paths in raw.items():
            if not isinstance(field_paths, list):
                continue
            cleaned = tuple(str(item).strip() for item in field_paths if isinstance(item, str) and str(item).strip())
            if cleaned:
                result[str(worker_name).strip()] = cleaned
        if result:
            return _postprocess_worker_routing_table(result)
    derived = _derive_worker_routing_table()
    final = derived or dict(_DEFAULT_WORKER_ROUTING)
    return _postprocess_worker_routing_table(final)


def planner_document_specs() -> list[dict[str, Any]]:
    payload = load_planner_registry()
    documents = payload.get("planner_documents", [])
    if isinstance(documents, list):
        return [item for item in documents if isinstance(item, dict)]
    return []


@lru_cache(maxsize=1)
def planner_registry_group_index() -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in planner_registry_fields():
        group = str(item.get("group", "")).strip()
        if not group:
            continue
        groups.setdefault(group, []).append(item)
    return groups


def planner_fields_for_group(group: str | None) -> list[dict[str, Any]]:
    normalized = str(group or "").strip()
    if not normalized:
        return []
    return list(planner_registry_group_index().get(normalized, []))



def _field_id_list_from_runtime(name: str, fallback: tuple[str, ...] = ()) -> list[str]:
    compatibility = _runtime_compatibility()
    raw = compatibility.get(name, [])
    valid_field_ids = set(planner_registry_field_map().keys())
    values = [
        str(item).strip()
        for item in raw
        if isinstance(item, str) and str(item).strip() and str(item).strip() in valid_field_ids
    ] if isinstance(raw, list) else []
    if values:
        return values
    return [field_id for field_id in fallback if field_id in valid_field_ids]


@lru_cache(maxsize=1)
def normalization_required_field_ids() -> list[str]:
    values = _field_id_list_from_runtime("normalization_required_field_ids")
    if values:
        return values
    derived: list[str] = []
    for field in planner_registry_fields():
        field_id = str(field.get("field_id", "")).strip()
        if not field_id:
            continue
        if "normalization" not in set(pipeline_touchpoints_for_field(field_id)):
            continue
        requiredness = str(field.get("requiredness", "optional")).strip().lower()
        planner_critical = bool(field.get("planner_critical", False))
        if planner_critical or requiredness in {"required", "conditional"}:
            derived.append(field_id)
    return derived or [field_id for field_id in _DEFAULT_NORMALIZATION_REQUIRED_FIELD_IDS if field_id in planner_registry_field_map()]


@lru_cache(maxsize=1)
def interview_priority_field_ids() -> list[str]:
    values = _field_id_list_from_runtime("interview_priority_field_ids")
    if values:
        return values
    derived: list[str] = []
    for field in planner_registry_fields():
        field_id = str(field.get("field_id", "")).strip()
        if not field_id:
            continue
        if "applicant_interview" not in set(pipeline_touchpoints_for_field(field_id)):
            continue
        requiredness = str(field.get("requiredness", "optional")).strip().lower()
        planner_critical = bool(field.get("planner_critical", False))
        if planner_critical or requiredness in {"required", "conditional"}:
            derived.append(field_id)
    return derived or [field_id for field_id in _DEFAULT_INTERVIEW_PRIORITY_FIELD_IDS if field_id in planner_registry_field_map()]


@lru_cache(maxsize=1)
def interview_priority_rank_map() -> dict[str, int]:
    ordered = interview_priority_field_ids()
    return {field_id: index for index, field_id in enumerate(ordered)}




@lru_cache(maxsize=1)
def planner_document_field_map() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for document in planner_document_specs():
        fields = document.get("data_fields_provided", []) if isinstance(document, dict) else []
        if not isinstance(fields, list):
            continue
        document_name = str(document.get("document_name", "")).strip() if isinstance(document, dict) else ""
        if not document_name:
            continue
        for field_id in fields:
            cleaned = str(field_id).strip()
            if not cleaned:
                continue
            mapping.setdefault(cleaned, [])
            if document_name not in mapping[cleaned]:
                mapping[cleaned].append(document_name)
    return mapping


def planner_document_names_for_field(field_path_or_id: str | None) -> list[str]:
    field_id = registry_field_id_for_path(field_path_or_id) or str(field_path_or_id or "").strip()
    if not field_id:
        return []
    mapping = planner_document_field_map()
    names: list[str] = []
    lookup_keys = [field_id]
    resolved = resolve_registry_field(field_id)
    if isinstance(resolved, dict):
        aliases = resolved.get("repo_aliases_or_related_fields", [])
        if isinstance(aliases, list):
            for item in aliases:
                cleaned = str(item).strip()
                if cleaned and cleaned not in lookup_keys:
                    lookup_keys.append(cleaned)
    for key in lookup_keys:
        for document_name in mapping.get(key, []):
            if document_name not in names:
                names.append(document_name)
    return names


def planner_registry_integrity_snapshot() -> dict[str, Any]:
    fields = planner_registry_fields()
    field_ids = {str(item.get("field_id", "")).strip() for item in fields if isinstance(item, dict)}
    required_samples = {
        "project_name",
        "point_of_interconnection_voltage_kv",
        "peak_demand_mw",
        "generator_unit_count",
        "generator_manufacturer",
        "generator_model",
        "generator_rated_kw_per_unit",
        "interconnection_transformer_unit_count",
        "interconnection_transformer_manufacturer",
        "interconnection_transformer_model",
        "interconnection_transformer_mva_per_unit",
        "ups_topology",
        "ups_unit_count",
        "accepted_dynamic_representation",
        "accepted_zip_representation",
    }
    return {
        "field_count": len(field_ids),
        "planner_document_count": len(planner_document_specs()),
        "group_count": len(planner_registry_group_index()),
        "missing_required_samples": sorted(required_samples - field_ids),
    }
def registry_lookup_keys(field_path_or_id: str | None) -> list[str]:
    field = resolve_registry_field(field_path_or_id)
    if not isinstance(field, dict):
        return []

    keys: list[str] = []
    field_id = str(field.get("field_id", "")).strip()
    if field_id:
        keys.append(field_id)
        for path in registry_field_id_to_legacy_paths().get(field_id, ()):
            if path not in keys:
                keys.append(path)

    aliases = field.get("repo_aliases_or_related_fields", [])
    if isinstance(aliases, list):
        for item in aliases:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
    return keys


def field_label(field_path_or_id: str | None) -> str:
    field = resolve_registry_field(field_path_or_id)
    if not isinstance(field, dict):
        value = str(field_path_or_id or "").strip()
        return value.replace("_", " ").replace(".", " " ).strip().title() if value else ""
    label = str(field.get("label", "")).strip()
    return label or str(field.get("field_id", "")).strip().replace("_", " " ).title()


def field_requiredness(field_path_or_id: str | None) -> str:
    field = resolve_registry_field(field_path_or_id)
    if not isinstance(field, dict):
        return "optional"
    return str(field.get("requiredness", "optional")).strip().lower() or "optional"


def field_is_planner_critical(field_path_or_id: str | None) -> bool:
    field = resolve_registry_field(field_path_or_id)
    return bool(field.get("planner_critical", False)) if isinstance(field, dict) else False


def build_followup_profile(field_path_or_id: str | None) -> dict[str, Any]:
    field = resolve_registry_field(field_path_or_id)
    field_id = registry_field_id_for_path(field_path_or_id)
    label = field_label(field_path_or_id)
    preferred_sources = preferred_sources_for_field(field_path_or_id)
    profile = {
        "field_id": field_id,
        "field_path": field_path_for_registry_field_id(field_id) or str(field_path_or_id or "").strip() or field_id,
        "label": label,
        "requiredness": field_requiredness(field_path_or_id),
        "planner_critical": field_is_planner_critical(field_path_or_id),
        "preferred_sources": preferred_sources,
        "search_keywords": search_keywords_for_field(field_path_or_id),
        "lookup_keys": registry_lookup_keys(field_path_or_id),
        "minimum_confidence_for_auto_accept": field.get("minimum_confidence_for_auto_accept") if isinstance(field, dict) else None,
        "packet_section": str(field.get("packet_section", "")).strip() if isinstance(field, dict) else "",
        "group": str(field.get("group", "")).strip() if isinstance(field, dict) else "",
    }
    return profile



def _normalization_seed_default_for_field(field_path_or_id: str | None) -> Any:
    field = resolve_registry_field(field_path_or_id)
    field_id = registry_field_id_for_path(field_path_or_id)
    data_type = str(field.get("data_type", "")).strip().lower() if isinstance(field, dict) else ""
    if field_id == "generator_frequency_hz" or str(field_path_or_id or "").strip() == "facility.frequency_hz":
        return 60
    if data_type.endswith("_list"):
        return []
    if data_type in {"contact", "address", "object", "mapping", "dict"}:
        return {}
    return None


def build_normalization_seed_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    requested_paths = normalization_seed_field_paths()
    seen: set[str] = set()
    for field_path in requested_paths:
        if field_path in seen:
            continue
        seen.add(field_path)
        default_value = _normalization_seed_default_for_field(field_path)
        cursor = payload
        parts = [part for part in field_path.split('.') if part]
        if not parts:
            continue
        for token in parts[:-1]:
            next_cursor = cursor.get(token)
            if not isinstance(next_cursor, dict):
                next_cursor = {}
                cursor[token] = next_cursor
            cursor = next_cursor
        cursor.setdefault(parts[-1], default_value)
    facility = payload.get("facility")
    if not isinstance(facility, dict):
        facility = {}
        payload["facility"] = facility
    facility.setdefault("frequency_hz", 60)
    return payload



def _normalize_translation_parameter_entry(parameter_path: str, payload: Any) -> dict[str, Any]:
    entry = payload if isinstance(payload, dict) else {}
    dependency_paths = [
        str(item).strip()
        for item in entry.get("dependency_paths", [])
        if isinstance(item, str) and str(item).strip()
    ] if isinstance(entry.get("dependency_paths"), list) else []
    source_field_paths = [
        str(item).strip()
        for item in entry.get("source_field_paths", [])
        if isinstance(item, str) and str(item).strip()
    ] if isinstance(entry.get("source_field_paths"), list) else []
    topics = [
        str(item).strip()
        for item in entry.get("topics", [])
        if isinstance(item, str) and str(item).strip()
    ] if isinstance(entry.get("topics"), list) else []
    return {
        "parameter_path": parameter_path,
        "label": str(entry.get("label", "")).strip() or parameter_path,
        "units": str(entry.get("units", "")).strip(),
        "accepted_field_id": str(entry.get("accepted_field_id", "")).strip(),
        "default_value": entry.get("default_value"),
        "dependency_paths": dependency_paths,
        "source_field_paths": source_field_paths or dependency_paths,
        "topics": topics,
    }


def _append_unique_paths(values: list[str], additions: tuple[str, ...]) -> list[str]:
    output = [str(item).strip() for item in values if str(item).strip()]
    seen = set(output)
    for item in additions:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            output.append(cleaned)
    return output


def _harden_translation_parameter_aliases(result: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Keep translation ledger-first even when registry compatibility aliases are legacy.

    Older compatibility metadata mapped steady-state P/Q to phase_1_mw.  For
    interconnection review, steady-state modeled power should prefer peak/maximum
    demand rows.  This enrichment is alias-based and project-agnostic.
    """
    # Keep public translation registry helpers stable for existing callers.
    # Ledger-native translation adds peak/ultimate aliases internally; registry
    # utility functions continue exposing the current registry dependency contract.
    steady_p = result.get("steady_state.p_mw")
    if isinstance(steady_p, dict):
        public_order = [
            "engineering_model.buildout_and_ramping.ramp_characteristics.block_load_step_mw",
            "engineering_model.load_system.peak_demand_mw",
            "facility.load_schedule.phase_1_mw",
        ]
        steady_p["dependency_paths"] = public_order
        steady_p["source_field_paths"] = public_order
    return result


@lru_cache(maxsize=1)
def translation_parameter_map() -> dict[str, dict[str, Any]]:
    compatibility = _runtime_compatibility()
    raw = compatibility.get("translation_parameters", {})
    result = {key: _normalize_translation_parameter_entry(key, value) for key, value in _DEFAULT_TRANSLATION_PARAMETER_MAP.items()}
    if isinstance(raw, dict):
        for parameter_path, payload in raw.items():
            normalized_path = str(parameter_path).strip()
            if normalized_path:
                result[normalized_path] = _normalize_translation_parameter_entry(normalized_path, payload)
    return _harden_translation_parameter_aliases(result)


def translation_parameter_config(parameter_path: str | None) -> dict[str, Any]:
    normalized = str(parameter_path or "").strip()
    if not normalized:
        return {}
    return dict(translation_parameter_map().get(normalized, {}))


def translation_dependency_paths(parameter_path: str | None) -> list[str]:
    config = translation_parameter_config(parameter_path)
    raw = config.get("dependency_paths", [])
    return list(raw) if isinstance(raw, list) else []


def translation_source_field_paths(parameter_path: str | None) -> list[str]:
    config = translation_parameter_config(parameter_path)
    raw = config.get("source_field_paths", [])
    return list(raw) if isinstance(raw, list) else []


def translation_topics(parameter_path: str | None) -> set[str]:
    config = translation_parameter_config(parameter_path)
    raw = config.get("topics", [])
    return {str(item).strip().lower() for item in raw if isinstance(item, str) and str(item).strip()}


def planner_translation_output_defaults() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for parameter_path, config in translation_parameter_map().items():
        if "default_value" not in config:
            continue
        default_value = config.get("default_value")
        cursor = payload
        tokens = [token for token in parameter_path.split(".") if token]
        if not tokens:
            continue
        for token in tokens[:-1]:
            next_value = cursor.get(token)
            if not isinstance(next_value, dict):
                next_value = {}
                cursor[token] = next_value
            cursor = next_value
        cursor[tokens[-1]] = default_value
    return payload


def planner_packet_sections() -> list[str]:
    payload = load_planner_registry()
    raw = payload.get("packet_sections", [])
    return [str(item).strip() for item in raw if isinstance(item, str) and str(item).strip()] if isinstance(raw, list) else []


def planner_packet_section_label(section_id: str | None) -> str:
    value = str(section_id or "").strip()
    if not value:
        return "Unknown Section"
    return value.replace("_", " ").title()


def planner_packet_fields(
    section_id: str | None = None,
    *,
    include_optional: bool = True,
    planner_critical_only: bool = False,
) -> list[dict[str, Any]]:
    normalized_section = str(section_id or "").strip()
    result: list[dict[str, Any]] = []
    for field in planner_registry_fields():
        touchpoints = field.get("pipeline_touchpoints", [])
        if not isinstance(touchpoints, list) or "planner_packet_export" not in touchpoints:
            continue
        if normalized_section and str(field.get("packet_section", "")).strip() != normalized_section:
            continue
        if planner_critical_only and not bool(field.get("planner_critical", False)):
            continue
        if not include_optional and str(field.get("requiredness", "")).strip().lower() == "optional":
            continue
        result.append(field)
    return result


def _canonical_field_record_index(canonical_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    records = canonical_state.get("field_records", []) if isinstance(canonical_state, dict) else []
    index: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(records, list):
        return index
    for record in records:
        if not isinstance(record, dict):
            continue
        field_path = str(record.get("field_path", "")).strip()
        if field_path:
            index.setdefault(field_path, []).append(record)
    return index


def _field_resolution_index(canonical_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(canonical_state, dict):
        return {}
    field_resolution = canonical_state.get("field_resolution") if isinstance(canonical_state.get("field_resolution"), dict) else {}
    ledger = field_resolution.get("ledger") if isinstance(field_resolution.get("ledger"), list) else []
    index: dict[str, dict[str, Any]] = {}
    for entry in ledger:
        if not isinstance(entry, dict):
            continue
        field_id = str(entry.get("field_id", "")).strip()
        field_path = str(entry.get("field_path", "")).strip()
        if field_id:
            index[field_id] = entry
        if field_path:
            index[field_path] = entry
    accepted_field_index = field_resolution.get("accepted_field_index") if isinstance(field_resolution.get("accepted_field_index"), dict) else {}
    for key, value in accepted_field_index.items():
        normalized_key = str(key).strip()
        if normalized_key and isinstance(value, dict):
            index[normalized_key] = value
    return index


def _validation_missing_field_set(validation_report: dict[str, Any] | None) -> set[str]:
    payload = validation_report if isinstance(validation_report, dict) else {}
    missing_fields = payload.get("missing_fields", [])
    result: set[str] = set()
    if not isinstance(missing_fields, list):
        return result
    for item in missing_fields:
        if isinstance(item, dict):
            field_path = str(item.get("field_path", "")).strip()
            if field_path:
                result.add(field_path)
        elif isinstance(item, str) and item.strip():
            result.add(item.strip())
    return result


def _field_lookup_keys(field: dict[str, Any]) -> list[str]:
    field_id = str(field.get("field_id", "")).strip()
    keys: list[str] = []
    if field_id:
        keys.append(field_id)
        for path in registry_field_id_to_legacy_paths().get(field_id, ()):  # legacy dotted runtime paths
            if path not in keys:
                keys.append(path)
    aliases = field.get("repo_aliases_or_related_fields", [])
    if isinstance(aliases, list):
        for item in aliases:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if not cleaned:
                continue
            if "." in cleaned or cleaned in planner_registry_field_map():
                if cleaned not in keys:
                    keys.append(cleaned)
    return keys


def _safe_stringify(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return str(value)


def _normalized_input_fallback(canonical_state: dict[str, Any], field: dict[str, Any]) -> Any:
    normalized_input = canonical_state.get("normalized_input", {}) if isinstance(canonical_state, dict) else {}
    if not isinstance(normalized_input, dict):
        return None
    for key in _field_lookup_keys(field):
        if "." not in key:
            continue
        cursor: Any = normalized_input
        found = True
        for token in key.split("."):
            if not isinstance(cursor, dict) or token not in cursor:
                found = False
                break
            cursor = cursor[token]
        if found:
            return cursor
    return None


def _field_status_from_records(records: list[dict[str, Any]], *, missing_keys: set[str]) -> tuple[str, Any, float | None]:
    if not records:
        return ("missing" if missing_keys else "unresolved", None, None)

    primary = next((item for item in records if item.get("is_primary") is True), records[0])
    distinct_values = {
        _safe_stringify(item.get("value"))
        for item in records
        if isinstance(item, dict) and item.get("value") is not None
    }

    has_conflict = False
    requires_review = False
    for record in records:
        legacy_status = str(record.get("status", "")).strip().lower()
        validation_status = str(record.get("validation_status", "")).strip().upper()
        review_status = str(record.get("review_status", "")).strip().upper()
        conflict_status = str(record.get("conflict_status", "")).strip().upper()
        if legacy_status == "conflicting" or validation_status == "CONFLICTING" or conflict_status in {"CONFLICT", "CONFLICT_PRESENT"}:
            has_conflict = True
        if legacy_status in {"review_required", "provisional_extracted", "provisional_retrieved", "missing"}:
            requires_review = True
        if validation_status in {"UNVALIDATED", "REVIEW_REQUIRED", "PROVISIONAL_EXTRACTED", "PROVISIONAL_RETRIEVED", "CANDIDATE"}:
            requires_review = True
        if review_status in {"PENDING_REVIEW", "PENDING_VALIDATION", "OPEN", "REVIEW_REQUIRED"}:
            requires_review = True

    value = primary.get("value")
    confidence = primary.get("confidence_score", primary.get("confidence"))
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    if len(distinct_values) > 1 or has_conflict:
        return "conflicting", value, confidence
    if value is None and missing_keys:
        return "missing", None, confidence
    if requires_review:
        return "review_required", value, confidence
    if value is None:
        return "unresolved", None, confidence
    return "resolved", value, confidence


def _status_priority(status: str | None) -> int:
    normalized = str(status or "unresolved").strip().lower() or "unresolved"
    ordering = {
        "conflicting": 0,
        "review_required": 1,
        "missing": 2,
        "unresolved": 3,
        "resolved": 4,
    }
    return ordering.get(normalized, 5)


def _requiredness_priority(requiredness: str | None) -> int:
    normalized = str(requiredness or "optional").strip().lower() or "optional"
    ordering = {
        "required": 0,
        "expected": 1,
        "conditional": 2,
        "optional": 3,
    }
    return ordering.get(normalized, 4)


def _row_priority_key(row: dict[str, Any]) -> tuple[Any, ...]:
    confidence = row.get("confidence")
    try:
        confidence_value = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence_value = None
    return (
        0 if bool(row.get("planner_critical", False)) else 1,
        _requiredness_priority(row.get("requiredness")),
        _status_priority(row.get("status")),
        0 if confidence_value is None else 1,
        confidence_value if confidence_value is not None else 999.0,
        str(row.get("packet_section_label", "")).strip().lower(),
        str(row.get("label", "")).strip().lower(),
        str(row.get("field_id", "")).strip().lower(),
    )


def planner_registry_resolution_queue(
    canonical_state: dict[str, Any] | None,
    validation_report: dict[str, Any] | None = None,
    *,
    include_optional: bool = False,
    include_resolved: bool = False,
) -> list[dict[str, Any]]:
    rows_by_section = build_planner_packet_field_rows(
        canonical_state,
        validation_report,
        include_optional=include_optional,
    )
    queue: list[dict[str, Any]] = []
    for section_id in planner_packet_sections():
        for row in rows_by_section.get(section_id, []):
            if not isinstance(row, dict):
                continue
            status = str(row.get("status", "unresolved")).strip().lower() or "unresolved"
            if not include_resolved and status == "resolved":
                continue
            item = dict(row)
            item["resolution_priority"] = len(queue) + 1
            queue.append(item)
    queue.sort(key=_row_priority_key)
    for index, item in enumerate(queue, start=1):
        item["resolution_priority"] = index
    return queue


def build_planner_packet_field_rows(
    canonical_state: dict[str, Any] | None,
    validation_report: dict[str, Any] | None = None,
    *,
    include_optional: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    state = canonical_state if isinstance(canonical_state, dict) else {}
    validation_payload = validation_report if isinstance(validation_report, dict) else {}
    record_index = _canonical_field_record_index(state)
    resolution_index = _field_resolution_index(state)
    missing_field_set = _validation_missing_field_set(validation_payload)
    rows_by_section: dict[str, list[dict[str, Any]]] = {}

    for section_id in planner_packet_sections():
        rows: list[dict[str, Any]] = []
        for field in planner_packet_fields(section_id, include_optional=include_optional):
            field_id = str(field.get("field_id", "")).strip()
            lookup_keys = _field_lookup_keys(field)
            resolution_entry = next(
                (resolution_index.get(key) for key in [field_id, *lookup_keys] if isinstance(resolution_index.get(key), dict)),
                None,
            )
            status = "unresolved"
            value: Any = None
            confidence: float | None = None
            matched_missing_keys = {key for key in lookup_keys if key in missing_field_set}
            if isinstance(resolution_entry, dict):
                status = str(resolution_entry.get("accepted_status", "unresolved")).strip().lower() or "unresolved"
                value = resolution_entry.get("accepted_value")
                try:
                    accepted_confidence = resolution_entry.get("accepted_confidence")
                    confidence = float(accepted_confidence) if accepted_confidence is not None else None
                except (TypeError, ValueError):
                    confidence = None
            else:
                records: list[dict[str, Any]] = []
                for key in lookup_keys:
                    records.extend(record_index.get(key, []))
                status, value, confidence = _field_status_from_records(records, missing_keys=matched_missing_keys)
                if value is None and status != "missing":
                    fallback = _normalized_input_fallback(state, field)
                    if fallback is not None:
                        value = fallback
                        if status == "unresolved":
                            status = "resolved"
            row: dict[str, Any] = {
                "field_id": field_id,
                "label": str(field.get("label", "")).strip() or field_id,
                "packet_section": section_id,
                "packet_section_label": planner_packet_section_label(section_id),
                "requiredness": str(field.get("requiredness", "")).strip() or "optional",
                "planner_critical": bool(field.get("planner_critical", False)),
                "status": status,
                "value": value,
                "confidence": confidence,
                "minimum_confidence_for_auto_accept": field.get("minimum_confidence_for_auto_accept"),
                "preferred_sources": preferred_sources_for_field(field_id),
                "lookup_keys": lookup_keys,
            }
            if isinstance(resolution_entry, dict):
                row.update(
                    {
                        "confidence_band": str(resolution_entry.get("confidence_band", "")).strip() or None,
                        "accepted_candidate_id": str(resolution_entry.get("accepted_candidate_id", "")).strip(),
                        "why_accepted": list(resolution_entry.get("why_accepted", [])) if isinstance(resolution_entry.get("why_accepted"), list) else [],
                        "source_anchors": list(resolution_entry.get("source_anchors", [])) if isinstance(resolution_entry.get("source_anchors"), list) else [],
                        "alternatives": list(resolution_entry.get("alternatives", [])) if isinstance(resolution_entry.get("alternatives"), list) else [],
                        "planner_review_flag": bool(resolution_entry.get("planner_review_flag", False)),
                        "needs_applicant_confirmation": bool(resolution_entry.get("needs_applicant_confirmation", False)),
                        "decision_basis": str(resolution_entry.get("decision_basis", "")).strip(),
                        "accepted_value_kind": str(resolution_entry.get("accepted_value_kind", "")).strip(),
                        "planner_attention_tier": str(resolution_entry.get("planner_attention_tier", "")).strip(),
                        "contradiction_summary": str(resolution_entry.get("contradiction_summary", "")).strip(),
                        "accepted_source_hierarchy": str(resolution_entry.get("accepted_source_hierarchy", "")).strip(),
                        "accepted_specificity": str(resolution_entry.get("accepted_specificity", "")).strip(),
                        "applicant_answer_state": str(resolution_entry.get("applicant_answer_state", "")).strip(),
                        "source_stream_counts": dict(resolution_entry.get("source_stream_counts", {})) if isinstance(resolution_entry.get("source_stream_counts"), dict) else {},
                        "supporting_source_count": len(resolution_entry.get("supporting_sources", [])) if isinstance(resolution_entry.get("supporting_sources"), list) else 0,
                    }
                )
            rows.append(row)
        rows.sort(key=_row_priority_key)
        rows_by_section[section_id] = rows
    return rows_by_section




def resolve_registry_field_resolution_entry(canonical_state: dict[str, Any] | None, field_key: str) -> dict[str, Any] | None:
    state = canonical_state if isinstance(canonical_state, dict) else {}
    key = str(field_key or '').strip()
    if not key:
        return None
    index = _field_resolution_index(state)
    entry = index.get(key)
    return dict(entry) if isinstance(entry, dict) else None


def resolve_registry_field_value(
    canonical_state: dict[str, Any] | None,
    field_key: str,
    fallback_value: Any = None,
) -> dict[str, Any]:
    state = canonical_state if isinstance(canonical_state, dict) else {}
    key = str(field_key or '').strip()
    entry = resolve_registry_field_resolution_entry(state, key)
    if isinstance(entry, dict):
        status = str(entry.get('accepted_status', 'unresolved')).strip().lower() or 'unresolved'
        value = entry.get('accepted_value', fallback_value)
        if value is None:
            value = fallback_value
        return {
            'value': value,
            'status': status,
            'confidence': entry.get('accepted_confidence'),
            'confidence_band': entry.get('confidence_band'),
            'why_accepted': list(entry.get('why_accepted', [])) if isinstance(entry.get('why_accepted'), list) else [],
            'source_anchors': list(entry.get('source_anchors', [])) if isinstance(entry.get('source_anchors'), list) else [],
            'planner_review_flag': bool(entry.get('planner_review_flag', False)),
            'needs_applicant_confirmation': bool(entry.get('needs_applicant_confirmation', False)),
            'decision_basis': str(entry.get('decision_basis', '')).strip(),
            'accepted_status': str(entry.get('accepted_status', '')).strip(),
            'accepted_value_kind': str(entry.get('accepted_value_kind', '')).strip(),
            'planner_attention_tier': str(entry.get('planner_attention_tier', '')).strip(),
            'accepted_source_hierarchy': str(entry.get('accepted_source_hierarchy', '')).strip(),
            'accepted_specificity': str(entry.get('accepted_specificity', '')).strip(),
            'contradiction_summary': str(entry.get('contradiction_summary', '')).strip(),
            'field_release_profile': dict(entry.get('field_release_profile', {})) if isinstance(entry.get('field_release_profile'), dict) else {},
            'supporting_sources': list(entry.get('supporting_sources', [])) if isinstance(entry.get('supporting_sources'), list) else [],
            'alternatives': list(entry.get('alternatives', [])) if isinstance(entry.get('alternatives'), list) else [],
            'label': str(entry.get('label', '')).strip(),
            'used_field_resolution': True,
        }

    field = planner_registry_field_map().get(key)
    if isinstance(field, dict):
        fallback = _normalized_input_fallback(state, field)
        if fallback is not None:
            return {
                'value': fallback,
                'status': 'resolved',
                'confidence': None,
                'confidence_band': None,
                'why_accepted': [],
                'source_anchors': [],
                'planner_review_flag': False,
                'needs_applicant_confirmation': False,
                'used_field_resolution': False,
            }
    return {
        'value': fallback_value,
        'status': 'unresolved',
        'confidence': None,
        'confidence_band': None,
        'why_accepted': [],
        'source_anchors': [],
        'planner_review_flag': False,
        'needs_applicant_confirmation': False,
        'used_field_resolution': False,
    }

def summarize_registry_packet_coverage(
    canonical_state: dict[str, Any] | None,
    validation_report: dict[str, Any] | None = None,
    *,
    include_optional: bool = False,
) -> dict[str, Any]:
    rows_by_section = build_planner_packet_field_rows(
        canonical_state,
        validation_report,
        include_optional=include_optional,
    )
    summary = {
        "total_field_count": 0,
        "resolved_count": 0,
        "review_required_count": 0,
        "conflicting_count": 0,
        "missing_count": 0,
        "unresolved_count": 0,
        "planner_critical_field_count": 0,
        "required_field_count": 0,
        "sections": [],
    }
    for section_id in planner_packet_sections():
        rows = rows_by_section.get(section_id, [])
        section_summary = {
            "section_id": section_id,
            "section_label": planner_packet_section_label(section_id),
            "field_count": len(rows),
            "resolved_count": 0,
            "review_required_count": 0,
            "conflicting_count": 0,
            "missing_count": 0,
            "unresolved_count": 0,
            "planner_critical_field_count": 0,
            "required_field_count": 0,
        }
        for row in rows:
            status = str(row.get("status", "unresolved")).strip().lower() or "unresolved"
            summary["total_field_count"] += 1
            section_summary["field_count"] += 0
            if bool(row.get("planner_critical", False)):
                summary["planner_critical_field_count"] += 1
                section_summary["planner_critical_field_count"] += 1
            if str(row.get("requiredness", "optional")).strip().lower() != "optional":
                summary["required_field_count"] += 1
                section_summary["required_field_count"] += 1
            key = f"{status}_count"
            if key in summary:
                summary[key] += 1
            else:
                summary["unresolved_count"] += 1
            if key in section_summary:
                section_summary[key] += 1
            else:
                section_summary["unresolved_count"] += 1
        summary["sections"].append(section_summary)
    return summary



def planner_registry_open_items(
    canonical_state: dict[str, Any] | None,
    validation_report: dict[str, Any] | None = None,
    *,
    include_optional: bool = False,
) -> dict[str, Any]:
    rows_by_section = build_planner_packet_field_rows(
        canonical_state,
        validation_report,
        include_optional=include_optional,
    )
    buckets: dict[str, list[dict[str, Any]]] = {
        "planner_critical_review_required": [],
        "planner_critical_conflicting": [],
        "planner_critical_missing": [],
        "planner_critical_unresolved": [],
        "required_missing": [],
    }

    def _item_from_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "field_id": str(row.get("field_id", "")).strip(),
            "label": str(row.get("label", "")).strip(),
            "packet_section": str(row.get("packet_section", "")).strip(),
            "packet_section_label": str(row.get("packet_section_label", "")).strip(),
            "requiredness": str(row.get("requiredness", "optional")).strip() or "optional",
            "planner_critical": bool(row.get("planner_critical", False)),
            "status": str(row.get("status", "unresolved")).strip().lower() or "unresolved",
            "value": row.get("value"),
            "confidence": row.get("confidence"),
            "preferred_sources": list(row.get("preferred_sources", [])) if isinstance(row.get("preferred_sources"), list) else [],
            "lookup_keys": list(row.get("lookup_keys", [])) if isinstance(row.get("lookup_keys"), list) else [],
        }

    for rows in rows_by_section.values():
        for row in rows:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status", "unresolved")).strip().lower() or "unresolved"
            planner_critical = bool(row.get("planner_critical", False))
            required = str(row.get("requiredness", "optional")).strip().lower() != "optional"
            item = _item_from_row(row)
            if required and status == "missing":
                buckets["required_missing"].append(item)
            if not planner_critical:
                continue
            if status == "review_required":
                buckets["planner_critical_review_required"].append(item)
            elif status == "conflicting":
                buckets["planner_critical_conflicting"].append(item)
            elif status == "missing":
                buckets["planner_critical_missing"].append(item)
            elif status == "unresolved":
                buckets["planner_critical_unresolved"].append(item)

    for key, items in buckets.items():
        buckets[key] = sorted(items, key=lambda item: (item.get("packet_section_label", ""), item.get("label", ""), item.get("field_id", "")))

    buckets["planner_critical_open_count"] = sum(len(buckets[key]) for key in (
        "planner_critical_review_required",
        "planner_critical_conflicting",
        "planner_critical_missing",
        "planner_critical_unresolved",
    ))
    buckets["required_missing_count"] = len(buckets["required_missing"])
    buckets["planner_critical_open_field_ids"] = [
        str(item.get("field_id", "")).strip()
        for key in (
            "planner_critical_review_required",
            "planner_critical_conflicting",
            "planner_critical_missing",
            "planner_critical_unresolved",
        )
        for item in buckets[key]
        if isinstance(item, dict) and str(item.get("field_id", "")).strip()
    ]
    resolution_queue = planner_registry_resolution_queue(
        canonical_state,
        validation_report,
        include_optional=include_optional,
        include_resolved=False,
    )
    buckets["resolution_queue"] = resolution_queue
    buckets["resolution_queue_count"] = len(resolution_queue)
    buckets["resolution_queue_field_ids"] = [
        str(item.get("field_id", "")).strip()
        for item in resolution_queue
        if isinstance(item, dict) and str(item.get("field_id", "")).strip()
    ]
    return buckets


def planner_registry_resolution_backlog(
    canonical_state: dict[str, Any] | None,
    validation_report: dict[str, Any] | None = None,
    *,
    include_optional: bool = False,
    queue_limit: int = 25,
) -> dict[str, Any]:
    open_items = planner_registry_open_items(
        canonical_state,
        validation_report,
        include_optional=include_optional,
    )
    queue = list(open_items.get("resolution_queue", [])) if isinstance(open_items.get("resolution_queue"), list) else []
    if queue_limit > 0:
        queue = queue[:queue_limit]
    return {
        "planner_registry_backed": True,
        "queue": queue,
        "queue_count": len(queue),
        "queue_field_ids": [
            str(item.get("field_id", "")).strip()
            for item in queue
            if isinstance(item, dict) and str(item.get("field_id", "")).strip()
        ],
        "planner_critical_open_count": int(open_items.get("planner_critical_open_count", 0)),
        "required_missing_count": int(open_items.get("required_missing_count", 0)),
        "planner_critical_open_field_ids": list(open_items.get("planner_critical_open_field_ids", [])),
        "open_items": open_items,
    }


def _value_for_field(payload: dict[str, Any] | None, field_path_or_id: str | None) -> Any:
    data = payload if isinstance(payload, dict) else {}
    field_id = registry_field_id_for_path(field_path_or_id)
    planner_field_values = data.get("planner_field_values") if isinstance(data.get("planner_field_values"), dict) else {}
    if field_id and field_id in planner_field_values:
        return planner_field_values.get(field_id)
    if isinstance(field_path_or_id, str) and field_path_or_id.strip() and field_path_or_id.strip() in planner_field_values:
        return planner_field_values.get(field_path_or_id.strip())
    keys = registry_lookup_keys(field_path_or_id)
    resolved_field = resolve_registry_field(field_path_or_id)
    if isinstance(resolved_field, dict):
        field_path = field_path_for_registry_field_id(str(resolved_field.get("field_id", "")).strip())
        if field_path:
            keys = [field_path, *keys]
    for key in keys:
        if not isinstance(key, str) or not key.strip():
            continue
        cursor: Any = data
        found = True
        for token in [part for part in key.split('.') if part]:
            if isinstance(cursor, dict) and token in cursor:
                cursor = cursor[token]
            else:
                found = False
                break
        if found:
            return cursor
    return None


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def build_normalization_runtime_schema_validation(payload: dict[str, Any] | None) -> dict[str, Any]:
    field_ids = normalization_required_field_ids()
    missing_fields: list[dict[str, Any]] = []
    resolved_count = 0
    for field_id in field_ids:
        value = _value_for_field(payload, field_id)
        if _is_missing_value(value):
            profile = build_followup_profile(field_id)
            missing_fields.append({
                'field_id': field_id,
                'field_path': profile.get('field_path', ''),
                'label': profile.get('label', ''),
                'planner_critical': bool(profile.get('planner_critical', False)),
                'requiredness': profile.get('requiredness', 'required'),
            })
        else:
            resolved_count += 1
    return {
        'schema_valid': not missing_fields,
        'planner_registry_backed': True,
        'registry_path': str(REGISTRY_PATH),
        'validation_mode': 'planner_required_fields.normalization_runtime',
        'required_field_count': len(field_ids),
        'resolved_required_field_count': resolved_count,
        'missing_required_field_count': len(missing_fields),
        'missing_required_fields': missing_fields,
        'errors': [
            f"Missing required normalization field: {item['field_id']}"
            for item in missing_fields
        ],
        'warnings': [],
    }


def build_translation_runtime_schema_validation(
    model_outputs: dict[str, Any] | None,
    output_parameters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    outputs = model_outputs if isinstance(model_outputs, dict) else {}
    parameters = output_parameters if isinstance(output_parameters, list) else []
    parameter_map = translation_parameter_map()
    configured_paths = sorted(parameter_map.keys())
    present_paths: list[str] = []
    missing_paths: list[str] = []
    parameter_records_by_path = {
        str(item.get('parameter_path', '')).strip(): item
        for item in parameters
        if isinstance(item, dict) and str(item.get('parameter_path', '')).strip()
    }
    for parameter_path in configured_paths:
        value = _value_for_field(outputs, parameter_path)
        if _is_missing_value(value) and parameter_path not in parameter_records_by_path:
            missing_paths.append(parameter_path)
        else:
            present_paths.append(parameter_path)
    return {
        'schema_valid': not missing_paths,
        'planner_registry_backed': True,
        'registry_path': str(REGISTRY_PATH),
        'validation_mode': 'planner_required_fields.translation_runtime',
        'configured_parameter_count': len(configured_paths),
        'present_parameter_count': len(present_paths),
        'missing_parameter_count': len(missing_paths),
        'missing_parameter_paths': missing_paths,
        'errors': [f'Missing translated parameter: {path}' for path in missing_paths],
        'warnings': [],
    }




def summarize_field_resolution_governance(
    canonical_state: dict[str, Any] | None,
    validation_report: dict[str, Any] | None = None,
    *,
    include_optional: bool = False,
) -> dict[str, Any]:
    rows_by_section = build_planner_packet_field_rows(
        canonical_state,
        validation_report,
        include_optional=include_optional,
    )
    field_resolution = {}
    state = canonical_state if isinstance(canonical_state, dict) else {}
    if isinstance(state.get("field_resolution"), dict):
        field_resolution = state.get("field_resolution")
    summary = field_resolution.get("summary") if isinstance(field_resolution.get("summary"), dict) else {}
    open_items = planner_registry_open_items(
        canonical_state,
        validation_report,
        include_optional=include_optional,
    )
    accepted_index = field_resolution.get("accepted_field_index") if isinstance(field_resolution.get("accepted_field_index"), dict) else {}

    accepted_count = 0
    review_required_count = 0
    conflicting_count = 0
    missing_count = 0
    unresolved_count = 0
    confirmation_needed_count = 0
    assumptions_count = 0
    inferred_count = 0
    value_kind_counts: dict[str, int] = {}
    attention_tier_counts: dict[str, int] = {}
    sections: list[dict[str, Any]] = []
    for section_id in planner_packet_sections():
        rows = rows_by_section.get(section_id, [])
        section_summary = {
            "section_id": section_id,
            "section_label": planner_packet_section_label(section_id),
            "field_count": len(rows),
            "accepted_count": 0,
            "review_required_count": 0,
            "conflicting_count": 0,
            "missing_count": 0,
            "unresolved_count": 0,
            "confirmation_needed_count": 0,
            "value_kind_counts": {},
            "attention_tier_counts": {},
        }
        for row in rows:
            status = str(row.get("status", "unresolved")).strip().lower() or "unresolved"
            if status not in {"missing", "unresolved"}:
                accepted_count += 1
                section_summary["accepted_count"] += 1
            if status == "review_required":
                review_required_count += 1
                section_summary["review_required_count"] += 1
            elif status == "conflicting":
                conflicting_count += 1
                section_summary["conflicting_count"] += 1
            elif status == "missing":
                missing_count += 1
                section_summary["missing_count"] += 1
            elif status == "unresolved":
                unresolved_count += 1
                section_summary["unresolved_count"] += 1
            if bool(row.get("needs_applicant_confirmation", False)):
                confirmation_needed_count += 1
                section_summary["confirmation_needed_count"] += 1
            value_kind = str(row.get("accepted_value_kind", "")).strip().lower()
            if value_kind:
                value_kind_counts[value_kind] = value_kind_counts.get(value_kind, 0) + 1
                section_value_kind_counts = section_summary.get("value_kind_counts")
                if isinstance(section_value_kind_counts, dict):
                    section_value_kind_counts[value_kind] = section_value_kind_counts.get(value_kind, 0) + 1
            attention_tier = str(row.get("planner_attention_tier", "")).strip().lower()
            if attention_tier:
                attention_tier_counts[attention_tier] = attention_tier_counts.get(attention_tier, 0) + 1
                section_attention_tier_counts = section_summary.get("attention_tier_counts")
                if isinstance(section_attention_tier_counts, dict):
                    section_attention_tier_counts[attention_tier] = section_attention_tier_counts.get(attention_tier, 0) + 1
            provenance = str(row.get("provenance_type", "")).strip().lower()
            if provenance == "assumption" or value_kind == "assumption":
                assumptions_count += 1
            elif provenance in {"evidence_backed_inference", "inference", "retrieved_reference"} or value_kind == "inferred":
                inferred_count += 1
        sections.append(section_summary)

    planner_review_count = int(open_items.get("planner_critical_open_count", 0))
    top_backlog_field_ids = list(open_items.get("resolution_queue_field_ids", []))[:10]
    return {
        "planner_registry_backed": True,
        "registry_path": str(REGISTRY_PATH),
        "accepted_planner_field_count": int(summary.get("accepted_field_index_count", accepted_count or len(accepted_index))),
        "applicant_confirmation_needed_count": int(summary.get("applicant_confirmation_needed_count", confirmation_needed_count)),
        "planner_review_count": int(summary.get("planner_review_count", planner_review_count)),
        "review_required_count": int(summary.get("review_required_count", review_required_count)),
        "conflicting_count": int(summary.get("conflicting_count", conflicting_count)),
        "missing_count": int(summary.get("missing_count", missing_count)),
        "unresolved_count": unresolved_count,
        "assumed_count": assumptions_count,
        "evidence_backed_inferred_count": inferred_count,
        "resolution_queue_count": int(open_items.get("resolution_queue_count", 0)),
        "resolution_queue_field_ids": list(open_items.get("resolution_queue_field_ids", [])),
        "top_backlog_field_ids": top_backlog_field_ids,
        "value_kind_counts": value_kind_counts,
        "attention_tier_counts": attention_tier_counts,
        "sections": sections,
    }

def field_resolution_family_policies() -> dict[str, dict[str, Any]]:
    payload = load_planner_registry()
    metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    policies = metadata.get("field_resolution_family_policies")
    if isinstance(policies, dict) and policies:
        merged: dict[str, dict[str, Any]] = {}
        for family, default in _DEFAULT_FIELD_RESOLUTION_FAMILY_POLICIES.items():
            override = policies.get(family, {}) if isinstance(policies.get(family), dict) else {}
            merged[family] = {**default, **override}
        for family, override in policies.items():
            if family not in merged and isinstance(override, dict):
                merged[str(family).strip().lower()] = dict(override)
        return merged
    return {family: dict(config) for family, config in _DEFAULT_FIELD_RESOLUTION_FAMILY_POLICIES.items()}


def field_resolution_policy_for_family(family: str) -> dict[str, Any]:
    key = str(family).strip().lower()
    return dict(field_resolution_family_policies().get(key, {}))





def field_resolution_field_type(field_family: str, field_id: str | None, field_path: str | None) -> str:
    blob = " ".join([str(field_family or "").strip().lower(), str(field_id or "").strip().lower(), str(field_path or "").strip().lower()])
    if any(token in blob for token in {"manufacturer", "model", "model_family", "unit_count", "equipment_name", "equipment_tag"}):
        return "identity"
    if any(token in blob for token in {"rating_basis", "prime_or_standby", "standby", "prime"}):
        return "rating_basis"
    if any(token in blob for token in {"voltage", "_kv", "_v", "poi"}):
        return "voltage"
    if any(token in blob for token in {"mva", "kw_per_unit", "capacity", "peak_demand", "nameplate", "rated_kw"}):
        return "capacity"
    if "runtime" in blob:
        return "runtime"
    if any(token in blob for token in {"topology", "bus", "breaker", "switchgear", "one_line", "configuration"}):
        return "topology"
    if any(token in blob for token in {"relay", "protection", "trip", "fault", "settings"}):
        return "protection"
    if any(token in blob for token in {"scada", "telemetry", "meter", "metering"}):
        return "telemetry"
    if "ramp" in blob:
        return "ramp"
    return "general"




def field_resolution_source_stream_profile(field_family: str, field_id: str = "", field_path: str = "") -> dict[str, int]:
    family = (field_family or "").strip().lower()
    profile = dict(_DEFAULT_SOURCE_STREAM_POLICY.get("general", {}))
    profile.update(_DEFAULT_SOURCE_STREAM_POLICY.get(family, {}))
    blob = f"{field_id} {field_path}".lower()
    if any(token in blob for token in ["poi", "interconnection", "service_voltage", "point_of_interconnection"]):
        profile["official_web"] = profile.get("official_web", 0) + 4
    if any(token in blob for token in ["runtime", "mva", "capacity", "rating"]):
        profile["vendor_pdf"] = profile.get("vendor_pdf", 0) + 2
        profile["knowledge_library"] = profile.get("knowledge_library", 0) + 2
    return profile
def field_resolution_scoring_profile(field_family: str, field_id: str | None, field_path: str | None) -> dict[str, Any]:
    policy = field_resolution_policy_for_family(field_family)
    field_type = field_resolution_field_type(field_family, field_id, field_path)
    boosts = policy.get("field_type_hierarchy_boosts", {}) if isinstance(policy.get("field_type_hierarchy_boosts"), dict) else {}
    penalties = policy.get("field_type_hierarchy_penalties", {}) if isinstance(policy.get("field_type_hierarchy_penalties"), dict) else {}
    return {
        "field_type": field_type,
        "source_hierarchy_boosts": dict(boosts.get(field_type, {})) if isinstance(boosts.get(field_type), dict) else {},
        "source_hierarchy_penalties": dict(penalties.get(field_type, {})) if isinstance(penalties.get(field_type), dict) else {},
    }
def build_inputs_schema_from_registry() -> dict[str, Any]:
    """Return the derived intake/normalized-input schema backed by planner_required_fields."""
    schema_path = REGISTRY_PATH.parent / "gridsenpai_inputs_schema.json"
    if schema_path.exists():
        return json.loads(schema_path.read_text())
    return {}


def build_outputs_schema_from_registry() -> dict[str, Any]:
    """Return the derived planner-output schema backed by planner_required_fields."""
    schema_path = REGISTRY_PATH.parent / "gridsenpai_outputs_schema.json"
    if schema_path.exists():
        return json.loads(schema_path.read_text())
    return {}




def build_canonical_schema_from_registry() -> dict[str, Any]:
    """Return the derived canonical facility support schema backed by planner_required_fields."""
    schema_path = REGISTRY_PATH.parent / "gridsenpai_canonical_facility_model.json"
    if schema_path.exists():
        return json.loads(schema_path.read_text())
    return {}


def planner_legacy_artifact_manifest() -> dict[str, Any]:
    payload = load_planner_registry()
    candidates = payload.get("candidate_repo_files_to_deprecate_after_migration")
    candidate_paths = [
        str(item).strip()
        for item in (candidates if isinstance(candidates, list) else [])
        if str(item).strip()
    ]
    deleted_legacy_artifacts = [
        "shared/schemas/master_QA_intake_schema.json",
        "shared/schemas/planner_documents_required.json",
        "shared/schemas/master_extraction_blueprint.json",
    ]
    still_supported = [
        "shared/schemas/gridsenpai_inputs_schema.json",
        "shared/schemas/gridsenpai_outputs_schema.json",
        "shared/schemas/gridsenpai_canonical_facility_model.json",
        "shared/field_paths.py",
    ]
    deferred_cleanup = sorted(path for path in candidate_paths if path not in deleted_legacy_artifacts)
    return {
        "planner_registry_backed": True,
        "registry_path": str(REGISTRY_PATH),
        "candidate_repo_files_to_deprecate_after_migration": candidate_paths,
        "safe_to_delete_now": [],
        "deleted_legacy_artifacts": deleted_legacy_artifacts,
        "inactive_legacy_fallback_artifacts": deleted_legacy_artifacts,
        "deferred_cleanup_candidates": deferred_cleanup,
        "still_supported_derived_or_runtime_artifacts": still_supported,
    }

def planner_schema_alignment_summary() -> dict[str, Any]:
    registry = load_planner_registry()
    fields = planner_registry_fields()
    field_ids = sorted({str(item.get("field_id", "")).strip() for item in fields if str(item.get("field_id", "")).strip()})
    inputs_schema = build_inputs_schema_from_registry()
    outputs_schema = build_outputs_schema_from_registry()
    input_field_ids = sorted({
        str(key).strip()
        for key in ((inputs_schema.get("properties", {}) or {}).get("field_values", {}) or {}).get("properties", {}).keys()
        if str(key).strip()
    })
    output_field_ids = sorted({
        str(key).strip()
        for key in ((outputs_schema.get("properties", {}) or {}).get("accepted_field_values", {}) or {}).get("properties", {}).keys()
        if str(key).strip()
    })
    registry_only_inputs = sorted(set(field_ids) - set(input_field_ids))
    registry_only_outputs = sorted(set(field_ids) - set(output_field_ids))
    canonical_schema = build_canonical_schema_from_registry()
    canonical_registry_count = int(((canonical_schema.get("authoritative_source_contract") or {}).get("registry_field_count") or 0)) if isinstance(canonical_schema, dict) else 0
    canonical_aligned = canonical_registry_count == len(field_ids) if canonical_registry_count else False
    return {
        "planner_required_fields_version": str(registry.get("schema_version", "")).strip(),
        "registry_field_count": len(field_ids),
        "input_schema_field_count": len(input_field_ids),
        "output_schema_field_count": len(output_field_ids),
        "canonical_schema_field_count": canonical_registry_count,
        "input_schema_aligned": field_ids == input_field_ids,
        "output_schema_aligned": field_ids == output_field_ids,
        "canonical_schema_aligned": canonical_aligned,
        "missing_from_input_schema": registry_only_inputs,
        "missing_from_output_schema": registry_only_outputs,
        "input_schema_path": str(REGISTRY_PATH.parent / "gridsenpai_inputs_schema.json"),
        "output_schema_path": str(REGISTRY_PATH.parent / "gridsenpai_outputs_schema.json"),
        "canonical_schema_path": str(REGISTRY_PATH.parent / "gridsenpai_canonical_facility_model.json"),
        "legacy_artifact_manifest": planner_legacy_artifact_manifest(),
    }
