from services.export_service.service import _build_planner_packet


def test_export_packet_includes_validation_contradictions_and_demotions_section() -> None:
    payload = _build_planner_packet(
        run_id="run-1",
        canonical_state={"field_resolution": {"ledger": [], "summary": {}}, "entities": [], "field_records": []},
        validation_result={
            "status": "REVIEW_REQUIRED",
            "validation_report": {
                "engineering_validation": {
                    "errors": [
                        {
                            "code": "INVALID_NET_POWER_FACTOR_AT_POI",
                            "field_path": "interconnection.net_power_factor_at_poi",
                            "message": "Resolved power factor 1.2 is invalid.",
                        }
                    ],
                    "warnings": [
                        {
                            "code": "UPS_TOPOLOGY_REDUNDANCY_MISMATCH",
                            "field_path": "facility.ups.topology",
                            "message": "UPS topology conflicts with redundancy architecture.",
                        }
                    ],
                },
                "missing_fields": [],
                "conflicts": [],
                "warnings": [],
                "summary": {},
            },
        },
        translation_result={
            "output_parameters": [
                {
                    "parameter_path": "steady_state.q_mvar",
                    "value": 20.0,
                    "confidence_tag": "LOW",
                    "review_note": "POI power factor contradiction requires planner review.",
                    "field_resolution_decision_basis": "accepted_with_validation_contradiction",
                    "field_resolution_contradiction_summary": "Resolved power factor conflicts with engineering validation.",
                    "planner_review_flag": True,
                }
            ],
            "model_outputs": {},
            "assumptions": [],
            "confidence_summary": {},
        },
        scenario_result={"scenarios": {}},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "## Validation Contradictions & Demotions" in payload
    assert "engineering_errors: 1; engineering_warnings: 1; review_parameters: 1" in payload
    assert "INVALID_NET_POWER_FACTOR_AT_POI [interconnection.net_power_factor_at_poi]" in payload
    assert "UPS_TOPOLOGY_REDUNDANCY_MISMATCH [facility.ups.topology]" in payload
    assert "parameter: steady_state.q_mvar [LOW]" in payload
    assert "decision_basis: accepted_with_validation_contradiction" in payload
    assert "contradiction: Resolved power factor conflicts with engineering validation." in payload



def test_export_packet_includes_scenario_driver_rationale_section() -> None:
    payload = _build_planner_packet(
        run_id="run-2",
        canonical_state={"field_resolution": {"ledger": [], "summary": {}}, "entities": [], "field_records": []},
        validation_result={"validation_report": {"engineering_validation": {}, "missing_fields": [], "conflicts": [], "warnings": [], "summary": {}}},
        translation_result={
            "output_parameters": [],
            "model_outputs": {},
            "assumptions": [],
            "confidence_summary": {},
            "scenario_driver_context": {
                "redundancy_architecture": "2N",
                "generator_unit_count": 8,
                "cooling_load_share": 0.42,
                "mw_mvar_telemetry_present": False,
                "protection_scheme_summary": "Incomplete relay summary",
                "load_ramp_profile_summary": "Fast transfer and block loading",
                "transfer_summary": "ATS fast transfer",
            },
        },
        scenario_result={
            "scenarios": {},
            "scenario_variants": [
                {
                    "label": "Fast Ramping",
                    "confidence": "LOW",
                    "metadata": {
                        "scenario_family": "ramping",
                        "changed_parameter_count": 3,
                        "review_required_change_count": 2,
                        "field_resolution_changed_count": 2,
                        "translation_resolution_summary": {"review_required_count": 2},
                    },
                }
            ],
        },
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "## Scenario Driver Rationale" in payload
    assert "driver: redundancy_architecture=2N" in payload
    assert "driver: generator_unit_count=8" in payload
    assert "driver: cooling_load_share=0.42" in payload
    assert "scenario: Fast Ramping [LOW] family=ramping; changed_parameters=3; review_required_changes=2" in payload
    assert "rationale: translation_review_required=2; field_resolution_changed=2" in payload
