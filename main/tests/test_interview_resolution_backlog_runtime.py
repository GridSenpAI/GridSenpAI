from pathlib import Path
from types import SimpleNamespace

from services.interview_service.service import ingest_interviews


def test_interview_service_seeds_questions_from_registry_resolution_backlog(tmp_path: Path) -> None:
    context = SimpleNamespace(
        run_id="run-interview-backlog",
        config=SimpleNamespace(project_name="Interview Backlog Project"),
        input_dir=tmp_path,
        project_root=tmp_path,
    )

    canonical_state_result = {
        "canonical_state": {
            "field_records": [
                {
                    "field_path": "facility.poi_voltage_kv",
                    "value": 138.0,
                    "status": "review_required",
                    "confidence": 0.55,
                    "is_primary": True,
                }
            ],
            "validation_report": {
                "missing_fields": [
                    {"field_path": "facility.generators.count"},
                ]
            },
            "normalized_input": {},
        }
    }

    result = ingest_interviews(
        context=context,
        input_dir=tmp_path,
        extraction_result={},
        normalization_result={"followup_questions": []},
        retrieval_result={},
        canonical_state_result=canonical_state_result,
    )

    questions = result["questions"]
    assert questions
    assert any(q["metadata"].get("planner_registry_backed") is True for q in questions)
    field_ids = {q["metadata"].get("field_id") for q in questions}
    assert "point_of_interconnection_voltage_kv" in field_ids
    assert "generator_unit_count" in field_ids
    tracking_backlog = result["field_tracking"]["planner_registry_resolution_backlog"]
    assert tracking_backlog
    assert tracking_backlog[0]["planner_registry_backed"] is True
