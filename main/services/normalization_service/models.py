# services/normalization_service/models.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FieldUpdateRecord:
    field_path: str
    candidate_value: Any
    accepted_value: Any
    source_type: str
    source_name: str = ""
    source_anchor_id: str = ""
    source_entity_id: str = ""
    question_id: str = ""
    confidence: str = ""
    decision: str = "ACCEPTED"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "candidate_value": self.candidate_value,
            "accepted_value": self.accepted_value,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "source_anchor_id": self.source_anchor_id,
            "source_entity_id": self.source_entity_id,
            "question_id": self.question_id,
            "confidence": self.confidence,
            "decision": self.decision,
            "reason": self.reason,
        }


@dataclass(slots=True)
class ConflictRecord:
    field_path: str
    existing_value: Any
    candidate_value: Any
    source_type: str
    reason: str
    review_status: str = "REVIEW_REQUIRED"
    entity_id: str = ""
    source_anchor_id: str = ""
    source_name: str = ""
    question_id: str = ""
    cue_type: str = ""
    artifact_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "existing_value": self.existing_value,
            "candidate_value": self.candidate_value,
            "source_type": self.source_type,
            "reason": self.reason,
            "review_status": self.review_status,
            "entity_id": self.entity_id,
            "source_anchor_id": self.source_anchor_id,
            "source_name": self.source_name,
            "question_id": self.question_id,
            "cue_type": self.cue_type,
            "artifact_id": self.artifact_id,
        }


@dataclass(slots=True)
class MissingFieldRecord:
    field_path: str
    severity: str = "HIGH"
    reason: str = "Required modeling parameter not identified in provided artifacts."

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "severity": self.severity,
            "reason": self.reason,
        }


@dataclass(slots=True)
class NormalizationServiceResult:
    run_id: str
    normalized_input: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)
    followup_questions: list[dict[str, Any]] = field(default_factory=list)
    accepted_updates: list[dict[str, Any]] = field(default_factory=list)
    rejected_updates: list[dict[str, Any]] = field(default_factory=list)
    status: str = "NORMALIZED"
    normalized_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "normalized_input": dict(self.normalized_input),
            "validation_report": dict(self.validation_report),
            "followup_questions": list(self.followup_questions),
            "accepted_updates": list(self.accepted_updates),
            "rejected_updates": list(self.rejected_updates),
            "status": self.status,
            "normalized_at": self.normalized_at,
        }