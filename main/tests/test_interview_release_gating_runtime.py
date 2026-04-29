from services.interview_service.service import _build_interview_readiness_summary

def test_interview_readiness_blocks_final_output_for_planner_critical_questions() -> None:
    readiness = _build_interview_readiness_summary(questions=[{"field_path": "facility.poi_voltage_kv", "question_category": "missing", "metadata": {"planner_critical": True}}], open_clarifications=[], answered_field_paths=set(), inferred_field_paths=[], conflicting_field_paths=[])
    assert readiness["ready_for_final_output"] is False
    assert readiness["planner_critical_remaining_question_count"] == 1
    assert readiness["completion_state"] == "NEEDS_CRITICAL_APPLICANT_INPUT"
