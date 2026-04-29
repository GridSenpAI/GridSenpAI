from __future__ import annotations

from app.orchestration.run_pipeline import (
    _build_blocked_export_result,
    _build_pre_export_gate,
    _interview_requires_user_action,
)


def test_runs9_failure_mode_waiting_interview_cannot_be_export_ready() -> None:
    interview = {
        "status": "WAITING_FOR_INTERVIEW",
        "workflow_state": {
            "state": "WAITING_FOR_INTERVIEW",
            "ready_for_downstream": False,
            "requires_user_action": True,
            "question_count": 51,
            "remaining_question_count": 51,
            "answered_count": 0,
        },
    }
    assert _interview_requires_user_action(interview) is True

    gate = _build_pre_export_gate(
        run_id="run_20260427_120906",
        interview_result=interview,
        translation_result={
            "status": "TRANSLATION_BLOCKED_LEDGER_FIRST_REQUIRED",
            "translation_source_contract": {
                "primary_source": "planner_field_ledger",
                "legacy_translation_fallback_used": False,
                "blocked_reason": "LEDGER_FIRST_TRANSLATION_REQUIRED",
            },
        },
        scenario_result={
            "status": "SCENARIOS_BLOCKED_LEDGER_FIRST_REQUIRED",
            "scenario_input_contract": {"baseline_output_source": "blocked_no_ledger_native_model_outputs"},
        },
        planner_ledger_adjudication={
            "status": "LEDGER_ADJUDICATION_READY_OR_SKIPPED",
            "field_resolution_adjudication_status": "ADJUDICATION_PACKETS_READY",
            "decision_count": 0,
        },
    )
    assert gate["status"] == "PRE_EXPORT_GATE_FAIL"
    assert set(gate["failed_gates"]) >= {
        "interview_resolved_for_downstream",
        "adjudication_closed",
        "ledger_native_scenario_inputs",
    }

    blocked = _build_blocked_export_result(run_id="run_20260427_120906", pre_export_gate=gate)
    assert blocked["export_manifest"]["summary"]["final_export_ready"] is False
    assert blocked["export_manifest"]["summary"]["planner_packet_ready"] is False
    assert blocked["export_manifest"]["summary"]["interview_ready_for_final_output"] is False
