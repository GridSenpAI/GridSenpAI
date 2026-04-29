from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceAnchor:
    anchor_id: str
    artifact_id: str
    file_name: str
    page: int
    text_pointer: str
    parser_block_id: str | None = None
    region_id: str | None = None
    bbox: dict[str, Any] | None = None
    source_method: str | None = None
    excerpt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(slots=True)
class ExtractionResult:
    run_id: str
    entities: list[dict[str, Any]]
    candidate_entities: list[dict[str, Any]]
    schema_field_candidates: list[dict[str, Any]]
    topology_cues: list[dict[str, Any]]
    source_anchors: list[dict[str, Any]]
    ontology: list[dict[str, Any]]
    llm_assistance: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    status: str = "EXTRACTED"
    extracted_at: str = ""
    planner_registry_summary: dict[str, Any] = field(default_factory=dict)
    planner_registry_field_targets: list[dict[str, Any]] = field(default_factory=list)
    uncovered_planner_registry_fields: list[dict[str, Any]] = field(default_factory=list)
    relevance_plan: list[dict[str, Any]] = field(default_factory=list)
    document_parser_result: dict[str, Any] | None = None
    layout_analysis_result: dict[str, Any] | None = None
    ocr_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "entities": self.entities,
            "candidate_entities": self.candidate_entities,
            "schema_field_candidates": self.schema_field_candidates,
            "topology_cues": self.topology_cues,
            "source_anchors": self.source_anchors,
            "ontology": self.ontology,
            "llm_assistance": self.llm_assistance,
            "warnings": self.warnings,
            "status": self.status,
            "extracted_at": self.extracted_at,
            "planner_registry_summary": self.planner_registry_summary,
            "planner_registry_field_targets": self.planner_registry_field_targets,
            "uncovered_planner_registry_fields": self.uncovered_planner_registry_fields,
            "relevance_plan": self.relevance_plan,
        }
        if self.document_parser_result is not None:
            payload["document_parser_result"] = self.document_parser_result
        if self.layout_analysis_result is not None:
            payload["layout_analysis_result"] = self.layout_analysis_result
        if self.ocr_result is not None:
            payload["ocr_result"] = self.ocr_result
        return payload


@dataclass(slots=True)
class ExtractionCandidate:
    field_path: str
    value: Any | None
    confidence: float
    source_artifact_id: str
    method: str
    evidence: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    review_notes: list[str] = field(default_factory=list)
    recommended: bool = False
    agent_id: str | None = None
    agent_status: str | None = None
    agent_audit_path: str | None = None
    agent_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "value": self.value,
            "confidence": self.confidence,
            "source_artifact_id": self.source_artifact_id,
            "method": self.method,
            "evidence": dict(self.evidence),
            "metadata": dict(self.metadata),
            "review_notes": list(self.review_notes),
            "recommended": self.recommended,
            "agent_id": self.agent_id,
            "agent_status": self.agent_status,
            "agent_audit_path": self.agent_audit_path,
            "agent_policy": dict(self.agent_policy),
        }


@dataclass(slots=True)
class EntityObservationRecord:
    entity_type: str
    entity_id: str
    aliases: list[str]
    source_artifact_id: str


@dataclass(slots=True)
class ResolvedEntity:
    entity_type: str
    canonical_entity_id: str
    aliases: list[str]
    source_artifact_ids: list[str]


@dataclass(slots=True)
class ExtractionPipelineInput:
    artifacts: list[dict[str, Any]]
    field_paths: list[str]
    canonical_state: dict[str, Any]
    context: Any | None = None


@dataclass(slots=True)
class ExtractionPipelineResult:
    canonical_state: dict[str, Any]
    extraction_candidates: list[ExtractionCandidate]
    unresolved_fields: list[str]
    interview_questions: list[Any]


@dataclass(slots=True)
class SpecExtractionResult:
    field_path: str
    value: Any | None
    confidence: float
    source_artifact_id: str
    method: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "value": self.value,
            "confidence": self.confidence,
            "source_artifact_id": self.source_artifact_id,
            "method": self.method,
            "evidence": dict(self.evidence),
        }


@dataclass(slots=True)
class ScheduleRow:
    equipment_id: str | None
    tokens: list[str]
    numeric_values: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "equipment_id": self.equipment_id,
            "tokens": list(self.tokens),
            "numeric_values": list(self.numeric_values),
        }


@dataclass(slots=True)
class ScheduleExtraction:
    artifact_id: str
    page_number: int
    schedule_type: str
    rows: list[ScheduleRow] = field(default_factory=list)
    confidence: float | None = None
    source_method: str = "table_schedule_extraction"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "page_number": self.page_number,
            "schedule_type": self.schedule_type,
            "rows": [row.to_dict() for row in self.rows],
            "confidence": self.confidence,
            "source_method": self.source_method,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ScheduleExtractionResult:
    run_id: str
    schedule_candidates: list[ScheduleExtraction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "SCHEDULE_EXTRACTION_COMPLETE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schedule_candidates": [candidate.to_dict() for candidate in self.schedule_candidates],
            "warnings": list(self.warnings),
            "status": self.status,
        }
