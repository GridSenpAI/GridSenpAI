from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, cast

from shared.types.canonical_state.canonical_facility_state import (
    CanonicalFacilityState,
)
from shared.types.canonical_state.canonical_models import (
    ArtifactRecord,
    AssumptionRecord,
    EntityRecord,
    EvidenceSnippet,
    OutputParameter,
    ScenarioVariant,
    SourceAnchor,
)


def _require_dict(payload: Any, name: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError(f"{name} must be a dict, got {type(payload).__name__}.")
    return payload


def _require_list(payload: Any, name: str) -> List[Any]:
    if not isinstance(payload, list):
        raise TypeError(f"{name} must be a list, got {type(payload).__name__}.")
    return payload


def artifact_record_from_dict(payload: Dict[str, Any]) -> ArtifactRecord:
    data = _require_dict(payload, "artifact_record")
    return ArtifactRecord(
        artifact_id=str(data["artifact_id"]),
        file_name=str(data["file_name"]),
        file_path=str(data["file_path"]),
        file_suffix=str(data["file_suffix"]),
        size_bytes=int(data["size_bytes"]),
        ingested_at=str(data["ingested_at"]),
        index_status=str(data["index_status"]),
        classification=str(data["classification"]),
    )


def entity_record_from_dict(payload: Dict[str, Any]) -> EntityRecord:
    data = _require_dict(payload, "entity_record")
    return EntityRecord(
        entity_id=str(data["entity_id"]),
        type=str(data["type"]),
        name=str(data["name"]),
        attributes=_require_dict(data.get("attributes", {}), "entity.attributes"),
        units=_require_dict(data.get("units", {}), "entity.units"),
        source_anchor_id=str(data["source_anchor_id"]),
    )


def source_anchor_from_dict(payload: Dict[str, Any]) -> SourceAnchor:
    data = _require_dict(payload, "source_anchor")
    return SourceAnchor(
        anchor_id=str(data["anchor_id"]),
        artifact_id=str(data["artifact_id"]),
        file_name=str(data["file_name"]),
        page=int(data["page"]),
        text_pointer=str(data["text_pointer"]),
    )


def evidence_snippet_from_dict(payload: Dict[str, Any]) -> EvidenceSnippet:
    data = _require_dict(payload, "evidence_snippet")
    return EvidenceSnippet(
        snippet_id=str(data["snippet_id"]),
        corpus=str(data["corpus"]),
        source_ref=str(data["source_ref"]),
        text=str(data["text"]),
        score=float(data["score"]),
        metadata=_require_dict(data.get("metadata", {}), "evidence_snippet.metadata"),
    )


def output_parameter_from_dict(payload: Dict[str, Any]) -> OutputParameter:
    data = _require_dict(payload, "output_parameter")
    return OutputParameter(
        parameter_path=str(data["parameter_path"]),
        value=data.get("value"),
        units=str(data["units"]),
        provenance_type=str(data["provenance_type"]),
        provenance_ref=data.get("provenance_ref"),
        confidence_tag=str(data["confidence_tag"]),
    )


def assumption_record_from_dict(payload: Dict[str, Any]) -> AssumptionRecord:
    data = _require_dict(payload, "assumption_record")
    return AssumptionRecord(
        assumption_id=str(data["assumption_id"]),
        parameter_path=str(data["parameter_path"]),
        nominal_value=data.get("nominal_value"),
        bounds=_require_dict(data.get("bounds", {}), "assumption.bounds"),
        rationale=str(data["rationale"]),
        created_by=str(data["created_by"]),
    )


def scenario_variant_from_dict(payload: Dict[str, Any]) -> ScenarioVariant:
    data = _require_dict(payload, "scenario_variant")
    return ScenarioVariant(
        label=str(data["label"]),
        description=str(data["description"]),
        outputs=_require_dict(data["outputs"], "scenario_variant.outputs"),
        confidence=str(data["confidence"]),
    )


from typing import cast


def serialize_records(records: Sequence[Any]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []

    for record in records:
        if hasattr(record, "to_dict") and callable(record.to_dict):
            serialized.append(cast(Dict[str, Any], record.to_dict()))
        elif isinstance(record, dict):
            serialized.append(record)
        else:
            raise TypeError(
                f"Record must be dict-like or expose to_dict(), got {type(record).__name__}."
            )

    return serialized


def hydrate_artifact_records(
    payloads: Iterable[Dict[str, Any]],
) -> List[ArtifactRecord]:
    return [artifact_record_from_dict(item) for item in payloads]


def hydrate_entity_records(
    payloads: Iterable[Dict[str, Any]],
) -> List[EntityRecord]:
    return [entity_record_from_dict(item) for item in payloads]


def hydrate_source_anchors(
    payloads: Iterable[Dict[str, Any]],
) -> List[SourceAnchor]:
    return [source_anchor_from_dict(item) for item in payloads]


def hydrate_evidence_snippets(
    payloads: Iterable[Dict[str, Any]],
) -> List[EvidenceSnippet]:
    return [evidence_snippet_from_dict(item) for item in payloads]


def hydrate_output_parameters(
    payloads: Iterable[Dict[str, Any]],
) -> List[OutputParameter]:
    return [output_parameter_from_dict(item) for item in payloads]


def hydrate_assumption_records(
    payloads: Iterable[Dict[str, Any]],
) -> List[AssumptionRecord]:
    return [assumption_record_from_dict(item) for item in payloads]


def hydrate_scenario_variants(
    payloads: Dict[str, Dict[str, Any]],
) -> Dict[str, ScenarioVariant]:
    if not isinstance(payloads, dict):
        raise TypeError(
            f"scenario_variants must be a dict, got {type(payloads).__name__}."
        )

    hydrated: Dict[str, ScenarioVariant] = {}
    for key, value in payloads.items():
        hydrated[str(key)] = scenario_variant_from_dict(value)
    return hydrated


def build_empty_canonical_state(run_id: str) -> CanonicalFacilityState:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string.")
    return CanonicalFacilityState(run_id=run_id.strip())


def canonical_state_from_stage_payloads(
    run_id: str,
    ingestion_result: Dict[str, Any] | None = None,
    extraction_result: Dict[str, Any] | None = None,
    normalization_result: Dict[str, Any] | None = None,
    retrieval_result: Dict[str, Any] | None = None,
    translation_result: Dict[str, Any] | None = None,
    scenario_result: Dict[str, Any] | None = None,
) -> CanonicalFacilityState:
    state = build_empty_canonical_state(run_id)

    if ingestion_result:
        artifacts = _require_list(ingestion_result.get("artifacts", []), "artifacts")
        state.add_artifacts(serialize_records(hydrate_artifact_records(artifacts)))
        status = ingestion_result.get("status")
        if status:
            state.set_stage_status("ingestion", str(status))

    if extraction_result:
        entities = _require_list(extraction_result.get("entities", []), "entities")
        topology_cues = _require_list(
            extraction_result.get("topology_cues", []),
            "topology_cues",
        )
        source_anchors = _require_list(
            extraction_result.get("source_anchors", []),
            "source_anchors",
        )

        state.add_entities(serialize_records(hydrate_entity_records(entities)))
        state.add_topology_cues(topology_cues)
        state.add_source_anchors(
            serialize_records(hydrate_source_anchors(source_anchors))
        )

        status = extraction_result.get("status")
        if status:
            state.set_stage_status("extraction", str(status))

    if normalization_result:
        normalized_input = _require_dict(
            normalization_result.get("normalized_input", {}),
            "normalized_input",
        )
        validation_report = _require_dict(
            normalization_result.get("validation_report", {}),
            "validation_report",
        )
        followup_questions = _require_list(
            normalization_result.get("followup_questions", []),
            "followup_questions",
        )

        state.set_normalized_input(
            normalized_input=normalized_input,
            validation_report=validation_report,
            followup_questions=followup_questions,
        )

        status = normalization_result.get("status")
        if status:
            state.set_stage_status("normalization", str(status))

    if retrieval_result:
        snippets = _require_list(retrieval_result.get("snippets", []), "snippets")
        state.add_evidence(serialize_records(hydrate_evidence_snippets(snippets)))

        status = retrieval_result.get("status")
        if status:
            state.set_stage_status("gap_resolution::retrieval", str(status))

    if translation_result:
        model_outputs = _require_dict(
            translation_result.get("model_outputs", {}),
            "model_outputs",
        )
        output_parameters = _require_list(
            translation_result.get("output_parameters", []),
            "output_parameters",
        )
        assumptions_raw = _require_list(
            translation_result.get("assumptions", []),
            "assumptions",
        )

        state.set_translation_outputs(
            model_outputs=model_outputs,
            output_parameters=serialize_records(
                hydrate_output_parameters(output_parameters)
            ),
            assumptions=serialize_records(hydrate_assumption_records(assumptions_raw)),
        )

        status = translation_result.get("status")
        if status:
            state.set_stage_status("translation", str(status))

    if scenario_result:
        scenarios = _require_dict(scenario_result.get("scenarios", {}), "scenarios")
        state.set_scenarios(
            {
                key: value.to_dict()
                for key, value in hydrate_scenario_variants(scenarios).items()
            }
        )

        status = scenario_result.get("status")
        if status:
            state.set_stage_status("scenarios", str(status))

    return state