from __future__ import annotations

from shared.planner_registry import planner_registry_open_items


def test_planner_registry_open_items_classifies_planner_critical_states() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_path": "facility.poi_voltage_kv",
                "value": 138.0,
                "status": "review_required",
                "confidence": 0.62,
                "is_primary": True,
            },
            {
                "field_path": "facility.load_schedule.phase_1_mw",
                "value": 120.0,
                "status": "conflicting",
                "confidence": 0.7,
                "is_primary": True,
            },
        ],
        "normalized_input": {},
    }
    validation_report = {
        "missing_fields": [
            {"field_path": "facility.generators.count"},
        ],
        "conflicts": [],
    }

    result = planner_registry_open_items(canonical_state, validation_report)

    assert result["planner_critical_open_count"] >= 3
    conflict_ids = {item["field_id"] for item in result["planner_critical_conflicting"]}
    review_ids = {item["field_id"] for item in result["planner_critical_review_required"]}
    missing_ids = {item["field_id"] for item in result["planner_critical_missing"]}

    assert "peak_demand_mw" in conflict_ids
    assert "point_of_interconnection_voltage_kv" in review_ids
    assert "generator_unit_count" in missing_ids
    assert "generator_unit_count" in result["planner_critical_open_field_ids"]
