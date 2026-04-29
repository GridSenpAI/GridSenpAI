from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    file_name: str
    file_path: str
    file_suffix: str
    size_bytes: int
    ingested_at: str
    index_status: str
    classification: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_suffix": self.file_suffix,
            "size_bytes": self.size_bytes,
            "ingested_at": self.ingested_at,
            "index_status": self.index_status,
            "classification": self.classification,
        }


@dataclass(slots=True)
class EntityRecord:
    entity_id: str
    type: str
    name: str
    attributes: Dict[str, Any]
    units: Dict[str, Any]
    source_anchor_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "type": self.type,
            "name": self.name,
            "attributes": self.attributes,
            "units": self.units,
            "source_anchor_id": self.source_anchor_id,
        }


@dataclass(slots=True)
class SourceAnchor:
    anchor_id: str
    artifact_id: str
    file_name: str
    page: int
    text_pointer: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "artifact_id": self.artifact_id,
            "file_name": self.file_name,
            "page": self.page,
            "text_pointer": self.text_pointer,
        }


@dataclass(slots=True)
class EvidenceSnippet:
    snippet_id: str
    corpus: str
    source_ref: str
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snippet_id": self.snippet_id,
            "corpus": self.corpus,
            "source_ref": self.source_ref,
            "text": self.text,
            "score": self.score,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class OutputParameter:
    parameter_path: str
    value: Any
    units: str
    provenance_type: str
    provenance_ref: Any
    confidence_tag: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter_path": self.parameter_path,
            "value": self.value,
            "units": self.units,
            "provenance_type": self.provenance_type,
            "provenance_ref": self.provenance_ref,
            "confidence_tag": self.confidence_tag,
        }


@dataclass(slots=True)
class AssumptionRecord:
    assumption_id: str
    parameter_path: str
    nominal_value: Any
    bounds: Dict[str, Any]
    rationale: str
    created_by: str
    status: str = "ACTIVE"
    evidence_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "parameter_path": self.parameter_path,
            "nominal_value": self.nominal_value,
            "bounds": self.bounds,
            "rationale": self.rationale,
            "created_by": self.created_by,
            "status": self.status,
            "evidence_refs": list(self.evidence_refs),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ScenarioVariant:
    label: str
    description: str
    outputs: Dict[str, Any]
    confidence: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "outputs": self.outputs,
            "confidence": self.confidence,
        }


@dataclass(slots=True)
class FieldRecord:
    field_record_id: str
    field_path: str
    value: Any
    source_stage: str
    source_type: str
    source_ref: List[str] = field(default_factory=list)
    confidence_score: float | None = None
    confidence_tag: str = "LOW"
    validation_status: str = "UNVALIDATED"
    review_status: str = "PENDING_REVIEW"
    evidence_strength: str = "UNKNOWN"
    conflict_status: str = "NO_CONFLICT"
    is_missing: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_record_id": self.field_record_id,
            "field_path": self.field_path,
            "value": self.value,
            "source_stage": self.source_stage,
            "source_type": self.source_type,
            "source_ref": list(self.source_ref),
            "confidence_score": self.confidence_score,
            "confidence_tag": self.confidence_tag,
            "validation_status": self.validation_status,
            "review_status": self.review_status,
            "evidence_strength": self.evidence_strength,
            "conflict_status": self.conflict_status,
            "is_missing": self.is_missing,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ConflictRecord:
    conflict_id: str
    field_path: str
    conflict_type: str
    severity: str
    status: str
    record_ids: List[str] = field(default_factory=list)
    candidate_values: List[Any] = field(default_factory=list)
    source_stages: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "field_path": self.field_path,
            "conflict_type": self.conflict_type,
            "severity": self.severity,
            "status": self.status,
            "record_ids": list(self.record_ids),
            "candidate_values": list(self.candidate_values),
            "source_stages": list(self.source_stages),
            "details": dict(self.details),
        }


@dataclass(slots=True)
class ReviewFlagRecord:
    review_flag_id: str
    category: str
    severity: str
    status: str
    message: str
    field_path: str | None = None
    record_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "review_flag_id": self.review_flag_id,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
            "field_path": self.field_path,
            "record_ids": list(self.record_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class CalibrationDatasetRecord:
    dataset_id: str
    dataset_type: str
    version: str
    source_artifact_id: str = ""
    source_file_name: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_type": self.dataset_type,
            "version": self.version,
            "source_artifact_id": self.source_artifact_id,
            "source_file_name": self.source_file_name,
            "provenance": dict(self.provenance),
            "parameters": list(self.parameters),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class CalibrationRecord:
    calibration_record_id: str
    field_path: str
    expected_value: Any
    observed_value: Any
    adjusted_value: Any
    tolerance: Dict[str, Any] = field(default_factory=dict)
    deviation: Dict[str, Any] = field(default_factory=dict)
    status: str = "REVIEW_REQUIRED"
    dataset_id: str = ""
    linked_field_record_ids: List[str] = field(default_factory=list)
    linked_assumption_ids: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calibration_record_id": self.calibration_record_id,
            "field_path": self.field_path,
            "expected_value": self.expected_value,
            "observed_value": self.observed_value,
            "adjusted_value": self.adjusted_value,
            "tolerance": dict(self.tolerance),
            "deviation": dict(self.deviation),
            "status": self.status,
            "dataset_id": self.dataset_id,
            "linked_field_record_ids": list(self.linked_field_record_ids),
            "linked_assumption_ids": list(self.linked_assumption_ids),
            "evidence_refs": list(self.evidence_refs),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ValidationRunRecord:
    validation_run_id: str
    rule_set_version: str
    executed_at: str
    status: str
    datasets_used: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_run_id": self.validation_run_id,
            "rule_set_version": self.rule_set_version,
            "executed_at": self.executed_at,
            "status": self.status,
            "datasets_used": list(self.datasets_used),
            "summary": dict(self.summary),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ReconciliationRecord:
    reconciliation_id: str
    field_path: str
    reconciliation_status: str
    rationale: str
    conflicting_record_ids: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reconciliation_id": self.reconciliation_id,
            "field_path": self.field_path,
            "reconciliation_status": self.reconciliation_status,
            "rationale": self.rationale,
            "conflicting_record_ids": list(self.conflicting_record_ids),
            "evidence_refs": list(self.evidence_refs),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ChangeLogRecord:
    change_id: str
    changed_at: str
    change_type: str
    field_path: str = ""
    prior_value: Any = None
    new_value: Any = None
    rationale: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_id": self.change_id,
            "changed_at": self.changed_at,
            "change_type": self.change_type,
            "field_path": self.field_path,
            "prior_value": self.prior_value,
            "new_value": self.new_value,
            "rationale": self.rationale,
            "metadata": dict(self.metadata),
        }