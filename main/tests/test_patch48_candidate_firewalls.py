from __future__ import annotations

from shared.field_value_policies import candidate_is_rejected_for_field, source_role_from_candidate


def test_title_block_revision_date_rejected_for_energization_field() -> None:
    candidate = {
        "field_path": "facility.energization.initial_energization_date",
        "value": "04/2026",
        "source_role": "title_block",
        "metadata": {"context": "Title Block Rev C sheet date 04/2026 issued for review"},
    }
    assert source_role_from_candidate(candidate) == "title_block"
    assert candidate_is_rejected_for_field("facility.energization.initial_energization_date", candidate) is True


def test_revision_table_value_rejected_for_load_or_count_fields() -> None:
    candidate = {
        "field_path": "facility.load_schedule.phase_1_mw",
        "value": 180.0,
        "document_role": "revision_table",
        "metadata": {"context": "Revision table Rev 2 description 180"},
    }
    assert source_role_from_candidate(candidate) == "revision_table"
    assert candidate_is_rejected_for_field("facility.load_schedule.phase_1_mw", candidate) is True


def test_new_ingestion_roles_are_resolved_to_governed_source_roles() -> None:
    assert source_role_from_candidate({"source_role": "construction_phasing_plan"}) == "phasing_energization_plan"
    assert source_role_from_candidate({"source_role": "metering_scada_telemetry"}) == "metering_scada"
    assert source_role_from_candidate({"source_role": "facilities_study_memo"}) == "facilities_interconnection_memo"
