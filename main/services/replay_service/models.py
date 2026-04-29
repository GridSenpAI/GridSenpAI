from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ReplayPlan:
    source_run_id: str
    source_run_dir: str
    requested_stage_boundary: str
    resume_from_stage: str
    public_stage_order: list[str] = field(default_factory=list)
    public_stage_labels: list[dict[str, str]] = field(default_factory=list)
    gap_resolution_substage_order: list[str] = field(default_factory=list)
    gap_resolution_substage_labels: list[dict[str, str]] = field(default_factory=list)
    active_bounded_assist_backend: str = ""
    inactive_compatibility_layers: list[str] = field(default_factory=list)
    canonical_knowledge_families: list[str] = field(default_factory=list)
    legacy_knowledge_fallbacks: list[str] = field(default_factory=list)
    reused_stages: list[str] = field(default_factory=list)
    rerun_stages: list[str] = field(default_factory=list)
    reused_gap_resolution_substages: list[str] = field(default_factory=list)
    source_pipeline_summary: dict[str, Any] = field(default_factory=dict)
    source_run_metadata: dict[str, Any] = field(default_factory=dict)
    source_lineage: dict[str, Any] = field(default_factory=dict)
    source_snapshot_manifest: dict[str, Any] = field(default_factory=dict)
    reused_stage_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    reused_gap_resolution_substage_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_canonical_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_run_id": self.source_run_id,
            "source_run_dir": self.source_run_dir,
            "requested_stage_boundary": self.requested_stage_boundary,
            "resume_from_stage": self.resume_from_stage,
            "public_stage_order": list(self.public_stage_order),
            "public_stage_labels": [dict(item) for item in self.public_stage_labels],
            "gap_resolution_substage_order": list(self.gap_resolution_substage_order),
            "gap_resolution_substage_labels": [dict(item) for item in self.gap_resolution_substage_labels],
            "active_bounded_assist_backend": self.active_bounded_assist_backend,
            "inactive_compatibility_layers": list(self.inactive_compatibility_layers),
            "canonical_knowledge_families": list(self.canonical_knowledge_families),
            "legacy_knowledge_fallbacks": list(self.legacy_knowledge_fallbacks),
            "reused_stages": list(self.reused_stages),
            "rerun_stages": list(self.rerun_stages),
            "reused_gap_resolution_substages": list(self.reused_gap_resolution_substages),
            "source_pipeline_summary": dict(self.source_pipeline_summary),
            "source_run_metadata": dict(self.source_run_metadata),
            "source_lineage": dict(self.source_lineage),
            "source_snapshot_manifest": dict(self.source_snapshot_manifest),
            "reused_stage_outputs": {
                key: dict(value) for key, value in self.reused_stage_outputs.items()
            },
            "reused_gap_resolution_substage_outputs": {
                key: dict(value) for key, value in self.reused_gap_resolution_substage_outputs.items()
            },
            "source_canonical_state": dict(self.source_canonical_state),
        }


@dataclass(slots=True)
class ReplayManifest:
    run_id: str
    created_at: str
    status: str
    source_run_id: str
    requested_stage_boundary: str
    resume_from_stage: str
    public_stage_order: list[str] = field(default_factory=list)
    public_stage_labels: list[dict[str, str]] = field(default_factory=list)
    gap_resolution_substage_order: list[str] = field(default_factory=list)
    gap_resolution_substage_labels: list[dict[str, str]] = field(default_factory=list)
    active_bounded_assist_backend: str = ""
    inactive_compatibility_layers: list[str] = field(default_factory=list)
    canonical_knowledge_families: list[str] = field(default_factory=list)
    legacy_knowledge_fallbacks: list[str] = field(default_factory=list)
    reused_stages: list[str] = field(default_factory=list)
    rerun_stages: list[str] = field(default_factory=list)
    reused_gap_resolution_substages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "status": self.status,
            "source_run_id": self.source_run_id,
            "requested_stage_boundary": self.requested_stage_boundary,
            "resume_from_stage": self.resume_from_stage,
            "public_stage_order": list(self.public_stage_order),
            "public_stage_labels": [dict(item) for item in self.public_stage_labels],
            "gap_resolution_substage_order": list(self.gap_resolution_substage_order),
            "gap_resolution_substage_labels": [dict(item) for item in self.gap_resolution_substage_labels],
            "active_bounded_assist_backend": self.active_bounded_assist_backend,
            "inactive_compatibility_layers": list(self.inactive_compatibility_layers),
            "canonical_knowledge_families": list(self.canonical_knowledge_families),
            "legacy_knowledge_fallbacks": list(self.legacy_knowledge_fallbacks),
            "reused_stages": list(self.reused_stages),
            "rerun_stages": list(self.rerun_stages),
            "reused_gap_resolution_substages": list(self.reused_gap_resolution_substages),
            "notes": list(self.notes),
        }
