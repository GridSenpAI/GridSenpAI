from __future__ import annotations

from pathlib import Path
from typing import Any

from shared.runtime_stage_contract import replay_contract_summary
from services.audit_logging_service.service import initialize_audit_logger
from services.replay_service.models import ReplayManifest, ReplayPlan
from services.replay_service.utils import (
    canonical_state_path,
    compute_reused_and_rerun_stages,
    compute_reused_gap_resolution_substages,
    read_json,
    require_non_empty_string,
    stage_output_path,
    substage_output_path,
    utc_now_iso,
    validate_stage_boundary,
    write_json,
)


def _require_context_run_id(context: Any) -> str:
    run_id = getattr(context, "run_id", None)
    return require_non_empty_string(run_id, "context.run_id")


def _require_context_run_dir(context: Any) -> Path:
    run_dir = getattr(context, "run_dir", None)
    if run_dir is None:
        raise ValueError("context.run_dir is required.")
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _require_context_output_dir(context: Any) -> Path:
    output_dir = getattr(context, "output_dir", None)
    if output_dir is None:
        raise ValueError("context.output_dir is required.")
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _source_run_dir(context: Any, source_run_id: str) -> Path:
    return _require_context_output_dir(context) / source_run_id


def build_replay_plan(
    context: Any,
    replay_source_run_id: str,
    replay_stage_boundary: str,
) -> dict[str, Any]:
    source_run_id = require_non_empty_string(
        replay_source_run_id,
        "replay_source_run_id",
    )
    boundary = validate_stage_boundary(replay_stage_boundary)

    source_run_dir = _source_run_dir(context, source_run_id)
    if not source_run_dir.exists():
        raise FileNotFoundError(f"Replay source run directory not found: {source_run_dir}")

    summary_path = source_run_dir / "pipeline_summary.json"
    metadata_path = source_run_dir / "run_metadata.json"
    lineage_path = source_run_dir / "lineage.json"
    snapshot_manifest_path = source_run_dir / "snapshots" / "snapshot_manifest.json"
    source_state_path = canonical_state_path(source_run_dir)

    pipeline_summary = read_json(summary_path, default=None)
    if not isinstance(pipeline_summary, dict):
        raise FileNotFoundError(
            f"Replay source pipeline summary missing or invalid: {summary_path}"
        )

    run_metadata = read_json(metadata_path, default={})
    if not isinstance(run_metadata, dict):
        run_metadata = {}

    source_lineage = read_json(lineage_path, default={})
    if not isinstance(source_lineage, dict):
        source_lineage = {}

    snapshot_manifest = read_json(snapshot_manifest_path, default={})
    if not isinstance(snapshot_manifest, dict):
        snapshot_manifest = {}

    source_canonical_state = read_json(source_state_path, default={})
    if not isinstance(source_canonical_state, dict):
        source_canonical_state = {}

    reused_stages, rerun_stages, resume_from_stage = compute_reused_and_rerun_stages(boundary)
    reused_gap_resolution_substages = compute_reused_gap_resolution_substages(boundary)

    reused_stage_outputs: dict[str, dict[str, Any]] = {}
    for stage_name in reused_stages:
        payload = read_json(stage_output_path(source_run_dir, stage_name), default=None)
        if not isinstance(payload, dict):
            raise FileNotFoundError(
                f"Required replay stage output missing or invalid: "
                f"{stage_output_path(source_run_dir, stage_name)}"
            )
        reused_stage_outputs[stage_name] = payload

    reused_gap_resolution_substage_outputs: dict[str, dict[str, Any]] = {}
    for qualified_substage_name in reused_gap_resolution_substages:
        _, _, substage_name = qualified_substage_name.partition("::")
        payload = read_json(substage_output_path(source_run_dir, "gap_resolution", substage_name), default=None)
        if not isinstance(payload, dict):
            raise FileNotFoundError(
                f"Required replay substage output missing or invalid: "
                f"{substage_output_path(source_run_dir, 'gap_resolution', substage_name)}"
            )
        reused_gap_resolution_substage_outputs[qualified_substage_name] = payload

    contract = replay_contract_summary()

    plan = ReplayPlan(
        source_run_id=source_run_id,
        source_run_dir=str(source_run_dir),
        requested_stage_boundary=boundary,
        resume_from_stage=resume_from_stage,
        public_stage_order=list(contract["public_stage_order"]),
        public_stage_labels=[dict(item) for item in contract.get("public_stage_labels", [])],
        gap_resolution_substage_order=list(contract["gap_resolution_substage_order"]),
        gap_resolution_substage_labels=[dict(item) for item in contract.get("gap_resolution_substage_labels", [])],
        active_bounded_assist_backend=str(contract.get("active_bounded_assist_backend", "")),
        inactive_compatibility_layers=list(contract.get("inactive_compatibility_layers", [])),
        canonical_knowledge_families=list(contract.get("canonical_knowledge_families", [])),
        legacy_knowledge_fallbacks=list(contract.get("legacy_knowledge_fallbacks", [])),
        reused_stages=reused_stages,
        rerun_stages=rerun_stages,
        reused_gap_resolution_substages=reused_gap_resolution_substages,
        source_pipeline_summary=pipeline_summary,
        source_run_metadata=run_metadata,
        source_lineage=source_lineage,
        source_snapshot_manifest=snapshot_manifest,
        reused_stage_outputs=reused_stage_outputs,
        reused_gap_resolution_substage_outputs=reused_gap_resolution_substage_outputs,
        source_canonical_state=source_canonical_state,
    )
    return plan.to_dict()


class ReplayManager:
    def __init__(
        self,
        context: Any,
        replay_source_run_id: str,
        replay_stage_boundary: str,
    ) -> None:
        self.context = context
        self.run_id = _require_context_run_id(context)
        self.run_dir = _require_context_run_dir(context)
        self.audit_logger = initialize_audit_logger(context)
        self.plan = build_replay_plan(
            context=context,
            replay_source_run_id=replay_source_run_id,
            replay_stage_boundary=replay_stage_boundary,
        )
        self.manifest_path = self.run_dir / "replay_manifest.json"
        self._write_manifest(status="INITIALIZED", notes=[])

        self.audit_logger.log_event(
            event_type="replay_initialized",
            stage_name="replay",
            status="STARTED",
            message="Replay manager initialized.",
            metadata={
                "source_run_id": self.plan["source_run_id"],
                "requested_stage_boundary": self.plan["requested_stage_boundary"],
                "resume_from_stage": self.plan["resume_from_stage"],
                "reused_stage_count": len(self.plan["reused_stages"]),
                "rerun_stage_count": len(self.plan["rerun_stages"]),
                "reused_gap_resolution_substage_count": len(self.plan.get("reused_gap_resolution_substages", [])),
                "reused_stages": list(self.plan["reused_stages"]),
                "rerun_stages": list(self.plan["rerun_stages"]),
                "reused_gap_resolution_substages": list(self.plan.get("reused_gap_resolution_substages", [])),
            },
        )

    def _write_manifest(self, status: str, notes: list[str]) -> None:
        manifest = ReplayManifest(
            run_id=self.run_id,
            created_at=utc_now_iso(),
            status=status,
            source_run_id=self.plan["source_run_id"],
            requested_stage_boundary=self.plan["requested_stage_boundary"],
            resume_from_stage=self.plan["resume_from_stage"],
            public_stage_order=list(self.plan.get("public_stage_order", [])),
            public_stage_labels=[dict(item) for item in self.plan.get("public_stage_labels", [])],
            gap_resolution_substage_order=list(self.plan.get("gap_resolution_substage_order", [])),
            gap_resolution_substage_labels=[dict(item) for item in self.plan.get("gap_resolution_substage_labels", [])],
            active_bounded_assist_backend=str(self.plan.get("active_bounded_assist_backend", "")),
            inactive_compatibility_layers=list(self.plan.get("inactive_compatibility_layers", [])),
            canonical_knowledge_families=list(self.plan.get("canonical_knowledge_families", [])),
            legacy_knowledge_fallbacks=list(self.plan.get("legacy_knowledge_fallbacks", [])),
            reused_stages=list(self.plan["reused_stages"]),
            rerun_stages=list(self.plan["rerun_stages"]),
            reused_gap_resolution_substages=list(self.plan.get("reused_gap_resolution_substages", [])),
            notes=notes,
        )
        write_json(self.manifest_path, manifest.to_dict())

    def persist_plan(self) -> None:
        write_json(self.run_dir / "replay_plan.json", self.plan)
        self.audit_logger.log_event(
            event_type="replay_plan_persisted",
            stage_name="replay",
            status="COMPLETED",
            message="Replay plan persisted.",
            metadata={
                "replay_plan_path": str(self.run_dir / "replay_plan.json"),
                "source_run_id": self.plan["source_run_id"],
                "requested_stage_boundary": self.plan["requested_stage_boundary"],
                "resume_from_stage": self.plan["resume_from_stage"],
                "reused_stages": list(self.plan["reused_stages"]),
                "rerun_stages": list(self.plan["rerun_stages"]),
                "reused_gap_resolution_substages": list(self.plan.get("reused_gap_resolution_substages", [])),
            },
        )

    def get_reused_stage_output(self, stage_name: str) -> dict[str, Any]:
        payload = self.plan["reused_stage_outputs"].get(stage_name)
        if not isinstance(payload, dict):
            raise KeyError(f"Replay stage output not available for stage: {stage_name}")

        self.audit_logger.log_event(
            event_type="replay_stage_output_loaded",
            stage_name=stage_name,
            substage_name="replay",
            status="REUSED",
            message=f"Loaded persisted replay output for stage '{stage_name}'.",
            metadata={
                "source_run_id": self.plan["source_run_id"],
                "requested_stage_boundary": self.plan["requested_stage_boundary"],
                "stage_name": stage_name,
            },
        )
        return payload

    def should_reuse_stage(self, stage_name: str) -> bool:
        return stage_name in self.plan["reused_stages"]

    def should_rerun_stage(self, stage_name: str) -> bool:
        return stage_name in self.plan["rerun_stages"]

    def should_reuse_gap_resolution_substage(self, qualified_substage_name: str) -> bool:
        return qualified_substage_name in self.plan.get("reused_gap_resolution_substages", [])

    def get_reused_gap_resolution_substage_output(self, qualified_substage_name: str) -> dict[str, Any]:
        payload = self.plan.get("reused_gap_resolution_substage_outputs", {}).get(qualified_substage_name)
        if not isinstance(payload, dict):
            raise KeyError(f"Replay gap-resolution substage output not available for stage: {qualified_substage_name}")

        _, _, substage_name = qualified_substage_name.partition("::")
        self.audit_logger.log_substage_complete(
            stage_name="gap_resolution",
            substage_name=substage_name,
            status=str(payload.get("status", "REUSED")),
            metadata={
                "qualified_name": qualified_substage_name,
                "mode": "reused",
                "replay_source_run_id": self.plan["source_run_id"],
                "replay_stage_boundary": self.plan["requested_stage_boundary"],
            },
        )
        return payload

    def source_canonical_state(self) -> dict[str, Any]:
        payload = self.plan.get("source_canonical_state", {})
        if isinstance(payload, dict):
            self.audit_logger.log_event(
                event_type="replay_source_canonical_state_loaded",
                stage_name="canonical_state",
                substage_name="replay",
                status="REUSED",
                message="Loaded source canonical state for replay.",
                metadata={
                    "source_run_id": self.plan["source_run_id"],
                    "requested_stage_boundary": self.plan["requested_stage_boundary"],
                },
            )
            return payload
        return {}

    def mark_completed(self) -> None:
        self._write_manifest(status="COMPLETED", notes=[])
        self.audit_logger.log_event(
            event_type="replay_completed",
            stage_name="replay",
            status="SUCCESS",
            message="Replay completed successfully.",
            metadata={
                "source_run_id": self.plan["source_run_id"],
                "requested_stage_boundary": self.plan["requested_stage_boundary"],
                "resume_from_stage": self.plan["resume_from_stage"],
                "reused_stages": list(self.plan["reused_stages"]),
                "rerun_stages": list(self.plan["rerun_stages"]),
                "reused_gap_resolution_substages": list(self.plan.get("reused_gap_resolution_substages", [])),
            },
        )

    def mark_failed(self, message: str) -> None:
        failure_message = str(message)
        self._write_manifest(status="FAILED", notes=[failure_message])
        self.audit_logger.log_event(
            event_type="replay_failed",
            stage_name="replay",
            status="FAILED",
            message="Replay failed.",
            metadata={
                "source_run_id": self.plan["source_run_id"],
                "requested_stage_boundary": self.plan["requested_stage_boundary"],
                "resume_from_stage": self.plan["resume_from_stage"],
                "reused_stages": list(self.plan["reused_stages"]),
                "rerun_stages": list(self.plan["rerun_stages"]),
                "reused_gap_resolution_substages": list(self.plan.get("reused_gap_resolution_substages", [])),
                "error": failure_message,
            },
        )


def initialize_replay_manager(
    context: Any,
    replay_source_run_id: str,
    replay_stage_boundary: str,
) -> ReplayManager:
    return ReplayManager(
        context=context,
        replay_source_run_id=replay_source_run_id,
        replay_stage_boundary=replay_stage_boundary,
    )