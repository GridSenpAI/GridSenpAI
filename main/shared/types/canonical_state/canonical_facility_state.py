from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class CanonicalFacilityState:
    """
    Governed canonical state for the GridSenpAI pipeline.

    Phase Four extends the governed state with:
    - calibration dataset lineage
    - calibration comparison records
    - assumption registry governance
    - validation run lineage
    - evidence reconciliation records
    - governed change logging

    Phase Five introduces the engineering_model container which will
    represent the structured electrical facility model used for
    scenario generation and translation to planner tooling
    (PSS/E, PSLF, etc.).
    """

    run_id: str

    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    state_version: str = "0.2.0"
    governance_version: str = "phase_two"

    artifacts: list[dict[str, Any]] = field(default_factory=list)

    entities: list[dict[str, Any]] = field(default_factory=list)
    topology_cues: list[dict[str, Any]] = field(default_factory=list)
    source_anchors: list[dict[str, Any]] = field(default_factory=list)

    normalized_input: dict[str, Any] | None = None
    validation_report: dict[str, Any] | None = None
    followup_questions: list[dict[str, Any]] = field(default_factory=list)

    evidence_snippets: list[dict[str, Any]] = field(default_factory=list)

    model_outputs: dict[str, Any] | None = None
    output_parameters: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)

    scenarios: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Phase Five: Structured engineering model container
    # ------------------------------------------------------------------

    engineering_model: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Governance structures
    # ------------------------------------------------------------------

    field_records: list[dict[str, Any]] = field(default_factory=list)
    conflict_records: list[dict[str, Any]] = field(default_factory=list)
    review_flags: list[dict[str, Any]] = field(default_factory=list)

    calibration_datasets: list[dict[str, Any]] = field(default_factory=list)
    calibration_records: list[dict[str, Any]] = field(default_factory=list)
    assumption_registry: list[dict[str, Any]] = field(default_factory=list)
    validation_runs: list[dict[str, Any]] = field(default_factory=list)
    reconciliation_records: list[dict[str, Any]] = field(default_factory=list)
    change_log: list[dict[str, Any]] = field(default_factory=list)

    stage_status: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Timestamp helpers
    # ------------------------------------------------------------------

    def update_timestamp(self) -> None:
        self.updated_at = utc_now_iso()

    # ------------------------------------------------------------------
    # Stage status helpers
    # ------------------------------------------------------------------

    def set_stage_status(self, stage: str, status: str) -> None:
        self.stage_status[stage] = status
        self.update_timestamp()

    # ------------------------------------------------------------------
    # Artifact and extraction structures
    # ------------------------------------------------------------------

    def add_artifacts(self, artifacts: list[dict[str, Any]]) -> None:
        self.artifacts.extend(artifacts)
        self.update_timestamp()

    def add_entities(self, entities: list[dict[str, Any]]) -> None:
        self.entities.extend(entities)
        self.update_timestamp()

    def add_topology_cues(self, cues: list[dict[str, Any]]) -> None:
        self.topology_cues.extend(cues)
        self.update_timestamp()

    def add_source_anchors(self, anchors: list[dict[str, Any]]) -> None:
        self.source_anchors.extend(anchors)
        self.update_timestamp()

    # ------------------------------------------------------------------
    # Normalization stage
    # ------------------------------------------------------------------

    def set_normalized_input(
        self,
        normalized_input: dict[str, Any],
        validation_report: dict[str, Any],
        followup_questions: list[dict[str, Any]],
    ) -> None:
        self.normalized_input = normalized_input
        self.validation_report = validation_report
        self.followup_questions = followup_questions
        self.update_timestamp()

    # ------------------------------------------------------------------
    # Retrieval stage
    # ------------------------------------------------------------------

    def add_evidence(self, snippets: list[dict[str, Any]]) -> None:
        self.evidence_snippets.extend(snippets)
        self.update_timestamp()

    # ------------------------------------------------------------------
    # Translation stage
    # ------------------------------------------------------------------

    def set_translation_outputs(
        self,
        model_outputs: dict[str, Any],
        output_parameters: list[dict[str, Any]],
        assumptions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.model_outputs = model_outputs
        self.output_parameters = output_parameters
        if assumptions is not None:
            self.assumptions = assumptions
        self.update_timestamp()

    # ------------------------------------------------------------------
    # Scenario stage
    # ------------------------------------------------------------------

    def set_scenarios(self, scenarios: dict[str, Any]) -> None:
        self.scenarios = scenarios
        self.update_timestamp()

    # ------------------------------------------------------------------
    # Phase Five: Engineering model setter
    # ------------------------------------------------------------------

    def set_engineering_model(self, engineering_model: dict[str, Any]) -> None:
        if not isinstance(engineering_model, dict):
            raise TypeError("engineering_model must be a dict.")
        self.engineering_model = engineering_model
        self.update_timestamp()

    # ------------------------------------------------------------------
    # Governance setters
    # ------------------------------------------------------------------

    def set_governance(
        self,
        field_records: list[dict[str, Any]],
        conflict_records: list[dict[str, Any]],
        review_flags: list[dict[str, Any]],
    ) -> None:
        self.field_records = field_records
        self.conflict_records = conflict_records
        self.review_flags = review_flags
        self.update_timestamp()

    def add_calibration_datasets(self, datasets: list[dict[str, Any]]) -> None:
        self.calibration_datasets.extend(datasets)
        self.update_timestamp()

    def add_calibration_records(self, records: list[dict[str, Any]]) -> None:
        self.calibration_records.extend(records)
        self.update_timestamp()

    def set_assumption_registry(self, records: list[dict[str, Any]]) -> None:
        self.assumption_registry = records
        self.update_timestamp()

    def add_validation_runs(self, runs: list[dict[str, Any]]) -> None:
        self.validation_runs.extend(runs)
        self.update_timestamp()

    def add_reconciliation_records(self, records: list[dict[str, Any]]) -> None:
        self.reconciliation_records.extend(records)
        self.update_timestamp()

    def add_change_log_entries(self, entries: list[dict[str, Any]]) -> None:
        self.change_log.extend(entries)
        self.update_timestamp()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "state_version": self.state_version,
            "governance_version": self.governance_version,
            "artifacts": self.artifacts,
            "entities": self.entities,
            "topology_cues": self.topology_cues,
            "source_anchors": self.source_anchors,
            "normalized_input": self.normalized_input,
            "validation_report": self.validation_report,
            "followup_questions": self.followup_questions,
            "evidence_snippets": self.evidence_snippets,
            "model_outputs": self.model_outputs,
            "output_parameters": self.output_parameters,
            "assumptions": self.assumptions,
            "scenarios": self.scenarios,
            "engineering_model": self.engineering_model,
            "field_records": self.field_records,
            "conflict_records": self.conflict_records,
            "review_flags": self.review_flags,
            "calibration_datasets": self.calibration_datasets,
            "calibration_records": self.calibration_records,
            "assumption_registry": self.assumption_registry,
            "validation_runs": self.validation_runs,
            "reconciliation_records": self.reconciliation_records,
            "change_log": self.change_log,
            "stage_status": self.stage_status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CanonicalFacilityState":
        return cls(
            run_id=payload["run_id"],
            created_at=payload.get("created_at", utc_now_iso()),
            updated_at=payload.get("updated_at", utc_now_iso()),
            state_version=str(payload.get("state_version", "0.2.0")),
            governance_version=str(payload.get("governance_version", "phase_two")),
            artifacts=payload.get("artifacts", []),
            entities=payload.get("entities", []),
            topology_cues=payload.get("topology_cues", []),
            source_anchors=payload.get("source_anchors", []),
            normalized_input=payload.get("normalized_input"),
            validation_report=payload.get("validation_report"),
            followup_questions=payload.get("followup_questions", []),
            evidence_snippets=payload.get("evidence_snippets", []),
            model_outputs=payload.get("model_outputs"),
            output_parameters=payload.get("output_parameters", []),
            assumptions=payload.get("assumptions", []),
            scenarios=payload.get("scenarios"),
            engineering_model=payload.get("engineering_model"),
            field_records=payload.get("field_records", []),
            conflict_records=payload.get("conflict_records", []),
            review_flags=payload.get("review_flags", []),
            calibration_datasets=payload.get("calibration_datasets", []),
            calibration_records=payload.get("calibration_records", []),
            assumption_registry=payload.get("assumption_registry", []),
            validation_runs=payload.get("validation_runs", []),
            reconciliation_records=payload.get("reconciliation_records", []),
            change_log=payload.get("change_log", []),
            stage_status=payload.get("stage_status", {}),
        )