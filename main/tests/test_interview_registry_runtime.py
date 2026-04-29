from pathlib import Path
from types import SimpleNamespace

from services.interview_service.service import ingest_interviews


def test_interview_questions_prioritize_registry_critical_fields(tmp_path: Path) -> None:
    context = SimpleNamespace(
        run_id="run-interview-registry",
        config=SimpleNamespace(project_name="Interview Registry Project"),
        input_dir=tmp_path,
        project_root=tmp_path,
    )

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "accepted_dynamic_representation",
                "field_id": "accepted_dynamic_representation",
                "reason": "Dynamic representation is still missing.",
                "suggested_sources": ["dynamic model package", "planner study assumptions"],
                "severity": "MODERATE",
                "planner_critical": True,
                "requiredness": "required",
                "label": "Accepted dynamic representation",
            },
            {
                "question_id": "fq_002",
                "field_path": "facility.poi_voltage_kv",
                "field_id": "point_of_interconnection_voltage_kv",
                "reason": "POI voltage is still missing.",
                "suggested_sources": ["one-line diagram", "interconnection application"],
                "severity": "HIGH",
                "planner_critical": True,
                "requiredness": "required",
                "label": "Point of interconnection voltage (kV)",
            },
        ]
    }

    result = ingest_interviews(
        context=context,
        input_dir=tmp_path,
        extraction_result={},
        normalization_result=normalization_result,
        retrieval_result=None,
        canonical_state_result=None,
    )

    questions = result["questions"]
    assert len(questions) >= 2
    assert questions[0]["field_path"] == "facility.poi_voltage_kv"
    assert questions[0]["metadata"]["field_id"] == "point_of_interconnection_voltage_kv"
    assert questions[0]["metadata"]["planner_critical"] is True
