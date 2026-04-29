from services.export_service.service import _build_planner_packet


def test_export_packet_includes_planner_packet_accepted_vs_alternatives_section() -> None:
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
                    "alternatives": [
                        {
                            "value": 115,
                            "source_anchor": "legacy_submittal.pdf:p9",
                            "not_accepted_reason": "Official interconnection source ranked higher.",
                        }
                    ],
                    "planner_review_flag": True,
                    "needs_applicant_confirmation": True,
                }
            ],
            "summary": {"accepted_field_index_count": 1, "applicant_confirmation_needed_count": 1, "planner_review_count": 1},
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
    assert "## Planner Packet Accepted vs Alternatives" in payload
    assert "POI nominal voltage kV (Site And Interconnection Context): accepted=138 [resolved; HIGH]" in payload
    assert "  - why: Official interconnection source ranked highest." in payload
    assert "  - anchor: poi_one_line.pdf:p2" in payload
    assert "  - contradiction: 115 kV alternative rejected" in payload
    assert "  - decision_basis: accepted_from_governed_adjudication" in payload
    assert "  - review: planner review required" in payload
    assert "  - review: applicant confirmation recommended" in payload
    assert "  - alternative: 115 (legacy_submittal.pdf:p9)" in payload
    assert "    - not accepted: Official interconnection source ranked higher." in payload


def test_export_packet_includes_planner_trust_dashboard_section() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "facility.poi_voltage_kv",
                    "label": "POI nominal voltage kV",
                    "planner_critical": True,
                    "planner_review_flag": True,
                    "planner_trust_row": {
                        "label": "POI nominal voltage kV",
                        "trust_posture": "contested",
                        "planner_action": "planner_review_before_use",
                    },
                    "field_release_profile": {
                        "release_state": "BLOCKED",
                        "reason_summary": "Material conflict between official and applicant values.",
                    },
                    "acceptance_policy_result": {
                        "outcome": "blocked_conflict",
                        "support_strength_tier": "contested_multi_source",
                    },
                    "adjudication_trace": {
                        "next_action": {"owner": "applicant", "action": "confirm_material_voltage_value"},
                    },
                }
            ],
            "summary": {"accepted_field_index_count": 0, "applicant_confirmation_needed_count": 1, "planner_review_count": 1},
        },
        "entities": [],
        "field_records": [],
    }
    payload = _build_planner_packet(
        run_id="run-2",
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
        export_result={
            "governed_release_decision": {"summary": {"release_state": "BLOCKED", "planner_packet_state": "REVIEW_REQUIRED", "blocking_field_count": 1, "provisional_field_count": 0}},
            "manual_review_queue": {"summary": {"total_count": 1}},
            "planner_action_queue": {"summary": {"total_count": 1}},
        },
        include_audit_appendices=True,
    )
    assert "## Planner Trust Dashboard" in payload
    assert "## Planner Review Guide" in payload
    assert "## Field Resolution Appendix" in payload
    assert "- Release state: BLOCKED" in payload
    assert "- High-attention fields:" in payload
    assert "  - POI nominal voltage kV: BLOCKED; contested; planner_review_before_use" in payload
    assert "    - next_action: confirm_material_voltage_value (applicant)" in payload
    assert "    - why: Material conflict between official and applicant values." in payload
    assert "- POI nominal voltage kV: BLOCKED; contested; blocked_conflict -> planner_review_before_use" in payload
