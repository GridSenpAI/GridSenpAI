from shared.ledger_adjudication import build_ledger_adjudication_artifact, apply_ledger_adjudication_to_contract


def _contract():
    row = {
        "field_path": "facility.poi_voltage_kv",
        "field_id": "facility.poi_voltage_kv",
        "field_label": "POI voltage",
        "status": "PROVISIONAL",
        "accepted_value": "13.8",
        "confidence_score": 0.52,
        "source_document": "05_single_line_diagram.pdf",
        "source_page": "1",
        "source_role": "one_line_diagram",
        "candidate_count": 2,
        "planner_critical": True,
        "requiredness": "required",
        "policy_family": "voltage",
        "manual_review_reason": "conflicting voltage contexts",
    }
    governance_item = {
        **row,
        "source_reference": "05_single_line_diagram.pdf, page 1",
        "adjudication_question": "Select the winning voltage candidate.",
    }
    return {
        "planner_field_ledger": [row],
        "planner_field_ledger_summary": {"field_count": 1},
        "planner_field_governance": {"adjudication_plan": [governance_item]},
    }


def test_failed_required_adjudication_blocks_planner_critical_row():
    artifact = build_ledger_adjudication_artifact(
        run_id="run-test",
        planner_field_contract=_contract(),
        adjudication_result={"status": "ADJUDICATION_REQUIRED_BUT_FAILED"},
    )
    updated = apply_ledger_adjudication_to_contract(_contract(), artifact)
    row = updated["planner_field_ledger"][0]
    assert artifact["status"] == "LEDGER_ADJUDICATION_REQUIRED_BUT_FAILED_CRITICAL"
    assert row["status"] == "BLOCKED_BY_ADJUDICATION_FAILURE"
    assert row["adjudication_required"] is True
    assert row["adjudication_status"] == "ADJUDICATION_REQUIRED_BUT_NOT_COMPLETED"
    assert updated["planner_field_ledger_summary"]["ledger_adjudication_planner_critical_failed_count"] == 1


def test_completed_adjudication_preserves_row_status_and_records_decision():
    artifact = build_ledger_adjudication_artifact(
        run_id="run-test",
        planner_field_contract=_contract(),
        adjudication_result={"status": "ADJUDICATION_COMPLETED", "support_summary": {"packet_count": 1}},
    )
    updated = apply_ledger_adjudication_to_contract(_contract(), artifact)
    row = updated["planner_field_ledger"][0]
    assert artifact["status"] == "LEDGER_ADJUDICATION_COMPLETED"
    assert row["status"] == "PROVISIONAL"
    assert row["adjudication_status"] == "ADJUDICATION_COMPLETED"
    assert row["adjudication_decision"]["recommended_row_action"] == "USE_ADJUDICATED_LEDGER_POSTURE"
