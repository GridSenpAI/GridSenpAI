from __future__ import annotations

import json
from pathlib import Path

from services.interview_service.service import (
    _deduplicate_question_records,
    _load_existing_session,
    _select_session_path_for_workflow,
)
from shared.project_identity import resolve_project_identity


def test_interview_loader_preserves_ui_skip_state(tmp_path: Path) -> None:
    session_path = tmp_path / "project_alpha_interview_session.json"
    session_path.write_text(
        json.dumps(
            {
                "session_id": "interview_project_alpha",
                "project_id": "PROJECT::alpha",
                "status": "WAITING_FOR_INTERVIEW",
                "ui_state": {
                    "status": "SKIPPED_BY_USER",
                    "run_id": "run_parent",
                    "decision_reason": "Skip for now.",
                },
                "questions": [{"question_id": "q1", "field_path": "facility.poi_voltage_kv", "question": "Confirm POI voltage."}],
                "answers_confirmed": [],
                "clarifications": [],
            }
        ),
        encoding="utf-8",
    )

    payload = _load_existing_session(session_path, "PROJECT::alpha")

    assert payload["ui_state"]["status"] == "SKIPPED_BY_USER"
    assert payload["ui_state"]["run_id"] == "run_parent"
    assert payload["questions"][0]["question_id"] == "q1"


def test_session_selector_prefers_user_action_session_over_empty_canonical(tmp_path: Path) -> None:
    primary = tmp_path / "project_number_interview_session.json"
    legacy = tmp_path / "project_name_interview_session.json"
    primary.write_text(json.dumps({"project_id": "PROJECT::number", "questions": []}), encoding="utf-8")
    legacy.write_text(
        json.dumps(
            {
                "project_id": "PROJECT::name",
                "ui_state": {"status": "SKIPPED_BY_USER", "run_id": "run_1"},
            }
        ),
        encoding="utf-8",
    )

    selected = _select_session_path_for_workflow(
        primary_path=primary,
        candidate_paths=[primary, legacy],
    )

    assert selected == legacy


def test_question_dedupe_keeps_best_question_per_field_path() -> None:
    questions = [
        {
            "question_id": "generic_voltage",
            "field_path": "facility.electrical_configuration.internal_voltage_levels",
            "question": "Please provide or confirm Distribution voltage levels.",
            "reason": "Missing required value.",
            "source": "normalization_result",
            "priority": "MODERATE",
            "metadata": {},
        },
        {
            "question_id": "confirm_voltage",
            "field_path": "facility.electrical_configuration.internal_voltage_levels",
            "question": "Please confirm or correct Distribution voltage levels: current best value is 13.8.",
            "reason": "Candidate value requires applicant confirmation.",
            "source": "pre_interview_planner_field_ledger",
            "priority": "HIGH",
            "metadata": {"candidate_value": 13.8, "planner_critical": True},
        },
    ]

    deduped = _deduplicate_question_records(questions)

    assert len(deduped) == 1
    assert deduped[0]["question_id"] == "confirm_voltage"
    assert deduped[0]["metadata"]["deduped_question_count"] == 1
    assert deduped[0]["metadata"]["deduped_from_question_ids"] == ["generic_voltage"]


def test_project_identity_rejects_electrical_owner_as_applicant() -> None:
    identity = resolve_project_identity(
        run_id="run_1",
        normalization_result={
            "normalized_input": {
                "facility": {
                    "project_name": "Prairie Horizon Data Campus",
                    "project_number": "PHDC-LL-2026-017",
                    "owner": "owned high-side",
                }
            }
        },
    )

    assert identity["project_id"] == "PROJECT::phdc_ll_2026_017"
    assert identity["project_name"] == "Prairie Horizon Data Campus"
    assert identity["project_number"] == "PHDC-LL-2026-017"
    assert identity["applicant"] == ""
