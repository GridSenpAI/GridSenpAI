from __future__ import annotations

from shared.field_value_policies import candidate_is_rejected_for_field


def test_revision_month_year_rejected_for_energization_date() -> None:
    candidate = {
        "field_path": "facility.energization.initial_energization_date",
        "value": "04/2026",
        "evidence": [{"text": "04/2026 ISSUED FOR INTERCONNECTION REVIEW CAD-STYLE DETAILING"}],
        "metadata": {"document_role": "title_block"},
    }
    assert candidate_is_rejected_for_field("facility.energization.initial_energization_date", candidate)


def test_structured_revision_payload_rejected_for_largest_motor_start() -> None:
    candidate = {
        "field_path": "largest_motor_start_mw",
        "value": {"facility": {"motor_schedule": [{"rev_date": "04/2026", "description": "ENHANCED CAD-STYLE DETAILING"}]}},
        "metadata": {"document_role": "revision_table"},
    }
    assert candidate_is_rejected_for_field("largest_motor_start_mw", candidate)


def test_tiny_phase_mw_without_load_context_rejected() -> None:
    candidate = {
        "field_path": "facility.load_schedule.phase_1_mw",
        "value": 2.0,
        "evidence": [{"text": "Phase 1 row marker sheet revision"}],
    }
    assert candidate_is_rejected_for_field("facility.load_schedule.phase_1_mw", candidate)
