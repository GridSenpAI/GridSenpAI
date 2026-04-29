from __future__ import annotations

from shared.planner_registry import build_planner_packet_field_rows, planner_registry_open_items


def test_packet_rows_prefer_field_resolution_accepted_values() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "raw-low",
                "field_path": "facility.poi_voltage_kv",
                "value": 115.0,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.40,
                "evidence_strength": "WEAK",
                "is_primary": True,
            }
        ],
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "field_path": "facility.poi_voltage_kv",
                    "label": "Point of Interconnection Voltage",
                    "packet_section": "interconnection",
                    "packet_section_label": "Interconnection",
                    "requiredness": "required",
                    "planner_critical": True,
                    "accepted_value": 138.0,
                    "accepted_status": "resolved",
                    "accepted_confidence": 0.92,
                    "accepted_candidate_id": "winner-1",
                    "confidence_band": "HIGH",
                    "why_accepted": ["Selected candidate had direct field match evidence."],
                    "alternatives": [
                        {"value": 115.0, "source_anchor": "old.pdf / page 1", "source_hierarchy": "secondary_web"}
                    ],
                    "source_anchors": ["one_line.pdf / page 2 / POI"],
                    "planner_review_flag": False,
                    "needs_applicant_confirmation": False,
                }
            ],
            "accepted_field_index": {
                "point_of_interconnection_voltage_kv": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "field_path": "facility.poi_voltage_kv",
                    "accepted_value": 138.0,
                    "accepted_status": "resolved",
                    "accepted_confidence": 0.92,
                    "confidence_band": "HIGH",
                    "why_accepted": ["Selected candidate had direct field match evidence."],
                    "alternatives": [{"value": 115.0}],
                    "source_anchors": ["one_line.pdf / page 2 / POI"],
                },
                "facility.poi_voltage_kv": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "field_path": "facility.poi_voltage_kv",
                    "accepted_value": 138.0,
                    "accepted_status": "resolved",
                    "accepted_confidence": 0.92,
                    "confidence_band": "HIGH",
                    "why_accepted": ["Selected candidate had direct field match evidence."],
                    "alternatives": [{"value": 115.0}],
                    "source_anchors": ["one_line.pdf / page 2 / POI"],
                },
            },
        },
    }

    rows = build_planner_packet_field_rows(canonical_state)
    interconnection_rows = rows["site_and_interconnection_context"]
    poi_row = next(row for row in interconnection_rows if row["field_id"] == "point_of_interconnection_voltage_kv")

    assert poi_row["value"] == 138.0
    assert poi_row["status"] == "resolved"
    assert poi_row["confidence"] == 0.92
    assert poi_row["why_accepted"] == ["Selected candidate had direct field match evidence."]
    assert poi_row["source_anchors"] == ["one_line.pdf / page 2 / POI"]
    assert poi_row["alternatives"][0]["value"] == 115.0


def test_open_items_use_field_resolution_statuses() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "peak_demand_mw",
                    "field_path": "facility.load_schedule.phase_1_mw",
                    "label": "Peak Demand",
                    "packet_section": "load_profile",
                    "packet_section_label": "Load Profile",
                    "requiredness": "required",
                    "planner_critical": True,
                    "accepted_value": None,
                    "accepted_status": "missing",
                    "accepted_confidence": None,
                    "confidence_band": "UNRESOLVED",
                    "accepted_candidate_id": "",
                    "why_accepted": [],
                    "alternatives": [],
                    "source_anchors": [],
                    "planner_review_flag": True,
                    "needs_applicant_confirmation": True,
                }
            ]
        }
    }

    open_items = planner_registry_open_items(canonical_state)
    assert open_items["planner_critical_open_count"] >= 1
    assert any(item["field_id"] == "peak_demand_mw" for item in open_items["planner_critical_missing"])
