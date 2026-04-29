# shared/types/stage_contracts.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class IngestionStageResult:
    run_id: str
    artifacts_discovered: list[dict[str, Any]] = field(default_factory=list)
    status: str = "INGESTED"
    ingested_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifacts_discovered": list(self.artifacts_discovered),
            "status": self.status,
            "ingested_at": self.ingested_at,
        }


@dataclass(slots=True)
class ExtractionStageResult:
    run_id: str
    candidate_entities: list[dict[str, Any]] = field(default_factory=list)
    status: str = "EXTRACTED"
    extracted_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "candidate_entities": list(self.candidate_entities),
            "status": self.status,
            "extracted_at": self.extracted_at,
        }


@dataclass(slots=True)
class InterviewStageResult:
    run_id: str
    answers_candidate: list[dict[str, Any]] = field(default_factory=list)
    answers_confirmed: list[dict[str, Any]] = field(default_factory=list)
    clarifications: list[dict[str, Any]] = field(default_factory=list)
    status: str = "INTERVIEW_PROCESSED"
    interview_processed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "answers_candidate": list(self.answers_candidate),
            "answers_confirmed": list(self.answers_confirmed),
            "clarifications": list(self.clarifications),
            "status": self.status,
            "interview_processed_at": self.interview_processed_at,
        }


@dataclass(slots=True)
class NormalizationStageResult:
    run_id: str
    normalized_input: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)
    followup_questions: list[dict[str, Any]] = field(default_factory=list)
    status: str = "NORMALIZED"
    normalized_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "normalized_input": dict(self.normalized_input),
            "validation_report": dict(self.validation_report),
            "followup_questions": list(self.followup_questions),
            "status": self.status,
            "normalized_at": self.normalized_at,
        }


@dataclass(slots=True)
class RetrievalStageResult:
    run_id: str
    snippets: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "RETRIEVED"
    retrieved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "snippets": list(self.snippets),
            "warnings": list(self.warnings),
            "status": self.status,
            "retrieved_at": self.retrieved_at,
        }


@dataclass(slots=True)
class CanonicalStateStageResult:
    run_id: str
    canonical_state: dict[str, Any] = field(default_factory=dict)
    build_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    status: str = "CANONICAL_STATE_PERSISTED"
    built_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "canonical_state": dict(self.canonical_state),
            "build_summary": dict(self.build_summary),
            "warnings": list(self.warnings),
            "status": self.status,
            "built_at": self.built_at,
        }


@dataclass(slots=True)
class ValidationStageResult:
    run_id: str
    validation_report: dict[str, Any] = field(default_factory=dict)
    canonical_state: dict[str, Any] = field(default_factory=dict)
    status: str = "VALIDATED"
    validated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "validation_report": dict(self.validation_report),
            "canonical_state": dict(self.canonical_state),
            "status": self.status,
            "validated_at": self.validated_at,
        }


@dataclass(slots=True)
class OutputParameter:
    parameter_path: str
    value: Any
    units: str
    provenance_type: str
    provenance_ref: str | list[str]
    dependency_paths: list[str] = field(default_factory=list)
    source_field_paths: list[str] = field(default_factory=list)
    supporting_snippet_ids: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    confidence_tag: str = "LOW"
    confidence_factors: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_path": self.parameter_path,
            "value": self.value,
            "units": self.units,
            "provenance_type": self.provenance_type,
            "provenance_ref": self.provenance_ref,
            "dependency_paths": list(self.dependency_paths),
            "source_field_paths": list(self.source_field_paths),
            "supporting_snippet_ids": list(self.supporting_snippet_ids),
            "confidence_score": round(float(self.confidence_score), 2),
            "confidence_tag": self.confidence_tag,
            "confidence_factors": dict(self.confidence_factors),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OutputParameter":
        return cls(
            parameter_path=str(payload["parameter_path"]),
            value=payload.get("value"),
            units=str(payload["units"]),
            provenance_type=str(payload["provenance_type"]),
            provenance_ref=payload["provenance_ref"],
            dependency_paths=[
                str(path)
                for path in payload.get("dependency_paths", [])
                if isinstance(path, str) and path.strip()
            ],
            source_field_paths=[
                str(path)
                for path in payload.get("source_field_paths", [])
                if isinstance(path, str) and path.strip()
            ],
            supporting_snippet_ids=[
                str(snippet_id)
                for snippet_id in payload.get("supporting_snippet_ids", [])
                if isinstance(snippet_id, str) and snippet_id.strip()
            ],
            confidence_score=float(payload.get("confidence_score", 0.0)),
            confidence_tag=str(payload.get("confidence_tag", "LOW")),
            confidence_factors=dict(payload.get("confidence_factors", {})),
        )


@dataclass(slots=True)
class TranslationStageResult:
    run_id: str
    model_outputs: dict[str, Any] = field(default_factory=dict)
    output_parameters: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    confidence_summary: dict[str, int] = field(default_factory=dict)
    schema_validation: dict[str, Any] = field(default_factory=dict)
    status: str = "TRANSLATED"
    translated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        normalized_parameters: list[dict[str, Any]] = []

        for parameter in self.output_parameters:
            if isinstance(parameter, OutputParameter):
                normalized_parameters.append(parameter.to_dict())
            else:
                normalized_parameters.append(OutputParameter.from_dict(parameter).to_dict())

        return {
            "run_id": self.run_id,
            "model_outputs": dict(self.model_outputs),
            "output_parameters": normalized_parameters,
            "assumptions": list(self.assumptions),
            "confidence_summary": dict(self.confidence_summary),
            "schema_validation": dict(self.schema_validation),
            "status": self.status,
            "translated_at": self.translated_at,
        }


@dataclass(slots=True)
class ScenarioChangeRecord:
    parameter_path: str
    baseline_parameter_path: str
    baseline_value: Any
    new_value: Any
    delta: float | None
    units: str
    change_reason: str
    dependency_paths: list[str] = field(default_factory=list)
    source_field_paths: list[str] = field(default_factory=list)
    supporting_snippet_ids: list[str] = field(default_factory=list)
    assumption_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_path": self.parameter_path,
            "baseline_parameter_path": self.baseline_parameter_path,
            "baseline_value": self.baseline_value,
            "new_value": self.new_value,
            "delta": self.delta,
            "units": self.units,
            "change_reason": self.change_reason,
            "dependency_paths": list(self.dependency_paths),
            "source_field_paths": list(self.source_field_paths),
            "supporting_snippet_ids": list(self.supporting_snippet_ids),
            "assumption_ids": list(self.assumption_ids),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioChangeRecord":
        delta_value = payload.get("delta")
        normalized_delta: float | None
        if delta_value is None:
            normalized_delta = None
        else:
            normalized_delta = float(delta_value)

        return cls(
            parameter_path=str(payload["parameter_path"]),
            baseline_parameter_path=str(payload["baseline_parameter_path"]),
            baseline_value=payload.get("baseline_value"),
            new_value=payload.get("new_value"),
            delta=normalized_delta,
            units=str(payload.get("units", "")),
            change_reason=str(payload.get("change_reason", "")),
            dependency_paths=[
                str(path)
                for path in payload.get("dependency_paths", [])
                if isinstance(path, str) and path.strip()
            ],
            source_field_paths=[
                str(path)
                for path in payload.get("source_field_paths", [])
                if isinstance(path, str) and path.strip()
            ],
            supporting_snippet_ids=[
                str(snippet_id)
                for snippet_id in payload.get("supporting_snippet_ids", [])
                if isinstance(snippet_id, str) and snippet_id.strip()
            ],
            assumption_ids=[
                str(assumption_id)
                for assumption_id in payload.get("assumption_ids", [])
                if isinstance(assumption_id, str) and assumption_id.strip()
            ],
        )


@dataclass(slots=True)
class ScenarioMetadata:
    source_confidence_summary: dict[str, int] = field(default_factory=dict)
    parameter_count: int = 0
    changed_parameter_count: int = 0
    changed_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_confidence_summary": dict(self.source_confidence_summary),
            "parameter_count": int(self.parameter_count),
            "changed_parameter_count": int(self.changed_parameter_count),
            "changed_paths": list(self.changed_paths),
        }


@dataclass(slots=True)
class ScenarioVariant:
    label: str
    description: str
    outputs: dict[str, Any] = field(default_factory=dict)
    confidence: str = "LOW"
    changes: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        normalized_changes: list[dict[str, Any]] = []
        for change in self.changes:
            if isinstance(change, ScenarioChangeRecord):
                normalized_changes.append(change.to_dict())
            else:
                normalized_changes.append(ScenarioChangeRecord.from_dict(change).to_dict())

        normalized_metadata: dict[str, Any]
        if isinstance(self.metadata, ScenarioMetadata):
            normalized_metadata = self.metadata.to_dict()
        else:
            normalized_metadata = dict(self.metadata)

        return {
            "label": self.label,
            "description": self.description,
            "outputs": dict(self.outputs),
            "confidence": self.confidence,
            "changes": normalized_changes,
            "metadata": normalized_metadata,
        }


@dataclass(slots=True)
class ScenarioStageResult:
    run_id: str
    scenarios: dict[str, Any] = field(default_factory=dict)
    scenario_variants: list[dict[str, Any]] = field(default_factory=list)
    status: str = "SCENARIOS_GENERATED"
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        normalized_variants: list[dict[str, Any]] = []
        for variant in self.scenario_variants:
            if isinstance(variant, ScenarioVariant):
                normalized_variants.append(variant.to_dict())
            else:
                normalized_variants.append(dict(variant))

        return {
            "run_id": self.run_id,
            "scenarios": dict(self.scenarios),
            "scenario_variants": normalized_variants,
            "status": self.status,
            "generated_at": self.generated_at,
        }


@dataclass(slots=True)
class ExportStageResult:
    run_id: str
    export_manifest: dict[str, Any] = field(default_factory=dict)
    status: str = "EXPORTED"
    exported_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "export_manifest": dict(self.export_manifest),
            "status": self.status,
            "exported_at": self.exported_at,
        }