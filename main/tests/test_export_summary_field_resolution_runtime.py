from services.export_service.service import _resolve_export_field_value


def test_export_summary_prefers_field_resolution_accepted_value() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_path": "facility.poi_voltage_kv",
                "value": 115,
                "status": "conflicting",
                "validation_status": "CONFLICTING",
                "review_status": "OPEN",
                "conflict_status": "CONFLICT_PRESENT",
            }
        ],
        "field_resolution": {
            "accepted_field_index": {
                "facility.poi_voltage_kv": {
                    "accepted_status": "resolved",
                    "accepted_value": 138,
                    "accepted_confidence": 0.92,
                    "planner_review_flag": False,
                }
            }
        },
    }

    assert _resolve_export_field_value(canonical_state, "facility.poi_voltage_kv", "Unknown") == 138
