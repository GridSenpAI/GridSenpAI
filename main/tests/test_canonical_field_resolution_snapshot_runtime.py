from types import SimpleNamespace

from services.canonical_state_service.service import build_canonical_state


def test_canonical_state_persists_field_resolution_snapshots() -> None:
    context = SimpleNamespace(run_id="run-accepted-snapshot")
    existing_state = {
        "run_id": "run-accepted-snapshot",
        "field_records": [],
        "conflict_records": [],
        "review_flags": [],
        "stage_status": {"interview": "COMPLETED"},
    }

    result = build_canonical_state(context=context, existing_state=existing_state)

    canonical_state = result["canonical_state"]
    accepted_index = canonical_state["accepted_planner_field_index"]
    packet_rows = canonical_state["planner_packet_field_rows"]
    summary = result["build_summary"]

    assert isinstance(accepted_index, dict)
    assert isinstance(packet_rows, dict) and packet_rows
    assert summary["field_resolution_accepted_field_count"] == 0
    assert summary["field_resolution_backlog_count"] >= 1
    assert isinstance(summary["field_resolution_top_backlog_field_ids"], list)
