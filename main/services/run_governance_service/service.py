from __future__ import annotations

from pathlib import Path
from typing import Any

from shared.runtime_stage_contract import ordered_stage_status, replay_contract_summary

from services.audit_logging_service.service import initialize_audit_logger
from services.run_governance_service.models import LineageRecord, RunMetadata, SnapshotRecord
from services.run_governance_service.utils import (
    count_persisted_stage_files,
    derive_canonical_state_stats,
    load_parent_lineage,
    relative_to_run_dir,
    slugify_label,
    utc_now_iso,
    write_json,
)


def _require_run_id(context: Any) -> str:
    run_id = getattr(context, "run_id", None)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("context.run_id must be a non-empty string.")
    return run_id.strip()


def _require_run_dir(context: Any) -> Path:
    run_dir = getattr(context, "run_dir", None)
    if run_dir is None:
        raise ValueError("context.run_dir is required.")
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _context_config_attr(context: Any, attribute: str, default: str = "") -> str:
    config = getattr(context, "config", None)
    value = getattr(config, attribute, default) if config is not None else default
    return str(value) if value is not None else default


def _context_optional_attr(context: Any, attribute: str) -> str | None:
    value = getattr(context, attribute, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_run_metadata(context: Any) -> RunMetadata:
    now = utc_now_iso()
    contract = replay_contract_summary()
    return RunMetadata(
        run_id=_require_run_id(context),
        created_at=now,
        updated_at=now,
        completed_at=None,
        status="INITIALIZED",
        execution_mode=_context_optional_attr(context, "execution_mode") or "STANDARD",
        project_name=_context_config_attr(context, "project_name", "GridSenpAI"),
        model_version=_context_config_attr(context, "model_version", ""),
        prompt_template_version=_context_config_attr(context, "prompt_template_version", ""),
        schema_version_input=_context_config_attr(context, "schema_version_input", ""),
        schema_version_output=_context_config_attr(context, "schema_version_output", ""),
        primary_planner_contract_path=str(contract.get("primary_planner_contract_path", "")),
        planner_required_fields_path=str(contract.get("planner_required_fields_path", "")),
        legacy_input_schema_path=str(contract.get("legacy_input_schema_path", "")),
        legacy_output_schema_path=str(contract.get("legacy_output_schema_path", "")),
        parent_run_id=_context_optional_attr(context, "parent_run_id"),
        replay_source_run_id=_context_optional_attr(context, "replay_source_run_id"),
        replay_stage_boundary=_context_optional_attr(context, "replay_stage_boundary"),
        notes=[],
        public_stage_order=list(contract["public_stage_order"]),
        public_stage_labels=[dict(item) for item in contract.get("public_stage_labels", [])],
        gap_resolution_substage_order=list(contract["gap_resolution_substage_order"]),
        gap_resolution_substage_labels=[dict(item) for item in contract.get("gap_resolution_substage_labels", [])],
        active_bounded_assist_backend=str(contract.get("active_bounded_assist_backend", "")),
        inactive_compatibility_layers=list(contract.get("inactive_compatibility_layers", [])),
        canonical_knowledge_families=list(contract.get("canonical_knowledge_families", [])),
        legacy_knowledge_fallbacks=list(contract.get("legacy_knowledge_fallbacks", [])),
    )


def _build_lineage(context: Any, run_dir: Path) -> LineageRecord:
    run_id = _require_run_id(context)
    parent_run_id = _context_optional_attr(context, "parent_run_id")
    replay_source_run_id = _context_optional_attr(context, "replay_source_run_id")
    replay_stage_boundary = _context_optional_attr(context, "replay_stage_boundary")

    ancestry: list[str] = []
    related_runs: list[str] = []

    if parent_run_id:
        parent_run_dir = Path(getattr(context, "output_dir")) / parent_run_id
        parent_lineage = load_parent_lineage(parent_run_dir)
        if isinstance(parent_lineage, dict):
            parent_ancestry = parent_lineage.get("ancestry", [])
            if isinstance(parent_ancestry, list):
                ancestry.extend(str(item) for item in parent_ancestry if str(item).strip())
            ancestry.append(parent_run_id)
        else:
            ancestry.append(parent_run_id)
        related_runs.append(parent_run_id)

    if replay_source_run_id and replay_source_run_id not in related_runs:
        related_runs.append(replay_source_run_id)

    lineage = LineageRecord(
        run_id=run_id,
        parent_run_id=parent_run_id,
        replay_source_run_id=replay_source_run_id,
        replay_stage_boundary=replay_stage_boundary,
        created_at=utc_now_iso(),
        lineage_depth=len(ancestry),
        ancestry=ancestry,
        related_runs=related_runs,
    )

    write_json(run_dir / "lineage.json", lineage.to_dict())
    return lineage


class RunGovernanceManager:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.run_id = _require_run_id(context)
        self.run_dir = _require_run_dir(context)

        self.audit_logger = initialize_audit_logger(context)

        self.snapshots_dir = self.run_dir / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        self.metadata_path = self.run_dir / "run_metadata.json"
        self.lineage_path = self.run_dir / "lineage.json"
        self.snapshot_manifest_path = self.snapshots_dir / "snapshot_manifest.json"

        self.metadata = build_run_metadata(context)
        self.metadata.lineage_path = relative_to_run_dir(self.lineage_path, self.run_dir)
        self.metadata.snapshot_manifest_path = relative_to_run_dir(
            self.snapshot_manifest_path,
            self.run_dir,
        )

        self.lineage = _build_lineage(context, self.run_dir)
        self.snapshots: list[dict[str, Any]] = []

        write_json(self.metadata_path, self.metadata.to_dict())

        write_json(
            self.snapshot_manifest_path,
            {
                "run_id": self.run_id,
                "generated_at": utc_now_iso(),
                "snapshot_count": 0,
                "snapshots": [],
            },
        )

        self.audit_logger.log_event(
            event_type="run_governance_initialized",
            stage_name="governance",
            status="STARTED",
            message="Run governance manager initialized.",
            metadata={"run_id": self.run_id},
        )

    def snapshot_canonical_state(self, label: str, canonical_state: dict[str, Any]) -> dict[str, Any]:
        stats = derive_canonical_state_stats(canonical_state)
        snapshot_index = len(self.snapshots) + 1
        snapshot_slug = slugify_label(label)
        snapshot_name = f"{snapshot_index:03d}_{snapshot_slug}.json"
        snapshot_path = self.snapshots_dir / snapshot_name

        write_json(snapshot_path, canonical_state)

        snapshot = SnapshotRecord(
            snapshot_id=f"{self.run_id}_snapshot_{snapshot_index:03d}",
            run_id=self.run_id,
            label=label,
            created_at=utc_now_iso(),
            relative_path=relative_to_run_dir(snapshot_path, self.run_dir),
            state_version=stats["state_version"],
            governance_version=stats["governance_version"],
            field_record_count=int(stats["field_record_count"]),
            conflict_count=int(stats["conflict_count"]),
            review_flag_count=int(stats["review_flag_count"]),
            stage_status=ordered_stage_status(stats["stage_status"]),
        )

        snapshot_payload = snapshot.to_dict()
        self.snapshots.append(snapshot_payload)

        write_json(
            self.snapshot_manifest_path,
            {
                "run_id": self.run_id,
                "generated_at": utc_now_iso(),
                "snapshot_count": len(self.snapshots),
                "snapshots": self.snapshots,
            },
        )

        self.metadata.snapshot_count = len(self.snapshots)
        self.metadata.updated_at = utc_now_iso()
        write_json(self.metadata_path, self.metadata.to_dict())

        self.audit_logger.log_event(
            event_type="canonical_snapshot_created",
            stage_name="canonical_state",
            status="COMPLETED",
            message=f"Snapshot created: {label}",
            metadata={
                "snapshot_index": snapshot_index,
                "field_record_count": stats["field_record_count"],
                "conflict_count": stats["conflict_count"],
            },
        )

        return snapshot_payload

    def update_project_identity(self, project_identity: dict[str, Any]) -> None:
        if not isinstance(project_identity, dict):
            return

        project_name = str(project_identity.get("project_name") or "").strip()
        project_id = str(project_identity.get("project_id") or "").strip()
        project_number = str(project_identity.get("project_number") or "").strip()
        applicant = str(project_identity.get("applicant") or "").strip()

        if project_name:
            self.metadata.project_name = project_name
        if hasattr(self.metadata, "project_id"):
            self.metadata.project_id = project_id
        if hasattr(self.metadata, "project_number"):
            self.metadata.project_number = project_number
        if hasattr(self.metadata, "applicant"):
            self.metadata.applicant = applicant

        self.metadata.updated_at = utc_now_iso()
        write_json(self.metadata_path, self.metadata.to_dict())


    def finalize(
        self,
        *,
        status: str,
        canonical_state_path: Path | None = None,
        pipeline_summary_path: Path | None = None,
        export_manifest_path: Path | None = None,
        notes: list[str] | None = None,
    ) -> dict[str, Any]:
        self.metadata.status = status
        self.metadata.updated_at = utc_now_iso()
        self.metadata.completed_at = utc_now_iso()
        self.metadata.persisted_stage_count = count_persisted_stage_files(self.run_dir)

        if canonical_state_path is not None:
            self.metadata.final_canonical_state_path = relative_to_run_dir(
                canonical_state_path,
                self.run_dir,
            )

        if pipeline_summary_path is not None:
            self.metadata.final_pipeline_summary_path = relative_to_run_dir(
                pipeline_summary_path,
                self.run_dir,
            )

        if export_manifest_path is not None:
            self.metadata.export_manifest_path = relative_to_run_dir(
                export_manifest_path,
                self.run_dir,
            )

        if notes:
            self.metadata.notes.extend(str(item) for item in notes if str(item).strip())

        write_json(self.metadata_path, self.metadata.to_dict())

        self.audit_logger.log_event(
            event_type="run_governance_finalized",
            stage_name="governance",
            status=status,
            message="Run governance finalized.",
            metadata={
                "snapshot_count": self.metadata.snapshot_count,
                "persisted_stage_count": self.metadata.persisted_stage_count,
            },
        )

        return {
            "run_id": self.run_id,
            "status": self.metadata.status,
            "run_metadata_path": relative_to_run_dir(self.metadata_path, self.run_dir),
            "lineage_path": relative_to_run_dir(self.lineage_path, self.run_dir),
            "snapshot_manifest_path": relative_to_run_dir(
                self.snapshot_manifest_path,
                self.run_dir,
            ),
            "snapshot_count": self.metadata.snapshot_count,
            "persisted_stage_count": self.metadata.persisted_stage_count,
        }


def initialize_run_governance(context: Any) -> RunGovernanceManager:
    return RunGovernanceManager(context)


def finalize_run_governance(
    manager: RunGovernanceManager,
    *,
    status: str,
    canonical_state_path: Path | None = None,
    pipeline_summary_path: Path | None = None,
    export_manifest_path: Path | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return manager.finalize(
        status=status,
        canonical_state_path=canonical_state_path,
        pipeline_summary_path=pipeline_summary_path,
        export_manifest_path=export_manifest_path,
        notes=notes,
    )