from shared.planner_registry import worker_routing_table


def test_equipment_schedule_is_not_routed_to_drawing_worker() -> None:
    routing = worker_routing_table()
    assert "facility.equipment_schedule" not in routing.get("drawing_worker", ())
    assert "facility.equipment_schedule" in routing.get("table_worker", ())
