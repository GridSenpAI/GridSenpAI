from __future__ import annotations

from app.orchestration.run_pipeline import (
    _build_blocked_export_result,
    _build_pre_export_gate,
    _scenario_is_ledger_native,
    _translation_is_ledger_first,
)


def test_pre_export_gate_blocks_legacy_translation_before_export_artifacts() -> None:
    translation = {
        "status": "TRANSLATED",
        "translation_source_contract": {
            "primary_source": "legacy_engineering_model",
            "legacy_translation_fallback_used": True,
        },
    }
    scenario = {
        "status": "SCENARIOS_GENERATED",
        "scenario_input_contract": {"baseline_output_source": "ledger_native_model_outputs"},
    }
    interview = {
        "workflow_state": {
            "state": "INTERVIEW_SKIPPED_BY_USER",
            "ready_for_downstream": True,
            "requires_user_action": False,
            "remaining_question_count": 0,
        }
    }

    gate = _build_pre_export_gate(
        run_id="run_001",
        interview_result=interview,
        translation_result=translation,
        scenario_result=scenario,
        planner_ledger_adjudication={
            "status": "LEDGER_ADJUDICATION_COMPLETED",
            "field_resolution_adjudication_status": "ADJUDICATION_COMPLETED",
            "decision_count": 1,
        },
    )
    assert gate["status"] == "PRE_EXPORT_GATE_FAIL"
    assert "ledger_first_translation" in gate["failed_gates"]

    blocked = _build_blocked_export_result(run_id="run_001", pre_export_gate=gate)
    assert blocked["status"] == "EXPORT_BLOCKED_PRECONTRACT"
    assert blocked["export_manifest"]["summary"]["final_export_ready"] is False
    assert blocked["export_manifest"]["summary"]["planner_packet_ready"] is False
    assert blocked["export_manifest"]["exports"] == {}


def test_pre_export_gate_passes_only_ledger_first_translation_and_scenarios() -> None:
    translation = {
        "status": "TRANSLATED",
        "translation_source_contract": {
            "primary_source": "planner_field_ledger",
            "legacy_translation_fallback_used": False,
            "planner_ledger_row_count": 12,
        },
    }
    scenario = {
        "status": "SCENARIOS_GENERATED",
        "scenario_input_contract": {"baseline_output_source": "ledger_native_model_outputs"},
    }
    interview = {
        "workflow_state": {
            "state": "INTERVIEW_NOT_REQUIRED",
            "ready_for_downstream": True,
            "requires_user_action": False,
            "remaining_question_count": 0,
        }
    }

    assert _translation_is_ledger_first(translation)[0] is True
    assert _scenario_is_ledger_native(scenario)[0] is True
    gate = _build_pre_export_gate(
        run_id="run_002",
        interview_result=interview,
        translation_result=translation,
        scenario_result=scenario,
        planner_ledger_adjudication={
            "status": "LEDGER_ADJUDICATION_COMPLETED",
            "field_resolution_adjudication_status": "ADJUDICATION_COMPLETED",
            "decision_count": 1,
        },
    )
    assert gate["status"] == "PRE_EXPORT_GATE_PASS"
    assert gate["ready_for_final_export"] is True
