from __future__ import annotations

from shared.pre_interview_planner_ledger import build_pre_interview_planner_field_contract
from shared.planner_field_workflow import build_interview_question_records_from_ledger, registry_field_work_items


def test_pre_interview_ledger_is_registry_complete_with_partial_candidate_rows() -> None:
    work_items = registry_field_work_items(include_optional=True)
    assert work_items
    target = work_items[0]
    normalization_result = {
        "normalized_input": {
            "planner_candidate_ledger": [
                {
                    "field_id": target["field_id"],
                    "field_path": target["field_path"],
                    "field_label": target["field_label"],
                    "requiredness": target.get("requiredness", "required"),
                    "planner_critical": target.get("planner_critical", False),
                    "candidate_count": 1,
                    "accepted_value": "TEST-VALUE",
                    "accepted_source": {
                        "source_name": "test_request_form.pdf",
                        "source_page": "1",
                        "confidence": 0.91,
                        "source_type": "application_form",
                    },
                    "candidates": [
                        {
                            "candidate_id": "c1",
                            "value": "TEST-VALUE",
                            "confidence_score": 0.91,
                            "source_document": "test_request_form.pdf",
                            "source_page": "1",
                            "source_role": "application_form",
                            "evidence_snippet": "Test field label: TEST-VALUE",
                        }
                    ],
                    "status": "ACCEPTED_BY_NORMALIZATION",
                }
            ]
        }
    }

    contract = build_pre_interview_planner_field_contract(normalization_result)
    rows = contract["planner_field_ledger"]
    summary = contract["planner_field_ledger_summary"]
    audit = summary["registry_completion_audit"]

    assert len(rows) == len(work_items)
    assert audit["registry_complete"] is True
    assert audit["missing_registry_field_ids"] == []
    matched = [row for row in rows if row["field_id"] == target["field_id"]][0]
    assert matched["accepted_value"] == "TEST-VALUE"
    assert matched["source_document"] == "test_request_form.pdf"


def test_pre_interview_ledger_drives_applicant_questions_for_missing_required_fields() -> None:
    contract = build_pre_interview_planner_field_contract({"normalized_input": {}})
    rows = contract["planner_field_ledger"]
    questions = build_interview_question_records_from_ledger(
        rows,
        answered_field_paths=set(),
        max_questions=25,
    )

    assert questions
    assert all(question["field_path"] for question in questions)
    assert any(
        question.get("metadata", {}).get("ledger_status") in {"BLOCKED_BY_MISSING_SOURCE", "UNRESOLVED", "PROVISIONAL"}
        for question in questions
    )
