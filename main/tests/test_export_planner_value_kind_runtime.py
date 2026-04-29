from services.export_service.service import _build_planner_packet


def test_export_registry_packet_fields_show_value_kind_attention_and_runner_up():
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
                    "why_accepted": ["Source hierarchy favored official interconnection source."],
                    "source_anchors": ["poi_one_line.pdf:p2"],
                    "alternatives": [{"value": 115, "not_accepted_reason": "Source hierarchy ranked below the accepted candidate."}],
                    "planner_review_flag": False,
                    "needs_applicant_confirmation": False,
                }
            ],
            "summary": {"accepted_field_index_count": 1, "applicant_confirmation_needed_count": 0, "planner_review_count": 0},
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
    assert "value_kind: direct_document_fact" in payload
    assert "attention: critical_resolved" in payload
    assert "runner_up: 115" in payload
