from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dataclasses import dataclass, field
from pathlib import Path
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


def test_translation_emits_power_factor_parameter_and_scenario_driver_context() -> None:
    context = DummyContext(run_id="translation_driver_test")
    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {
                "interconnection": {
                    "telemetry": {"present": True, "points_list": []},
                    "protection": {"protection_summary": "Relay package pending final stamp."},
                },
                "facility": {
                    "load": {"transfer_summary": "Fast transfer on outage"},
                },
            },
            "validation_report": {},
            "evidence_snippets": [],
            "engineering_model": {},
            "field_resolution": {
                "ledger": [
                    {"field_id": "accepted_peak_demand_mw", "accepted_value": 120.0, "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "net_power_factor_at_poi", "accepted_value": 0.96, "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "generator_unit_count", "accepted_value": 4, "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "cooling_load_share_percent_of_total", "accepted_value": 45.0, "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "redundancy_architecture", "accepted_value": "2N", "accepted_status": "confirmed", "confidence_band": "HIGH"},
                    {"field_id": "load_ramp_profile_summary", "accepted_value": "fast staged pickup", "accepted_status": "confirmed", "confidence_band": "HIGH"},
                ]
            },
        }
    }

    result = run_service(context=context, canonical_state_result=canonical_state_result)
    pf_param = _get_param(result, "steady_state.power_factor")
    assert pf_param["value"] == 0.96
    driver = result["scenario_driver_context"]
    assert driver["generator_unit_count"] == 4
    assert abs(driver["cooling_load_share"] - 0.45) < 1e-9
    assert driver["redundancy_architecture"] == "2N"
    assert driver["telemetry_present"] is True
    assert driver["telemetry_points_count"] == 0
    assert driver["load_ramp_profile_summary"] == "fast staged pickup"
