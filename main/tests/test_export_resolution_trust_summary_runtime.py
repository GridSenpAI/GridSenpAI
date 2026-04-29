from services.export_service.service import _build_planner_packet


def test_export_packet_includes_resolution_trust_summary_section() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "field_path": "interconnection.point_of_interconnection_voltage_kv",
                    "label": "POI Service Voltage",
                    "packet_section": "site_and_interconnection_context",
                    "packet_section_label": "Site & Interconnection Context",
                    "requiredness": "required",
                    "planner_critical": True,
                    "accepted_status": "resolved",
                    "accepted_value": 138,
                    "accepted_confidence": 0.96,
                    "confidence_band": "HIGH",
                    "accepted_value_kind": "direct_document_fact",
                    "planner_attention_tier": "critical_resolved",
                    "decision_basis": "accepted_from_governed_adjudication",
                    "why_accepted": ["Official interconnection source ranked highest."],
                    "source_anchors": ["poi_one_line.pdf:p2"],
                    "contradiction_summary": "115 kV alternative rejected",
                    "alternatives": [{"value": 115, "not_accepted_reason": "Official interconnection source ranked higher."}],
                }
            ],
            "summary": {"accepted_field_index_count": 1, "applicant_confirmation_needed_count": 0, "planner_review_count": 0},
        },
        "planner_packet_field_rows": {
            "site_and_interconnection_context": [
                {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "status": "resolved",
                    "accepted_value_kind": "direct_document_fact",
                    "planner_attention_tier": "critical_resolved",
                    "decision_basis": "accepted_from_governed_adjudication",
                    "contradiction_summary": "115 kV alternative rejected",
                    "source_anchors": ["poi_one_line.pdf:p2"],
                    "alternatives": [{"value": 115}],
                }
            ]
        },
        "entities": [],
        "field_records": [],
    }
    payload = _build_planner_packet(
        run_id="run-1",
        canonical_state=canonical_state,
        validation_result={"validation_report": {}},
        translation_result={"output_parameters": [], "model_outputs": {}, "assumptions": [], "confidence_summary": {}},
        scenario_result={"scenarios": {}},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "## Resolution Trust Summary" in payload
    assert "- contradictions: 1" in payload
    assert "- anchored_fields: 1" in payload
    assert "- runner_up_fields: 1" in payload
    assert "- decision_basis: accepted_from_governed_adjudication=1" in payload
    assert "- value_kinds: direct_document_fact=1" in payload
