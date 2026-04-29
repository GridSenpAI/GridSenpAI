from __future__ import annotations

from typing import Dict, Set

from shared.planner_registry import worker_routing_table

FIELD_ALIASES: Dict[str, str] = {
    "facility.transformer_count": "facility.transformers.count",
    "facility.transformer_ratings": "facility.transformers.ratings_mva",
    "facility.generator_count": "facility.generators.count",
    "facility.generator_ratings": "facility.generators.ratings",
    "facility.ups_count": "facility.ups.count",
    "facility.ups_topology": "facility.ups.topology",
    "facility.substation_configuration": "facility.substation.configuration",
    "facility.motor_schedule": "facility.motor_schedule",
    "facility.relay_settings": "facility.relay_settings",
    "facility.equipment_schedule": "facility.equipment_schedule",
    "facility.dynamic_model_available": "facility.modeling.dynamic_model_available",
    "facility.pscad_model_package": "facility.modeling.pscad_model_package",
}

_ROUTING = worker_routing_table()
DRAWING_FIELDS: Set[str] = set(_ROUTING.get("drawing_worker", ()))
TABLE_FIELDS: Set[str] = set(_ROUTING.get("table_worker", ()))
SPEC_FIELDS: Set[str] = set(_ROUTING.get("spec_worker", ()))
RETRIEVAL_FIELDS: Set[str] = set(_ROUTING.get("retrieval_worker", ()))


def normalize_field_path(field_path: str) -> str:
    return FIELD_ALIASES.get(field_path, field_path)


def determine_worker(field_path: str) -> str:
    normalized_field_path = normalize_field_path(field_path)

    if normalized_field_path in DRAWING_FIELDS:
        return "drawing_worker"

    if normalized_field_path in TABLE_FIELDS:
        return "table_worker"

    if normalized_field_path in SPEC_FIELDS:
        return "spec_worker"

    if normalized_field_path in RETRIEVAL_FIELDS:
        return "retrieval_worker"

    return "interview_worker"
