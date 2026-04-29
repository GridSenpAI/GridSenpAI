from shared.planner_registry import planner_registry_integrity_snapshot


def test_planner_required_fields_preserves_broad_field_universe() -> None:
    snapshot = planner_registry_integrity_snapshot()

    assert snapshot["field_count"] >= 524
    assert snapshot["planner_document_count"] >= 18
    assert snapshot["group_count"] >= 13
    assert snapshot["missing_required_samples"] == []
