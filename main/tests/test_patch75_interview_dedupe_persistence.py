from services.interview_service.service import _deduplicate_question_records


def test_interview_dedupe_collapses_generic_and_confirmation_question_by_field_path():
    questions = [
        {
            "question_id": "generic_voltage",
            "field_path": "facility.poi_voltage_kv",
            "question": "Please provide or confirm POI voltage.",
            "source": "normalization_result",
            "priority": "MODERATE",
            "metadata": {"planner_critical": True},
        },
        {
            "question_id": "confirm_voltage",
            "field_path": "facility.poi_voltage_kv",
            "question": "Please confirm or correct POI voltage: current best value is 345 kV.",
            "source": "planner_registry_resolution_backlog",
            "priority": "HIGH",
            "metadata": {"planner_critical": True, "candidate_value": "345"},
        },
    ]

    deduped = _deduplicate_question_records(questions)

    assert len(deduped) == 1
    assert deduped[0]["question_id"] == "confirm_voltage"
    assert deduped[0]["metadata"]["deduped_question_count"] == 1


def test_interview_dedupe_uses_metadata_canonical_field_path_before_question_id():
    questions = [
        {
            "question_id": "q1",
            "field_path": "",
            "question": "Please provide ramp rate.",
            "source": "normalization_result",
            "metadata": {"canonical_field_path": "facility.dynamic_behavior.max_ramp_up_mw_per_min"},
        },
        {
            "question_id": "q2",
            "field_path": "facility.dynamic_behavior.max_ramp_up_mw_per_min",
            "question": "Please confirm or correct ramp rate: current best value is 8 MW/min.",
            "source": "planner_registry_resolution_backlog",
            "metadata": {"candidate_value": "8"},
        },
    ]

    deduped = _deduplicate_question_records(questions)

    assert len(deduped) == 1
    assert deduped[0]["question_id"] == "q2"
