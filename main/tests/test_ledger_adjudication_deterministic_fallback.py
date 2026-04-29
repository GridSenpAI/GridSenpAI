from shared.ledger_adjudication import build_ledger_adjudication_artifact, apply_ledger_adjudication_to_contract


def _contract_with_candidates(candidate_options):
    row = {
        "field_path": "facility.poi_voltage_kv",
        "field_id": "facility.poi_voltage_kv",
        "field_label": "POI voltage",
        "status": "PROVISIONAL",
        "accepted_value": "13.8",
        "normalized_value": "13.8",
        "unit": "kV",
        "confidence_score": 0.52,
        "confidence_band": "LOW",
        "source_document": "05_single_line_diagram.pdf",
        "source_page": "1",
        "source_role": "one_line_diagram",
        "candidate_count": len(candidate_options),
        "candidate_options": candidate_options,
        "planner_critical": True,
        "requiredness": "required",
        "policy_family": "voltage",
        "manual_review_reason": "conflicting voltage contexts",
    }
    governance_item = {
        **row,
        "source_reference": "05_single_line_diagram.pdf, page 1",
        "adjudication_question": "Select the winning POI voltage candidate.",
    }
    return {
        "planner_field_ledger": [row],
        "planner_field_ledger_summary": {"field_count": 1},
        "planner_field_governance": {"adjudication_plan": [governance_item]},
    }


def test_failed_llm_adjudication_uses_deterministic_candidate_fallback():
    candidates = [
        {
            "candidate_id": "cand-internal-13-8",
            "value": "13.8",
            "normalized_value": "13.8",
            "unit": "kV",
            "confidence_score": 0.52,
            "source_document": "05_single_line_diagram.pdf",
            "source_page": "1",
            "source_section": "medium-voltage distribution",
            "source_role": "one_line_diagram",
            "evidence_snippet": "13.8 kV campus distribution bus",
        },
        {
            "candidate_id": "cand-poi-138",
            "value": "138",
            "normalized_value": "138",
            "unit": "kV",
            "confidence_score": 0.88,
            "source_document": "01_large_load_request_form.pdf",
            "source_page": "1",
            "source_section": "Electrical Characteristics table",
            "source_line": "row Nominal service voltage",
            "source_role": "application_request_form",
            "evidence_snippet": "Nominal service voltage: 138 kV",
        },
    ]
    contract = _contract_with_candidates(candidates)
    artifact = build_ledger_adjudication_artifact(
        run_id="run-test",
        planner_field_contract=contract,
        adjudication_result={"status": "ADJUDICATION_REQUIRED_BUT_FAILED"},
    )
    updated = apply_ledger_adjudication_to_contract(contract, artifact)
    row = updated["planner_field_ledger"][0]

    assert row["accepted_value"] == "138"
    assert row["accepted_candidate_id"] == "cand-poi-138"
    assert row["source_document"] == "01_large_load_request_form.pdf"
    assert row["adjudication_method"] == "deterministic"
    assert row["adjudication_applied"] is True
    assert row["status"] in {"ACCEPTED", "ACCEPTED_WITH_CONFLICT_NOTE"}
    assert row["adjudication_decision"]["deterministic_decision_status"] == "DETERMINISTIC_ADJUDICATION_COMPLETED"


def test_deterministic_adjudication_blocks_close_low_confidence_conflict_without_llm():
    candidates = [
        {
            "candidate_id": "cand-a",
            "value": "60",
            "confidence_score": 0.50,
            "source_role": "drawing",
            "source_document": "drawing.pdf",
        },
        {
            "candidate_id": "cand-b",
            "value": "64",
            "confidence_score": 0.51,
            "source_role": "drawing",
            "source_document": "drawing.pdf",
        },
    ]
    contract = _contract_with_candidates(candidates)
    artifact = build_ledger_adjudication_artifact(
        run_id="run-test",
        planner_field_contract=contract,
        adjudication_result={"status": "ADJUDICATION_REQUIRED_BUT_FAILED"},
    )
    updated = apply_ledger_adjudication_to_contract(contract, artifact)
    row = updated["planner_field_ledger"][0]

    assert row["status"] == "BLOCKED_BY_CONFLICT"
    assert row["adjudication_method"] == "deterministic"
    assert row["adjudication_decision"]["deterministic_decision_status"] == "DETERMINISTIC_ADJUDICATION_BLOCKED"


def test_nonresponsive_interview_answer_does_not_beat_document_candidate():
    candidates = [
        {
            "candidate_id": "candidate-doc",
            "value": "60",
            "confidence_score": 0.82,
            "source_role": "equipment_schedule",
            "source_document": "equipment_schedule.pdf",
        },
        {
            "candidate_id": "candidate-interview-unknown",
            "value": "I don't know",
            "confidence_score": 0.99,
            "source_role": "applicant_interview",
            "source_document": "interview_session",
        },
    ]
    contract = _contract_with_candidates(candidates)
    artifact = build_ledger_adjudication_artifact(
        run_id="run-test",
        planner_field_contract=contract,
        adjudication_result={"status": "ADJUDICATION_REQUIRED_BUT_FAILED"},
    )
    updated = apply_ledger_adjudication_to_contract(contract, artifact)
    row = updated["planner_field_ledger"][0]

    assert row["accepted_value"] == "60"
    assert row["accepted_candidate_id"] == "candidate-doc"
    assert row["adjudication_method"] == "deterministic"
