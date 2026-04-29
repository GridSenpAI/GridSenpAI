from __future__ import annotations

from app.orchestration.run_pipeline import _build_blocked_export_result, _build_pre_export_gate


def test_blocked_export_manifest_is_diagnostic_not_final() -> None:
    gate = _build_pre_export_gate(
        run_id="run_001",
        interview_result={"workflow_state": {"state": "WAITING_FOR_INTERVIEW", "ready_for_downstream": False, "requires_user_action": True, "remaining_question_count": 2}},
        translation_result={},
        scenario_result={},
        planner_ledger_adjudication={},
    )
    blocked = _build_blocked_export_result(run_id="run_001", pre_export_gate=gate)
    assert blocked["export_mode"] == "BLOCKED_DIAGNOSTIC_ONLY"
    assert blocked["export_manifest"]["status"] == "EXPORT_BLOCKED_PRECONTRACT"
    assert blocked["export_manifest"]["summary"]["final_export_ready"] is False
    assert blocked["export_manifest"]["summary"]["planner_packet_ready"] is False
