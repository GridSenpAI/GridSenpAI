from __future__ import annotations

from types import SimpleNamespace

from shared.project_identity import resolve_project_identity
from shared.planner_interview_closure import apply_interview_answers_to_planner_contract


def test_project_identity_promotes_extracted_values() -> None:
    identity = resolve_project_identity(
        run_id="run_child",
        replay_source_run_id="run_parent",
        normalization_result={
            "normalized_input": {
                "facility": {"project_name": "Prairie Horizon Data Campus"},
                "project_number": "PHDC-LL-2026-017",
                "applicant": "Prairie Horizon Digital Infrastructure LLC Page 1",
            }
        },
    )
    assert identity["project_id"].startswith("PROJECT::")
    assert identity["project_name"] == "Prairie Horizon Data Campus"
    assert identity["project_number"] == "PHDC-LL-2026-017"
    assert identity["applicant"] == "Prairie Horizon Digital Infrastructure LLC"


def test_interview_answer_appends_missing_ledger_row() -> None:
    contract = {"planner_field_ledger": []}
    result = apply_interview_answers_to_planner_contract(
        contract,
        interview_result={
            "answers_confirmed": [
                {
                    "question_id": "q1",
                    "field_path": "facility.load_schedule.phase_1_mw",
                    "confirmed_answer": "120",
                    "answer_status": "CONFIRMED",
                }
            ]
        },
    )
    rows = result["planner_field_ledger"]
    assert len(rows) == 1
    assert rows[0]["source_role"] == "interview"
    assert rows[0]["accepted_value"] == "120"
    assert result["planner_interview_closure"]["rows_updated_count"] == 1
