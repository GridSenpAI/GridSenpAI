from __future__ import annotations

from pathlib import Path

from services.export_service.service import _build_planner_packet
from shared.planner_registry import planner_registry_open_items


class _Context:
    def __init__(self, run_dir: Path) -> None:
        self.run_id = "test-run"
        self.run_dir = run_dir


def test_export_includes_registry_open_items_section(tmp_path: Path) -> None:
    canonical_state = {
        "field_records": [
            {
                "field_path": "facility.poi_voltage_kv",
                "value": 138.0,
                "status": "review_required",
                "confidence": 0.55,
                "is_primary": True,
            },
            {
                "field_path": "facility.load_schedule.phase_1_mw",
                "value": 120.0,
                "status": "conflicting",
                "confidence": 0.72,
                "is_primary": True,
            },
        ],
        "normalized_input": {},
        "project_name": {"value": "Test Project"},
    }
    validation_report = {
        "missing_fields": [{"field_path": "facility.generators.count"}],
        "conflicts": [],
        "summary": {
            "planner_registry_open_items": planner_registry_open_items(
                canonical_state,
                {"missing_fields": [{"field_path": "facility.generators.count"}], "conflicts": []},
            )
        },
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
    assert "## Planner-Critical Open Items" in packet
    assert "POI nominal voltage kV" in packet
