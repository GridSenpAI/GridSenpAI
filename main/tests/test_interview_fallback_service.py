from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services.interview_service.question_catalog import get_question_by_field_path
from services.interview_service.service import run_service
from services.interview_service.utils import process_raw_answer


def _build_context(*, project_root: Path, input_dir: Path, run_id: str, project_name: str):
    run_dir = project_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        run_id=run_id,
        project_root=project_root,
        input_dir=input_dir,
        output_dir=run_dir / "outputs",
        run_dir=run_dir,
        config=SimpleNamespace(project_name=project_name),
    )


def test_interview_utils_generates_clarification_for_ambiguous_numeric_answer() -> None:
    question = get_question_by_field_path("facility.load_schedule.phase_1_mw")
    assert question is not None

    candidate, confirmed, clarification = process_raw_answer(
        question=question,
        raw_answer="maybe around one hundred and something",
        source_name="facility_intake.txt",
    )

    assert candidate.interpreted_candidate is None
    assert confirmed is None
    assert clarification is not None
    assert clarification.field_path == "facility.load_schedule.phase_1_mw"


def test_interview_service_generates_fallback_question_for_missing_field(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_interview_fallback_001",
        project_name="Test Project",
    )

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "facility.generators.count",
                "reason": "Generator count missing.",
                "severity": "HIGH",
                "suggested_sources": ["generator_schedule"],
            },
        ]
    }

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
    )

    assert result["status"] == "INTERVIEWS_INGESTED"
    assert result["questions"]
    question = next(item for item in result["questions"] if item["field_path"] == "facility.generators.count")
    assert question["question_id"] == "GENERATOR_UNIT_COUNT"
    assert question["metadata"]["answer_type"] == "integer"
