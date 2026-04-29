from __future__ import annotations

from pathlib import Path

from services.export_service.service import _build_planner_packet
from shared.planner_registry import planner_registry_resolution_queue


def test_planner_registry_resolution_queue_prioritizes_critical_open_fields() -> None:
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
                "confidence": 0.70,
                "is_primary": True,
            },
            {
                "field_path": "facility.ups.topology",
                "value": "2N",
                "status": "resolved",
                "confidence": 0.95,
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

    queue = planner_registry_resolution_queue(canonical_state, validation_report)

    assert queue
    assert queue[0]["field_id"] == "peak_demand_mw"
    assert queue[0]["status"] == "conflicting"
    field_ids = [item["field_id"] for item in queue]
    assert "generator_unit_count" in field_ids
    assert all(item["status"] != "resolved" for item in queue)
    assert [item["resolution_priority"] for item in queue] == list(range(1, len(queue) + 1))


def test_export_includes_resolution_priority_queue_section(tmp_path: Path) -> None:
    canonical_state = {
        "field_records": [
            {
                "field_path": "facility.load_schedule.phase_1_mw",
                "value": 120.0,
                "status": "conflicting",
                "confidence": 0.72,
                "is_primary": True,
            },
            {
                "field_path": "facility.poi_voltage_kv",
                "value": 138.0,
                "status": "review_required",
                "confidence": 0.55,
                "is_primary": True,
            },
        ],
        "normalized_input": {},
        "project_name": {"value": "Test Project"},
    }
    validation_report = {
        "missing_fields": [{"field_path": "facility.generators.count"}],
        "conflicts": [],
        "summary": {},
    }
    packet = _build_planner_packet(
        run_id="test-run",
        canonical_state=canonical_state,
        validation_result={"validation_report": validation_report, "summary": validation_report.get("summary", {})},
        translation_result={"status": "ok", "output_parameters": []},
        scenario_result={},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "## Resolution Priority Queue" in packet
    assert "P1: Peak demand MW" in packet
