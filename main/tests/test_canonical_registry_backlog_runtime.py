from types import SimpleNamespace

from services.canonical_state_service.service import build_canonical_state


def test_canonical_state_build_includes_registry_resolution_backlog() -> None:
    context = SimpleNamespace(run_id="run-canonical-backlog")
    normalization_result = {
        "normalized_input": {
            "facility": {
                "ups": {"topology": "2N"},
            }
        },
        "validation_report": {
            "missing_fields": [
                {"field_path": "facility.poi_voltage_kv"},
                {"field_path": "facility.generators.count"},
            ]
        },
        "followup_questions": [],
    }
    result = build_canonical_state(
        context=context,
        normalization_result=normalization_result,
    )

    canonical_state = result["canonical_state"]
    backlog = canonical_state["planner_registry_resolution_backlog"]
    open_items = canonical_state["planner_registry_open_items"]
    summary = result["build_summary"]

    assert backlog["planner_registry_backed"] is True
    assert backlog["queue_count"] > 0
    assert "point_of_interconnection_voltage_kv" in backlog["queue_field_ids"]
    assert open_items["required_missing_count"] > 0
    assert summary["planner_registry_resolution_queue_count"] == backlog["queue_count"]
    assert "point_of_interconnection_voltage_kv" in summary["planner_registry_resolution_queue_field_ids"]
