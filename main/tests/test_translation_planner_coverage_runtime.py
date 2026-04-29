from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dataclasses import dataclass, field
from typing import Any

from services.translation_service.service import run_service


@dataclass(slots=True)
class DummyConfig:
    schema_version_output: str = "1.0.0"


@dataclass(slots=True)
class DummyContext:
    run_id: str
    config: DummyConfig = field(default_factory=DummyConfig)
    run_dir: Path | None = None


def _get_param(result: dict[str, Any], path: str) -> dict[str, Any]:
    for item in result.get("output_parameters", []):
        if isinstance(item, dict) and item.get("parameter_path") == path:
            return item
    raise AssertionError(path)


def test_translation_enriches_planner_critical_parameters_from_driver_context() -> None:
    context = DummyContext(run_id="translation_planner_coverage")
    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {
                "interconnection": {
                    "telemetry": {"present": True, "points_list": []},
                    "protection": {"protection_summary": ""},
                },
                "facility": {
                    "load": {"transfer_summary": "Manual delayed transfer after outage"},
                },
            },
            "validation_report": {},
            "evidence_snippets": [],
            "engineering_model": {},
            "field_resolution": {
                "ledger": [
                    {"field_id": "accepted_peak_demand_mw", "accepted_value": 120.0, "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "net_power_factor_at_poi", "accepted_value": 0.95, "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "generator_unit_count", "accepted_value": 3, "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "redundancy_architecture", "accepted_value": "N+1", "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "cooling_load_share_percent_of_total", "accepted_value": 52.0, "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "cooling_architecture_summary", "accepted_value": "Mechanical chiller plant", "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "load_ramp_profile_summary", "accepted_value": "Fast staged pickup", "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "planned_operating_modes_summary", "accepted_value": "Normal and staged energization", "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "generator_transfer_sequence_summary", "accepted_value": "Manual staged transfer", "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "emergency_operating_mode_summary", "accepted_value": "Emergency load shed / restoration", "accepted_status": "confirmed", "confidence_band": "HIGH"},
                ]
            },
        }
    }

    result = run_service(context=context, canonical_state_result=canonical_state_result)
    p_param = _get_param(result, "steady_state.p_mw")
    q_param = _get_param(result, "steady_state.q_mvar")
    ramp_param = _get_param(result, "ramping.max_ramp_up_mw_per_min")

    assert "Resolved generator unit count: 3." in p_param["planner_note"]
    assert "Resolved redundancy architecture: N+1." in p_param["planner_note"]
    assert "Cooling architecture context: Mechanical chiller plant." in q_param["planner_note"]
    assert "Transfer behavior context: Manual delayed transfer after outage." in q_param["planner_note"]
    assert "Resolved ramp profile summary: Fast staged pickup." in ramp_param["planner_note"]
    assert "Generator transfer sequence context: Manual staged transfer." in ramp_param["planner_note"]
    assert ramp_param["confidence_tag"] == "LOW"
    assert "Telemetry is present but no telemetry points list was resolved." in ramp_param["review_note"]
    assert result["scenario_driver_context"]["cooling_architecture_summary"] == "Mechanical chiller plant"
    assert result["scenario_driver_context"]["planned_operating_modes_summary"] == "Normal and staged energization"
