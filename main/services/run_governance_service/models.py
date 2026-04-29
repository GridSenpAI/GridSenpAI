from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RunMetadata:
    run_id: str
    created_at: str
    updated_at: str
    completed_at: str | None
    status: str
    execution_mode: str
    project_name: str
    model_version: str
    prompt_template_version: str
    schema_version_input: str
    schema_version_output: str
    project_id: str = ""
    project_number: str = ""
    applicant: str = ""
    primary_planner_contract_path: str = ""
    planner_required_fields_path: str = ""
    legacy_input_schema_path: str = ""
    legacy_output_schema_path: str = ""
    parent_run_id: str | None = None
    replay_source_run_id: str | None = None
    replay_stage_boundary: str | None = None
    notes: list[str] = field(default_factory=list)
    public_stage_order: list[str] = field(default_factory=list)
    public_stage_labels: list[dict[str, str]] = field(default_factory=list)
    gap_resolution_substage_order: list[str] = field(default_factory=list)
    gap_resolution_substage_labels: list[dict[str, str]] = field(default_factory=list)
    active_bounded_assist_backend: str = ""
    inactive_compatibility_layers: list[str] = field(default_factory=list)
    canonical_knowledge_families: list[str] = field(default_factory=list)
    legacy_knowledge_fallbacks: list[str] = field(default_factory=list)
    snapshot_count: int = 0
    persisted_stage_count: int = 0
    final_canonical_state_path: str | None = None
    final_pipeline_summary_path: str | None = None
    export_manifest_path: str | None = None
    lineage_path: str | None = None
    snapshot_manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "execution_mode": self.execution_mode,
            "project_name": self.project_name,
            "project_id": self.project_id,
            "project_number": self.project_number,
            "applicant": self.applicant,
            "model_version": self.model_version,
            "prompt_template_version": self.prompt_template_version,
            "schema_version_input": self.schema_version_input,
            "schema_version_output": self.schema_version_output,
            "primary_planner_contract_path": self.primary_planner_contract_path,
            "planner_required_fields_path": self.planner_required_fields_path,
            "legacy_input_schema_path": self.legacy_input_schema_path,
            "legacy_output_schema_path": self.legacy_output_schema_path,
            "parent_run_id": self.parent_run_id,
            "replay_source_run_id": self.replay_source_run_id,
            "replay_stage_boundary": self.replay_stage_boundary,
            "notes": list(self.notes),
            "public_stage_order": list(self.public_stage_order),
            "public_stage_labels": [dict(item) for item in self.public_stage_labels],
            "gap_resolution_substage_order": list(self.gap_resolution_substage_order),
            "gap_resolution_substage_labels": [dict(item) for item in self.gap_resolution_substage_labels],
            "active_bounded_assist_backend": self.active_bounded_assist_backend,
            "inactive_compatibility_layers": list(self.inactive_compatibility_layers),
            "canonical_knowledge_families": list(self.canonical_knowledge_families),
            "legacy_knowledge_fallbacks": list(self.legacy_knowledge_fallbacks),
            "snapshot_count": self.snapshot_count,
            "persisted_stage_count": self.persisted_stage_count,
            "final_canonical_state_path": self.final_canonical_state_path,
            "final_pipeline_summary_path": self.final_pipeline_summary_path,
            "export_manifest_path": self.export_manifest_path,
            "lineage_path": self.lineage_path,
            "snapshot_manifest_path": self.snapshot_manifest_path,
        }


@dataclass(slots=True)
class SnapshotRecord:
    snapshot_id: str
    run_id: str
    label: str
    created_at: str
    relative_path: str
    state_version: str
    governance_version: str
    field_record_count: int
    conflict_count: int
    review_flag_count: int
    stage_status: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "label": self.label,
            "created_at": self.created_at,
            "relative_path": self.relative_path,
            "state_version": self.state_version,
            "governance_version": self.governance_version,
            "field_record_count": self.field_record_count,
            "conflict_count": self.conflict_count,
            "review_flag_count": self.review_flag_count,
            "stage_status": dict(self.stage_status),
        }


@dataclass(slots=True)
class LineageRecord:
    run_id: str
    parent_run_id: str | None
    replay_source_run_id: str | None
    replay_stage_boundary: str | None
    created_at: str
    lineage_depth: int
    ancestry: list[str] = field(default_factory=list)
    related_runs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "replay_source_run_id": self.replay_source_run_id,
            "replay_stage_boundary": self.replay_stage_boundary,
            "created_at": self.created_at,
            "lineage_depth": self.lineage_depth,
            "ancestry": list(self.ancestry),
            "related_runs": list(self.related_runs),
        }