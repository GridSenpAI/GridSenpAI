from __future__ import annotations

from shared.ledger_native_translation import build_ledger_first_translation_inputs


def test_missing_planner_ledger_blocks_ledger_native_translation() -> None:
    contract = build_ledger_first_translation_inputs({"normalized_input": {"facility": {"load_schedule": {"phase_1_mw": 100}}}})
    assert contract["used_ledger_native_primary"] is False
    assert contract["output_parameters"] == []
    assert contract["planner_ledger_row_count"] == 0


def test_phase_mw_titleblock_guard_blocks_untrusted_rows() -> None:
    from shared.planner_field_ledger import _apply_final_row_guards

    row = {
        "field_id": "phase_1_demand_mw",
        "field_path": "facility.load_schedule.phase_1_mw",
        "accepted_value": "1",
        "source_role": "title_block",
        "evidence_snippet": "Revision table row 1",
        "planner_critical": True,
    }
    _apply_final_row_guards(row)
    assert row["status"] == "UNRESOLVED"
    assert row["translation_use_policy"] == "do_not_use"


def test_semantic_voltage_guard_blocks_low_voltage_for_poi() -> None:
    from shared.planner_field_ledger import _apply_final_row_guards

    row = {
        "field_id": "poi_voltage_kv",
        "field_path": "facility.poi_voltage_kv",
        "accepted_value": "480",
        "source_role": "equipment_schedule",
        "evidence_snippet": "UPS output voltage 480 V",
        "planner_critical": True,
    }
    row["semantic_role"] = "load_distribution_voltage"
    _apply_final_row_guards(row)
    assert row["status"] == "UNRESOLVED"
    assert row["planner_packet_use_policy"] == "show_as_unresolved_semantic_role_mismatch"
