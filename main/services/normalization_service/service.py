# services/normalization_service/service.py

from __future__ import annotations

from typing import Any

from services.normalization_service.models import (
    ConflictRecord,
    FieldUpdateRecord,
    NormalizationServiceResult,
)
from services.normalization_service.utils import (
    build_followup_question,
    get_nested_value,
    safe_bool,
    safe_float,
    safe_int,
    set_nested_value,
    utc_now_iso,
)
from shared.field_value_policies import (
    candidate_is_rejected_for_field,
    normalization_authority_score,
    source_role_from_candidate,
)
from shared.planner_candidate_ledger import (
    build_registry_candidate_ledger,
    build_registry_extraction_worklist,
)
from shared.value_quality import contamination_reasons
from shared.planner_registry import (
    build_followup_profile,
    build_normalization_runtime_schema_validation,
    build_normalization_seed_payload,
    field_data_type_for_path,
    field_path_for_registry_field_id,
    field_group_for_path,
    field_label_for_path,
    field_minimum_confidence_for_auto_accept,
    field_requiredness_for_path,
    normalization_required_field_ids,
    planner_critical_for_path,
    registry_field_id_for_path,
    registry_lookup_keys,
)


NORMALIZATION_FIELD_ALIASES: dict[str, str] = {
    "facility.poi_voltage_kv": "facility.poi_voltage_kv",
    "facility.load_schedule.phase_1_mw": "facility.load_schedule.phase_1_mw",
    "facility.load_schedule.phase_2_mw": "facility.load_schedule.phase_2_mw",
    "facility.load_schedule.phase_3_mw": "facility.load_schedule.phase_3_mw",
    "facility.ups.topology": "facility.ups.topology",
    "facility.ups.count": "facility.ups.count",
    "facility.generators.count": "facility.generators.count",
    "facility.transformers.count": "facility.transformers.count",
    "facility.transformers.ratings_mva": "facility.transformers.ratings_mva",
    "ups_unit_count": "facility.ups.count",
    "ups_topology": "facility.ups.topology",
    "generator_unit_count": "facility.generators.count",
    "interconnection_transformer_unit_count": "facility.transformers.count",
    "switchgear_unit_count": "facility.switchgear.count",
    "switchgear_bus_rating_amps": "facility.switchgear.bus_rating_amps",
    "switchgear_interrupting_rating_ka": "facility.switchgear.interrupting_rating_ka",
    "project_name": "facility.project_name",
    "project_number": "facility.project_number",
    "load_customer_name": "facility.owner",
    "requested_in_service_date": "facility.requested_in_service_date",
    "ultimate_commercial_operation_date": "facility.ultimate_commercial_operation_date",
    "point_of_interconnection_name": "facility.point_of_interconnection",
    "nominal_poi_voltage_kv": "facility.poi_voltage_kv",
    "facility_nominal_medium_voltage_kv": "facility.electrical_configuration.internal_voltage_levels",
    "peak_demand_mw": "facility.load_schedule.phase_3_mw",
    "accepted_peak_demand_mw": "facility.load_schedule.phase_3_mw",
    "maximum_coincident_demand_mw": "facility.load_schedule.phase_3_mw",
    "ultimate_demand_mw": "facility.load_schedule.phase_3_mw",
    "critical_it_load_mw": "facility.load_schedule.critical_it_mw",
    "interconnection_transformer_rating_mva": "facility.transformers.ratings_mva",
    "service_transformer_rating_summary": "facility.transformers.rating_summary",
    "switchgear_model_family": "facility.switchgear.model_family",
    "switchgear_manufacturer": "facility.switchgear.manufacturer",
    "ups_model_family": "facility.ups.model_family",
    "ups_capacity_kw_per_unit": "facility.ups.capacity_kw_per_unit",
    "ups_output_voltage_kv_or_v": "facility.ups.output_voltage_v",
    "generator_model_family": "facility.generators.model_family",
    "generator_rated_kw_per_unit": "facility.generators.rated_kw_per_unit",
    "generator_terminal_voltage_kv": "facility.generators.terminal_voltage_kv",
    "capacitor_bank_step_count": "facility.reactive_compensation.capacitor_bank_step_count",
    "capacitor_bank_step_size_mvar": "facility.reactive_compensation.capacitor_bank_step_size_mvar",
    "buildout_phases_summary": "facility.load_schedule.buildout_phases_summary",
    "maximum_daily_weekly_monthly_ramp_summary": "facility.load_schedule.ramp_summary",
    "interconnection_configuration": "facility.interconnection_configuration",
    "point_of_interconnection_voltage_kv": "facility.poi_voltage_kv",
    "distribution_voltage_levels": "facility.electrical_configuration.internal_voltage_levels",
    "equipment_schedule_present": "facility.equipment_schedule.present",
    "reactive_compensation_summary": "facility.reactive_compensation.summary",
    "requested_peak_load_mw": "facility.load_schedule.phase_3_mw",
    "ultimate_load_mw": "facility.load_schedule.phase_3_mw",
    "phase_1_load_mw": "facility.load_schedule.phase_1_mw",
    "phase_2_load_mw": "facility.load_schedule.phase_2_mw",
    "phase_3_load_mw": "facility.load_schedule.phase_3_mw",
}


def _planner_field_values(normalized: dict[str, Any]) -> dict[str, Any]:
    values = normalized.get("planner_field_values")
    if not isinstance(values, dict):
        values = {}
        normalized["planner_field_values"] = values
    return values


def _planner_field_sources(normalized: dict[str, Any]) -> dict[str, Any]:
    values = normalized.get("planner_field_sources")
    if not isinstance(values, dict):
        values = {}
        normalized["planner_field_sources"] = values
    return values


def _normalization_alias_field_path(field_path_or_id: str | None) -> str:
    value = str(field_path_or_id or "").strip()
    if not value:
        return ""
    if value in NORMALIZATION_FIELD_ALIASES:
        return NORMALIZATION_FIELD_ALIASES[value]
    registry_field_id = registry_field_id_for_path(value)
    if registry_field_id and registry_field_id in NORMALIZATION_FIELD_ALIASES:
        return NORMALIZATION_FIELD_ALIASES[registry_field_id]
    mapped_path = field_path_for_registry_field_id(registry_field_id or value)
    if isinstance(mapped_path, str) and mapped_path.strip():
        return mapped_path.strip()
    if "." in value:
        return value
    return ""


def _record_planner_field_value(
    normalized: dict[str, Any],
    *,
    field_path_or_id: str,
    accepted_value: Any,
    source_type: str,
    source_name: str = "",
    source_anchor_id: str = "",
    confidence: str = "",
) -> None:
    field_id = registry_field_id_for_path(field_path_or_id) or str(field_path_or_id or "").strip()
    if not field_id:
        return
    _planner_field_values(normalized)[field_id] = accepted_value
    _planner_field_sources(normalized)[field_id] = {
        "field_id": field_id,
        "field_path": _normalization_alias_field_path(field_path_or_id),
        "source_type": source_type,
        "source_name": source_name,
        "source_anchor_id": source_anchor_id,
        "confidence": confidence,
    }


def _initialize_facility_schema(context: Any) -> dict[str, Any]:
    payload = build_normalization_seed_payload()
    payload["run_id"] = context.run_id
    payload["schema_version"] = context.config.schema_version_input
    payload["source_summary"] = {
        "entity_count": 0,
        "topology_cue_count": 0,
        "evidence_snippet_count": 0,
        "confirmed_interview_count": 0,
        "clarification_count": 0,
        "canonical_field_count": 0,
        "calibration_dataset_count": 0,
        "planner_field_value_count": 0,
    }
    facility = payload.get("facility")
    if not isinstance(facility, dict):
        facility = {}
        payload["facility"] = facility
    facility.setdefault("frequency_hz", 60)
    facility.setdefault("switchgear", {})
    payload.setdefault("planner_field_values", {})
    payload.setdefault("planner_field_sources", {})
    payload.setdefault("planner_field_groups", {})
    payload["planner_extraction_worklist"] = build_registry_extraction_worklist(include_optional=True)
    payload["planner_extraction_worklist_summary"] = {
        "registry_field_count": len(payload["planner_extraction_worklist"]),
        "source": "shared/schemas/planner_required_fields.json",
        "registry_first_bridge": True,
    }
    return payload


def _coerce_registry_typed_value(field_path: str, candidate_value: Any) -> Any:
    data_type = field_data_type_for_path(field_path)
    lowered_path = str(field_path or "").strip().lower()

    if candidate_value is None:
        return None

    if data_type in {"float", "number", "decimal"} or lowered_path.endswith(("_mw", "_mvar", "_mva", "_kv", "_v", "_a", "_pf", "_pu")):
        return safe_float(str(candidate_value).replace(",", ""))

    if data_type in {"integer", "int", "count"} or lowered_path.endswith(("_count", ".count")):
        return safe_int(str(candidate_value).replace(",", ""))

    if data_type in {"boolean", "bool"} or lowered_path.endswith((".present", "_present")):
        return safe_bool(candidate_value)

    if data_type in {"array", "list"}:
        if isinstance(candidate_value, list):
            return list(candidate_value)
        if isinstance(candidate_value, tuple):
            return list(candidate_value)
        return [candidate_value]

    if data_type in {"object", "mapping", "dict"}:
        return candidate_value if isinstance(candidate_value, dict) else None

    if data_type in {"text", "string", "enum", "date"}:
        if isinstance(candidate_value, str):
            cleaned = candidate_value.strip()
            return cleaned or None
        return str(candidate_value)

    if lowered_path.endswith(("frequency_hz", ".frequency_hz")):
        return safe_int(str(candidate_value).replace(",", ""))

    if isinstance(candidate_value, str):
        cleaned = candidate_value.strip()
        return cleaned or None
    return candidate_value


def _normalize_candidate_value(field_path: str, candidate_value: Any) -> Any:
    normalized = _coerce_registry_typed_value(field_path, candidate_value)

    if field_path == "facility.ups.topology" and isinstance(normalized, str):
        return normalized.strip() or None

    if field_path == "facility.project_name" and isinstance(normalized, str):
        return normalized.strip() or None

    return normalized


def _normalize_unit(unit: Any) -> str:
    if unit is None:
        return ""
    normalized = str(unit).strip().lower()
    mapping = {
        "mw": "MW",
        "kw": "kW",
        "mva": "MVA",
        "kva": "kVA",
        "kv": "kV",
        "v": "V",
        "a": "A",
        "amp": "A",
        "amps": "A",
        "hz": "Hz",
        "%": "%",
        "pu": "pu",
        "ohm": "ohm",
    }
    return mapping.get(normalized, str(unit).strip())


def _convert_numeric_value(value: float, from_unit: str, to_unit: str) -> float:
    source = from_unit.strip().lower()
    target = to_unit.strip().lower()

    if not source or not target or source == target:
        return value

    conversion_table: dict[tuple[str, str], float] = {
        ("kw", "mw"): 0.001,
        ("mw", "kw"): 1000.0,
        ("kva", "mva"): 0.001,
        ("mva", "kva"): 1000.0,
        ("v", "kv"): 0.001,
        ("kv", "v"): 1000.0,
    }

    factor = conversion_table.get((source, target))
    if factor is None:
        return value
    return value * factor


def _normalize_calibration_parameter(item: dict[str, Any]) -> dict[str, Any]:
    field_path = str(item.get("field_path", "")).strip()
    value = item.get("value")
    units = _normalize_unit(item.get("units"))
    target_units = _normalize_unit(item.get("target_units") or units)

    numeric_value = safe_float(value)
    normalized_value: Any = value
    if numeric_value is not None and units and target_units:
        normalized_value = round(
            _convert_numeric_value(numeric_value, units, target_units),
            6,
        )

    metadata = item.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    source_ref = item.get("source_ref", [])
    if not isinstance(source_ref, list):
        source_ref = []

    return {
        "field_path": field_path,
        "value": value,
        "normalized_value": normalized_value,
        "units": units,
        "target_units": target_units,
        "source_ref": source_ref,
        "metadata": metadata,
    }


def _extract_candidate_calibration_datasets(
    extraction_result: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    direct_payload = extraction_result.get("calibration_datasets", [])
    if isinstance(direct_payload, list):
        candidates.extend(item for item in direct_payload if isinstance(item, dict))

    nested_ingestion_payload = extraction_result.get("ingestion_result", {})
    if isinstance(nested_ingestion_payload, dict):
        ingestion_candidates = nested_ingestion_payload.get("calibration_datasets", [])
        if isinstance(ingestion_candidates, list):
            candidates.extend(item for item in ingestion_candidates if isinstance(item, dict))

    return candidates


def _normalize_calibration_datasets(
    extraction_result: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = _extract_candidate_calibration_datasets(extraction_result)
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for item in candidates:
        dataset_id = str(item.get("dataset_id", "")).strip()
        if not dataset_id or dataset_id in seen_ids:
            continue
        seen_ids.add(dataset_id)

        parameters = item.get("parameters", [])
        if not isinstance(parameters, list):
            parameters = []

        normalized_parameters = [
            _normalize_calibration_parameter(parameter)
            for parameter in parameters
            if isinstance(parameter, dict) and str(parameter.get("field_path", "")).strip()
        ]

        provenance = item.get("provenance", {})
        if not isinstance(provenance, dict):
            provenance = {}

        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        metadata.setdefault("normalization_stage", "normalization")
        metadata.setdefault("parameter_count", len(normalized_parameters))

        normalized.append(
            {
                "dataset_id": dataset_id,
                "dataset_type": str(item.get("dataset_type", "ENGINEERING_REFERENCE")).strip()
                or "ENGINEERING_REFERENCE",
                "version": str(item.get("version", "1.0.0")).strip() or "1.0.0",
                "source_artifact_id": str(item.get("source_artifact_id", "")).strip(),
                "source_file_name": str(item.get("source_file_name", "")).strip(),
                "provenance": provenance,
                "parameters": normalized_parameters,
                "metadata": metadata,
            }
        )

    return normalized


def _make_conflict(
    *,
    field_path: str,
    existing_value: Any,
    candidate_value: Any,
    source_type: str,
    reason: str,
    entity_id: str = "",
    source_anchor_id: str = "",
    source_name: str = "",
    question_id: str = "",
    cue_type: str = "",
    artifact_id: str = "",
) -> ConflictRecord:
    return ConflictRecord(
        field_path=field_path,
        existing_value=existing_value,
        candidate_value=candidate_value,
        source_type=source_type,
        reason=reason,
        entity_id=entity_id,
        source_anchor_id=source_anchor_id,
        source_name=source_name,
        question_id=question_id,
        cue_type=cue_type,
        artifact_id=artifact_id,
    )




def _is_normalization_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False

def _apply_scalar_update(
    normalized: dict[str, Any],
    *,
    field_path: str,
    candidate_value: Any,
    source_type: str,
    accepted_updates: list[FieldUpdateRecord],
    rejected_updates: list[FieldUpdateRecord],
    conflicts: list[ConflictRecord],
    source_name: str = "",
    source_anchor_id: str = "",
    source_entity_id: str = "",
    question_id: str = "",
    confidence: str = "",
    reason: str = "",
) -> None:
    normalized_value = _normalize_candidate_value(field_path, candidate_value)
    if normalized_value is None:
        return

    contamination = contamination_reasons(field_path, normalized_value, {"source_type": source_type, "source_name": source_name})
    if contamination:
        rejected_updates.append(
            FieldUpdateRecord(
                field_path=field_path,
                candidate_value=candidate_value,
                accepted_value=None,
                source_type=source_type,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                question_id=question_id,
                confidence=confidence,
                decision="REJECTED_CONTAMINATED_VALUE",
                reason="Rejected contaminated normalization candidate: " + "; ".join(contamination),
            )
        )
        return

    existing_value = get_nested_value(normalized, field_path)

    if existing_value is None or _is_normalization_empty_value(existing_value):
        set_nested_value(normalized, field_path, normalized_value)
        accepted_updates.append(
            FieldUpdateRecord(
                field_path=field_path,
                candidate_value=candidate_value,
                accepted_value=normalized_value,
                source_type=source_type,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                question_id=question_id,
                confidence=confidence,
                decision="ACCEPTED",
                reason=reason or "Accepted as first deterministic value for field.",
            )
        )
        _record_planner_field_value(
            normalized,
            field_path_or_id=field_path,
            accepted_value=normalized_value,
            source_type=source_type,
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            confidence=confidence,
        )
        return

    if existing_value == normalized_value:
        accepted_updates.append(
            FieldUpdateRecord(
                field_path=field_path,
                candidate_value=candidate_value,
                accepted_value=normalized_value,
                source_type=source_type,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                question_id=question_id,
                confidence=confidence,
                decision="CONFIRMED_DUPLICATE",
                reason=reason or "Value matched existing normalized value.",
            )
        )
        _record_planner_field_value(
            normalized,
            field_path_or_id=field_path,
            accepted_value=normalized_value,
            source_type=source_type,
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            confidence=confidence,
        )
        return

    interview_override_sources = {"engineer_interview", "applicant_interview", "planner_interview_closure"}
    if source_type in interview_override_sources:
        conflicts.append(
            _make_conflict(
                field_path=field_path,
                existing_value=existing_value,
                candidate_value=normalized_value,
                source_type=source_type,
                reason="Interview-confirmed value superseded an earlier non-interview normalized value.",
                entity_id=source_entity_id,
                source_anchor_id=source_anchor_id,
                source_name=source_name,
                question_id=question_id,
            )
        )
        set_nested_value(normalized, field_path, normalized_value)
        accepted_updates.append(
            FieldUpdateRecord(
                field_path=field_path,
                candidate_value=candidate_value,
                accepted_value=normalized_value,
                source_type=source_type,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                question_id=question_id,
                confidence=confidence,
                decision="INTERVIEW_OVERRIDE_ACCEPTED",
                reason=reason or "Accepted interview-confirmed value as highest-authority source for this field.",
            )
        )
        _record_planner_field_value(
            normalized,
            field_path_or_id=field_path,
            accepted_value=normalized_value,
            source_type=source_type,
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            confidence=confidence,
        )
        return

    conflicts.append(
        _make_conflict(
            field_path=field_path,
            existing_value=existing_value,
            candidate_value=normalized_value,
            source_type=source_type,
            reason="Conflicting values mapped to the same canonical field.",
            entity_id=source_entity_id,
            source_anchor_id=source_anchor_id,
            source_name=source_name,
            question_id=question_id,
        )
    )
    rejected_updates.append(
        FieldUpdateRecord(
            field_path=field_path,
            candidate_value=candidate_value,
            accepted_value=existing_value,
            source_type=source_type,
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            source_entity_id=source_entity_id,
            question_id=question_id,
            confidence=confidence,
            decision="REJECTED_CONFLICT",
            reason="Rejected because the field already had a different normalized value.",
        )
    )


def _append_transformer_rating(
    normalized: dict[str, Any],
    candidate_value: Any,
    accepted_updates: list[FieldUpdateRecord],
    source_type: str,
    source_name: str = "",
    source_anchor_id: str = "",
    source_entity_id: str = "",
    confidence: str = "",
) -> None:
    rating = safe_float(candidate_value)
    if rating is None:
        return

    ratings = normalized.get("facility", {}).get("transformers", {}).get("ratings_mva")
    if not isinstance(ratings, list):
        ratings = []
        normalized.setdefault("facility", {}).setdefault("transformers", {})["ratings_mva"] = ratings
    if rating in ratings:
        accepted_updates.append(
            FieldUpdateRecord(
                field_path="facility.transformers.ratings_mva",
                candidate_value=candidate_value,
                accepted_value=rating,
                source_type=source_type,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                decision="CONFIRMED_DUPLICATE",
                reason="Transformer rating already existed in normalized list.",
            )
        )
        return

    ratings.append(rating)
    _record_planner_field_value(
        normalized,
        field_path_or_id="facility.transformers.ratings_mva",
        accepted_value=list(ratings),
        source_type=source_type,
        source_name=source_name,
        source_anchor_id=source_anchor_id,
        confidence=confidence,
    )
    accepted_updates.append(
        FieldUpdateRecord(
            field_path="facility.transformers.ratings_mva",
            candidate_value=candidate_value,
            accepted_value=rating,
            source_type=source_type,
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            source_entity_id=source_entity_id,
            confidence=confidence,
            decision="ACCEPTED",
            reason="Transformer rating appended to deterministic rating list.",
        )
    )


def _map_parameter_path_entity(
    normalized: dict[str, Any],
    entity: dict[str, Any],
    accepted_updates: list[FieldUpdateRecord],
    rejected_updates: list[FieldUpdateRecord],
    conflicts: list[ConflictRecord],
) -> bool:
    attributes = entity.get("attributes", {})
    if not isinstance(attributes, dict):
        attributes = {}

    parameter_path = attributes.get("parameter_path")
    normalized_value = attributes.get("normalized_value")

    if not isinstance(parameter_path, str) or not parameter_path.strip():
        return False

    source_name = str(entity.get("name", "")).strip()
    source_anchor_id = str(entity.get("source_anchor_id", "")).strip()
    source_entity_id = str(entity.get("entity_id", "")).strip()
    confidence = str(entity.get("confidence", "")).strip()

    if parameter_path == "facility.transformers.ratings_mva":
        _append_transformer_rating(
            normalized,
            normalized_value,
            accepted_updates,
            source_type="document_extraction",
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            source_entity_id=source_entity_id,
            confidence=confidence,
        )
        return True

    _apply_scalar_update(
        normalized,
        field_path=parameter_path,
        candidate_value=normalized_value,
        source_type="document_extraction",
        accepted_updates=accepted_updates,
        rejected_updates=rejected_updates,
        conflicts=conflicts,
        source_name=source_name,
        source_anchor_id=source_anchor_id,
        source_entity_id=source_entity_id,
        confidence=confidence,
        reason="Accepted from extraction entity parameter mapping.",
    )
    return True



def _planner_field_has_locked_value(
    normalized: dict[str, Any],
    accepted_updates: list[FieldUpdateRecord],
    field_path: str,
) -> bool:
    """Return True when a planner field already has a non-legacy accepted value.

    Legacy entity detections are useful as weak fallback evidence, but they must
    not overwrite or inflate explicit schema-field, canonical, retrieval, or
    interview values. This guard keeps drawing/device-symbol detections from
    corrupting schedule/form quantities and generic voltage/MW entities from
    replacing field-intent matches.
    """
    normalized_path = _normalization_alias_field_path(field_path) or str(field_path or "").strip()
    field_id = registry_field_id_for_path(normalized_path) or registry_field_id_for_path(field_path) or str(field_path or "").strip()

    explicit_source_types = {
        "schema_field_candidate",
        "canonical_state",
        "engineer_interview",
        "retrieval_candidate",
        "applicant_interview",
        "planner_interview_closure",
    }

    for update in accepted_updates:
        if not isinstance(update, FieldUpdateRecord):
            continue
        update_path = _normalization_alias_field_path(update.field_path) or update.field_path
        update_field_id = registry_field_id_for_path(update_path) or registry_field_id_for_path(update.field_path)
        if update_path == normalized_path or (field_id and update_field_id == field_id):
            if update.source_type in explicit_source_types:
                return True
            if update.source_type != "document_extraction" and update.decision in {
                "ACCEPTED",
                "CONFIRMED_DUPLICATE",
                "INTERVIEW_CONFIRMED",
                "INTERVIEW_SUPPLIED",
            }:
                return True

    if field_id and field_id in _planner_field_values(normalized):
        source = _planner_field_sources(normalized).get(field_id, {})
        if isinstance(source, dict):
            source_type = str(source.get("source_type", "")).strip()
            return source_type in explicit_source_types
        return True

    return False


def _reject_legacy_entity_inference(
    rejected_updates: list[FieldUpdateRecord],
    *,
    field_path: str,
    candidate_value: Any,
    source_name: str,
    source_anchor_id: str,
    source_entity_id: str,
    confidence: str,
    reason: str,
) -> None:
    rejected_updates.append(
        FieldUpdateRecord(
            field_path=field_path,
            candidate_value=candidate_value,
            accepted_value=None,
            source_type="document_extraction",
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            source_entity_id=source_entity_id,
            confidence=confidence,
            decision="REJECTED_LEGACY_ENTITY_INFERENCE",
            reason=reason,
        )
    )


def _legacy_entity_candidate(
    *,
    field_path: str,
    entity: dict[str, Any],
    value: Any,
    source_name: str,
) -> dict[str, Any]:
    attrs = entity.get("attributes", {})
    metadata = attrs if isinstance(attrs, dict) else {}
    return {
        "field_path": field_path,
        "value": value,
        "confidence": entity.get("confidence"),
        "method": "legacy_entity_inference",
        "source_type": "document_extraction",
        "source_name": source_name,
        "source_role": entity.get("source_role"),
        "document_role": entity.get("document_role"),
        "metadata": metadata,
        "evidence": [
            {
                "text": " ".join(
                    str(part)
                    for part in (source_name, metadata.get("context"), metadata.get("text"), metadata.get("label"))
                    if part not in (None, "")
                ),
                "metadata": metadata,
            }
        ],
    }

def _map_legacy_entity(
    normalized: dict[str, Any],
    entity: dict[str, Any],
    accepted_updates: list[FieldUpdateRecord],
    rejected_updates: list[FieldUpdateRecord],
    conflicts: list[ConflictRecord],
) -> None:
    entity_type = entity.get("type")
    attrs = entity.get("attributes", {})
    if not isinstance(attrs, dict):
        attrs = {}

    source_name = str(entity.get("name", "")).strip()
    source_anchor_id = str(entity.get("source_anchor_id", "")).strip()
    source_entity_id = str(entity.get("entity_id", "")).strip()
    confidence = str(entity.get("confidence", "")).strip()

    if entity_type == "ups_system":
        target = "facility.ups.count"
        if _planner_field_has_locked_value(normalized, accepted_updates, target):
            _reject_legacy_entity_inference(
                rejected_updates,
                field_path=target,
                candidate_value=1,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                reason="Rejected legacy UPS entity count because an explicit planner-field value already exists.",
            )
            return
        _apply_scalar_update(
            normalized,
            field_path=target,
            candidate_value=1,
            source_type="document_extraction",
            accepted_updates=accepted_updates,
            rejected_updates=rejected_updates,
            conflicts=conflicts,
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            source_entity_id=source_entity_id,
            confidence=confidence,
            reason="Derived minimum UPS count from detected UPS system entity as weak fallback evidence.",
        )
        return

    if entity_type == "generator":
        _apply_scalar_update(
            normalized,
            field_path="facility.generators.present",
            candidate_value=True,
            source_type="document_extraction",
            accepted_updates=accepted_updates,
            rejected_updates=rejected_updates,
            conflicts=conflicts,
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            source_entity_id=source_entity_id,
            confidence=confidence,
            reason="Derived generator presence from generator entity.",
        )
        target = "facility.generators.count"
        if _planner_field_has_locked_value(normalized, accepted_updates, target):
            _reject_legacy_entity_inference(
                rejected_updates,
                field_path=target,
                candidate_value=1,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                reason="Rejected legacy generator entity count because an explicit schedule/form/interview value already exists.",
            )
            return
        existing_count = get_nested_value(normalized, target)
        proposed_count = 1 if existing_count is None else int(existing_count) + 1
        set_nested_value(normalized, target, proposed_count)
        accepted_updates.append(
            FieldUpdateRecord(
                field_path=target,
                candidate_value=proposed_count,
                accepted_value=proposed_count,
                source_type="document_extraction",
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                decision="ACCEPTED_LEGACY_FALLBACK",
                reason="Incremented generator count from legacy entity only because no explicit count source was available.",
            )
        )
        return

    if entity_type == "transformer":
        target = "facility.transformers.count"
        if _planner_field_has_locked_value(normalized, accepted_updates, target):
            _reject_legacy_entity_inference(
                rejected_updates,
                field_path=target,
                candidate_value=1,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                reason="Rejected legacy transformer entity count because an explicit schedule/form/interview value already exists.",
            )
            return
        existing_count = get_nested_value(normalized, target)
        proposed_count = 1 if existing_count is None else int(existing_count) + 1
        set_nested_value(normalized, target, proposed_count)
        accepted_updates.append(
            FieldUpdateRecord(
                field_path=target,
                candidate_value=proposed_count,
                accepted_value=proposed_count,
                source_type="document_extraction",
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                decision="ACCEPTED_LEGACY_FALLBACK",
                reason="Incremented transformer count from legacy entity only because no explicit count source was available.",
            )
        )
        return

    if entity_type == "transformer_rating":
        _append_transformer_rating(
            normalized,
            attrs.get("value"),
            accepted_updates,
            source_type="document_extraction",
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            source_entity_id=source_entity_id,
            confidence=confidence,
        )
        return

    if entity_type == "voltage_value":
        target = "facility.poi_voltage_kv"
        value = attrs.get("value")
        candidate = _legacy_entity_candidate(field_path=target, entity=entity, value=value, source_name=source_name)
        if _planner_field_has_locked_value(normalized, accepted_updates, target):
            _reject_legacy_entity_inference(
                rejected_updates,
                field_path=target,
                candidate_value=value,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                reason="Rejected generic voltage entity because an explicit POI/service-voltage planner-field value already exists.",
            )
            return
        if candidate_is_rejected_for_field(target, candidate):
            _reject_legacy_entity_inference(
                rejected_updates,
                field_path=target,
                candidate_value=value,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                reason="Rejected generic voltage entity because its context does not match POI/service-voltage field intent.",
            )
            return
        _apply_scalar_update(
            normalized,
            field_path=target,
            candidate_value=value,
            source_type="document_extraction",
            accepted_updates=accepted_updates,
            rejected_updates=rejected_updates,
            conflicts=conflicts,
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            source_entity_id=source_entity_id,
            confidence=confidence,
            reason="Mapped generic voltage entity to POI voltage only as weak fallback evidence.",
        )
        return

    if entity_type == "mw_value":
        # A generic MW mention is far more likely to represent project peak/
        # maximum/ultimate load than Phase 1 load.  Phase-specific values must
        # come from row/label-aware extraction, not generic numeric fallback.
        target = "facility.load_schedule.phase_3_mw"
        value = attrs.get("value")
        candidate = _legacy_entity_candidate(field_path=target, entity=entity, value=value, source_name=source_name)
        load_targets = (
            "facility.load_schedule.phase_1_mw",
            "facility.load_schedule.phase_2_mw",
            "facility.load_schedule.phase_3_mw",
            "facility.load_schedule.ultimate_mw",
            "facility.load_schedule.maximum_coincident_demand_mw",
        )
        if any(_planner_field_has_locked_value(normalized, accepted_updates, load_target) for load_target in load_targets):
            _reject_legacy_entity_inference(
                rejected_updates,
                field_path=target,
                candidate_value=value,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                reason="Rejected generic MW entity because an explicit peak/phase-load planner-field value already exists.",
            )
            return
        if candidate_is_rejected_for_field(target, candidate):
            _reject_legacy_entity_inference(
                rejected_updates,
                field_path=target,
                candidate_value=value,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                source_entity_id=source_entity_id,
                confidence=confidence,
                reason="Rejected generic MW entity because its context does not match peak/phase-load field intent.",
            )
            return
        _apply_scalar_update(
            normalized,
            field_path=target,
            candidate_value=value,
            source_type="document_extraction",
            accepted_updates=accepted_updates,
            rejected_updates=rejected_updates,
            conflicts=conflicts,
            source_name=source_name,
            source_anchor_id=source_anchor_id,
            source_entity_id=source_entity_id,
            confidence=confidence,
            reason="Mapped generic MW entity to ultimate/peak load only as weak fallback evidence; phase-specific fields require row-bound extraction.",
        )
        return

def _apply_entity_mappings(
    normalized: dict[str, Any],
    entities: list[dict[str, Any]],
    accepted_updates: list[FieldUpdateRecord],
    rejected_updates: list[FieldUpdateRecord],
) -> list[ConflictRecord]:
    conflicts: list[ConflictRecord] = []

    for entity in entities:
        handled = _map_parameter_path_entity(
            normalized,
            entity,
            accepted_updates,
            rejected_updates,
            conflicts,
        )
        if handled:
            continue

        _map_legacy_entity(
            normalized,
            entity,
            accepted_updates,
            rejected_updates,
            conflicts,
        )

    return conflicts


def _apply_interview_answers(
    normalized: dict[str, Any],
    interview_result: dict[str, Any] | None,
    accepted_updates: list[FieldUpdateRecord],
    rejected_updates: list[FieldUpdateRecord],
    conflicts: list[ConflictRecord],
) -> tuple[int, int]:
    if not interview_result:
        return 0, 0

    confirmed_answers = interview_result.get("answers_confirmed", [])
    clarifications = interview_result.get("clarifications", [])

    if not isinstance(confirmed_answers, list):
        confirmed_answers = []
    if not isinstance(clarifications, list):
        clarifications = []

    confirmed_count = 0

    for answer in confirmed_answers:
        if not isinstance(answer, dict):
            continue

        field_path = answer.get("field_path")
        if not isinstance(field_path, str) or not field_path.strip():
            continue

        confirmed_value = answer.get("confirmed_answer", answer.get("answer"))
        question_id = str(answer.get("question_id", "")).strip()
        source_name = str(answer.get("source_name", "")).strip()

        _apply_scalar_update(
            normalized,
            field_path=field_path.strip(),
            candidate_value=confirmed_value,
            source_type="engineer_interview",
            accepted_updates=accepted_updates,
            rejected_updates=rejected_updates,
            conflicts=conflicts,
            source_name=source_name,
            question_id=question_id,
            confidence="HIGH",
            reason="Accepted from confirmed engineer interview answer.",
        )
        confirmed_count += 1

    return confirmed_count, len([item for item in clarifications if isinstance(item, dict)])


def _apply_topology_cues(
    normalized: dict[str, Any],
    topology_cues: list[dict[str, Any]],
    accepted_updates: list[FieldUpdateRecord],
    rejected_updates: list[FieldUpdateRecord],
    conflicts: list[ConflictRecord],
) -> None:
    for cue in topology_cues:
        if not isinstance(cue, dict):
            continue

        cue_type = str(cue.get("type", "")).strip()
        artifact_id = str(cue.get("artifact_id", "")).strip()

        if cue_type == "topology_2n":
            _apply_scalar_update(
                normalized,
                field_path="facility.ups.topology",
                candidate_value="2N",
                source_type="topology_cue",
                accepted_updates=accepted_updates,
                rejected_updates=rejected_updates,
                conflicts=conflicts,
                source_name=artifact_id,
                reason="Applied deterministic topology cue for 2N architecture.",
            )
            continue

        if cue_type == "topology_n_plus_1":
            _apply_scalar_update(
                normalized,
                field_path="facility.ups.topology",
                candidate_value="N+1",
                source_type="topology_cue",
                accepted_updates=accepted_updates,
                rejected_updates=rejected_updates,
                conflicts=conflicts,
                source_name=artifact_id,
                reason="Applied deterministic topology cue for N+1 architecture.",
            )


def _build_missing_fields(
    normalized: dict[str, Any],
    accepted_updates: list[FieldUpdateRecord],
) -> list[dict[str, Any]]:
    missing_fields: list[dict[str, Any]] = []
    accepted_registry_field_ids = {
        registry_field_id_for_path(update.field_path)
        for update in accepted_updates
        if isinstance(update.field_path, str) and update.field_path.strip()
    }
    accepted_registry_field_ids = {field_id for field_id in accepted_registry_field_ids if field_id}

    for field_id in normalization_required_field_ids():
        profile = build_followup_profile(field_id)
        lookup_keys = profile.get("lookup_keys", [])
        resolved = False

        for key in lookup_keys if isinstance(lookup_keys, list) else registry_lookup_keys(field_id):
            if not isinstance(key, str) or not key.strip() or "." not in key:
                continue
            if get_nested_value(normalized, key.strip()) is not None:
                resolved = True
                break

        if not resolved and field_id in accepted_registry_field_ids:
            resolved = True
        if not resolved and field_id in _planner_field_values(normalized):
            resolved = True

        if resolved:
            continue

        missing_fields.append(
            {
                "field_id": field_id,
                "field_path": profile.get("field_path") or field_id,
                "label": profile.get("label") or field_id,
                "requiredness": profile.get("requiredness") or "required",
                "planner_critical": bool(profile.get("planner_critical", False)),
                "preferred_sources": list(profile.get("preferred_sources", [])) if isinstance(profile.get("preferred_sources"), list) else [],
                "search_keywords": list(profile.get("search_keywords", [])) if isinstance(profile.get("search_keywords"), list) else [],
                "packet_section": profile.get("packet_section") or "",
                "group": profile.get("group") or "",
                "lookup_keys": list(lookup_keys) if isinstance(lookup_keys, list) else registry_lookup_keys(field_id),
            }
        )

    return missing_fields


def _build_clarification_followups(
    interview_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not interview_result:
        return []

    clarifications = interview_result.get("clarifications", [])
    if not isinstance(clarifications, list):
        return []

    followups: list[dict[str, Any]] = []

    for index, clarification in enumerate(clarifications, start=1):
        if not isinstance(clarification, dict):
            continue

        followups.append(
            build_followup_question(
                question_id=f"clarify_{index:03d}",
                field_path=str(clarification.get("field_path", "")).strip(),
                reason=(
                    "Engineer response could not be safely normalized into the "
                    "expected canonical field."
                ),
                suggested_sources=[
                    "engineer clarification",
                    "facility design basis",
                    "equipment schedule",
                ],
                severity="HIGH",
                extra_fields={
                    "raw_answer": clarification.get("answer"),
                    "source_name": clarification.get("source_name"),
                    "answer_status": clarification.get("answer_status"),
                },
            )
        )

    return followups


def _build_normalized_field_index(
    normalized_input: dict[str, Any],
    accepted_updates: list[FieldUpdateRecord],
    conflicts: list[ConflictRecord],
) -> dict[str, dict[str, Any]]:
    accepted_by_field_path: dict[str, FieldUpdateRecord] = {}
    for item in accepted_updates:
        if isinstance(item, FieldUpdateRecord) and item.field_path and item.field_path not in accepted_by_field_path:
            accepted_by_field_path[item.field_path] = item

    conflict_counts: dict[str, int] = {}
    for conflict in conflicts:
        if isinstance(conflict, ConflictRecord) and conflict.field_path:
            conflict_counts[conflict.field_path] = conflict_counts.get(conflict.field_path, 0) + 1

    index: dict[str, dict[str, Any]] = {}
    for field_id in normalization_required_field_ids():
        lookup_keys = registry_lookup_keys(field_id)
        field_path = next((key for key in lookup_keys if "." in key), "")
        if not field_path:
            continue
        current_value = get_nested_value(normalized_input, field_path)
        if current_value is None:
            current_value = _planner_field_values(normalized_input).get(field_id)
        accepted = accepted_by_field_path.get(field_path)
        conflict_count = int(conflict_counts.get(field_path, 0))
        status = "resolved" if current_value not in (None, "", [], {}) else "missing"
        if conflict_count > 0:
            status = "conflicting"
        entry = {
            "field_id": field_id,
            "field_path": field_path,
            "label": field_label_for_path(field_id),
            "group": field_group_for_path(field_id),
            "data_type": field_data_type_for_path(field_id),
            "requiredness": field_requiredness_for_path(field_id),
            "planner_critical": planner_critical_for_path(field_id),
            "minimum_confidence_for_auto_accept": field_minimum_confidence_for_auto_accept(field_id),
            "value": current_value,
            "status": status,
            "conflict_count": conflict_count,
            "accepted_update": accepted.to_dict() if isinstance(accepted, FieldUpdateRecord) else None,
        }
        if isinstance(accepted, FieldUpdateRecord):
            entry["source_type"] = accepted.source_type
            entry["source_name"] = accepted.source_name
            entry["source_anchor_id"] = accepted.source_anchor_id
            entry["decision"] = accepted.decision
            entry["reason"] = accepted.reason
        index[field_id] = entry
    return index


def _build_conflict_followups(conflicts: list[ConflictRecord]) -> list[dict[str, Any]]:
    followups: list[dict[str, Any]] = []

    for index, conflict in enumerate(conflicts, start=1):
        payload = conflict.to_dict()
        followups.append(
            build_followup_question(
                question_id=f"conflict_{index:03d}",
                field_path=payload.get("field_path", ""),
                reason=(
                    "Conflicting values were identified for this canonical field "
                    "and require operator resolution."
                ),
                suggested_sources=[
                    "engineer confirmation",
                    "one-line diagram",
                    "equipment schedule",
                    "vendor specification",
                ],
                severity="HIGH",
                extra_fields={
                    "existing_value": payload.get("existing_value"),
                    "candidate_value": payload.get("candidate_value"),
                    "source_type": payload.get("source_type"),
                    "review_status": payload.get("review_status"),
                },
            )
        )

    return followups


def _build_missing_field_followups(missing_fields: list[dict[str, Any] | str]) -> list[dict[str, Any]]:
    followups: list[dict[str, Any]] = []

    for index, item in enumerate(missing_fields, start=1):
        if isinstance(item, dict):
            field_id = str(item.get("field_id", "")).strip()
            field_path = str(item.get("field_path", "")).strip() or field_id
            label = str(item.get("label", "")).strip() or field_path
            preferred_sources = item.get("preferred_sources", [])
            suggested_sources = [
                str(value).strip()
                for value in preferred_sources
                if isinstance(value, str) and str(value).strip()
            ] if isinstance(preferred_sources, list) else []
            if not suggested_sources:
                suggested_sources = [
                    "interconnection application",
                    "one-line diagram",
                    "equipment specifications",
                    "engineer interview",
                ]
            severity = "HIGH" if bool(item.get("planner_critical", False)) else "MODERATE"
            reason = f"Required planner field '{label}' was not resolved during normalization from the current document and interview evidence."
            extra_fields = {
                "field_id": field_id,
                "label": label,
                "requiredness": item.get("requiredness"),
                "planner_critical": bool(item.get("planner_critical", False)),
                "packet_section": item.get("packet_section"),
                "group": item.get("group"),
                "lookup_keys": item.get("lookup_keys", []),
                "search_keywords": item.get("search_keywords", []),
            }
        else:
            field_path = str(item).strip()
            if not field_path:
                continue
            profile = build_followup_profile(field_path)
            field_id = str(profile.get("field_id", "")).strip()
            label = str(profile.get("label", "")).strip() or field_path
            suggested_sources = list(profile.get("preferred_sources", [])) if isinstance(profile.get("preferred_sources"), list) else []
            if not suggested_sources:
                suggested_sources = [
                    "interconnection application",
                    "one-line diagram",
                    "equipment specifications",
                    "engineer interview",
                ]
            severity = "HIGH" if bool(profile.get("planner_critical", False)) else "MODERATE"
            reason = f"Required planner field '{label}' was not resolved during normalization from the current document and interview evidence."
            extra_fields = {
                "field_id": field_id,
                "label": label,
                "requiredness": profile.get("requiredness"),
                "planner_critical": bool(profile.get("planner_critical", False)),
                "packet_section": profile.get("packet_section"),
                "group": profile.get("group"),
                "lookup_keys": profile.get("lookup_keys", []),
                "search_keywords": profile.get("search_keywords", []),
            }

        followups.append(
            build_followup_question(
                question_id=f"fq_{index:03d}",
                field_path=field_path,
                reason=reason,
                suggested_sources=suggested_sources,
                severity=severity,
                extra_fields=extra_fields,
            )
        )

    return followups


def _apply_canonical_state_payload(
    normalized: dict[str, Any],
    canonical_state: dict[str, Any],
    accepted_updates: list[FieldUpdateRecord],
    rejected_updates: list[FieldUpdateRecord],
    conflicts: list[ConflictRecord],
) -> None:
    if not isinstance(canonical_state, dict):
        return

    for canonical_field_path, payload in canonical_state.items():
        if not isinstance(payload, dict):
            continue

        accepted_value = payload.get("value")
        if accepted_value is None:
            continue

        normalized_field_path = _normalization_alias_field_path(canonical_field_path)
        source_name = str(payload.get("method", "")).strip()
        source_anchor_id = str(payload.get("source_artifact_id", "")).strip()
        confidence = str(payload.get("confidence", "")).strip()

        if normalized_field_path == "facility.transformers.ratings_mva":
            if isinstance(accepted_value, list):
                for item in accepted_value:
                    _append_transformer_rating(
                        normalized,
                        item,
                        accepted_updates,
                        source_type="canonical_state_extraction",
                        source_name=source_name,
                        source_anchor_id=source_anchor_id,
                        confidence=confidence,
                    )
            else:
                _append_transformer_rating(
                    normalized,
                    accepted_value,
                    accepted_updates,
                    source_type="canonical_state_extraction",
                    source_name=source_name,
                    source_anchor_id=source_anchor_id,
                    confidence=confidence,
                )
            continue

        if normalized_field_path:
            _apply_scalar_update(
                normalized,
                field_path=normalized_field_path,
                candidate_value=accepted_value,
                source_type="canonical_state_extraction",
                accepted_updates=accepted_updates,
                rejected_updates=rejected_updates,
                conflicts=conflicts,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                confidence=confidence,
                reason="Accepted from extraction-stage canonical state payload.",
            )
            if canonical_field_path != normalized_field_path:
                _record_planner_field_value(
                    normalized,
                    field_path_or_id=canonical_field_path,
                    accepted_value=_normalize_candidate_value(canonical_field_path, accepted_value),
                    source_type="canonical_state_extraction",
                    source_name=source_name,
                    source_anchor_id=source_anchor_id,
                    confidence=confidence,
                )
        else:
            _record_planner_field_value(
                normalized,
                field_path_or_id=canonical_field_path,
                accepted_value=accepted_value,
                source_type="canonical_state_extraction",
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                confidence=confidence,
            )

    generator_count = get_nested_value(normalized, "facility.generators.count")
    if generator_count is not None:
        set_nested_value(normalized, "facility.generators.present", bool(generator_count > 0))




def _candidate_source_family(candidate: dict[str, Any]) -> str:
    role = source_role_from_candidate(candidate)
    return {
        "application_request_form": "PROJECT_PRIMARY",
        "project_summary_load_schedule": "PROJECT_PRIMARY",
        "equipment_schedule": "PROJECT_SUPPORTING",
        "facilities_interconnection_memo": "PROJECT_SUPPORTING",
        "phasing_energization_plan": "PROJECT_SUPPORTING",
        "one_line_diagram": "PROJECT_DRAWING",
        "drawing": "PROJECT_DRAWING",
        "oem_reference": "OEM_REFERENCE",
        "interview": "PROJECT_PRIMARY",
    }.get(role, "PROJECT_PACKAGE")


def _candidate_authority_score(candidate: dict[str, Any]) -> tuple[int, int, int, int, int]:
    field_path = str(candidate.get("field_path", "")).strip()
    return normalization_authority_score(field_path, candidate)

def _rank_schema_field_candidates_for_normalization(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((candidate for candidate in candidates if isinstance(candidate, dict)), key=_candidate_authority_score, reverse=True)

def _apply_schema_field_candidates(
    normalized: dict[str, Any],
    schema_field_candidates: list[dict[str, Any]],
    accepted_updates: list[FieldUpdateRecord],
    rejected_updates: list[FieldUpdateRecord],
    conflicts: list[ConflictRecord],
) -> None:
    if not isinstance(schema_field_candidates, list):
        return

    seen: set[str] = set()
    for candidate in _rank_schema_field_candidates_for_normalization(schema_field_candidates):
        field_path = str(candidate.get("field_path", "")).strip()
        normalized_field_path = _normalization_alias_field_path(field_path)
        seen_key = normalized_field_path or registry_field_id_for_path(field_path) or field_path
        if not field_path or seen_key in seen:
            continue
        raw_confidence = candidate.get("confidence", "")
        if isinstance(raw_confidence, (int, float)):
            confidence = "HIGH" if float(raw_confidence) >= 0.8 else "MODERATE" if float(raw_confidence) >= 0.5 else "LOW"
        else:
            confidence = str(raw_confidence).strip().upper()
        if confidence not in {"HIGH", "MODERATE"}:
            continue
        if candidate_is_rejected_for_field(normalized_field_path or field_path, candidate):
            rejected_updates.append(
                FieldUpdateRecord(
                    field_path=normalized_field_path or field_path,
                    candidate_value=candidate.get("value"),
                    accepted_value=None,
                    source_type="schema_field_candidate",
                    source_name=str(candidate.get("method", "")).strip(),
                    source_anchor_id=str(candidate.get("artifact_id", candidate.get("source_artifact_id", ""))).strip(),
                    confidence=confidence,
                    decision="REJECTED_CONTEXT",
                    reason="Rejected because source context does not match the target planner field intent.",
                )
            )
            continue
        value = candidate.get("value")
        source_name = str(candidate.get("method", "")).strip()
        source_anchor_id = str(candidate.get("artifact_id", candidate.get("source_artifact_id", ""))).strip()
        if normalized_field_path == "facility.transformers.ratings_mva":
            _append_transformer_rating(
                normalized,
                value,
                accepted_updates,
                source_type="schema_field_candidate",
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                confidence=confidence,
            )
            seen.add(seen_key)
            continue
        if normalized_field_path:
            _apply_scalar_update(
                normalized,
                field_path=normalized_field_path,
                candidate_value=value,
                source_type="schema_field_candidate",
                accepted_updates=accepted_updates,
                rejected_updates=rejected_updates,
                conflicts=conflicts,
                source_name=source_name,
                source_anchor_id=source_anchor_id,
                confidence=confidence,
                reason="Accepted from schema-field candidate during normalization hardening.",
            )
            seen.add(seen_key)
            continue
        field_id = registry_field_id_for_path(field_path)
        if field_id:
            normalized_value = _normalize_candidate_value(field_id, value)
            if normalized_value is not None:
                _record_planner_field_value(
                    normalized,
                    field_path_or_id=field_id,
                    accepted_value=normalized_value,
                    source_type="schema_field_candidate",
                    source_name=source_name,
                    source_anchor_id=source_anchor_id,
                    confidence=confidence,
                )
                seen.add(seen_key)


def _build_validation_report(
    context: Any,
    normalized: dict[str, Any],
    conflicts: list[ConflictRecord],
    confirmed_interview_count: int,
    clarification_count: int,
    accepted_updates: list[FieldUpdateRecord],
    rejected_updates: list[FieldUpdateRecord],
) -> dict[str, Any]:
    missing_fields = _build_missing_fields(normalized, accepted_updates)

    confirmed_field_paths = sorted(
        {
            update.field_path
            for update in accepted_updates
            if update.source_type == "engineer_interview" and update.field_path
        }
    )

    return {
        "run_id": context.run_id,
        "errors": [],
        "warnings": [],
        "missing_fields": missing_fields,
        "conflicts": [conflict.to_dict() for conflict in conflicts],
        "schema_valid": True,
        "schema_path": "planner_required_fields.normalization_runtime",
        "decision_summary": {
            "accepted_update_count": len(accepted_updates),
            "rejected_update_count": len(rejected_updates),
        },
        "interview_summary": {
            "confirmed_answers": confirmed_interview_count,
            "clarifications_required": clarification_count,
            "confirmed_field_paths": confirmed_field_paths,
        },
    }


def _build_followup_questions(
    missing_fields: list[str],
    interview_result: dict[str, Any] | None,
    conflicts: list[ConflictRecord],
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    questions.extend(_build_missing_field_followups(missing_fields))
    questions.extend(_build_clarification_followups(interview_result))
    questions.extend(_build_conflict_followups(conflicts))
    return questions


def run_service(
    context: Any,
    extraction_result: dict[str, Any],
    interview_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entities = extraction_result.get("entities", extraction_result.get("candidate_entities", []))
    topology_cues = extraction_result.get("topology_cues", [])
    canonical_state = extraction_result.get("canonical_state", {})
    schema_field_candidates = extraction_result.get("schema_field_candidates", [])
    snippets = [] if retrieval_result is None else retrieval_result.get("snippets", [])
    calibration_datasets = _normalize_calibration_datasets(extraction_result)

    if not isinstance(entities, list):
        entities = []
    if not isinstance(topology_cues, list):
        topology_cues = []
    if not isinstance(snippets, list):
        snippets = []
    if not isinstance(canonical_state, dict):
        canonical_state = {}
    if not isinstance(schema_field_candidates, list):
        schema_field_candidates = []

    normalized_input = _initialize_facility_schema(context)
    normalized_input["source_summary"]["entity_count"] = len(entities)
    normalized_input["source_summary"]["topology_cue_count"] = len(topology_cues)
    normalized_input["source_summary"]["evidence_snippet_count"] = len(snippets)
    normalized_input["source_summary"]["canonical_field_count"] = len(canonical_state)
    normalized_input["source_summary"]["calibration_dataset_count"] = len(calibration_datasets)

    accepted_updates: list[FieldUpdateRecord] = []
    rejected_updates: list[FieldUpdateRecord] = []
    conflicts: list[ConflictRecord] = []

    _apply_canonical_state_payload(
        normalized_input,
        canonical_state,
        accepted_updates,
        rejected_updates,
        conflicts,
    )
    _apply_schema_field_candidates(
        normalized_input,
        schema_field_candidates,
        accepted_updates,
        rejected_updates,
        conflicts,
    )

    entity_conflicts = _apply_entity_mappings(
        normalized_input,
        entities,
        accepted_updates,
        rejected_updates,
    )
    conflicts.extend(entity_conflicts)

    confirmed_count, clarification_count = _apply_interview_answers(
        normalized_input,
        interview_result,
        accepted_updates,
        rejected_updates,
        conflicts,
    )
    normalized_input["source_summary"]["confirmed_interview_count"] = confirmed_count
    normalized_input["source_summary"]["clarification_count"] = clarification_count

    _apply_topology_cues(
        normalized_input,
        topology_cues,
        accepted_updates,
        rejected_updates,
        conflicts,
    )

    normalized_input["source_summary"]["planner_field_value_count"] = len(_planner_field_values(normalized_input))
    normalized_input["planner_field_groups"] = {
        field_id: {
            "group": field_group_for_path(field_id),
            "label": field_label_for_path(field_id),
            "requiredness": field_requiredness_for_path(field_id),
            "planner_critical": planner_critical_for_path(field_id),
            "value": value,
        }
        for field_id, value in sorted(_planner_field_values(normalized_input).items())
    }

    planner_candidate_contract = build_registry_candidate_ledger(
        schema_field_candidates=schema_field_candidates,
        normalized_input=normalized_input,
        accepted_updates=[item.to_dict() for item in accepted_updates],
        rejected_updates=[item.to_dict() for item in rejected_updates],
        conflicts=[item.to_dict() for item in conflicts],
        include_optional=True,
    )
    normalized_input["planner_candidate_ledger"] = planner_candidate_contract.get("planner_candidate_ledger", [])
    normalized_input["planner_candidate_ledger_summary"] = planner_candidate_contract.get("planner_candidate_ledger_summary", {})

    validation_report = _build_validation_report(
        context,
        normalized_input,
        conflicts,
        confirmed_count,
        clarification_count,
        accepted_updates,
        rejected_updates,
    )

    schema_validation = build_normalization_runtime_schema_validation(normalized_input)

    validation_report["planner_candidate_ledger_summary"] = normalized_input.get("planner_candidate_ledger_summary", {})
    validation_report["planner_extraction_worklist_summary"] = normalized_input.get("planner_extraction_worklist_summary", {})

    if isinstance(schema_validation, dict):
        validation_report["schema_valid"] = bool(schema_validation.get("schema_valid", False))
        validation_report["schema_validation"] = schema_validation
        validation_report["planner_registry_required_field_count"] = int(schema_validation.get("required_field_count", 0))
        validation_report["planner_registry_resolved_required_field_count"] = int(schema_validation.get("resolved_required_field_count", 0))
        validation_report["planner_registry_missing_required_field_count"] = int(schema_validation.get("missing_required_field_count", 0))
        if not validation_report["schema_valid"]:
            validation_report["errors"] = list(validation_report.get("errors", [])) + list(
                schema_validation.get("errors", [])
                if isinstance(schema_validation.get("errors"), list)
                else []
            )
            validation_report["warnings"] = list(validation_report.get("warnings", [])) + list(
                schema_validation.get("warnings", [])
                if isinstance(schema_validation.get("warnings"), list)
                else []
            )

    followup_questions = _build_followup_questions(
        validation_report["missing_fields"],
        interview_result,
        conflicts,
    )

    status = "NORMALIZED" if validation_report["schema_valid"] else "FAILED_SCHEMA_VALIDATION"

    result = NormalizationServiceResult(
        run_id=context.run_id,
        normalized_input=normalized_input,
        validation_report=validation_report,
        followup_questions=followup_questions,
        accepted_updates=[item.to_dict() for item in accepted_updates],
        rejected_updates=[item.to_dict() for item in rejected_updates],
        status=status,
        normalized_at=utc_now_iso(),
    )

    payload = result.to_dict()
    payload["calibration_datasets"] = calibration_datasets
    payload["calibration_dataset_count"] = len(calibration_datasets)
    return payload


def normalize_inputs(
    context: Any,
    extraction_result: dict[str, Any],
    interview_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_service(
        context=context,
        extraction_result=extraction_result,
        interview_result=interview_result,
        retrieval_result=retrieval_result,
    )