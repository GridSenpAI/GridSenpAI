from shared.planner_interview_closure import apply_interview_answers_to_planner_contract


def _contract(row):
    return {"planner_field_ledger": [row], "planner_field_ledger_summary": {}}


def test_interview_supplies_unresolved_field_value():
    row = {
        "field_path": "facility.poi_voltage_kv",
        "field_label": "POI voltage",
        "accepted_value": "UNRESOLVED",
        "normalized_value": "UNRESOLVED",
        "confidence_score": 0.0,
        "status": "UNRESOLVED",
        "planner_critical": True,
    }
    result = apply_interview_answers_to_planner_contract(
        _contract(row),
        interview_result={"answers_confirmed": [{"field_path": "facility.poi_voltage_kv", "question_id": "q1", "confirmed_answer": "138 kV"}]},
    )
    out = result["planner_field_ledger"][0]
    assert out["status"] == "INTERVIEW_SUPPLIED"
    assert out["accepted_value"] == "138 kV"
    assert out["source_role"] == "interview"
    assert out["source_document"] == "Applicant interview"


def test_unknown_interview_answer_keeps_document_value():
    row = {
        "field_path": "facility.poi_voltage_kv",
        "field_label": "POI voltage",
        "accepted_value": "138 kV",
        "normalized_value": "138",
        "confidence_score": 0.91,
        "status": "ACCEPTED",
        "source_document": "request.pdf",
        "planner_critical": True,
    }
    result = apply_interview_answers_to_planner_contract(
        _contract(row),
        interview_result={"answers_confirmed": [{"field_path": "facility.poi_voltage_kv", "question_id": "q1", "confirmed_answer": "I don't know"}]},
    )
    out = result["planner_field_ledger"][0]
    assert out["accepted_value"] == "138 kV"
    assert out["status"] == "ACCEPTED"
    assert out["interview_status"] == "UNKNOWN_OR_DECLINED"


def test_high_confidence_document_conflict_requires_confirmation():
    row = {
        "field_path": "facility.poi_voltage_kv",
        "field_label": "POI voltage",
        "accepted_value": "138 kV",
        "normalized_value": "138",
        "confidence_score": 0.95,
        "status": "ACCEPTED",
        "source_document": "request.pdf",
        "source_page": "1",
        "source_role": "application_request_form",
        "planner_critical": True,
    }
    result = apply_interview_answers_to_planner_contract(
        _contract(row),
        interview_result={"answers_confirmed": [{"field_path": "facility.poi_voltage_kv", "question_id": "q1", "confirmed_answer": "13.8 kV"}]},
    )
    out = result["planner_field_ledger"][0]
    assert out["status"] == "BLOCKED_BY_CONFLICT"
    assert out["needs_interview_confirmation"] is True
    assert "Are you sure?" in out["interview_confirmation_prompt"]
