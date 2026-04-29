from __future__ import annotations

from functools import lru_cache
from typing import Any

from shared.planner_registry import planner_document_specs, planner_fields_for_group

FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "generators": ("generator", "generators", "genset", "diesel", "standby power"),
    "ups": ("ups", "uninterruptible power supply", "ride-through", "battery"),
    "transformers": ("transformer", "transformers", "xfmr"),
    "switchgear": ("switchgear", "switch gear", "breaker", "bus"),
    "relays": ("relay", "protective relay", "protection"),
    "cooling_systems": ("cooling", "chiller", "pump", "fan", "motor"),
}

FAMILY_TO_REGISTRY_GROUP: dict[str, str] = {
    "generators": "generator_system",
    "ups": "ups_and_power_electronics",
    "transformers": "transformers_and_switchgear",
    "switchgear": "transformers_and_switchgear",
    "relays": "protection_controls_and_relaying",
    "cooling_systems": "mechanical_and_cooling_loads",
}

LEGACY_FAMILY_PRIORITY_FIELDS: dict[str, tuple[str, ...]] = {
    "generators": (
        "facility.generators.rated_power_kw",
        "facility.generators.rated_power_kva",
        "facility.generators.voltage_v",
        "facility.generators.frequency_hz",
        "facility.generators.power_factor",
        "facility.generators.standby_or_prime_rating",
        "facility.generators.startup_delay_seconds",
        "facility.generators.step_load_acceptance_percent",
        "facility.generators.synchronization_behavior",
        "facility.generators.loading_sequence",
        "facility.generators.breaker_configuration",
        "facility.generators.transfer_or_islanding_mode",
    ),
    "ups": (
        "facility.ups.rated_power_kw",
        "facility.ups.rated_power_kva",
        "facility.ups.voltage_v",
        "facility.ups.frequency_hz",
        "facility.ups.transfer_time_ms",
        "facility.ups.ups_operating_mode",
        "facility.ups.ups_can_condition_power",
        "facility.ups.power_electronic_load_description",
    ),
    "transformers": (
        "facility.transformers.rated_capacity_kva",
        "facility.transformers.primary_voltage_v",
        "facility.transformers.secondary_voltage_v",
        "facility.transformers.impedance_percent",
        "facility.transformers.cooling_class",
        "facility.transformers.winding_configuration",
        "facility.transformers.tap_range_percent",
    ),
    "switchgear": (
        "facility.switchgear.voltage_v",
        "facility.switchgear.current_a",
        "facility.switchgear.short_circuit_rating_ka",
        "facility.switchgear.breaker_configuration",
        "facility.switchgear.arc_flash_mitigation_present",
    ),
    "relays": (
        "facility.relays.relay_family",
        "facility.relays.protection_functions",
        "facility.relays.communications_protocol",
    ),
}

ALLOWED_RETRIEVAL_TOUCHPOINTS: frozenset[str] = frozenset(
    {
        "internal_knowledge_retrieval",
        "vendor_pdf_retrieval",
        "official_web_retrieval",
        "field_resolution",
        "applicant_interview",
        "planner_packet_export",
    }
)

ALLOWED_DATA_TYPES: frozenset[str] = frozenset({"string", "integer", "number", "boolean", "enum"})


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


@lru_cache(maxsize=1)
def _registry_family_fields() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {family: [] for family in FAMILY_KEYWORDS}
    for family, group_name in FAMILY_TO_REGISTRY_GROUP.items():
        ordered: list[str] = []
        for item in planner_fields_for_group(group_name):
            if not isinstance(item, dict):
                continue
            field_id = str(item.get("field_id", "")).strip()
            if not field_id:
                continue
            data_type = str(item.get("data_type", "")).strip().lower()
            if data_type and data_type not in ALLOWED_DATA_TYPES:
                continue
            touchpoints = {
                str(value).strip()
                for value in item.get("pipeline_touchpoints", [])
                if isinstance(value, str) and str(value).strip()
            }
            if not touchpoints.intersection(ALLOWED_RETRIEVAL_TOUCHPOINTS):
                continue
            preferred_sources_blob = " ".join(
                str(value).strip().lower()
                for value in item.get("preferred_sources", [])
                if isinstance(value, str) and str(value).strip()
            )
            if family in {"generators", "ups", "transformers", "switchgear", "relays"}:
                if not any(token in preferred_sources_blob for token in ("manufacturer", "vendor", "datasheet", "spec", "catalog", "validated_applicant_answer")):
                    continue
            ordered.append(field_id)
        # Preserve older runtime-first ordering for fields the rest of the system already knows.
        for legacy_field in LEGACY_FAMILY_PRIORITY_FIELDS.get(family, ()):
            if legacy_field not in ordered:
                ordered.insert(0, legacy_field)
        deduped: list[str] = []
        seen: set[str] = set()
        for field in ordered:
            if field in seen:
                continue
            seen.add(field)
            deduped.append(field)
        result[family] = deduped
    return result


@lru_cache(maxsize=1)
def planner_document_field_map() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {family: [] for family in FAMILY_KEYWORDS}
    for document in planner_document_specs():
        if not isinstance(document, dict):
            continue
        description = " ".join(
            [
                str(document.get("document_name", "")),
                str(document.get("description", "")),
                " ".join(str(item) for item in document.get("used_for", []) if isinstance(item, str)),
                " ".join(str(item) for item in document.get("data_fields_provided", []) if isinstance(item, str)),
            ]
        ).lower()
        fields = [
            str(item).strip()
            for item in document.get("data_fields_provided", [])
            if isinstance(item, str) and str(item).strip()
        ]
        for family, keywords in FAMILY_KEYWORDS.items():
            family_group = FAMILY_TO_REGISTRY_GROUP.get(family, "")
            if any(keyword in description for keyword in keywords) or any(
                field.startswith(family[:-1] + "_") or field.startswith(family_group[:-1] if family_group else "")
                for field in fields
            ):
                for field in fields:
                    if field not in result[family]:
                        result[family].append(field)
    return result


@lru_cache(maxsize=1)
def canonical_input_schema_fields() -> dict[str, list[str]]:
    return _registry_family_fields()


def infer_relevant_families(*, missing_fields: list[str], observed_families: list[str]) -> list[str]:
    route: list[str] = []
    for family in observed_families:
        cleaned = _normalize(family)
        if cleaned in FAMILY_KEYWORDS and cleaned not in route:
            route.append(cleaned)

    tokenized_fields = [set(_normalize(field).replace('.', ' ').replace('_', ' ').split()) for field in missing_fields]
    for family, keywords in FAMILY_KEYWORDS.items():
        if family in route:
            continue
        family_tokens = set(family.replace('_', ' ').split())
        singular_tokens = {token[:-1] if token.endswith('s') else token for token in family_tokens}
        for field_tokens in tokenized_fields:
            if family_tokens & field_tokens or singular_tokens & field_tokens:
                route.append(family)
                break
            if any(set(_normalize(keyword).split()) <= field_tokens for keyword in keywords):
                route.append(family)
                break
    return route


def _is_vendor_resolvable_field(field_name: Any, family: str) -> bool:
    cleaned = str(field_name or "").strip()
    if not cleaned:
        return False
    known_fields = canonical_input_schema_fields().get(family, [])
    if cleaned in known_fields:
        return True
    suffix = cleaned.split(".")[-1].lower()
    registry_suffixes = {field.split(".")[-1].lower() for field in known_fields}
    return suffix in registry_suffixes


def target_fields_for_families(
    *,
    families: list[str],
    requested_missing_fields: list[str],
    family_record_fields: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    family_record_fields = family_record_fields or {}
    planner_doc_map = planner_document_field_map()
    input_map = canonical_input_schema_fields()

    target_fields: list[str] = []
    family_targets: dict[str, list[str]] = {}
    vendor_resolvable_requested_fields: list[str] = []
    out_of_scope_requested_fields: list[str] = []

    for field in requested_missing_fields:
        cleaned = str(field).strip()
        if not cleaned:
            continue
        if any(_is_vendor_resolvable_field(cleaned, family) for family in families):
            if cleaned not in vendor_resolvable_requested_fields:
                vendor_resolvable_requested_fields.append(cleaned)
        elif cleaned not in out_of_scope_requested_fields:
            out_of_scope_requested_fields.append(cleaned)

    for family in families:
        ordered: list[str] = []
        candidate_sources = (
            vendor_resolvable_requested_fields,
            input_map.get(family, []),
            planner_doc_map.get(family, []),
            family_record_fields.get(family, []),
        )
        for source in candidate_sources:
            for field in source:
                cleaned = str(field).strip()
                if not cleaned:
                    continue
                if source is not family_record_fields.get(family, []) and not _is_vendor_resolvable_field(cleaned, family):
                    continue
                if cleaned not in ordered:
                    ordered.append(cleaned)
        family_targets[family] = ordered
        for field in ordered:
            if field not in target_fields:
                target_fields.append(field)

    return {
        "families": list(families),
        "target_fields": target_fields,
        "family_targets": family_targets,
        "vendor_resolvable_requested_fields": vendor_resolvable_requested_fields,
        "out_of_scope_requested_fields": out_of_scope_requested_fields,
        "sources": {
            "planner_documents": "shared/schemas/planner_required_fields.json#planner_documents",
            "planner_registry_groups": {
                family: FAMILY_TO_REGISTRY_GROUP.get(family, "")
                for family in families
            },
        },
    }
