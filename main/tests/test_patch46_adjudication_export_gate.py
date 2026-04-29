from __future__ import annotations

from app.orchestration.run_pipeline import _adjudication_is_closed, _build_pre_export_gate


def _ready_interview() -> dict:
    return {
        "workflow_state": {
            "state": "INTERVIEW_NOT_REQUIRED",
            "ready_for_downstream": True,
            "requires_user_action": False,
            "remaining_question_count": 0,
        }
    }


def _ready_translation() -> dict:
    return {
        "status": "TRANSLATED",
        "translation_source_contract": {
            "primary_source": "planner_field_ledger",
            "legacy_translation_fallback_used": False,
        },
    }


def _ready_scenario() -> dict:
    return {
        "status": "SCENARIOS_GENERATED",
        "scenario_input_contract": {"baseline_output_source": "ledger_native_model_outputs"},
    }


def test_adjudication_packets_ready_does_not_satisfy_final_export_gate() -> None:
    adjudication = {
        "status": "LEDGER_ADJUDICATION_READY_OR_SKIPPED",
        "field_resolution_adjudication_status": "ADJUDICATION_PACKETS_READY",
        "decision_count": 0,
        "release_effect": "no_global_export_block",
    }
    closed, evidence = _adjudication_is_closed(adjudication)
    assert closed is False
    assert evidence["field_resolution_adjudication_status"] == "ADJUDICATION_PACKETS_READY"

    gate = _build_pre_export_gate(
        run_id="run_001",
        interview_result=_ready_interview(),
        translation_result=_ready_translation(),
        scenario_result=_ready_scenario(),
        planner_ledger_adjudication=adjudication,
    )
    assert gate["status"] == "PRE_EXPORT_GATE_FAIL"
    assert "adjudication_closed" in gate["failed_gates"]


def test_adjudication_skipped_no_conflicts_satisfies_final_export_gate() -> None:
    adjudication = {
        "status": "LEDGER_ADJUDICATION_READY_OR_SKIPPED",
        "field_resolution_adjudication_status": "ADJUDICATION_SKIPPED_NO_CONFLICTS",
        "decision_count": 0,
    }
    assert _adjudication_is_closed(adjudication)[0] is True

    gate = _build_pre_export_gate(
        run_id="run_002",
        interview_result=_ready_interview(),
        translation_result=_ready_translation(),
        scenario_result=_ready_scenario(),
        planner_ledger_adjudication=adjudication,
    )
    assert gate["status"] == "PRE_EXPORT_GATE_PASS"
