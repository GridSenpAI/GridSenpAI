from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.orchestration.run_pipeline import GridSenpAIPipeline, RunConfig, RunContext


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.integration
def test_pipeline_halts_when_validation_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_id = "validation_blocking_test"

    project_root = tmp_path
    input_dir = tmp_path / "sample_data"
    output_dir = tmp_path / "runs"
    run_dir = output_dir / run_id

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    context = RunContext(
        run_id=run_id,
        project_root=project_root,
        input_dir=input_dir,
        output_dir=output_dir,
        run_dir=run_dir,
        config=RunConfig(
            project_name="GridSenpAI Test Project",
            schema_version_input="0.1.0",
            schema_version_output="0.1.0",
            prompt_template_version="test-template-v1",
            model_version="test-model-v1",
            retrieval_config={"top_k": 5, "rerank": False},
        ),
    )

    def _stub_run_internal_substage(
        self: GridSenpAIPipeline,
        stage_name: str,
        substage_name: str,
        callable_to_use,
        **kwargs,
    ) -> dict[str, object]:
        if stage_name == "extraction":
            status = {
                "document_parser": "DOCUMENTS_PARSED",
                "layout_analysis": "LAYOUT_ANALYZED",
                "ocr": "OCR_COMPLETED",
            }[substage_name]
            result = {
                "run_id": self.context.run_id,
                "status": status,
                "warnings": [],
                "errors": [],
            }
        elif stage_name == "gap_resolution":
            if substage_name == "retrieval":
                result = {
                    "run_id": self.context.run_id,
                    "status": "EVIDENCE_RETRIEVED",
                    "snippets": [],
                    "warnings": [],
                    "errors": [],
                }
            elif substage_name == "interview":
                result = {
                    "run_id": self.context.run_id,
                    "status": "QUESTIONS_GENERATED",
                    "questions": [],
                    "clarifications": [],
                    "answers_confirmed": [],
                    "warnings": [],
                    "errors": [],
                }
            else:
                raise AssertionError(f"Unexpected gap_resolution substage: {substage_name}")
        else:
            raise AssertionError(f"Unexpected internal substage: {stage_name}::{substage_name}")

        self._persist_substage_output(stage_name, substage_name, result)
        return result

    def _stub_reuse_or_run_stage(
        self: GridSenpAIPipeline,
        stage_name: str,
        default_callable,
        **kwargs,
    ) -> dict[str, object]:
        if stage_name == "ingestion":
            result = {
                "run_id": self.context.run_id,
                "status": "ARTIFACTS_INGESTED",
                "artifacts": [],
                "artifact_count": 0,
                "warnings": [],
                "errors": [],
                "intake_session": {
                    "session_id": f"{self.context.run_id}_intake",
                    "session_path": str(self.context.run_dir / "intake"),
                    "status": "COMPLETE",
                    "required_artifact_count": 0,
                    "uploaded_artifact_count": 0,
                    "missing_required_count": 0,
                },
            }
        elif stage_name == "extraction":
            result = {
                "run_id": self.context.run_id,
                "status": "EXTRACTED",
                "entities": [],
                "candidate_entities": [],
                "resolved_entities": [],
                "canonical_state": {},
                "unresolved_fields": [],
                "interview_questions": [],
                "ready_for_interview": False,
                "llm_task_policy": {"allowed": [], "blocked": [], "notes": ""},
                "topology_cues": [],
                "source_anchors": [],
                "warnings": [],
                "errors": [],
            }
        elif stage_name == "normalization":
            result = {
                "run_id": self.context.run_id,
                "status": "FAILED_SCHEMA_VALIDATION",
                "normalized_input": {
                    "run_id": self.context.run_id,
                    "schema_version": "0.1.0",
                    "facility": {
                        "project_name": "GridSenpAI Test Project",
                        "poi_voltage_kv": 138.0,
                        "frequency_hz": 60,
                        "load_schedule": {"phase_1_mw": 25.0},
                    },
                    "source_summary": {},
                },
                "validation_report": {
                    "errors": [],
                    "warnings": [],
                    "info": [],
                    "missing_fields": [],
                    "conflicts": [],
                },
                "followup_questions": [],
                "warnings": [],
                "errors": [],
            }
        elif stage_name == "validation":
            result = {
                "run_id": self.context.run_id,
                "status": "VALIDATION_FAILED",
                "validation_report": {
                    "status": "VALIDATION_FAILED",
                    "errors": [
                        {
                            "code": "EMPTY_NORMALIZED_INPUT",
                            "severity": "error",
                            "message": "Canonical state normalized_input is empty.",
                            "field_path": "normalized_input",
                            "source_stage": "normalization",
                            "recommendation": "Normalization must produce an accepted deterministic input set.",
                        }
                    ],
                    "warnings": [],
                    "info": [],
                    "missing_fields": [],
                    "conflicts": [],
                    "summary": {
                        "is_blocked": True,
                        "model_readiness": "BLOCKED",
                    },
                },
                "canonical_state": {
                    "run_id": self.context.run_id,
                    "governance_version": "phase_two",
                    "field_records": [],
                    "conflict_records": [],
                    "review_flags": [],
                    "stage_status": {
                        "ingestion": "ARTIFACTS_INGESTED",
                        "extraction": "EXTRACTED",
                        "normalization": "FAILED_SCHEMA_VALIDATION",
                        "gap_resolution::interview": "QUESTIONS_GENERATED",
                        "gap_resolution::retrieval": "EVIDENCE_RETRIEVED",
                        "validation": "VALIDATION_FAILED",
                    },
                },
                "warnings": [],
                "errors": [],
            }
        elif stage_name == "canonical_state":
            raise AssertionError("canonical_state should not execute after validation failure")
        else:
            raise AssertionError(f"Downstream stage should not execute after validation failure: {stage_name}")

        self._persist_stage_output(stage_name, result)
        return result

    monkeypatch.setattr(
        GridSenpAIPipeline,
        "_run_internal_substage",
        _stub_run_internal_substage,
    )
    monkeypatch.setattr(
        GridSenpAIPipeline,
        "_reuse_or_run_stage",
        _stub_reuse_or_run_stage,
    )

    pipeline = GridSenpAIPipeline(context)
    summary = pipeline.run()

    assert summary["run_id"] == run_id
    assert summary["status"] == "VALIDATION_FAILED"

    stage_status = summary["stage_status"]
    assert stage_status["ingestion"] == "ARTIFACTS_INGESTED"
    assert stage_status["extraction"] == "EXTRACTED"
    assert stage_status["normalization"] == "FAILED_SCHEMA_VALIDATION"
    assert stage_status["gap_resolution"] == "GAP_RESOLUTION_COMPLETE"
    assert summary["gap_resolution_substages"]["gap_resolution::interview"] == "QUESTIONS_GENERATED"
    assert summary["gap_resolution_substages"]["gap_resolution::retrieval"] == "EVIDENCE_RETRIEVED"
    assert stage_status["validation"] == "VALIDATION_FAILED"
    assert stage_status["canonical_state"] == "SKIPPED_DUE_TO_VALIDATION_FAILURE"

    assert "translation" not in stage_status
    assert "scenarios" not in stage_status
    assert "export" not in stage_status

    stages_dir = run_dir / "stages"
    assert (stages_dir / "ingestion.json").exists()
    assert (stages_dir / "extraction.json").exists()
    assert (stages_dir / "normalization.json").exists()
    assert (stages_dir / "gap_resolution.json").exists()
    assert (stages_dir / "gap_resolution__interview.json").exists()
    assert (stages_dir / "gap_resolution__retrieval.json").exists()
    assert (stages_dir / "validation.json").exists()

    assert not (stages_dir / "canonical_state.json").exists()
    assert not (stages_dir / "translation.json").exists()
    assert not (stages_dir / "scenarios.json").exists()
    assert not (stages_dir / "export.json").exists()

    summary_path = run_dir / "pipeline_summary.json"
    assert summary_path.exists()

    persisted_summary = _load_json(summary_path)
    assert persisted_summary["status"] == "VALIDATION_FAILED"

    audit_log_path = run_dir / "audit" / "audit_log.jsonl"
    assert audit_log_path.exists()

    audit_lines = [
        json.loads(line)
        for line in audit_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = {line["event_type"] for line in audit_lines}

    assert "pipeline_start" in event_types
    assert "pipeline_complete" in event_types
    assert "run_governance_initialized" in event_types
    assert "canonical_snapshot_created" in event_types
    assert "run_governance_finalized" in event_types

    state_path = run_dir / "state" / "canonical_facility_state.json"
    assert state_path.exists()

    persisted_state = _load_json(state_path)
    assert persisted_state["run_id"] == run_id
    assert persisted_state["governance_version"] == "phase_two"
    assert isinstance(persisted_state.get("stage_status", {}), dict)
