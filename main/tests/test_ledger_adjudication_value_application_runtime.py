from shared.adjudication_result import build_adjudication_result_from_canonical
from shared.ledger_adjudication import build_ledger_adjudication_artifact, apply_ledger_adjudication_to_contract


def _contract_with_candidates():
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
        "candidate_count": 2,
        "candidate_options": [
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
                "confidence_score": 0.94,
                "confidence_band": "HIGH",
                "source_document": "01_large_load_request_form.pdf",
                "source_page": "1",
                "source_section": "Electrical Characteristics table",
                "source_line": "row Nominal service voltage",
                "source_role": "application_request_form",
                "evidence_snippet": "Nominal service voltage: 138 kV",
            },
        ],
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


def test_completed_adjudication_selected_candidate_updates_planner_ledger_value_and_source():
    adjudication_result = {
        "status": "ADJUDICATION_COMPLETED",
        "support_summary": {"packet_count": 1},
        "per_field_decisions": [
            {
                "field_path": "facility.poi_voltage_kv",
                "accepted_candidate_id": "cand-poi-138",
                "accepted_value": "138",
                "confidence_score": 0.96,
                "rationale": "Application request form service voltage is the POI voltage; 13.8 kV is internal distribution.",
                "conflict_note": "13.8 kV candidate retained as internal voltage context, not POI.",
            }
        ],
    }
    artifact = build_ledger_adjudication_artifact(
        run_id="run-test",
        planner_field_contract=_contract_with_candidates(),
        adjudication_result=adjudication_result,
    )
    updated = apply_ledger_adjudication_to_contract(_contract_with_candidates(), artifact)
    row = updated["planner_field_ledger"][0]
    assert row["accepted_value"] == "138"
    assert row["accepted_candidate_id"] == "cand-poi-138"
    assert row["confidence_score"] == 0.94
    assert row["confidence_band"] == "HIGH"
    assert row["source_document"] == "01_large_load_request_form.pdf"
    assert row["source_section"] == "Electrical Characteristics table"
    assert row["status"] == "ACCEPTED_WITH_CONFLICT_NOTE"
    assert row["adjudication_applied"] is True
    assert updated["planner_field_ledger_summary"]["ledger_adjudication_applied_value_count"] == 1


def test_adjudication_result_extracts_compact_per_field_decisions_from_packet_outputs():
    payload = build_adjudication_result_from_canonical(
        run_id="run-test",
        canonical_state_result={
            "canonical_state": {
                "field_resolution": {
                    "adjudication_status": "ADJUDICATION_COMPLETED",
                    "adjudication_packet_plan": {"target_count": 1, "packet_count": 1},
                    "adjudication_support": {
                        "completed_packet_count": 1,
                        "packet_results": [
                            {
                                "status": "COMPLETED",
                                "structured_output": {
                                    "per_field_adjudication": [
                                        {
                                            "field_path": "facility.poi_voltage_kv",
                                            "selected_candidate_id": "cand-poi-138",
                                            "accepted_value": "138",
                                            "confidence": 0.95,
                                            "rationale": "Form row is the strongest source.",
                                        }
                                    ]
                                },
                            }
                        ],
                    },
                    "summary": {"planner_review_count": 1},
                }
            }
        },
    )
    assert payload["per_field_decision_count"] == 1
    assert payload["per_field_decisions"][0]["field_path"] == "facility.poi_voltage_kv"
    assert payload["per_field_decisions"][0]["accepted_candidate_id"] == "cand-poi-138"
