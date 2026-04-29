from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class CanonicalStateBuildInputs:
    run_id: str
    ingestion_result: dict[str, Any] | None = None
    extraction_result: dict[str, Any] | None = None
    interview_result: dict[str, Any] | None = None
    normalization_result: dict[str, Any] | None = None
    retrieval_result: dict[str, Any] | None = None
    translation_result: dict[str, Any] | None = None
    scenario_result: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    existing_state: dict[str, Any] | None = None


@dataclass(slots=True)
class CanonicalStateBuildSummary:
    artifact_count: int = 0
    entity_count: int = 0
    topology_cue_count: int = 0
    source_anchor_count: int = 0
    evidence_snippet_count: int = 0
    output_parameter_count: int = 0
    assumption_count: int = 0
    scenario_count: int = 0
    followup_question_count: int = 0
    field_record_count: int = 0
    conflict_count: int = 0
    review_flag_count: int = 0
    missing_field_count: int = 0
    planner_registry_total_field_count: int = 0
    planner_registry_required_field_count: int = 0
    planner_registry_resolved_count: int = 0
    planner_registry_review_required_count: int = 0
    planner_registry_conflicting_count: int = 0
    planner_registry_missing_count: int = 0
    planner_registry_unresolved_count: int = 0
    planner_registry_resolution_queue_count: int = 0
    planner_registry_resolution_queue_field_ids: list[str] = field(default_factory=list)
    planner_registry_planner_critical_open_count: int = 0
    planner_registry_required_missing_count: int = 0
    planner_registry_coverage: dict[str, Any] = field(default_factory=dict)
    planner_registry_open_items: dict[str, Any] = field(default_factory=dict)
    planner_registry_resolution_backlog: dict[str, Any] = field(default_factory=dict)
    field_resolution_summary: dict[str, Any] = field(default_factory=dict)
    field_resolution_backlog_count: int = 0
    field_resolution_accepted_field_count: int = 0
    field_resolution_planner_review_count: int = 0
    field_resolution_confirmation_needed_count: int = 0
    field_resolution_high_materiality_conflict_count: int = 0
    field_resolution_planner_review_queue_count: int = 0
    field_resolution_top_backlog_field_ids: list[str] = field(default_factory=list)
    field_resolution_governance_posture: dict[str, Any] = field(default_factory=dict)
    stage_status: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_count": self.artifact_count,
            "entity_count": self.entity_count,
            "topology_cue_count": self.topology_cue_count,
            "source_anchor_count": self.source_anchor_count,
            "evidence_snippet_count": self.evidence_snippet_count,
            "output_parameter_count": self.output_parameter_count,
            "assumption_count": self.assumption_count,
            "scenario_count": self.scenario_count,
            "followup_question_count": self.followup_question_count,
            "field_record_count": self.field_record_count,
            "conflict_count": self.conflict_count,
            "review_flag_count": self.review_flag_count,
            "missing_field_count": self.missing_field_count,
            "planner_registry_total_field_count": self.planner_registry_total_field_count,
            "planner_registry_required_field_count": self.planner_registry_required_field_count,
            "planner_registry_resolved_count": self.planner_registry_resolved_count,
            "planner_registry_review_required_count": self.planner_registry_review_required_count,
            "planner_registry_conflicting_count": self.planner_registry_conflicting_count,
            "planner_registry_missing_count": self.planner_registry_missing_count,
            "planner_registry_unresolved_count": self.planner_registry_unresolved_count,
            "planner_registry_resolution_queue_count": self.planner_registry_resolution_queue_count,
            "planner_registry_resolution_queue_field_ids": list(self.planner_registry_resolution_queue_field_ids),
            "planner_registry_planner_critical_open_count": self.planner_registry_planner_critical_open_count,
            "planner_registry_required_missing_count": self.planner_registry_required_missing_count,
            "planner_registry_coverage": dict(self.planner_registry_coverage),
            "planner_registry_open_items": dict(self.planner_registry_open_items),
            "planner_registry_resolution_backlog": dict(self.planner_registry_resolution_backlog),
            "field_resolution_summary": dict(self.field_resolution_summary),
            "field_resolution_backlog_count": self.field_resolution_backlog_count,
            "field_resolution_accepted_field_count": self.field_resolution_accepted_field_count,
            "field_resolution_planner_review_count": self.field_resolution_planner_review_count,
            "field_resolution_confirmation_needed_count": self.field_resolution_confirmation_needed_count,
            "field_resolution_high_materiality_conflict_count": self.field_resolution_high_materiality_conflict_count,
            "field_resolution_planner_review_queue_count": self.field_resolution_planner_review_queue_count,
            "field_resolution_top_backlog_field_ids": list(self.field_resolution_top_backlog_field_ids),
            "field_resolution_governance_posture": dict(self.field_resolution_governance_posture),
            "stage_status": dict(self.stage_status),
        }


@dataclass(slots=True)
class CanonicalStateServiceResult:
    run_id: str
    canonical_state: dict[str, Any]
    build_summary: CanonicalStateBuildSummary
    warnings: list[str] = field(default_factory=list)
    status: str = "CANONICAL_STATE_PERSISTED"
    built_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "canonical_state": dict(self.canonical_state),
            "build_summary": self.build_summary.to_dict(),
            "warnings": list(self.warnings),
            "status": self.status,
            "built_at": self.built_at,
        }


@dataclass(slots=True)
class CanonicalFieldUpdate:
    field_path: str
    value: Any | None
    confidence: float
    source_artifact_id: str
    method: str
    evidence: dict[str, Any]
    status: str = "provisional_extracted"
    last_update_stage: str = "extraction"
    updated_at: str = field(default_factory=utc_now_iso)
    run_id: str | None = None


@dataclass(slots=True)
class CanonicalFieldRecord:
    field_path: str
    value: Any | None
    status: str
    confidence: float
    source_artifact_id: str
    method: str
    evidence: dict[str, Any]
    last_update_stage: str = "extraction"
    updated_at: str = field(default_factory=utc_now_iso)
    run_id: str | None = None
    is_primary: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "value": self.value,
            "status": self.status,
            "confidence": self.confidence,
            "source_artifact_id": self.source_artifact_id,
            "method": self.method,
            "evidence": dict(self.evidence),
            "last_update_stage": self.last_update_stage,
            "updated_at": self.updated_at,
            "run_id": self.run_id,
            "is_primary": self.is_primary,
        }


@dataclass(slots=True)
class ConflictRecord:
    field_path: str
    primary_value: Any | None
    conflicting_value: Any | None
    primary_source_artifact_id: str
    conflicting_source_artifact_id: str
    confidence_delta: float
    conflict_reason: str
    created_at: str = field(default_factory=utc_now_iso)
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "primary_value": self.primary_value,
            "conflicting_value": self.conflicting_value,
            "primary_source_artifact_id": self.primary_source_artifact_id,
            "conflicting_source_artifact_id": self.conflicting_source_artifact_id,
            "confidence_delta": self.confidence_delta,
            "conflict_reason": self.conflict_reason,
            "created_at": self.created_at,
            "run_id": self.run_id,
        }


@dataclass(slots=True)
class ReviewFlag:
    review_flag_id: str
    category: str
    field_path: str
    message: str
    source_stage: str = "extraction"
    related_artifact_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_flag_id": self.review_flag_id,
            "category": self.category,
            "field_path": self.field_path,
            "message": self.message,
            "source_stage": self.source_stage,
            "related_artifact_ids": list(self.related_artifact_ids),
            "created_at": self.created_at,
            "run_id": self.run_id,
        }
