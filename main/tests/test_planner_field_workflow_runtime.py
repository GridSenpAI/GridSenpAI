from shared.planner_field_ledger import build_planner_field_ledger, planner_field_ledger_summary
from shared.planner_field_workflow import (
    build_interview_question_records_from_ledger,
    registry_completion_audit,
    registry_field_work_items,
)
from shared.planner_registry import planner_registry_fields


def test_registry_work_items_cover_master_planner_fields() -> None:
    items = registry_field_work_items()
    assert len(items) == len(planner_registry_fields())
    assert all(item["field_id"] for item in items)
    assert any(item["policy_family"] == "interconnection" for item in items)


def test_empty_ledger_backfills_all_master_fields_and_audits_complete() -> None:
    rows = build_planner_field_ledger([])
    summary = planner_field_ledger_summary(rows)
    assert len(rows) == len(planner_registry_fields())
    assert summary["registry_complete"] is True
    assert summary["registry_field_count"] == len(planner_registry_fields())
    assert summary["registry_completion"]["registry_complete"] is True


def test_planner_ledger_builds_prioritized_interview_questions() -> None:
    rows = build_planner_field_ledger([])
    questions = build_interview_question_records_from_ledger(rows, max_questions=5)
    assert questions
    assert len(questions) <= 5
    assert all(question["source"] == "planner_field_ledger" for question in questions)
    assert all(question["metadata"].get("field_policy") for question in questions)
    assert questions[0]["priority"] in {"HIGH", "MODERATE"}


def test_registry_completion_audit_detects_missing_field_rows() -> None:
    rows = build_planner_field_ledger([])
    audit = registry_completion_audit(rows[:-1])
    assert audit["registry_complete"] is False
    assert audit["missing_registry_field_ids"]
