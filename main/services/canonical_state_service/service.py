from __future__ import annotations

from collections import defaultdict
from typing import Any

from shared.gap_resolution_utils import resolve_gap_resolution_stage_inputs
from shared.canonical_state_contract import annotate_final_canonical_state_result
from shared.governed_summary import build_governed_summary
from shared.planner_candidate_bridge import attach_candidate_ledger_to_canonical_state

from services.canonical_state_service.models import (
    CanonicalFieldRecord,
    CanonicalStateBuildInputs,
    CanonicalStateBuildSummary,
    CanonicalStateServiceResult,
    ConflictRecord,
    ReviewFlag,
)
from services.canonical_state_service.utils import (
    canonical_state_summary_from_payload,
    canonicalize_value_for_compare,
    confidence_score_from_tag,
    confidence_tag_from_score,
    deduplicate_strings,
    evidence_strength_from_sources,
    extract_missing_field_paths,
    flatten_scalar_paths,
    require_dict,
    require_list,
    require_run_id,
    review_status_from_context,
    safe_float,
    utc_now_iso,
    validate_stage_run_id,
    validation_status_from_context,
)
from shared.types import CanonicalFacilityState, build_empty_canonical_state
from services.extraction_service.models import ExtractionCandidate
from shared.field_paths import normalize_field_path
from shared.planner_registry import (
    build_planner_packet_field_rows,
    planner_registry_open_items,
    planner_registry_resolution_backlog,
    summarize_registry_packet_coverage,
)
from services.field_resolution_service.service import build_field_resolution_result


EXTRACTION_CONFIDENCE_THRESHOLD = 0.60
EXTRACTION_CONFLICT_DELTA_THRESHOLD = 0.20


def merge_extraction_candidates(
    *,
    candidates: list[ExtractionCandidate],
    canonical_state: dict[str, Any],
) -> dict[str, Any]:
    """Canonical-state-owned merge of extraction candidates into a working state payload."""
    state = dict(canonical_state)
    field_records = list(state.get("field_records")) if isinstance(state.get("field_records"), list) else []
    conflict_records = list(state.get("conflict_records")) if isinstance(state.get("conflict_records"), list) else []
    review_flags = list(state.get("review_flags")) if isinstance(state.get("review_flags"), list) else []

    grouped_candidates: dict[str, list[ExtractionCandidate]] = {}
    for candidate in candidates:
        grouped_candidates.setdefault(normalize_field_path(candidate.field_path), []).append(candidate)

    for field_path, field_candidates in grouped_candidates.items():
        ranked = sorted(field_candidates, key=lambda item: item.confidence, reverse=True)
        best_candidate = ranked[0]

        if best_candidate.value is None:
            field_records.append(
                CanonicalFieldRecord(
                    field_path=field_path,
                    value=None,
                    status="missing",
                    confidence=0.0,
                    source_artifact_id=best_candidate.source_artifact_id,
                    method=best_candidate.method,
                    evidence=best_candidate.evidence or {},
                ).to_dict()
            )
            review_flags.append(
                ReviewFlag(
                    review_flag_id=f"MISSING_FIELD:{field_path}",
                    category="MISSING_FIELD",
                    field_path=field_path,
                    message=f"No usable value was extracted for '{field_path}'.",
                    related_artifact_ids=sorted({c.source_artifact_id for c in ranked if c.source_artifact_id}),
                ).to_dict()
            )
            continue

        primary_status = (
            "provisional_extracted"
            if best_candidate.confidence >= EXTRACTION_CONFIDENCE_THRESHOLD
            else "review_required"
        )
        field_records.append(
            CanonicalFieldRecord(
                field_path=field_path,
                value=best_candidate.value,
                status=primary_status,
                confidence=best_candidate.confidence,
                source_artifact_id=best_candidate.source_artifact_id,
                method=best_candidate.method,
                evidence=best_candidate.evidence or {},
                is_primary=True,
            ).to_dict()
        )
        state[field_path] = {
            "value": best_candidate.value,
            "confidence": best_candidate.confidence,
            "source_artifact_id": best_candidate.source_artifact_id,
            "method": best_candidate.method,
            "evidence": best_candidate.evidence or {},
            "status": primary_status,
            "last_update_stage": "extraction",
        }
        if primary_status == "review_required":
            review_flags.append(
                ReviewFlag(
                    review_flag_id=f"LOW_CONFIDENCE_FIELD:{field_path}",
                    category="LOW_CONFIDENCE_FIELD",
                    field_path=field_path,
                    message=(
                        f"Best extracted value for '{field_path}' did not meet provisional confidence threshold "
                        f"({best_candidate.confidence:.2f})."
                    ),
                    related_artifact_ids=[best_candidate.source_artifact_id] if best_candidate.source_artifact_id else [],
                ).to_dict()
            )

        for competing_candidate in ranked[1:]:
            if competing_candidate.value is None:
                continue
            if _canonical_values_match(best_candidate.value, competing_candidate.value):
                continue
            confidence_delta = abs(best_candidate.confidence - competing_candidate.confidence)
            conflict_reason = (
                "material_value_disagreement"
                if confidence_delta <= EXTRACTION_CONFLICT_DELTA_THRESHOLD
                else "lower_ranked_alternative_value"
            )
            conflict_records.append(
                ConflictRecord(
                    field_path=field_path,
                    primary_value=best_candidate.value,
                    conflicting_value=competing_candidate.value,
                    primary_source_artifact_id=best_candidate.source_artifact_id,
                    conflicting_source_artifact_id=competing_candidate.source_artifact_id,
                    confidence_delta=confidence_delta,
                    conflict_reason=conflict_reason,
                ).to_dict()
            )
            field_records.append(
                CanonicalFieldRecord(
                    field_path=field_path,
                    value=competing_candidate.value,
                    status="conflicting",
                    confidence=competing_candidate.confidence,
                    source_artifact_id=competing_candidate.source_artifact_id,
                    method=competing_candidate.method,
                    evidence=competing_candidate.evidence or {},
                    is_primary=False,
                ).to_dict()
            )
            review_flags.append(
                ReviewFlag(
                    review_flag_id=f"CONFLICTING_FIELD:{field_path}",
                    category="CONFLICTING_FIELD",
                    field_path=field_path,
                    message=(
                        f"Conflicting extracted values were found for '{field_path}'. Primary value "
                        f"'{best_candidate.value}' conflicts with '{competing_candidate.value}'."
                    ),
                    related_artifact_ids=sorted(
                        {
                            best_candidate.source_artifact_id,
                            competing_candidate.source_artifact_id,
                        }
                        - {""}
                    ),
                ).to_dict()
            )
            state[field_path]["status"] = "conflicting"

    state["field_records"] = field_records
    state["conflict_records"] = conflict_records
    state["review_flags"] = review_flags
    return state


def _canonical_values_match(left: Any, right: Any) -> bool:
    return _canonical_normalize_value(left) == _canonical_normalize_value(right)


def _canonical_normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return tuple(_canonical_normalize_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(
            (str(key), _canonical_normalize_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    return value

def _dedupe_phase_four_records(
    records: list[dict[str, Any]],
    *,
    id_key: str,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for record in records:
        if not isinstance(record, dict):
            continue
        record_id = record.get(id_key)
        if not isinstance(record_id, str) or not record_id.strip():
            continue
        normalized_id = record_id.strip()
        if normalized_id in seen_ids:
            continue
        deduped.append(record)
        seen_ids.add(normalized_id)

    return deduped


def _merge_phase_four_ingestion(
    state: CanonicalFacilityState,
    ingestion_result: dict[str, Any] | None,
) -> None:
    if not ingestion_result:
        return

    calibration_datasets = ingestion_result.get("calibration_datasets", [])
    if calibration_datasets is None:
        calibration_datasets = []
    if not isinstance(calibration_datasets, list):
        raise TypeError("ingestion_result calibration_datasets must be a list.")

    if calibration_datasets:
        existing = require_list(
            getattr(state, "calibration_datasets", []),
            "state.calibration_datasets",
        )
        merged = existing + [item for item in calibration_datasets if isinstance(item, dict)]
        state.calibration_datasets = _dedupe_phase_four_records(
            merged,
            id_key="dataset_id",
        )
        state.update_timestamp()


def _merge_phase_four_normalization(
    state: CanonicalFacilityState,
    normalization_result: dict[str, Any] | None,
) -> None:
    if not normalization_result:
        return

    calibration_datasets = normalization_result.get("calibration_datasets", [])
    if calibration_datasets is None:
        calibration_datasets = []
    if not isinstance(calibration_datasets, list):
        raise TypeError("normalization_result calibration_datasets must be a list.")

    if calibration_datasets:
        existing = require_list(
            getattr(state, "calibration_datasets", []),
            "state.calibration_datasets",
        )
        merged = existing + [item for item in calibration_datasets if isinstance(item, dict)]
        state.calibration_datasets = _dedupe_phase_four_records(
            merged,
            id_key="dataset_id",
        )
        state.update_timestamp()


def _merge_phase_four_translation(
    state: CanonicalFacilityState,
    translation_result: dict[str, Any] | None,
) -> None:
    if not translation_result:
        return

    assumption_registry = translation_result.get("assumption_registry")
    assumptions = translation_result.get("assumptions", [])

    if assumption_registry is None:
        assumption_registry = []
    if not isinstance(assumption_registry, list):
        raise TypeError("translation_result assumption_registry must be a list.")
    if not isinstance(assumptions, list):
        raise TypeError("translation_result assumptions must be a list.")

    normalized_registry: list[dict[str, Any]] = []

    for item in assumption_registry:
        if isinstance(item, dict):
            normalized_registry.append(item)

    if not normalized_registry:
        for index, item in enumerate(assumptions, start=1):
            if not isinstance(item, dict):
                continue

            assumption_id = item.get("assumption_id")
            if not isinstance(assumption_id, str) or not assumption_id.strip():
                assumption_id = f"translation_assumption_{index:03d}"

            parameter_path = item.get("parameter_path")
            if not isinstance(parameter_path, str) or not parameter_path.strip():
                parameter_path = item.get("field_path", "")
            if not isinstance(parameter_path, str):
                parameter_path = ""

            normalized_registry.append(
                {
                    "assumption_id": assumption_id.strip(),
                    "field_path": parameter_path.strip(),
                    "parameter_path": parameter_path.strip(),
                    "assumption_value": item.get("assumption_value", item.get("nominal_value")),
                    "nominal_value": item.get("nominal_value", item.get("assumption_value")),
                    "bounds": require_dict(
                        item.get("bounds", {}),
                        "translation.assumption.bounds",
                    ),
                    "rationale": str(item.get("rationale", "")).strip(),
                    "created_by": str(item.get("created_by", "translation")).strip() or "translation",
                    "created_by_stage": str(
                        item.get("created_by_stage", item.get("created_by", "translation"))
                    ).strip() or "translation",
                    "status": str(item.get("status", "ACTIVE")).strip() or "ACTIVE",
                    "evidence_refs": [
                        str(value).strip()
                        for value in require_list(
                            item.get("evidence_refs", []),
                            "translation.assumption.evidence_refs",
                        )
                        if str(value).strip()
                    ],
                    "metadata": require_dict(
                        item.get("metadata", {}),
                        "translation.assumption.metadata",
                    ),
                }
            )

    if normalized_registry:
        existing = require_list(
            getattr(state, "assumption_registry", []),
            "state.assumption_registry",
        )
        merged = existing + normalized_registry
        state.assumption_registry = _dedupe_phase_four_records(
            merged,
            id_key="assumption_id",
        )
        state.update_timestamp()

def _merge_artifacts(
    state: CanonicalFacilityState,
    ingestion_result: dict[str, Any] | None,
) -> None:
    if not ingestion_result:
        return

    artifacts = ingestion_result.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = ingestion_result.get("artifacts_discovered", [])

    if not isinstance(artifacts, list):
        raise TypeError("ingestion_result artifacts payload must be a list.")

    state.add_artifacts([item for item in artifacts if isinstance(item, dict)])

    status = ingestion_result.get("status")
    if isinstance(status, str) and status.strip():
        state.set_stage_status("ingestion", status.strip())


def _merge_extraction(
    state: CanonicalFacilityState,
    extraction_result: dict[str, Any] | None,
) -> None:
    if not extraction_result:
        return

    entities = extraction_result.get("entities")
    if not isinstance(entities, list):
        entities = extraction_result.get("candidate_entities", [])

    topology_cues = extraction_result.get("topology_cues", [])
    source_anchors = extraction_result.get("source_anchors", [])

    if not isinstance(entities, list):
        raise TypeError("extraction_result entities payload must be a list.")
    if not isinstance(topology_cues, list):
        raise TypeError("extraction_result topology_cues payload must be a list.")
    if not isinstance(source_anchors, list):
        raise TypeError("extraction_result source_anchors payload must be a list.")

    state.add_entities([item for item in entities if isinstance(item, dict)])
    state.add_topology_cues([item for item in topology_cues if isinstance(item, dict)])
    state.add_source_anchors([item for item in source_anchors if isinstance(item, dict)])

    status = extraction_result.get("status")
    if isinstance(status, str) and status.strip():
        state.set_stage_status("extraction", status.strip())


def _merge_interview(
    state: CanonicalFacilityState,
    interview_result: dict[str, Any] | None,
) -> None:
    if not interview_result:
        return

    status = interview_result.get("status")
    if isinstance(status, str) and status.strip():
        state.set_stage_status("gap_resolution::interview", status.strip())


def _merge_normalization(
    state: CanonicalFacilityState,
    normalization_result: dict[str, Any] | None,
) -> None:
    if not normalization_result:
        return

    normalized_input = normalization_result.get("normalized_input", {})
    validation_report = normalization_result.get("validation_report", {})
    followup_questions = normalization_result.get("followup_questions", [])

    if not isinstance(normalized_input, dict):
        raise TypeError("normalization_result normalized_input must be a dict.")
    if not isinstance(validation_report, dict):
        raise TypeError("normalization_result validation_report must be a dict.")
    if not isinstance(followup_questions, list):
        raise TypeError("normalization_result followup_questions must be a list.")

    state.set_normalized_input(
        normalized_input=normalized_input,
        validation_report=validation_report,
        followup_questions=[item for item in followup_questions if isinstance(item, dict)],
    )

    status = normalization_result.get("status")
    if isinstance(status, str) and status.strip():
        state.set_stage_status("normalization", status.strip())

def _source_refs_for_parameter_paths(
    state: CanonicalFacilityState,
    parameter_paths: list[str],
) -> list[str]:
    source_ref: list[str] = []
    normalized_paths = {
        path.strip()
        for path in parameter_paths
        if isinstance(path, str) and path.strip()
    }
    if not normalized_paths:
        return []

    anchor_lookup = _anchor_lookup(state.source_anchors)

    for entity in state.entities:
        if not isinstance(entity, dict):
            continue
        attributes = require_dict(entity.get("attributes", {}), "entity.attributes")
        parameter_path = attributes.get("parameter_path")
        if not isinstance(parameter_path, str) or parameter_path.strip() not in normalized_paths:
            continue

        entity_id = entity.get("entity_id")
        if isinstance(entity_id, str) and entity_id.strip():
            source_ref.append(entity_id.strip())

        anchor_id = entity.get("source_anchor_id")
        if isinstance(anchor_id, str) and anchor_id.strip():
            source_ref.append(anchor_id.strip())
            anchor_payload = anchor_lookup.get(anchor_id.strip(), {})
            artifact_id = anchor_payload.get("artifact_id")
            if isinstance(artifact_id, str) and artifact_id.strip():
                source_ref.append(artifact_id.strip())

    return deduplicate_strings(source_ref)


def _source_refs_for_topology_cues(
    state: CanonicalFacilityState,
) -> list[str]:
    source_ref: list[str] = []

    for cue in state.topology_cues:
        if not isinstance(cue, dict):
            continue

        artifact_id = cue.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id.strip():
            source_ref.append(artifact_id.strip())

        cue_type = cue.get("type")
        if isinstance(cue_type, str) and cue_type.strip():
            source_ref.append(cue_type.strip())

    return deduplicate_strings(source_ref)


def _wrapped_field(
    value: Any,
    *,
    unit: str | None = None,
    status: str | None = None,
    source_refs: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    normalized_status = status
    if normalized_status is None:
        normalized_status = "observed" if value is not None else "missing"

    payload: dict[str, Any] = {
        "value": value,
        "status": normalized_status,
        "source_refs": deduplicate_strings(source_refs or []),
        "conflict_refs": [],
        "notes": notes or [],
    }
    if unit is not None:
        payload["unit"] = unit
    return payload


def _build_transformer_models(
    state: CanonicalFacilityState,
    facility: dict[str, Any],
) -> list[dict[str, Any]]:
    transformers = require_dict(facility.get("transformers", {}), "facility.transformers")
    count_raw = transformers.get("count")
    ratings_raw = require_list(transformers.get("ratings_mva", []), "facility.transformers.ratings_mva")

    count = 0
    if isinstance(count_raw, int) and count_raw > 0:
        count = count_raw
    elif ratings_raw:
        count = len(ratings_raw)

    if count <= 0:
        return []

    rating_refs = _source_refs_for_parameter_paths(
        state,
        ["facility.transformers.count", "facility.transformers.ratings_mva"],
    )

    models: list[dict[str, Any]] = []
    for index in range(count):
        rating_value = ratings_raw[index] if index < len(ratings_raw) else None
        models.append(
            {
                "transformer_id": f"transformer_{index + 1:03d}",
                "name": None,
                "role": None,
                "primary_voltage_kv": _wrapped_field(
                    None,
                    unit="kV",
                    source_refs=[],
                ),
                "secondary_voltage_kv": _wrapped_field(
                    None,
                    unit="kV",
                    source_refs=[],
                ),
                "rating_mva": _wrapped_field(
                    rating_value,
                    unit="MVA",
                    source_refs=rating_refs,
                ),
                "impedance_percent": _wrapped_field(
                    None,
                    unit="%",
                    source_refs=[],
                ),
                "cooling_class": _wrapped_field(
                    None,
                    source_refs=[],
                ),
            }
        )

    return models


def _build_load_blocks(
    state: CanonicalFacilityState,
    facility: dict[str, Any],
) -> tuple[list[dict[str, Any]], float | None, float | None]:
    load_schedule = require_dict(facility.get("load_schedule", {}), "facility.load_schedule")
    block_entries: list[tuple[str, Any]] = []

    for key, value in load_schedule.items():
        if isinstance(key, str) and key.strip():
            block_entries.append((key.strip(), value))

    block_entries.sort(key=lambda item: item[0])

    load_blocks: list[dict[str, Any]] = []
    numeric_values: list[float] = []
    load_refs = _source_refs_for_parameter_paths(
        state,
        [
            "facility.load_schedule.phase_1_mw",
            "facility.load_schedule.phase_2_mw",
            "facility.load_schedule.phase_3_mw",
        ],
    )

    for index, (phase_name, phase_value) in enumerate(block_entries, start=1):
        numeric_value = safe_float(phase_value)
        if numeric_value is not None:
            numeric_values.append(numeric_value)

        load_blocks.append(
            {
                "load_block_id": f"load_block_{index:03d}",
                "name": phase_name,
                "load_type": "facility_phase",
                "connected_load_mw": _wrapped_field(
                    numeric_value,
                    unit="MW",
                    source_refs=load_refs,
                ),
                "demand_load_mw": _wrapped_field(
                    numeric_value,
                    unit="MW",
                    source_refs=load_refs,
                ),
                "criticality_class": _wrapped_field(
                    None,
                    source_refs=[],
                ),
            }
        )

    peak_demand = max(numeric_values) if numeric_values else None
    minimum_demand = min(numeric_values) if numeric_values else None
    return load_blocks, peak_demand, minimum_demand


def _build_ups_models(
    state: CanonicalFacilityState,
    facility: dict[str, Any],
) -> list[dict[str, Any]]:
    ups = require_dict(facility.get("ups", {}), "facility.ups")
    if not ups:
        return []

    topology = ups.get("topology")
    count = ups.get("count")
    count_value = count if isinstance(count, int) else safe_float(count)

    ups_refs = _source_refs_for_parameter_paths(
        state,
        ["facility.ups.topology", "facility.ups.count"],
    )

    return [
        {
            "ups_id": "ups_001",
            "name": None,
            "topology": _wrapped_field(
                topology,
                source_refs=ups_refs,
            ),
            "redundancy_configuration": _wrapped_field(
                None,
                source_refs=[],
            ),
            "module_count": _wrapped_field(
                count_value,
                unit="count",
                source_refs=ups_refs,
            ),
            "module_rating_kw": _wrapped_field(
                None,
                unit="kW",
                source_refs=[],
            ),
            "total_rating_mw": _wrapped_field(
                None,
                unit="MW",
                source_refs=[],
            ),
            "battery_backup_minutes": _wrapped_field(
                None,
                unit="minutes",
                source_refs=[],
            ),
            "inverter_based_fraction": _wrapped_field(
                None,
                unit="pu",
                source_refs=[],
            ),
        }
    ]


def _build_generator_models(
    state: CanonicalFacilityState,
    facility: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    generators = require_dict(facility.get("generators", {}), "facility.generators")
    present = generators.get("present")
    count = generators.get("count")

    count_value = count if isinstance(count, int) else safe_float(count)
    generator_refs = _source_refs_for_parameter_paths(
        state,
        ["facility.generators.present", "facility.generators.count"],
    )

    plant_present = _wrapped_field(
        present,
        source_refs=generator_refs,
    )

    if present is not True and count_value in (None, 0):
        return plant_present, []

    return plant_present, [
        {
            "generator_id": "generator_group_001",
            "name": None,
            "prime_mover_type": _wrapped_field(
                None,
                source_refs=[],
            ),
            "rating_mw": _wrapped_field(
                None,
                unit="MW",
                source_refs=[],
            ),
            "count": _wrapped_field(
                count_value,
                unit="count",
                source_refs=generator_refs,
                status="observed" if count_value is not None else "missing",
            ),
            "dispatch_mode": _wrapped_field(
                None,
                source_refs=[],
            ),
            "parallel_operation_supported": _wrapped_field(
                None,
                source_refs=[],
            ),
        }
    ]


def _build_buildout_phases(
    state: CanonicalFacilityState,
    facility: dict[str, Any],
) -> list[dict[str, Any]]:
    load_schedule = require_dict(facility.get("load_schedule", {}), "facility.load_schedule")
    phase_entries: list[tuple[str, Any]] = []

    for key, value in load_schedule.items():
        if isinstance(key, str) and key.strip():
            phase_entries.append((key.strip(), value))

    phase_entries.sort(key=lambda item: item[0])
    phase_refs = _source_refs_for_parameter_paths(
        state,
        [
            "facility.load_schedule.phase_1_mw",
            "facility.load_schedule.phase_2_mw",
            "facility.load_schedule.phase_3_mw",
        ],
    )

    phases: list[dict[str, Any]] = []
    for index, (phase_name, phase_value) in enumerate(phase_entries, start=1):
        phases.append(
            {
                "phase_id": f"phase_{index:03d}",
                "phase_name": phase_name,
                "target_in_service_date": None,
                "incremental_load_mw": _wrapped_field(
                    safe_float(phase_value),
                    unit="MW",
                    source_refs=phase_refs,
                ),
            }
        )

    return phases


def _build_engineering_model(
    state: CanonicalFacilityState,
) -> dict[str, Any] | None:
    normalized_input = require_dict(state.normalized_input, "state.normalized_input")
    if not normalized_input:
        return None

    facility = require_dict(normalized_input.get("facility", {}), "normalized_input.facility")
    source_summary = require_dict(
        normalized_input.get("source_summary", {}),
        "normalized_input.source_summary",
    )

    poi_refs = _source_refs_for_parameter_paths(state, ["facility.poi_voltage_kv"])
    topology_refs = _source_refs_for_topology_cues(state)

    load_blocks, peak_demand, minimum_demand = _build_load_blocks(state, facility)
    transformers = _build_transformer_models(state, facility)
    ups_systems = _build_ups_models(state, facility)
    generator_plant_present, generator_units = _build_generator_models(state, facility)
    buildout_phases = _build_buildout_phases(state, facility)

    topology_label = None
    if state.topology_cues:
        first_cue = next(
            (cue for cue in state.topology_cues if isinstance(cue, dict)),
            None,
        )
        if first_cue is not None:
            cue_type = first_cue.get("type")
            if isinstance(cue_type, str) and cue_type.strip():
                topology_label = cue_type.strip()

    engineering_model: dict[str, Any] = {
        "schema_name": "gridsenpai_canonical_facility_model",
        "schema_version": str(normalized_input.get("schema_version", "0.1.0")),
        "project_context": {
            "project_id": None,
            "run_id": state.run_id,
            "project_name": facility.get("project_name"),
            "facility_name": facility.get("project_name"),
            "facility_type": None,
            "region": None,
            "utility_or_iso": None,
            "transmission_owner": None,
            "queue_position": None,
            "study_type": None,
            "study_revision": None,
        },
        "interconnection_context": {
            "interconnection_type": _wrapped_field(
                None,
                source_refs=[],
            ),
            "point_of_interconnection": {
                "poi_name": _wrapped_field(
                    None,
                    source_refs=[],
                ),
                "poi_voltage_kv": _wrapped_field(
                    facility.get("poi_voltage_kv"),
                    unit="kV",
                    source_refs=poi_refs,
                ),
                "poi_substation_name": _wrapped_field(
                    None,
                    source_refs=[],
                ),
                "poi_line_or_bus_name": _wrapped_field(
                    None,
                    source_refs=[],
                ),
                "interconnecting_line_owner": _wrapped_field(
                    None,
                    source_refs=[],
                ),
            },
            "substation_topology": {
                "switching_scheme": _wrapped_field(
                    topology_label,
                    source_refs=topology_refs,
                ),
                "breaker_count": _wrapped_field(
                    None,
                    unit="count",
                    source_refs=topology_refs,
                ),
                "bus_section_count": _wrapped_field(
                    None,
                    unit="count",
                    source_refs=topology_refs,
                ),
                "tie_breaker_present": _wrapped_field(
                    None,
                    source_refs=topology_refs,
                ),
                "topology_notes": [],
            },
            "required_interconnection_facilities": {
                "customer_side_facilities": [],
                "utility_side_facilities": [],
                "network_upgrades": [],
            },
        },
        "facility_electrical_system": {
            "utility_service": {
                "service_voltage_kv": _wrapped_field(
                    facility.get("poi_voltage_kv"),
                    unit="kV",
                    source_refs=poi_refs,
                ),
                "service_configuration": _wrapped_field(
                    None,
                    source_refs=[],
                ),
            },
            "transformers": transformers,
            "medium_voltage_switchgear": [],
            "low_voltage_switchgear": [],
            "feeders": [],
            "distribution_buses": [],
        },
        "load_system": {
            "peak_demand_mw": _wrapped_field(
                peak_demand,
                unit="MW",
                source_refs=_source_refs_for_parameter_paths(
                    state,
                    [
                        "facility.load_schedule.phase_1_mw",
                        "facility.load_schedule.phase_2_mw",
                        "facility.load_schedule.phase_3_mw",
                    ],
                ),
                status="derived" if peak_demand is not None else "missing",
                notes=["Derived from normalized_input facility.load_schedule."],
            ),
            "minimum_demand_mw": _wrapped_field(
                minimum_demand,
                unit="MW",
                source_refs=_source_refs_for_parameter_paths(
                    state,
                    [
                        "facility.load_schedule.phase_1_mw",
                        "facility.load_schedule.phase_2_mw",
                        "facility.load_schedule.phase_3_mw",
                    ],
                ),
                status="derived" if minimum_demand is not None else "missing",
                notes=["Derived from normalized_input facility.load_schedule."],
            ),
            "load_blocks": load_blocks,
            "composition": {
                "it_load_fraction": _wrapped_field(
                    None,
                    unit="pu",
                    source_refs=[],
                ),
                "mechanical_load_fraction": _wrapped_field(
                    None,
                    unit="pu",
                    source_refs=[],
                ),
                "auxiliary_load_fraction": _wrapped_field(
                    None,
                    unit="pu",
                    source_refs=[],
                ),
            },
        },
        "power_conversion_and_ups": {
            "ups_systems": ups_systems,
            "static_transfer_switches": [],
            "battery_systems": [],
        },
        "backup_power_system": {
            "generator_plant_present": generator_plant_present,
            "generator_units": generator_units,
            "fuel_system": {
                "fuel_type": _wrapped_field(
                    None,
                    source_refs=[],
                ),
                "onsite_fuel_hours": _wrapped_field(
                    None,
                    unit="hours",
                    source_refs=[],
                ),
            },
        },
        "buildout_and_ramping": {
            "buildout_phases": buildout_phases,
            "ramp_characteristics": {
                "normal_ramp_rate_mw_per_min": _wrapped_field(
                    None,
                    unit="MW/min",
                    source_refs=[],
                ),
                "block_load_step_mw": _wrapped_field(
                    peak_demand,
                    unit="MW",
                    source_refs=_source_refs_for_parameter_paths(
                        state,
                        [
                            "facility.load_schedule.phase_1_mw",
                            "facility.load_schedule.phase_2_mw",
                            "facility.load_schedule.phase_3_mw",
                        ],
                    ),
                    status="derived" if peak_demand is not None else "missing",
                    notes=["Derived as the largest normalized load schedule phase value."],
                ),
            },
        },
        "engineering_model_metadata": {
            "hydrated_by": "canonical_state_service",
            "hydration_method": "deterministic_from_normalized_input",
            "source_summary": source_summary,
        },
    }

    return engineering_model


def _merge_engineering_model(
    state: CanonicalFacilityState,
) -> None:
    engineering_model = _build_engineering_model(state)
    if engineering_model is None:
        return
    state.set_engineering_model(engineering_model)

def _merge_retrieval(
    state: CanonicalFacilityState,
    retrieval_result: dict[str, Any] | None,
) -> None:
    if not retrieval_result:
        return

    snippets = retrieval_result.get("snippets", [])
    if not isinstance(snippets, list):
        raise TypeError("retrieval_result snippets must be a list.")

    state.add_evidence([item for item in snippets if isinstance(item, dict)])

    status = retrieval_result.get("status")
    if isinstance(status, str) and status.strip():
        state.set_stage_status("gap_resolution::retrieval", status.strip())


def _merge_translation(
    state: CanonicalFacilityState,
    translation_result: dict[str, Any] | None,
) -> None:
    if not translation_result:
        return

    model_outputs = translation_result.get("model_outputs", {})
    output_parameters = translation_result.get("output_parameters", [])
    assumptions = translation_result.get("assumptions", [])

    if not isinstance(model_outputs, dict):
        raise TypeError("translation_result model_outputs must be a dict.")
    if not isinstance(output_parameters, list):
        raise TypeError("translation_result output_parameters must be a list.")
    if not isinstance(assumptions, list):
        raise TypeError("translation_result assumptions must be a list.")

    state.set_translation_outputs(
        model_outputs=model_outputs,
        output_parameters=[item for item in output_parameters if isinstance(item, dict)],
        assumptions=[item for item in assumptions if isinstance(item, dict)],
    )

    status = translation_result.get("status")
    if isinstance(status, str) and status.strip():
        state.set_stage_status("translation", status.strip())



def _merge_scenarios(
    state: CanonicalFacilityState,
    scenario_result: dict[str, Any] | None,
) -> None:
    if not scenario_result:
        return

    scenarios = scenario_result.get("scenarios", {})
    if not isinstance(scenarios, dict):
        raise TypeError("scenario_result scenarios must be a dict.")

    normalized_scenarios: dict[str, Any] = {}
    for label, payload in scenarios.items():
        if isinstance(label, str) and label.strip() and isinstance(payload, dict):
            normalized_scenarios[label] = payload

    state.set_scenarios(normalized_scenarios)

    status = scenario_result.get("status")
    if isinstance(status, str) and status.strip():
        state.set_stage_status("scenarios", status.strip())


def _build_state(
    build_inputs: CanonicalStateBuildInputs,
) -> CanonicalFacilityState:
    run_id = require_run_id(build_inputs.run_id)

    validate_stage_run_id(run_id, build_inputs.ingestion_result, "ingestion")
    validate_stage_run_id(run_id, build_inputs.extraction_result, "extraction")
    validate_stage_run_id(run_id, build_inputs.interview_result, "gap_resolution::interview")
    validate_stage_run_id(run_id, build_inputs.normalization_result, "normalization")
    validate_stage_run_id(run_id, build_inputs.retrieval_result, "gap_resolution::retrieval")
    validate_stage_run_id(run_id, build_inputs.translation_result, "translation")
    validate_stage_run_id(run_id, build_inputs.scenario_result, "scenarios")
    validate_stage_run_id(run_id, build_inputs.existing_state, "existing_state")

    existing_state_payload = require_dict(build_inputs.existing_state, "existing_state")
    if existing_state_payload:
        state = CanonicalFacilityState.from_dict(existing_state_payload)
    else:
        state = build_empty_canonical_state(run_id)

    _merge_artifacts(state, build_inputs.ingestion_result)
    _merge_phase_four_ingestion(state, build_inputs.ingestion_result)

    _merge_extraction(state, build_inputs.extraction_result)
    _merge_interview(state, build_inputs.interview_result)

    _merge_normalization(state, build_inputs.normalization_result)
    _merge_phase_four_normalization(state, build_inputs.normalization_result)
    _merge_engineering_model(state)

    _merge_retrieval(state, build_inputs.retrieval_result)

    _merge_translation(state, build_inputs.translation_result)
    _merge_phase_four_translation(state, build_inputs.translation_result)

    _merge_scenarios(state, build_inputs.scenario_result)

    return state


def _anchor_lookup(source_anchors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for anchor in source_anchors:
        if not isinstance(anchor, dict):
            continue
        anchor_id = anchor.get("anchor_id")
        if isinstance(anchor_id, str) and anchor_id.strip():
            lookup[anchor_id] = anchor
    return lookup


def _snippet_lookup(snippets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        snippet_id = snippet.get("snippet_id")
        if isinstance(snippet_id, str) and snippet_id.strip():
            lookup[snippet_id] = snippet
    return lookup


def _build_extraction_field_records(
    state: CanonicalFacilityState,
    extraction_result: dict[str, Any] | None,
    next_index: int,
) -> tuple[list[dict[str, Any]], int]:
    if not extraction_result:
        return [], next_index

    schema_field_candidates = require_list(
        extraction_result.get("schema_field_candidates", []),
        "extraction_result.schema_field_candidates",
    )
    if not schema_field_candidates:
        return [], next_index

    source_anchor_lookup = _anchor_lookup(state.source_anchors)
    validation_report = require_dict(state.validation_report, "validation_report")
    schema_valid = bool(validation_report.get("schema_valid", False))
    missing_paths = set(extract_missing_field_paths(validation_report))

    records: list[dict[str, Any]] = []

    for candidate in schema_field_candidates:
        if not isinstance(candidate, dict):
            continue

        field_path_raw = candidate.get("field_path")
        if not isinstance(field_path_raw, str) or not field_path_raw.strip():
            continue

        field_path = field_path_raw.strip()
        source_anchor_ids = deduplicate_strings(
            list(require_list(candidate.get("source_anchor_ids", []), "schema_field_candidate.source_anchor_ids"))
            + list(require_list(candidate.get("source_ref", []), "schema_field_candidate.source_ref"))
        )
        source_ref: list[str] = deduplicate_strings(
            list(source_anchor_ids)
            + list(require_list(candidate.get("source_ref", []), "schema_field_candidate.source_ref"))
        )

        for anchor_id in source_anchor_ids:
            anchor_payload = source_anchor_lookup.get(anchor_id, {})
            artifact_id = anchor_payload.get("artifact_id")
            if isinstance(artifact_id, str) and artifact_id.strip():
                source_ref.append(artifact_id)

        evidence_payload = require_list(candidate.get("evidence", []), "schema_field_candidate.evidence")
        source_artifact_id = candidate.get("source_artifact_id") or candidate.get("artifact_id")
        if isinstance(source_artifact_id, str) and source_artifact_id.strip():
            source_ref.append(source_artifact_id.strip())
        for evidence_item in evidence_payload:
            if not isinstance(evidence_item, dict):
                continue
            artifact_id = evidence_item.get("artifact_id")
            if isinstance(artifact_id, str) and artifact_id.strip():
                source_ref.append(artifact_id)
            anchor_id = evidence_item.get("anchor_id")
            if isinstance(anchor_id, str) and anchor_id.strip():
                source_ref.append(anchor_id)

        source_ref = deduplicate_strings(source_ref)

        confidence_score = safe_float(candidate.get("confidence"))
        confidence_tag = str(
            candidate.get("confidence_label")
            or confidence_tag_from_score(confidence_score)
        ).strip().upper()

        if confidence_score is None:
            confidence_score = confidence_score_from_tag(confidence_tag)

        value = candidate.get("value")
        status_text = str(candidate.get("status", "")).strip().lower()
        is_missing = field_path in missing_paths or value is None or status_text == "missing"

        metadata = require_dict(candidate.get("metadata", {}), "schema_field_candidate.metadata")
        notes = [
            str(item).strip()
            for item in require_list(candidate.get("notes", []), "schema_field_candidate.notes")
            if isinstance(item, str) and item.strip()
        ]

        record = {
            "field_record_id": f"field_{next_index:05d}",
            "field_path": field_path,
            "value": value,
            "source_stage": "extraction",
            "source_type": "schema_field_candidate",
            "source_ref": source_ref,
            "confidence_score": round(confidence_score, 2) if confidence_score is not None else None,
            "confidence_tag": confidence_tag,
            "validation_status": validation_status_from_context(
                schema_valid=schema_valid,
                has_conflict=False,
                is_missing=is_missing,
                confidence_tag=confidence_tag,
            ),
            "review_status": review_status_from_context(
                has_conflict=False,
                is_missing=is_missing,
                confidence_tag=confidence_tag,
            ),
            "evidence_strength": evidence_strength_from_sources(
                source_type="schema_field_candidate",
                source_ref=source_ref,
                confidence_tag=confidence_tag,
            ),
            "conflict_status": "NO_CONFLICT",
            "is_missing": is_missing,
            "metadata": {
                "record_origin": "extraction.schema_field_candidate",
                "candidate_id": candidate.get("candidate_id"),
                "candidate_status": candidate.get("status"),
                "source_method": candidate.get("source_method") or candidate.get("method"),
                "source_anchor_ids": source_anchor_ids,
                "source_artifact_id": source_artifact_id,
                "artifact_id": source_artifact_id,
                "page_number": candidate.get("page_number"),
                "worker_name": candidate.get("worker_name"),
                "region_type": candidate.get("region_type"),
                "evidence_count": len(evidence_payload),
                "notes": notes,
                "candidate_metadata": metadata,
                "unit": candidate.get("unit"),
            },
        }
        records.append(record)
        next_index += 1

    return records, next_index


def _build_normalized_input_field_records(
    state: CanonicalFacilityState,
    next_index: int,
) -> tuple[list[dict[str, Any]], int]:
    normalized_input = require_dict(state.normalized_input, "normalized_input")
    validation_report = require_dict(state.validation_report, "validation_report")

    source_anchor_lookup = _anchor_lookup(state.source_anchors)
    entity_map: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for entity in state.entities:
        if not isinstance(entity, dict):
            continue
        attributes = require_dict(entity.get("attributes", {}), "entity.attributes")
        parameter_path = attributes.get("parameter_path")
        if isinstance(parameter_path, str) and parameter_path.strip():
            entity_map[parameter_path.strip()].append(entity)

    schema_valid = bool(validation_report.get("schema_valid", False))
    missing_paths = set(extract_missing_field_paths(validation_report))
    records: list[dict[str, Any]] = []

    for field_path, value in flatten_scalar_paths(normalized_input):
        normalized_field_path = field_path
        if normalized_field_path.startswith("facility."):
            canonical_field_path = normalized_field_path
        else:
            canonical_field_path = normalized_field_path

        related_entities = entity_map.get(canonical_field_path, [])
        related_anchor_ids = deduplicate_strings(
            entity.get("source_anchor_id")
            for entity in related_entities
            if isinstance(entity, dict)
        )

        source_ref = []
        for anchor_id in related_anchor_ids:
            source_ref.append(anchor_id)
            anchor_payload = source_anchor_lookup.get(anchor_id, {})
            artifact_id = anchor_payload.get("artifact_id")
            if isinstance(artifact_id, str) and artifact_id.strip():
                source_ref.append(artifact_id)

        source_ref = deduplicate_strings(source_ref)
        is_missing = canonical_field_path in missing_paths or value is None
        confidence_score = 0.80 if source_ref else 0.55
        confidence_tag = confidence_tag_from_score(confidence_score)

        record = {
            "field_record_id": f"field_{next_index:05d}",
            "field_path": canonical_field_path,
            "value": value,
            "source_stage": "normalization",
            "source_type": "normalized_input",
            "source_ref": source_ref,
            "confidence_score": round(confidence_score, 2),
            "confidence_tag": confidence_tag,
            "validation_status": validation_status_from_context(
                schema_valid=schema_valid,
                has_conflict=False,
                is_missing=is_missing,
                confidence_tag=confidence_tag,
            ),
            "review_status": review_status_from_context(
                has_conflict=False,
                is_missing=is_missing,
                confidence_tag=confidence_tag,
            ),
            "evidence_strength": evidence_strength_from_sources(
                source_type="normalized_input",
                source_ref=source_ref,
                confidence_tag=confidence_tag,
            ),
            "conflict_status": "NO_CONFLICT",
            "is_missing": is_missing,
            "metadata": {
                "record_origin": "normalized_input",
                "related_entity_ids": deduplicate_strings(
                    entity.get("entity_id")
                    for entity in related_entities
                    if isinstance(entity, dict)
                ),
                "source_anchor_ids": related_anchor_ids,
                "source_schema_valid": schema_valid,
            },
        }
        records.append(record)
        next_index += 1

    return records, next_index


def _build_retrieval_field_records(
    state: CanonicalFacilityState,
    retrieval_result: dict[str, Any] | None,
    next_index: int,
) -> tuple[list[dict[str, Any]], int]:
    if not retrieval_result:
        return [], next_index

    validation_report = require_dict(state.validation_report, "validation_report")
    schema_valid = bool(validation_report.get("schema_valid", False))
    records: list[dict[str, Any]] = []

    equipment_resolution = require_dict(
        retrieval_result.get("equipment_reference_resolution", {}),
        "retrieval_result.equipment_reference_resolution",
    )

    candidate_fields = require_list(
        equipment_resolution.get("candidate_fields", []),
        "retrieval_result.equipment_reference_resolution.candidate_fields",
    )
    matched_records = require_list(
        equipment_resolution.get("matched_records", []),
        "retrieval_result.equipment_reference_resolution.matched_records",
    )
    unresolved_missing_fields = deduplicate_strings(
        require_list(
            equipment_resolution.get("unresolved_missing_fields", []),
            "retrieval_result.equipment_reference_resolution.unresolved_missing_fields",
        )
    )
    review_required_fields = set(
        deduplicate_strings(
            require_list(
                equipment_resolution.get("review_required_fields", []),
                "retrieval_result.equipment_reference_resolution.review_required_fields",
            )
        )
    )
    official_sources = require_list(
        equipment_resolution.get("official_source_candidates", []),
        "retrieval_result.equipment_reference_resolution.official_source_candidates",
    )
    pdf_sources = require_list(
        equipment_resolution.get("pdf_repository_candidates", []),
        "retrieval_result.equipment_reference_resolution.pdf_repository_candidates",
    )

    shared_source_refs = deduplicate_strings(
        [
            str(item.get("source_ref", "")).strip()
            for item in matched_records
            if isinstance(item, dict) and str(item.get("source_ref", "")).strip()
        ]
        + [
            str(item.get("source_url", "")).strip()
            for item in official_sources
            if isinstance(item, dict) and str(item.get("source_url", "")).strip()
        ]
        + [
            str(item.get("source_ref", "")).strip()
            for item in pdf_sources
            if isinstance(item, dict) and str(item.get("source_ref", "")).strip()
        ]
    )

    for candidate in candidate_fields:
        if not isinstance(candidate, dict):
            continue

        field_path = str(
            candidate.get("canonical_field_key")
            or candidate.get("matched_field_key")
            or candidate.get("spec_field")
            or ""
        ).strip()
        if not field_path:
            continue

        confidence_score = safe_float(candidate.get("confidence"))
        confidence_tag = confidence_tag_from_score(confidence_score)
        is_missing = candidate.get("value") is None
        review_required = bool(candidate.get("review_required")) or field_path in review_required_fields

        source_ref = deduplicate_strings(
            shared_source_refs
            + [
                str(candidate.get("source_ref", "")).strip(),
                str(candidate.get("source_url", "")).strip(),
            ]
        )

        records.append(
            {
                "field_record_id": f"field_{next_index:05d}",
                "field_path": field_path,
                "value": candidate.get("value"),
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "source_ref": source_ref,
                "confidence_score": round(confidence_score, 2) if confidence_score is not None else None,
                "confidence_tag": confidence_tag,
                "validation_status": "REVIEW_REQUIRED" if review_required else "PROVISIONAL_RETRIEVED",
                "review_status": "REVIEW_REQUIRED" if review_required else "PENDING_REVIEW",
                "evidence_strength": evidence_strength_from_sources(
                    source_type="equipment_reference_candidate",
                    source_ref=source_ref,
                    confidence_tag=confidence_tag,
                ),
                "conflict_status": "NO_CONFLICT",
                "is_missing": is_missing,
                "metadata": {
                    "record_origin": "retrieval.equipment_reference_resolution.candidate_field",
                    "equipment_family": candidate.get("equipment_family"),
                    "manufacturer": candidate.get("manufacturer"),
                    "model": candidate.get("model"),
                    "spec_field": candidate.get("spec_field"),
                    "matched_field_key": candidate.get("matched_field_key"),
                    "canonical_field_key": candidate.get("canonical_field_key"),
                    "confidence_reason": candidate.get("confidence_reason"),
                    "source_lookup_strategy": equipment_resolution.get("lookup_strategy"),
                    "review_required": review_required,
                    "source_type_detail": candidate.get("source_type"),
                },
            }
        )
        next_index += 1

    for field_path in unresolved_missing_fields:
        records.append(
            {
                "field_record_id": f"field_{next_index:05d}",
                "field_path": field_path,
                "value": None,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_unresolved",
                "source_ref": shared_source_refs,
                "confidence_score": None,
                "confidence_tag": "UNRESOLVED",
                "validation_status": "MISSING",
                "review_status": "REVIEW_REQUIRED",
                "evidence_strength": "UNKNOWN",
                "conflict_status": "NO_CONFLICT",
                "is_missing": True,
                "metadata": {
                    "record_origin": "retrieval.equipment_reference_resolution.unresolved_missing_field",
                    "lookup_strategy": equipment_resolution.get("lookup_strategy"),
                    "web_lookup_required": bool(equipment_resolution.get("web_lookup_required", False)),
                    "evidence_gap": bool(equipment_resolution.get("evidence_gap", False)),
                    "trigger_reasons": require_list(
                        equipment_resolution.get("trigger_reasons", []),
                        "retrieval_result.equipment_reference_resolution.trigger_reasons",
                    ),
                },
            }
        )
        next_index += 1

    return records, next_index



def _build_interview_field_records(
    state: CanonicalFacilityState,
    interview_result: dict[str, Any] | None,
    next_index: int,
) -> tuple[list[dict[str, Any]], int]:
    if not interview_result:
        return [], next_index

    records: list[dict[str, Any]] = []
    answers_confirmed = require_list(
        interview_result.get("answers_confirmed", []),
        "interview_result.answers_confirmed",
    )
    unresolved_fields = deduplicate_strings(
        require_list(interview_result.get("unresolved_fields", []), "interview_result.unresolved_fields")
    )

    for answer in answers_confirmed:
        if not isinstance(answer, dict):
            continue
        field_path = str(answer.get("field_path", "")).strip()
        if not field_path:
            continue
        value = answer.get("confirmed_answer", answer.get("value"))
        records.append(
            {
                "field_record_id": f"field_{next_index:05d}",
                "field_path": field_path,
                "value": value,
                "source_stage": "interview",
                "source_type": "human_input",
                "source_ref": ["engineer_input"],
                "confidence_score": 1.0,
                "confidence_tag": "HIGH",
                "validation_status": "INTERVIEW_CONFIRMED",
                "review_status": "RESOLVED",
                "evidence_strength": "STRONG",
                "conflict_status": "NO_CONFLICT",
                "is_missing": value is None,
                "metadata": {
                    "record_origin": "interview.answers_confirmed",
                    "question_id": answer.get("question_id"),
                    "source_context": answer.get("source_context"),
                    "confirmed_by": answer.get("confirmed_by", "applicant"),
                },
            }
        )
        next_index += 1

    for field_path in unresolved_fields:
        records.append(
            {
                "field_record_id": f"field_{next_index:05d}",
                "field_path": field_path,
                "value": None,
                "source_stage": "interview",
                "source_type": "interview_unresolved",
                "source_ref": ["interview_followup"],
                "confidence_score": None,
                "confidence_tag": "UNRESOLVED",
                "validation_status": "MISSING",
                "review_status": "REVIEW_REQUIRED",
                "evidence_strength": "UNKNOWN",
                "conflict_status": "NO_CONFLICT",
                "is_missing": True,
                "metadata": {
                    "record_origin": "interview.unresolved_fields",
                },
            }
        )
        next_index += 1

    return records, next_index



def _build_translation_field_records(
    state: CanonicalFacilityState,
    next_index: int,
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    validation_report = require_dict(state.validation_report, "validation_report")
    schema_valid = bool(validation_report.get("schema_valid", False))
    missing_paths = set(extract_missing_field_paths(validation_report))
    snippet_lookup = _snippet_lookup(state.evidence_snippets)

    for parameter in state.output_parameters:
        if not isinstance(parameter, dict):
            continue

        field_path_raw = parameter.get("parameter_path")
        if not isinstance(field_path_raw, str) or not field_path_raw.strip():
            continue

        canonical_field_path = field_path_raw.strip()
        confidence_score = safe_float(parameter.get("confidence_score"))
        confidence_tag = str(
            parameter.get("confidence_tag")
            or confidence_tag_from_score(confidence_score)
        ).strip().upper()

        if confidence_score is None:
            confidence_score = confidence_score_from_tag(confidence_tag)

        supporting_snippet_ids = deduplicate_strings(
            require_list(
                parameter.get("supporting_snippet_ids", []),
                "translation.output_parameter.supporting_snippet_ids",
            )
        )
        dependency_paths = deduplicate_strings(
            require_list(
                parameter.get("dependency_paths", []),
                "translation.output_parameter.dependency_paths",
            )
        )
        source_field_paths = deduplicate_strings(
            require_list(
                parameter.get("source_field_paths", []),
                "translation.output_parameter.source_field_paths",
            )
        )

        source_ref = deduplicate_strings(
            list(supporting_snippet_ids)
            + [parameter.get("provenance_ref")]
            + dependency_paths
            + source_field_paths
        )

        supporting_sources: list[str] = []
        for snippet_id in supporting_snippet_ids:
            snippet = snippet_lookup.get(snippet_id, {})
            source_ref_value = snippet.get("source_ref")
            if isinstance(source_ref_value, str) and source_ref_value.strip():
                supporting_sources.append(source_ref_value)

        source_ref.extend(deduplicate_strings(supporting_sources))
        source_ref = deduplicate_strings(source_ref)

        is_missing = canonical_field_path in missing_paths or parameter.get("value") is None

        record = {
            "field_record_id": f"field_{next_index:05d}",
            "field_path": canonical_field_path,
            "value": parameter.get("value"),
            "source_stage": "translation",
            "source_type": "translation_output",
            "source_ref": source_ref,
            "confidence_score": round(confidence_score, 2) if confidence_score is not None else None,
            "confidence_tag": confidence_tag,
            "validation_status": validation_status_from_context(
                schema_valid=schema_valid,
                has_conflict=False,
                is_missing=is_missing,
                confidence_tag=confidence_tag,
            ),
            "review_status": review_status_from_context(
                has_conflict=False,
                is_missing=is_missing,
                confidence_tag=confidence_tag,
            ),
            "evidence_strength": evidence_strength_from_sources(
                source_type="translation_output",
                source_ref=source_ref,
                confidence_tag=confidence_tag,
            ),
            "conflict_status": "NO_CONFLICT",
            "is_missing": is_missing,
            "metadata": {
                "record_origin": "output_parameter",
                "units": parameter.get("units"),
                "provenance_type": parameter.get("provenance_type"),
                "dependency_paths": dependency_paths,
                "source_field_paths": source_field_paths,
                "supporting_snippet_ids": supporting_snippet_ids,
                "confidence_factors": require_dict(
                    parameter.get("confidence_factors", {}),
                    "translation.output_parameter.confidence_factors",
                ),
            },
        }
        records.append(record)
        next_index += 1

    return records, next_index


def _build_missing_field_records(
    state: CanonicalFacilityState,
    existing_field_records: list[dict[str, Any]],
    next_index: int,
) -> tuple[list[dict[str, Any]], int]:
    validation_report = require_dict(state.validation_report, "validation_report")
    missing_paths = extract_missing_field_paths(validation_report)
    existing_paths = {
        str(record.get("field_path")).strip()
        for record in existing_field_records
        if isinstance(record, dict) and isinstance(record.get("field_path"), str)
    }

    synthesized_records: list[dict[str, Any]] = []

    for missing_path in missing_paths:
        if missing_path in existing_paths:
            continue

        synthesized_records.append(
            {
                "field_record_id": f"field_{next_index:05d}",
                "field_path": missing_path,
                "value": None,
                "source_stage": "validation",
                "source_type": "missing_field",
                "source_ref": [],
                "confidence_score": None,
                "confidence_tag": "UNRESOLVED",
                "validation_status": "MISSING",
                "review_status": "REVIEW_REQUIRED",
                "evidence_strength": "UNKNOWN",
                "conflict_status": "NO_CONFLICT",
                "is_missing": True,
                "metadata": {
                    "record_origin": "validation_report.missing_fields",
                },
            }
        )
        next_index += 1

    return synthesized_records, next_index


def _build_conflict_records(
    field_records: list[dict[str, Any]],
    validation_report: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in field_records:
        if not isinstance(record, dict):
            continue
        field_path = record.get("field_path")
        if isinstance(field_path, str) and field_path.strip():
            grouped[field_path.strip()].append(record)

    conflicts: list[dict[str, Any]] = []
    conflict_index = 1

    for field_path in sorted(grouped.keys()):
        records = grouped[field_path]
        comparable_values = {
            canonicalize_value_for_compare(record.get("value")): record.get("value")
            for record in records
        }

        if len(comparable_values) <= 1:
            continue

        conflicts.append(
            {
                "conflict_id": f"conflict_{conflict_index:05d}",
                "field_path": field_path,
                "conflict_type": "VALUE_MISMATCH",
                "severity": "HIGH",
                "status": "OPEN",
                "record_ids": deduplicate_strings(
                    record.get("field_record_id") for record in records
                ),
                "candidate_values": [
                    comparable_values[key]
                    for key in sorted(comparable_values.keys())
                ],
                "source_stages": deduplicate_strings(
                    record.get("source_stage") for record in records
                ),
                "details": {
                    "detected_by": "canonical_state_governance",
                    "source_count": len(records),
                },
            }
        )
        conflict_index += 1

    validation_conflicts = require_list(validation_report.get("conflicts", []), "validation_report.conflicts")
    for item in validation_conflicts:
        if isinstance(item, str) and item.strip():
            conflicts.append(
                {
                    "conflict_id": f"conflict_{conflict_index:05d}",
                    "field_path": "",
                    "conflict_type": "VALIDATION_REPORTED_CONFLICT",
                    "severity": "MODERATE",
                    "status": "OPEN",
                    "record_ids": [],
                    "candidate_values": [],
                    "source_stages": ["validation"],
                    "details": {"message": item.strip()},
                }
            )
            conflict_index += 1
            continue

        if not isinstance(item, dict):
            continue

        field_path = ""
        for key in ("field_path", "path", "parameter_path", "target_path"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                field_path = value.strip()
                break

        conflicts.append(
            {
                "conflict_id": f"conflict_{conflict_index:05d}",
                "field_path": field_path,
                "conflict_type": str(item.get("conflict_type", "VALIDATION_REPORTED_CONFLICT")),
                "severity": str(item.get("severity", "MODERATE")),
                "status": str(item.get("status", "OPEN")),
                "record_ids": deduplicate_strings(item.get("record_ids", [])),
                "candidate_values": require_list(item.get("candidate_values", []), "validation_conflict.candidate_values"),
                "source_stages": deduplicate_strings(
                    list(require_list(item.get("source_stages", []), "validation_conflict.source_stages"))
                    + ["validation"]
                ),
                "details": {
                    key: value
                    for key, value in item.items()
                    if key not in {
                        "field_path",
                        "path",
                        "parameter_path",
                        "target_path",
                        "conflict_type",
                        "severity",
                        "status",
                        "record_ids",
                        "candidate_values",
                        "source_stages",
                    }
                },
            }
        )
        conflict_index += 1

    conflicts.sort(key=lambda item: (str(item.get("field_path", "")), str(item.get("conflict_id", ""))))
    return conflicts


def _apply_conflict_annotations(
    field_records: list[dict[str, Any]],
    conflict_records: list[dict[str, Any]],
) -> None:
    conflict_paths = {
        str(conflict.get("field_path")).strip()
        for conflict in conflict_records
        if isinstance(conflict, dict)
        and isinstance(conflict.get("field_path"), str)
        and str(conflict.get("field_path")).strip()
    }

    for record in field_records:
        field_path = record.get("field_path")
        if not isinstance(field_path, str):
            continue
        if field_path not in conflict_paths:
            continue

        record["conflict_status"] = "CONFLICT"
        record["validation_status"] = validation_status_from_context(
            schema_valid=True,
            has_conflict=True,
            is_missing=bool(record.get("is_missing", False)),
            confidence_tag=str(record.get("confidence_tag", "UNRESOLVED")),
        )
        record["review_status"] = "REVIEW_REQUIRED"


def _build_review_flags(
    state: CanonicalFacilityState,
    field_records: list[dict[str, Any]],
    conflict_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    review_flags: list[dict[str, Any]] = []
    next_index = 1

    missing_paths = set(
        record["field_path"]
        for record in field_records
        if isinstance(record, dict) and bool(record.get("is_missing", False))
    )

    for field_path in sorted(missing_paths):
        review_flags.append(
            {
                "review_flag_id": f"review_{next_index:05d}",
                "category": "MISSING_FIELD",
                "severity": "HIGH",
                "status": "OPEN",
                "message": f"Required field missing: {field_path}",
                "field_path": field_path,
                "record_ids": deduplicate_strings(
                    record.get("field_record_id")
                    for record in field_records
                    if isinstance(record, dict) and record.get("field_path") == field_path
                ),
                "metadata": {"generated_by": "canonical_state_governance"},
            }
        )
        next_index += 1

    for conflict in conflict_records:
        if not isinstance(conflict, dict):
            continue
        review_flags.append(
            {
                "review_flag_id": f"review_{next_index:05d}",
                "category": "CONFLICT",
                "severity": str(conflict.get("severity", "HIGH")),
                "status": "OPEN",
                "message": (
                    f"Conflict detected for field '{conflict.get('field_path') or 'unknown'}'."
                ),
                "field_path": conflict.get("field_path"),
                "record_ids": deduplicate_strings(conflict.get("record_ids", [])),
                "metadata": {
                    "generated_by": "canonical_state_governance",
                    "conflict_id": conflict.get("conflict_id"),
                    "conflict_type": conflict.get("conflict_type"),
                },
            }
        )
        next_index += 1

    for record in field_records:
        if not isinstance(record, dict):
            continue
        confidence_tag = str(record.get("confidence_tag", "UNRESOLVED"))
        if confidence_tag not in {"LOW", "UNRESOLVED"}:
            continue

        review_flags.append(
            {
                "review_flag_id": f"review_{next_index:05d}",
                "category": "LOW_CONFIDENCE",
                "severity": "MODERATE" if confidence_tag == "LOW" else "HIGH",
                "status": "OPEN",
                "message": (
                    f"Field '{record.get('field_path')}' has {confidence_tag} confidence."
                ),
                "field_path": record.get("field_path"),
                "record_ids": [str(record.get("field_record_id"))],
                "metadata": {
                    "generated_by": "canonical_state_governance",
                    "confidence_score": record.get("confidence_score"),
                    "source_stage": record.get("source_stage"),
                    "source_type": record.get("source_type"),
                },
            }
        )
        next_index += 1

    for question in state.followup_questions:
        if not isinstance(question, dict):
            continue
        question_text = question.get("question") or question.get("message") or "Follow-up required."
        related_field = (
            question.get("field_path")
            or question.get("parameter_path")
            or question.get("target_path")
        )

        review_flags.append(
            {
                "review_flag_id": f"review_{next_index:05d}",
                "category": "FOLLOWUP_REQUIRED",
                "severity": "MODERATE",
                "status": "OPEN",
                "message": str(question_text),
                "field_path": str(related_field) if related_field else None,
                "record_ids": [],
                "metadata": {
                    "generated_by": "canonical_state_governance",
                    "question_payload": question,
                },
            }
        )
        next_index += 1

    review_flags.sort(
        key=lambda item: (
            str(item.get("category", "")),
            str(item.get("field_path", "")),
            str(item.get("review_flag_id", "")),
        )
    )
    return review_flags


def _build_governance_records(
    state: CanonicalFacilityState,
    extraction_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    interview_result: dict[str, Any] | None = None,
) -> None:
    next_index = 1

    extraction_records, next_index = _build_extraction_field_records(
        state=state,
        extraction_result=extraction_result,
        next_index=next_index,
    )

    normalized_records, next_index = _build_normalized_input_field_records(
        state=state,
        next_index=next_index,
    )

    retrieval_records, next_index = _build_retrieval_field_records(
        state=state,
        retrieval_result=retrieval_result,
        next_index=next_index,
    )

    interview_records, next_index = _build_interview_field_records(
        state=state,
        interview_result=interview_result,
        next_index=next_index,
    )

    translation_records, next_index = _build_translation_field_records(
        state=state,
        next_index=next_index,
    )

    all_field_records = extraction_records + normalized_records + retrieval_records + interview_records + translation_records

    synthesized_missing_records, next_index = _build_missing_field_records(
        state=state,
        existing_field_records=all_field_records,
        next_index=next_index,
    )

    all_field_records.extend(synthesized_missing_records)

    validation_report = require_dict(state.validation_report, "validation_report")

    conflict_records = _build_conflict_records(
        field_records=all_field_records,
        validation_report=validation_report,
    )

    _apply_conflict_annotations(
        field_records=all_field_records,
        conflict_records=conflict_records,
    )

    review_flags = _build_review_flags(
    state=state,
    field_records=all_field_records,
    conflict_records=conflict_records,
)

    all_field_records.sort(
        key=lambda item: (
            str(item.get("field_path", "")),
            str(item.get("source_stage", "")),
            str(item.get("field_record_id", "")),
        )
    )

    state.set_governance(
        field_records=all_field_records,
        conflict_records=conflict_records,
        review_flags=review_flags,
    )

    state.set_stage_status("canonical_state_governance", "GOVERNED")




def _build_source_candidate_inputs(
    extraction_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    interview_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extraction_candidates: list[dict[str, Any]] = []
    retrieval_candidates: list[dict[str, Any]] = []
    interview_candidates: list[dict[str, Any]] = []
    knowledge_library_sources: list[dict[str, Any]] = []
    vendor_pdf_sources: list[dict[str, Any]] = []
    official_web_sources: list[dict[str, Any]] = []
    evidence_route_records: list[dict[str, Any]] = []

    if isinstance(extraction_result, dict):
        for candidate in require_list(extraction_result.get("schema_field_candidates", []), "extraction_result.schema_field_candidates"):
            if not isinstance(candidate, dict):
                continue
            field_path = str(candidate.get("field_path", "")).strip()
            if not field_path:
                continue
            extraction_candidates.append(
                {
                    "field_path": field_path,
                    "value": candidate.get("value"),
                    "confidence": safe_float(candidate.get("confidence")),
                    "unit": candidate.get("unit"),
                    "status": candidate.get("status"),
                    "source_method": candidate.get("source_method") or candidate.get("method"),
                    "source_anchor_ids": deduplicate_strings(require_list(candidate.get("source_anchor_ids", []), "schema_field_candidate.source_anchor_ids")),
                    "source_ref": deduplicate_strings(require_list(candidate.get("source_ref", []), "schema_field_candidate.source_ref")),
                    "source_artifact_id": candidate.get("source_artifact_id") or candidate.get("artifact_id"),
                    "page_number": candidate.get("page_number"),
                    "worker_name": candidate.get("worker_name"),
                    "region_type": candidate.get("region_type"),
                    "metadata": require_dict(candidate.get("metadata", {}), "schema_field_candidate.metadata"),
                }
            )

    if isinstance(retrieval_result, dict):
        equipment_resolution = require_dict(
            retrieval_result.get("equipment_reference_resolution", {}),
            "retrieval_result.equipment_reference_resolution",
        )
        for candidate in require_list(
            equipment_resolution.get("candidate_fields", []),
            "retrieval_result.equipment_reference_resolution.candidate_fields",
        ):
            if not isinstance(candidate, dict):
                continue
            field_path = str(
                candidate.get("canonical_field_key")
                or candidate.get("matched_field_key")
                or candidate.get("spec_field")
                or candidate.get("field_path")
                or ""
            ).strip()
            if not field_path:
                continue
            retrieval_candidates.append(
                {
                    "field_path": field_path,
                    "value": candidate.get("value"),
                    "confidence": safe_float(candidate.get("confidence")),
                    "manufacturer": candidate.get("manufacturer"),
                    "model": candidate.get("model"),
                    "equipment_family": candidate.get("equipment_family"),
                    "spec_field": candidate.get("spec_field"),
                    "matched_field_key": candidate.get("matched_field_key"),
                    "canonical_field_key": candidate.get("canonical_field_key"),
                    "source_type": candidate.get("source_type"),
                    "source_ref": candidate.get("source_ref"),
                    "source_url": candidate.get("source_url"),
                    "confidence_reason": candidate.get("confidence_reason"),
                    "review_required": bool(candidate.get("review_required")),
                    "lookup_strategy": equipment_resolution.get("lookup_strategy"),
                    "source_priority": candidate.get("source_priority"),
                    "source_kind": candidate.get("source_kind"),
                    "document_type": candidate.get("document_type"),
                    "document_path": candidate.get("document_path"),
                    "evidence_tier": candidate.get("evidence_tier"),
                    "match_reason": candidate.get("match_reason"),
                }
            )
        for field_path in deduplicate_strings(require_list(equipment_resolution.get("unresolved_missing_fields", []), "retrieval_result.equipment_reference_resolution.unresolved_missing_fields")):
            retrieval_candidates.append(
                {
                    "field_path": field_path,
                    "value": None,
                    "confidence": None,
                    "source_type": "equipment_reference_unresolved",
                    "lookup_strategy": equipment_resolution.get("lookup_strategy"),
                    "review_required": True,
                }
            )

        matched_records = require_list(
            equipment_resolution.get("matched_records", []),
            "retrieval_result.equipment_reference_resolution.matched_records",
        )
        candidate_fields = require_list(
            equipment_resolution.get("candidate_fields", []),
            "retrieval_result.equipment_reference_resolution.candidate_fields",
        )
        for record in matched_records:
            if not isinstance(record, dict):
                continue
            manufacturer = record.get("manufacturer")
            model = record.get("model")
            family = record.get("equipment_family")
            path_value = str(record.get("__path", "")).strip()
            source_urls = [str(item).strip() for item in require_list(record.get("source_urls", []), "matched_record.source_urls") if str(item).strip()]
            target_fields = sorted({
                str(item.get("canonical_field_key") or item.get("matched_field_key") or item.get("spec_field") or "").strip()
                for item in candidate_fields
                if isinstance(item, dict)
                and str(item.get("manufacturer", "")).strip() == str(manufacturer or "").strip()
                and str(item.get("model", "")).strip() == str(model or "").strip()
            })
            knowledge_library_sources.append(
                {
                    "equipment_family": family,
                    "manufacturer": manufacturer,
                    "model": model,
                    "source_ref": path_value,
                    "source_url": source_urls[0] if source_urls else "",
                    "target_fields": [field for field in target_fields if field],
                    "source_type": "knowledge_library_match",
                    "matched_target_fields": [field for field in target_fields if field],
                    "source_kind": "equipment_catalog",
                    "source_priority": "equipment_catalog",
                    "evidence_tier": "structured_catalog",
                }
            )

        for item in require_list(
            equipment_resolution.get("pdf_repository_candidates", []),
            "retrieval_result.equipment_reference_resolution.pdf_repository_candidates",
        ):
            if not isinstance(item, dict):
                continue
            vendor_pdf_sources.append(
                {
                    "equipment_family": item.get("equipment_family"),
                    "manufacturer": item.get("manufacturer"),
                    "model": item.get("model"),
                    "source_ref": str(item.get("path", "")).strip() or str(item.get("document_label", "")).strip(),
                    "source_url": str(item.get("source_url", "")).strip(),
                    "document_type": item.get("document_type"),
                    "target_fields": [],
                    "source_type": str(item.get("document_type", "vendor_pdf_pointer")).strip() or "vendor_pdf_pointer",
                    "matched_target_fields": [],
                    "source_kind": "vendor_document",
                    "source_priority": "vendor_documents",
                    "evidence_tier": item.get("evidence_tier") or ("vendor_document_pointer" if str(item.get("document_type", "")).strip().lower() == "vendor_pdf_pointer" else "vendor_document"),
                    "match_reason": ", ".join(item.get("match_reasons", [])) if isinstance(item.get("match_reasons"), list) else "",
                }
            )
        for plan in require_list(
            equipment_resolution.get("pdf_lookup_plans", []),
            "retrieval_result.equipment_reference_resolution.pdf_lookup_plans",
        ):
            if not isinstance(plan, dict):
                continue
            vendor_pdf_sources.append(
                {
                    "equipment_family": plan.get("equipment_family"),
                    "manufacturer": plan.get("manufacturer"),
                    "model": plan.get("model"),
                    "source_ref": str(plan.get("document_path", "")).strip() or str(plan.get("document_label", "")).strip(),
                    "source_url": str(plan.get("source_url", "")).strip(),
                    "document_type": plan.get("document_type"),
                    "target_fields": deduplicate_strings(require_list(plan.get("missing_fields", []), "pdf_lookup_plan.missing_fields")),
                    "source_type": "vendor_pdf_lookup_plan",
                    "matched_target_fields": deduplicate_strings(require_list(plan.get("missing_fields", []), "pdf_lookup_plan.missing_fields")),
                    "source_kind": "vendor_document",
                    "source_priority": "vendor_documents",
                    "evidence_tier": plan.get("evidence_tier") or "vendor_document_pointer",
                    "match_reason": ", ".join(plan.get("match_reasons", [])) if isinstance(plan.get("match_reasons"), list) else "",
                }
            )

        for item in require_list(
            equipment_resolution.get("official_source_candidates", []),
            "retrieval_result.equipment_reference_resolution.official_source_candidates",
        ):
            if not isinstance(item, dict):
                continue
            official_web_sources.append(
                {
                    "equipment_family": item.get("equipment_family"),
                    "manufacturer": item.get("manufacturer"),
                    "model": item.get("model"),
                    "source_ref": str(item.get("source_url", "")).strip(),
                    "source_url": str(item.get("source_url", "")).strip(),
                    "allowed_domain": item.get("allowed_domain") or item.get("host"),
                    "target_fields": [],
                    "source_type": str(item.get("source_type", "official_source_index")).strip() or "official_source_index",
                    "matched_target_fields": [],
                    "source_kind": "official_source_index",
                    "source_priority": "official_interconnection",
                    "evidence_tier": "official_interconnection_source",
                    "match_reason": ", ".join(item.get("match_reasons", [])) if isinstance(item.get("match_reasons"), list) else "",
                }
            )
        for plan in require_list(
            equipment_resolution.get("web_lookup_plans", []),
            "retrieval_result.equipment_reference_resolution.web_lookup_plans",
        ):
            if not isinstance(plan, dict):
                continue
            official_web_sources.append(
                {
                    "equipment_family": plan.get("equipment_family"),
                    "manufacturer": plan.get("manufacturer"),
                    "model": plan.get("model"),
                    "source_ref": ", ".join(deduplicate_strings(require_list(plan.get("allowed_urls", []), "web_lookup_plan.allowed_urls"))[:1]),
                    "source_url": ", ".join(deduplicate_strings(require_list(plan.get("allowed_urls", []), "web_lookup_plan.allowed_urls"))[:1]),
                    "allowed_domain": ", ".join(deduplicate_strings(require_list(plan.get("allowed_domains", []), "web_lookup_plan.allowed_domains"))[:2]),
                    "target_fields": deduplicate_strings(require_list(plan.get("missing_fields", []), "web_lookup_plan.missing_fields")),
                    "source_type": "official_web_lookup_plan",
                    "matched_target_fields": deduplicate_strings(require_list(plan.get("missing_fields", []), "web_lookup_plan.missing_fields")),
                    "source_kind": "official_web",
                    "source_priority": "official_interconnection",
                    "evidence_tier": "official_interconnection_source",
                    "match_reason": ", ".join(plan.get("allowed_domains", [])) if isinstance(plan.get("allowed_domains"), list) else "",
                }
            )

    if isinstance(retrieval_result, dict):
        for record in require_list(retrieval_result.get("evidence_route_records", []), "retrieval_result.evidence_route_records"):
            if isinstance(record, dict):
                evidence_route_records.append(dict(record))

    if isinstance(interview_result, dict):
        for answer in require_list(interview_result.get("answers_confirmed", []), "interview_result.answers_confirmed"):
            if not isinstance(answer, dict):
                continue
            field_path = str(answer.get("field_path", "")).strip()
            if not field_path:
                continue
            interview_candidates.append(
                {
                    "field_path": field_path,
                    "value": answer.get("confirmed_answer", answer.get("value")),
                    "question_id": answer.get("question_id"),
                    "source_context": answer.get("source_context"),
                    "confirmed_by": answer.get("confirmed_by", "applicant"),
                }
            )
        for field_path in deduplicate_strings(require_list(interview_result.get("unresolved_fields", []), "interview_result.unresolved_fields")):
            interview_candidates.append({"field_path": field_path, "value": None, "unresolved": True})

    return {
        "extraction_candidates": extraction_candidates,
        "retrieval_candidates": retrieval_candidates,
        "interview_candidates": interview_candidates,
        "knowledge_library_sources": knowledge_library_sources,
        "vendor_pdf_sources": vendor_pdf_sources,
        "official_web_sources": official_web_sources,
        "evidence_route_records": evidence_route_records,
        "field_support_summary": require_dict(retrieval_result.get("field_support_summary", {}), "retrieval_result.field_support_summary") if isinstance(retrieval_result, dict) else {},
    }

def build_canonical_state(
    context: Any,
    ingestion_result: dict[str, Any] | None = None,
    extraction_result: dict[str, Any] | None = None,
    interview_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    translation_result: dict[str, Any] | None = None,
    scenario_result: dict[str, Any] | None = None,
    existing_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = require_run_id(getattr(context, "run_id", None))

    build_inputs = CanonicalStateBuildInputs(
        run_id=run_id,
        ingestion_result=ingestion_result,
        extraction_result=extraction_result,
        interview_result=interview_result,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
        translation_result=translation_result,
        scenario_result=scenario_result,
        existing_state=existing_state,
    )

    warnings: list[str] = []

    if interview_result:
        answers_confirmed = interview_result.get("answers_confirmed", [])
        if isinstance(answers_confirmed, list) and not answers_confirmed:
            warnings.append("Interview stage completed with zero confirmed answers.")

    state = _build_state(build_inputs)
    _build_governance_records(
        state,
        extraction_result=extraction_result,
        retrieval_result=retrieval_result,
        interview_result=interview_result,
    )

    canonical_state_payload = state.to_dict()
    canonical_state_payload["source_candidate_inputs"] = _build_source_candidate_inputs(
        extraction_result=extraction_result,
        retrieval_result=retrieval_result,
        interview_result=interview_result,
    )
    attach_candidate_ledger_to_canonical_state(
        canonical_state_payload,
        normalization_result=normalization_result,
    )
    validation_payload = canonical_state_payload.get("validation_report") if isinstance(canonical_state_payload, dict) else None
    planner_registry_coverage = summarize_registry_packet_coverage(
        canonical_state_payload,
        validation_payload,
    )
    planner_registry_open_items_payload = planner_registry_open_items(
        canonical_state_payload,
        validation_payload,
    )
    planner_registry_resolution_backlog_payload = planner_registry_resolution_backlog(
        canonical_state_payload,
        validation_payload,
    )
    canonical_state_payload["planner_registry_coverage"] = planner_registry_coverage
    canonical_state_payload["planner_registry_open_items"] = planner_registry_open_items_payload
    canonical_state_payload["planner_registry_resolution_backlog"] = planner_registry_resolution_backlog_payload
    field_resolution_payload = build_field_resolution_result(
        canonical_state_payload,
        validation_payload if isinstance(validation_payload, dict) else None,
        context=context,
    )
    canonical_state_payload["field_resolution"] = field_resolution_payload
    canonical_state_payload["governed_truth_summary"] = build_governed_summary(
        canonical_state_payload,
        {"validation_report": validation_payload} if isinstance(validation_payload, dict) else None,
    )
    accepted_field_index = field_resolution_payload.get("accepted_field_index") if isinstance(field_resolution_payload, dict) else {}
    canonical_state_payload["accepted_planner_field_index"] = dict(accepted_field_index) if isinstance(accepted_field_index, dict) else {}
    canonical_state_payload["field_resolution_overview"] = {
        "planner_review_queue": [dict(item) for item in field_resolution_payload.get("planner_review_queue", [])] if isinstance(field_resolution_payload, dict) else [],
        "high_materiality_conflicts": [dict(item) for item in field_resolution_payload.get("high_materiality_conflicts", [])] if isinstance(field_resolution_payload, dict) else [],
        "backlog_top": [dict(item) for item in field_resolution_payload.get("backlog", [])[:10]] if isinstance(field_resolution_payload, dict) else [],
        "governance_posture_summary": dict(field_resolution_payload.get("governance_posture_summary", {})) if isinstance(field_resolution_payload, dict) else {},
        "summary": dict(field_resolution_payload.get("summary", {})) if isinstance(field_resolution_payload, dict) else {},
    }
    packet_rows_by_section = build_planner_packet_field_rows(
        canonical_state_payload,
        validation_payload if isinstance(validation_payload, dict) else None,
        include_optional=True,
    )
    canonical_state_payload["planner_packet_field_rows"] = {
        str(section_id): [dict(row) for row in rows if isinstance(row, dict)]
        for section_id, rows in packet_rows_by_section.items()
    }

    summary_payload = canonical_state_summary_from_payload(canonical_state_payload)
    summary = CanonicalStateBuildSummary(**summary_payload)
    summary.planner_registry_total_field_count = planner_registry_coverage.get("total_field_count", 0)
    summary.planner_registry_required_field_count = planner_registry_coverage.get("required_field_count", 0)
    summary.planner_registry_resolved_count = planner_registry_coverage.get("resolved_count", 0)
    summary.planner_registry_review_required_count = planner_registry_coverage.get("review_required_count", 0)
    summary.planner_registry_conflicting_count = planner_registry_coverage.get("conflicting_count", 0)
    summary.planner_registry_missing_count = planner_registry_coverage.get("missing_count", 0)
    summary.planner_registry_unresolved_count = planner_registry_coverage.get("unresolved_count", 0)
    summary.planner_registry_resolution_queue_count = planner_registry_resolution_backlog_payload.get("queue_count", 0)
    summary.planner_registry_resolution_queue_field_ids = list(planner_registry_resolution_backlog_payload.get("queue_field_ids", []))
    summary.planner_registry_planner_critical_open_count = planner_registry_open_items_payload.get("planner_critical_open_count", 0)
    summary.planner_registry_required_missing_count = planner_registry_open_items_payload.get("required_missing_count", 0)
    summary.planner_registry_coverage = dict(planner_registry_coverage)
    summary.planner_registry_open_items = dict(planner_registry_open_items_payload)
    summary.planner_registry_resolution_backlog = dict(planner_registry_resolution_backlog_payload)
    summary.field_resolution_summary = dict(field_resolution_payload.get("summary", {})) if isinstance(field_resolution_payload, dict) else {}
    summary.field_resolution_backlog_count = int(field_resolution_payload.get("backlog_count", 0)) if isinstance(field_resolution_payload, dict) else 0
    summary.field_resolution_accepted_field_count = int(field_resolution_payload.get("summary", {}).get("accepted_field_index_count", 0)) if isinstance(field_resolution_payload, dict) else 0
    summary.field_resolution_planner_review_count = int(field_resolution_payload.get("summary", {}).get("planner_review_count", 0)) if isinstance(field_resolution_payload, dict) else 0
    summary.field_resolution_confirmation_needed_count = int(field_resolution_payload.get("summary", {}).get("applicant_confirmation_needed_count", 0)) if isinstance(field_resolution_payload, dict) else 0
    summary.field_resolution_top_backlog_field_ids = list(field_resolution_payload.get("backlog_field_ids", [])[:10]) if isinstance(field_resolution_payload, dict) else []
    summary.field_resolution_high_materiality_conflict_count = int(field_resolution_payload.get("summary", {}).get("high_materiality_conflict_count", 0)) if isinstance(field_resolution_payload, dict) else 0
    summary.field_resolution_planner_review_queue_count = int(field_resolution_payload.get("planner_review_queue_count", 0)) if isinstance(field_resolution_payload, dict) else 0
    summary.field_resolution_governance_posture = dict(field_resolution_payload.get("governance_posture_summary", {})) if isinstance(field_resolution_payload, dict) else {}

    result = CanonicalStateServiceResult(
        run_id=run_id,
        canonical_state=canonical_state_payload,
        build_summary=summary,
        warnings=warnings,
        status="CANONICAL_STATE_BUILT",
        built_at=utc_now_iso(),
    )

    return annotate_final_canonical_state_result(result.to_dict())


def run_service(
    context: Any,
    ingestion_result: dict[str, Any] | None = None,
    extraction_result: dict[str, Any] | None = None,
    interview_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    gap_resolution_result: dict[str, Any] | None = None,
    translation_result: dict[str, Any] | None = None,
    scenario_result: dict[str, Any] | None = None,
    validation_result: dict[str, Any] | None = None,
    existing_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.authorization_service.service import AuthorizationService
    retrieval_result, interview_result = resolve_gap_resolution_stage_inputs(
        retrieval_result=retrieval_result,
        interview_result=interview_result,
        gap_resolution_result=gap_resolution_result,
    )

    from shared.security.models import AuthorizationRequest
    from shared.security.permissions import Permission
    from shared.security.run_access_registry import RunAccessRegistry

    actor = getattr(context, "actor", None)
    run_id = require_run_id(getattr(context, "run_id", None))

    if actor is None:
        raise RuntimeError("Canonical state mutation requires an authenticated actor.")

    run_access_registry = getattr(context, "run_access_registry", None)
    if run_access_registry is None:
        run_access_registry = RunAccessRegistry()
        run_access_registry.register_run(run_id, actor)
        try:
            setattr(context, "run_access_registry", run_access_registry)
        except AttributeError:
            pass

    audit_service = getattr(context, "audit_logger", None)
    auth_service = AuthorizationService(
        audit_service=audit_service,
        run_access_registry=run_access_registry,
    )

    auth_service.require(
        AuthorizationRequest(
            actor=actor,
            permission=Permission.MODIFY_CANONICAL_STATE,
            resource_type="canonical_state",
            resource_id=run_id,
        )
    )

    if validation_result is not None:
        if not isinstance(validation_result, dict):
            raise TypeError("validation_result must be a dict when provided.")

        validation_status = str(validation_result.get("status", "")).strip().upper()
        if validation_status != "VALIDATED":
            raise ValueError(
                "canonical_state_service requires a VALIDATED validation_result before persisting canonical state."
            )

        canonical_state = require_dict(
            validation_result.get("canonical_state"),
            "validation_result.canonical_state",
        )
        attach_candidate_ledger_to_canonical_state(canonical_state, normalization_result=normalization_result)
        summary_payload = canonical_state_summary_from_payload(canonical_state)
        summary = CanonicalStateBuildSummary(**summary_payload)
        return CanonicalStateServiceResult(
            run_id=run_id,
            canonical_state=canonical_state,
            build_summary=summary,
            warnings=[],
            status="CANONICAL_STATE_PERSISTED",
            built_at=utc_now_iso(),
        ).to_dict()

    return build_canonical_state(
        context=context,
        ingestion_result=ingestion_result,
        extraction_result=extraction_result,
        interview_result=interview_result,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
        translation_result=translation_result,
        scenario_result=scenario_result,
        existing_state=existing_state,
    )