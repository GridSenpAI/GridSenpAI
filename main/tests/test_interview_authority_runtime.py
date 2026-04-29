from __future__ import annotations

from services.interview_service.authority import merge_interview_answer_into_ledger_entry


def _entry(value=None, confidence=None):
    return {
        "field_id": "facility.poi_voltage_kv",
        "field_path": "facility.poi_voltage_kv",
        "label": "POI voltage",
        "accepted_value": value,
        "accepted_confidence": confidence,
        "accepted_status": "resolved" if value is not None else "unresolved",
        "confidence_band": "HIGH" if confidence and confidence >= 0.85 else "LOW",
        "accepted_source_hierarchy": "application_request_form" if value is not None else "",
        "candidates": [],
        "supporting_sources": [],
        "source_anchors": ["doc::form::p1"] if value is not None else [],
        "why_accepted": ["Document evidence selected." ] if value is not None else [],
        "planner_review_flag": False,
        "needs_applicant_confirmation": False,
        "conflict_materiality": "none",
    }


def _answer(value, raw=None):
    return {
        "question_id": "FACILITY_POI_VOLTAGE_KV",
        "field_path": "facility.poi_voltage_kv",
        "confirmed_answer": value,
        "raw_answer": str(raw if raw is not None else value),
        "source_name": "interview_session.json",
        "answer_status": "CONFIRMED",
    }


def test_interview_confirms_document_value_boosts_confidence() -> None:
    updated, decision = merge_interview_answer_into_ledger_entry(_entry(138, 0.94), _answer(138))

    assert decision["action"] == "INTERVIEW_CONFIRMED_DOCUMENT_VALUE"
    assert updated["accepted_value"] == 138
    assert updated["accepted_confidence"] >= 0.99
    assert updated["applicant_answer_state"] == "confirmed_existing_value"
    assert any(candidate["source_stage"] == "interview" for candidate in updated["candidates"])


def test_interview_supplied_value_wins_when_no_document_value_exists() -> None:
    updated, decision = merge_interview_answer_into_ledger_entry(_entry(), _answer(60))

    assert decision["action"] == "INTERVIEW_VALUE_ACCEPTED"
    assert updated["accepted_value"] == 60
    assert updated["accepted_source_hierarchy"] == "applicant_confirmed_answer"
    assert updated["applicant_answer_state"] == "confirmed_supplied"


def test_interview_wins_lower_confidence_document_conflict_with_note() -> None:
    updated, decision = merge_interview_answer_into_ledger_entry(_entry(64, 0.62), _answer(60))

    assert decision["action"] == "INTERVIEW_VALUE_ACCEPTED_WITH_CONFLICT_NOTE"
    assert updated["accepted_value"] == 60
    assert updated["applicant_answer_state"] == "confirmed_override"
    assert "conflicts" in updated["contradiction_summary"].lower()


def test_high_confidence_document_conflict_requires_followup_confirmation() -> None:
    updated, decision = merge_interview_answer_into_ledger_entry(_entry(138, 0.96), _answer(13.8))

    assert decision["action"] == "HIGH_CONFIDENCE_DOCUMENT_CONFLICT_REQUIRES_CONFIRMATION"
    assert updated["accepted_value"] == 138
    assert updated["needs_applicant_confirmation"] is True
    assert updated["planner_review_flag"] is True
    assert updated["applicant_answer_state"] == "conflict_requires_confirmation"
    assert "13.8" in updated["applicant_question_profile"]["prompt"]
    assert "138" in updated["applicant_question_profile"]["prompt"]


def test_unknown_interview_answer_retains_document_value() -> None:
    updated, decision = merge_interview_answer_into_ledger_entry(_entry(138, 0.94), _answer("I don't know"))

    assert decision["action"] == "UNKNOWN_ANSWER_DOCUMENT_OR_UNRESOLVED_VALUE_RETAINED"
    assert updated["accepted_value"] == 138
    assert updated["applicant_answer_state"] == "unknown"
    assert any(candidate["source_stage"] == "interview" for candidate in updated["candidates"])

def test_explicit_confirmation_overrides_high_confidence_document_conflict() -> None:
    confirmed_conflict_answer = _answer(13.8)
    confirmed_conflict_answer["question_id"] = "INTERVIEW_CONFIRM_CONFLICT::FACILITY_POI_VOLTAGE_KV"
    confirmed_conflict_answer["answer_status"] = "CONFIRMED_CONFLICT"

    updated, decision = merge_interview_answer_into_ledger_entry(_entry(138, 0.96), confirmed_conflict_answer)

    assert decision["action"] == "INTERVIEW_CONFLICT_CONFIRMED"
    assert updated["accepted_value"] == 13.8
    assert updated["applicant_answer_state"] == "conflict_confirmed"
    assert updated["conflict_materiality"] == "high"
