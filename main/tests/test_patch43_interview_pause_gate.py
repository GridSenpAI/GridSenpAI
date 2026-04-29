from __future__ import annotations

from pathlib import Path

import pytest

from app.orchestration import run_pipeline
from app.orchestration.run_pipeline import GridSenpAIPipeline, RunConfig, RunContext


def test_interview_workflow_state_waiting_requires_user_action() -> None:
    interview_result = {
        "run_id": "run_waiting",
        "status": "WAITING_FOR_INTERVIEW",
        "questions": [{"field_path": "facility.poi_voltage_kv"}],
        "workflow_state": {
            "state": "WAITING_FOR_INTERVIEW",
            "ready_for_downstream": False,
            "requires_user_action": True,
            "question_count": 1,
            "remaining_question_count": 1,
        },
    }

    workflow_state = run_pipeline._interview_workflow_state(interview_result)

    assert workflow_state["state"] == "WAITING_FOR_INTERVIEW"
    assert workflow_state["requires_user_action"] is True
    assert workflow_state["ready_for_downstream"] is False
    assert run_pipeline._interview_requires_user_action(interview_result) is True


def test_gap_resolution_waits_when_interview_questions_are_open(tmp_path: Path) -> None:
    context = RunContext(
        run_id="run_patch43_waiting",
        project_root=tmp_path,
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "runs",
        run_dir=tmp_path / "runs" / "run_patch43_waiting",
        config=RunConfig(project_name="Patch 43 Test"),
    )
    context.input_dir.mkdir(parents=True)

    pipeline = GridSenpAIPipeline(context)
    interview_result = {
        "run_id": context.run_id,
        "status": "WAITING_FOR_INTERVIEW",
        "questions": [{"field_path": "facility.poi_voltage_kv"}],
        "clarifications": [],
        "warnings": [],
        "workflow_state": {
            "state": "WAITING_FOR_INTERVIEW",
            "ready_for_downstream": False,
            "requires_user_action": True,
            "question_count": 1,
            "remaining_question_count": 1,
        },
    }
    retrieval_result = {"run_id": context.run_id, "status": "EVIDENCE_RETRIEVED", "snippets": []}

    result = pipeline._build_gap_resolution_stage_result(
        interview_result=interview_result,
        retrieval_result=retrieval_result,
    )

    assert result["status"] == "GAP_RESOLUTION_WAITING_FOR_INTERVIEW"
    assert result["workflow_state"]["requires_user_action"] is True
    assert result["summary"]["interview_requires_user_action"] is True


def test_pipeline_stops_before_validation_translation_scenarios_and_export_when_waiting_for_interview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = RunContext(
        run_id="run_patch43_pipeline_pause",
        project_root=tmp_path,
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "runs",
        run_dir=tmp_path / "runs" / "run_patch43_pipeline_pause",
        config=RunConfig(project_name="Patch 43 Pipeline Pause"),
    )
    context.input_dir.mkdir(parents=True)

    def fake_ingestion(**_: object) -> dict[str, object]:
        return {
            "run_id": context.run_id,
            "artifacts_discovered": [],
            "status": "ARTIFACTS_INGESTED",
            "ingested_at": "2026-04-27T00:00:00Z",
        }

    def fake_document_parser(**_: object) -> dict[str, object]:
        return {"run_id": context.run_id, "status": "DOCUMENTS_PARSED", "documents": []}

    def fake_layout(**_: object) -> dict[str, object]:
        return {"run_id": context.run_id, "status": "LAYOUT_ANALYZED"}

    def fake_ocr(**_: object) -> dict[str, object]:
        return {"run_id": context.run_id, "status": "OCR_SKIPPED"}

    def fake_extraction(**_: object) -> dict[str, object]:
        return {
            "run_id": context.run_id,
            "status": "EXTRACTED",
            "candidate_entities": [],
            "canonical_state": {},
            "unresolved_fields": ["facility.poi_voltage_kv"],
            "extracted_at": "2026-04-27T00:00:00Z",
        }

    def fake_normalization(**_: object) -> dict[str, object]:
        return {
            "run_id": context.run_id,
            "status": "NORMALIZED",
            "normalized_input": {},
            "validation_report": {},
            "followup_questions": [],
            "normalized_at": "2026-04-27T00:00:00Z",
        }

    def fake_retrieval(**_: object) -> dict[str, object]:
        return {"run_id": context.run_id, "status": "EVIDENCE_RETRIEVED", "snippets": []}

    def fake_interview(**_: object) -> dict[str, object]:
        return {
            "run_id": context.run_id,
            "status": "WAITING_FOR_INTERVIEW",
            "questions": [{"field_path": "facility.poi_voltage_kv"}],
            "answers_confirmed": [],
            "clarifications": [],
            "workflow_state": {
                "state": "WAITING_FOR_INTERVIEW",
                "ready_for_downstream": False,
                "requires_user_action": True,
                "question_count": 1,
                "remaining_question_count": 1,
            },
        }

    def forbidden_downstream(**_: object) -> dict[str, object]:
        raise AssertionError("Downstream stage should not run while interview is waiting.")

    monkeypatch.setattr(run_pipeline, "default_ingestion", fake_ingestion)
    monkeypatch.setattr(run_pipeline, "default_document_parser_service", fake_document_parser)
    monkeypatch.setattr(run_pipeline, "default_layout_analysis_service", fake_layout)
    monkeypatch.setattr(run_pipeline, "default_ocr_service", fake_ocr)
    monkeypatch.setattr(run_pipeline, "default_extraction", fake_extraction)
    monkeypatch.setattr(run_pipeline, "default_normalization", fake_normalization)
    monkeypatch.setattr(run_pipeline, "default_retrieval", fake_retrieval)
    monkeypatch.setattr(run_pipeline, "default_interview", fake_interview)
    monkeypatch.setattr(run_pipeline, "default_validation_service", forbidden_downstream)
    monkeypatch.setattr(run_pipeline, "default_translation", forbidden_downstream)
    monkeypatch.setattr(run_pipeline, "default_scenarios", forbidden_downstream)
    monkeypatch.setattr(run_pipeline, "default_export", forbidden_downstream)

    result = GridSenpAIPipeline(context).run()

    assert result["status"] == "PIPELINE_WAITING_FOR_INTERVIEW"
    assert result["stage_status"]["gap_resolution"] == "GAP_RESOLUTION_WAITING_FOR_INTERVIEW"
    assert result["stage_status"]["validation"] == "SKIPPED_WAITING_FOR_INTERVIEW"
    assert result["stage_status"]["translation"] == "SKIPPED_WAITING_FOR_INTERVIEW"
    assert result["stage_status"]["scenarios"] == "SKIPPED_WAITING_FOR_INTERVIEW"
    assert result["stage_status"]["export"] == "SKIPPED_WAITING_FOR_INTERVIEW"
    assert result["next_action"] == "APPLICANT_INTERVIEW_REQUIRED"
    assert not (context.run_dir / "stages" / "validation.json").exists()
    assert not (context.run_dir / "stages" / "translation.json").exists()
    assert not (context.run_dir / "stages" / "scenarios.json").exists()
    assert not (context.run_dir / "stages" / "export.json").exists()
