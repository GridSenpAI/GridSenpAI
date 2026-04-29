from shared.phase6_redesign_contract import build_phase6_redesign_runtime_contract


def test_phase6_redesign_contract_passes_when_active_runtime_artifacts_are_ledger_first():
    ledger_row = {
        "field_path": "facility.poi_voltage_kv",
        "field_id": "facility.poi_voltage_kv",
        "field_label": "POI voltage",
        "status": "ACCEPTED",
        "accepted_value": "138",
        "confidence_score": 0.94,
        "source_document": "01_large_load_request_form.pdf",
    }
    contract = build_phase6_redesign_runtime_contract(
        run_id="run-test",
        canonical_state_result={
            "canonical_state": {
                "source_candidate_inputs": {
                    "candidate_governance_source": "planner_candidate_ledger",
                    "planner_candidate_ledger": [{"field_path": "facility.poi_voltage_kv", "candidate_count": 1}],
                },
            }
        },
        normalization_result={"planner_candidate_ledger": [{"field_path": "facility.poi_voltage_kv"}]},
        interview_result={
            "pre_interview_planner_field_contract": {"contract_version": "pre_interview_planner_field_contract_v1"},
            "pre_interview_planner_field_ledger_question_count": 1,
        },
        translation_result={
            "translation_source_contract": {
                "primary_source": "planner_field_ledger",
                "legacy_translation_fallback_used": False,
            },
            "ledger_native_translation": {"contract_version": "ledger_native_translation_v2"},
        },
        scenario_result={"scenario_input_contract": {"baseline_output_source": "ledger_native_model_outputs"}},
        export_result={"status": "EXPORTED", "export_manifest": {"summary": {"planner_packet_ready": True}}},
        adjudication_result={"status": "ADJUDICATION_COMPLETED", "packet_count": 1, "blocked_packet_count": 0},
        planner_field_contract={
            "planner_field_ledger": [ledger_row] * 524,
            "planner_field_ledger_summary": {"field_count": 524},
        },
        planner_interview_closure={"contract_version": "planner_interview_closure_v1", "applied_answer_count": 0},
        planner_ledger_adjudication={
            "contract_version": "planner_ledger_adjudication_v1",
            "status": "LEDGER_ADJUDICATION_COMPLETED",
            "field_resolution_adjudication_status": "ADJUDICATION_COMPLETED",
            "decision_count": 1,
        },
    )

    assert contract["status"] == "PHASE6_REDESIGN_RUNTIME_CONTRACT_PASS"
    assert contract["required_gate_fail_count"] == 0
    by_name = {gate["gate"]: gate for gate in contract["gates"]}
    assert by_name["ledger_first_translation"]["status"] == "PASS"
    assert by_name["ledger_native_scenario_inputs"]["status"] == "PASS"
    assert by_name["candidate_ledger_primary_source_available"]["status"] == "PASS"


def test_phase6_redesign_contract_fails_when_translation_uses_legacy_primary_path():
    contract = build_phase6_redesign_runtime_contract(
        run_id="run-test",
        canonical_state_result={
            "canonical_state": {
                "source_candidate_inputs": {
                    "candidate_governance_source": "planner_candidate_ledger",
                    "planner_candidate_ledger": [{"field_path": "facility.poi_voltage_kv"}],
                },
            }
        },
        normalization_result={"planner_candidate_ledger": [{"field_path": "facility.poi_voltage_kv"}]},
        interview_result={"pre_interview_planner_field_ledger_question_count": 0},
        translation_result={"translation_source_contract": {"primary_source": "legacy_translation", "legacy_translation_fallback_used": True}},
        scenario_result={"scenario_input_contract": {"baseline_output_source": "model_outputs"}},
        export_result={"status": "EXPORTED", "export_manifest": {"summary": {}}},
        adjudication_result={"status": "ADJUDICATION_COMPLETED"},
        planner_field_contract={"planner_field_ledger": [{"field_path": "facility.poi_voltage_kv", "status": "UNRESOLVED"}] * 524},
        planner_interview_closure={"contract_version": "planner_interview_closure_v1"},
        planner_ledger_adjudication={"contract_version": "planner_ledger_adjudication_v1"},
    )

    assert contract["status"] == "PHASE6_REDESIGN_RUNTIME_CONTRACT_FAIL"
    by_name = {gate["gate"]: gate for gate in contract["gates"]}
    assert by_name["ledger_first_translation"]["status"] == "FAIL"
    assert by_name["ledger_native_scenario_inputs"]["status"] == "FAIL"
