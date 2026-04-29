from __future__ import annotations

import pytest
import json
import subprocess
import sys
from pathlib import Path

from tests.integration.helpers import prepare_writable_workspace


ALLOWED_PIPELINE_OUTCOMES = {"SUCCESS", "SUCCESS_FINAL", "SUCCESS_PROVISIONAL", "BLOCKED_PENDING_INTERVIEW", "BLOCKED_REVIEW_REQUIRED"}
ALLOWED_EXPORT_STATUSES = {"EXPORTED", "EXPORTED_PROVISIONAL", "EXPORTED_BLOCKED"}


EXPECTED_STAGE_FILES = [
    "ingestion.json",
    "extraction.json",
    "extraction__document_parser.json",
    "extraction__layout_analysis.json",
    "extraction__ocr.json",
    "normalization.json",
    "gap_resolution.json",
    "gap_resolution__retrieval.json",
    "gap_resolution__interview.json",
    "validation.json",
    "validation__engineering_validation.json",
    "validation__calibration_dataset.json",
    "validation__calibration_comparison.json",
    "canonical_state.json",
    "translation.json",
    "scenarios.json",
    "export.json",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.integration
def test_pipeline_smoke(tmp_path: Path) -> None:
    project_root = prepare_writable_workspace(tmp_path)
    output_root = project_root / "runs"
    run_id = "smoke_test"

    result = subprocess.run(
        [sys.executable, "-m", "app.main", "--run-id", run_id, "--output-dir", str(output_root)],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Pipeline failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    run_dir = output_root / run_id
    assert run_dir.exists(), f"Run directory was not created: {run_dir}"

    summary_path = run_dir / "pipeline_summary.json"
    assert summary_path.exists(), "pipeline_summary.json was not written."

    stages_dir = run_dir / "stages"
    assert stages_dir.exists(), "stages directory was not written."

    for filename in EXPECTED_STAGE_FILES:
        stage_path = stages_dir / filename
        assert stage_path.exists(), f"Expected stage file missing: {filename}"

    pipeline_summary = _load_json(summary_path)
    assert pipeline_summary["run_id"] == run_id
    assert pipeline_summary["status"] in ALLOWED_PIPELINE_OUTCOMES

    stage_status = pipeline_summary["stage_status"]
    assert stage_status["ingestion"] == "ARTIFACTS_INGESTED"
    assert stage_status["extraction"] == "EXTRACTED"
    assert stage_status["normalization"] == "FAILED_SCHEMA_VALIDATION"
    assert stage_status["gap_resolution"] == "GAP_RESOLUTION_COMPLETE"
    assert pipeline_summary["gap_resolution_substages"]["gap_resolution::retrieval"] == "EVIDENCE_RETRIEVED"
    assert pipeline_summary["gap_resolution_substages"]["gap_resolution::interview"] == "INTERVIEWS_INGESTED"
    assert stage_status["canonical_state"] == "CANONICAL_STATE_PERSISTED"
    assert stage_status["validation"] == "VALIDATED"
    assert stage_status["translation"] == "TRANSLATED"
    assert stage_status["scenarios"] == "SCENARIOS_GENERATED"
    assert stage_status["export"] in ALLOWED_EXPORT_STATUSES

    intake_summary = pipeline_summary["intake_summary"]
    assert isinstance(intake_summary, dict)
    assert isinstance(intake_summary["artifact_count"], int)
    assert isinstance(intake_summary["required_artifact_count"], int)
    assert isinstance(intake_summary["uploaded_artifact_count"], int)
    assert isinstance(intake_summary["missing_required_count"], int)
    assert isinstance(intake_summary["missing_required_requirement_ids"], list)
    assert isinstance(intake_summary["missing_required_labels"], list)
    assert isinstance(intake_summary["complete"], bool)

    observability_summary = pipeline_summary["observability_summary"]
    assert observability_summary["stage_timing"]["total_stage_duration_ms"] >= 0
    assert observability_summary["stage_timing"]["stages"]["ingestion"]["mode"] in {"executed", "reused"}
    assert observability_summary["runtime_metrics"]["extraction"]["schema_field_candidate_count"] >= 0
    assert observability_summary["runtime_metrics"]["retrieval"]["snippet_count"] >= 0
    assert observability_summary["runtime_metrics"]["interview"]["question_count"] >= 0

    governed_runtime = pipeline_summary["governed_run_summary"]["runtime_observability"]
    assert governed_runtime["canonical_resolution"]["accepted_planner_field_count"] >= 0
    assert governed_runtime["retrieval"]["executed_official_web_count"] >= 0

    ingestion_stage = _load_json(stages_dir / "ingestion.json")
    assert ingestion_stage["run_id"] == run_id
    assert ingestion_stage["status"] == "ARTIFACTS_INGESTED"
    assert "intake_session" in ingestion_stage

    intake_session = ingestion_stage["intake_session"]
    assert intake_summary["status"] == intake_session["status"]
    assert intake_summary["required_artifact_count"] == intake_session["required_artifact_count"]
    assert intake_summary["uploaded_artifact_count"] == intake_session["uploaded_artifact_count"]
    assert intake_summary["missing_required_count"] == intake_session["missing_required_count"]
    assert intake_summary["session_path"] == intake_session["session_path"]

    extraction_stage = _load_json(stages_dir / "extraction.json")
    assert extraction_stage["run_id"] == run_id

    stage_status_value = extraction_stage.get("status")
    assert isinstance(stage_status_value, str)

    assert isinstance(extraction_stage.get("candidate_entities", []), list)
    assert isinstance(extraction_stage.get("entities", []), list)
    assert isinstance(extraction_stage.get("warnings", []), list)
    assert isinstance(extraction_stage.get("errors", []), list)

    if "resolved_entities" in extraction_stage:
        assert isinstance(extraction_stage["resolved_entities"], list)

    if "canonical_state" in extraction_stage:
        assert isinstance(extraction_stage["canonical_state"], dict)

    if "unresolved_fields" in extraction_stage:
        assert isinstance(extraction_stage["unresolved_fields"], list)

    if "interview_questions" in extraction_stage:
        assert isinstance(extraction_stage["interview_questions"], list)

    if "ready_for_interview" in extraction_stage:
        assert isinstance(extraction_stage["ready_for_interview"], bool)

    if "llm_task_policy" in extraction_stage:
        assert isinstance(extraction_stage["llm_task_policy"], dict)

    gap_resolution_stage = _load_json(stages_dir / "gap_resolution.json")
    assert gap_resolution_stage["run_id"] == run_id
    assert gap_resolution_stage["status"] == "GAP_RESOLUTION_COMPLETE"
    assert gap_resolution_stage["summary"]["retrieval_status"] == "EVIDENCE_RETRIEVED"
    assert gap_resolution_stage["summary"]["interview_status"] == "INTERVIEWS_INGESTED"

    interview_stage = _load_json(stages_dir / "gap_resolution__interview.json")
    assert interview_stage["run_id"] == run_id
    assert interview_stage["status"] == "INTERVIEWS_INGESTED"
    assert isinstance(interview_stage.get("questions", []), list)
    assert isinstance(interview_stage.get("clarifications", []), list)

    normalization_stage = _load_json(stages_dir / "normalization.json")
    assert normalization_stage["run_id"] == run_id
    assert normalization_stage["status"] == "FAILED_SCHEMA_VALIDATION"

    normalized_input = normalization_stage["normalized_input"]
    assert normalized_input["run_id"] == run_id
    assert normalized_input["schema_version"]
    assert isinstance(normalized_input["facility"], dict)
    assert isinstance(normalized_input["source_summary"], dict)

    validation_report = normalization_stage["validation_report"]
    assert isinstance(validation_report, dict)
    if "run_id" in validation_report:
        assert validation_report["run_id"] == run_id
    assert isinstance(validation_report.get("missing_fields", []), list)
    assert isinstance(normalization_stage.get("followup_questions", []), list)

    retrieval_stage = _load_json(stages_dir / "gap_resolution__retrieval.json")
    assert retrieval_stage["run_id"] == run_id
    assert retrieval_stage["status"] == "EVIDENCE_RETRIEVED"

    canonical_stage = _load_json(stages_dir / "canonical_state.json")
    canonical_state = canonical_stage["canonical_state"]

    assert canonical_stage["run_id"] == run_id
    assert canonical_stage["status"] == "CANONICAL_STATE_PERSISTED"
    assert canonical_state["run_id"] == run_id
    assert canonical_state["governance_version"] == "phase_two"
    assert isinstance(canonical_state["field_records"], list)
    assert isinstance(canonical_state["conflict_records"], list)
    assert isinstance(canonical_state["review_flags"], list)

    validation_stage = _load_json(stages_dir / "validation.json")
    assert validation_stage["run_id"] == run_id
    assert validation_stage["status"] == "VALIDATED"

    translation_stage = _load_json(stages_dir / "translation.json")
    assert translation_stage["run_id"] == run_id
    assert translation_stage["status"] == "TRANSLATED"

    output_parameters = translation_stage["output_parameters"]
    assert isinstance(output_parameters, list)
    assert output_parameters

    confidence_summary = translation_stage["confidence_summary"]
    assert isinstance(confidence_summary, dict)

    state_path = run_dir / "state" / "canonical_facility_state.json"
    assert state_path.exists()
    persisted_state = _load_json(state_path)
    assert persisted_state["run_id"] == run_id
    assert persisted_state["governance_version"] == "phase_two"

    run_metadata_path = run_dir / "run_metadata.json"
    lineage_path = run_dir / "lineage.json"
    snapshot_manifest_path = run_dir / "snapshots" / "snapshot_manifest.json"

    assert run_metadata_path.exists()
    assert lineage_path.exists()
    assert snapshot_manifest_path.exists()

    run_metadata = _load_json(run_metadata_path)
    lineage = _load_json(lineage_path)
    snapshot_manifest = _load_json(snapshot_manifest_path)

    assert run_metadata["run_id"] == run_id
    assert run_metadata["status"] in ALLOWED_PIPELINE_OUTCOMES
    assert run_metadata["execution_mode"] == "STANDARD"
    assert run_metadata["snapshot_count"] >= 3
    assert run_metadata["persisted_stage_count"] >= len(EXPECTED_STAGE_FILES)

    assert lineage["run_id"] == run_id
    assert lineage["lineage_depth"] == 0

    assert snapshot_manifest["run_id"] == run_id
    assert snapshot_manifest["snapshot_count"] >= 3

    labels = [item["label"] for item in snapshot_manifest["snapshots"]]
    assert "initial" in labels
    assert "after_canonical_state" in labels
    assert "final" in labels

    assert "ontology" in extraction_stage
    assert "llm_assistance" in extraction_stage
    assert "llm_assistance" in retrieval_stage
    assert "llm_assistance" in translation_stage

    exports_dir = run_dir / "exports"
    manifest_path = exports_dir / "run_manifest.json"
    planner_packet_pdf_path = exports_dir / "planner_packet.pdf"
    planner_packet_markdown_path = exports_dir / "planner_packet.md"
    assert manifest_path.exists()
    assert planner_packet_pdf_path.exists()

    export_manifest = _load_json(manifest_path)
    assert export_manifest["run_id"] == run_id
    assert export_manifest["status"] in ALLOWED_EXPORT_STATUSES
    assert "intake_summary" in export_manifest
    assert export_manifest["intake_summary"] == intake_summary

    planner_packet_exports = export_manifest.get("exports", {})
    assert planner_packet_exports.get("planner_packet_pdf")
    if planner_packet_markdown_path.exists():
        assert planner_packet_exports.get("planner_packet_md")
        planner_packet = planner_packet_markdown_path.read_text(encoding="utf-8")
        assert "## Intake Status" in planner_packet
        assert "Missing required artifact categories:" in planner_packet
    else:
        assert planner_packet_exports.get("planner_packet_md", "") == ""


