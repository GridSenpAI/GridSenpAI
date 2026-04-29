from __future__ import annotations

from services.export_service.service import _build_interview_readiness_summary
from shared.field_value_policies import candidate_is_rejected_for_field


def test_export_interview_readiness_marks_skipped_as_draft_not_final() -> None:
    readiness = _build_interview_readiness_summary(
        {
            "status": "INTERVIEW_SKIPPED_BY_USER",
            "workflow_state": {
                "state": "INTERVIEW_SKIPPED_BY_USER",
                "ready_for_downstream": True,
                "requires_user_action": False,
            },
            "interview_session": {
                "ui_state": {"status": "SKIPPED_BY_USER"},
            },
        },
        {},
    )

    assert readiness["completion_state"] == "SKIPPED_OR_DEFERRED_BY_USER"
    assert readiness["ready_for_validation"] is True
    assert readiness["ready_for_final_output"] is False
    assert readiness["draft_outputs_allowed"] is True
    assert "applicant_interview_skipped" in readiness["blocking_categories"]


def test_field_policy_rejects_revision_month_as_energization_date() -> None:
    candidate = {
        "field_path": "facility.energization.initial_energization_date",
        "value": "04/2026",
        "source_method": "project_primary.schedule",
        "evidence": ["04/2026 ISSUED FOR INTERCONNECTION REVIEW CAD-style detailing"],
        "metadata": {"raw_text": "04/2026 ISSUED FOR INTERCONNECTION REVIEW"},
    }

    assert candidate_is_rejected_for_field("facility.energization.initial_energization_date", candidate) is True


def test_field_policy_rejects_tiny_phase_mw_without_strong_load_context() -> None:
    candidate = {
        "field_path": "facility.load_schedule.phase_1_mw",
        "value": 2.0,
        "unit": "MW",
        "source_method": "project_primary.load_phase",
        "evidence": ["Phase 1 row id 2 MW drawing marker"],
        "metadata": {"promotion_family": "load_phase"},
    }

    assert candidate_is_rejected_for_field("facility.load_schedule.phase_1_mw", candidate) is True
