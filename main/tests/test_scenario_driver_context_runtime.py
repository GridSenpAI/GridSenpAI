from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dataclasses import dataclass, field
from typing import Any

from services.scenario_service.service import run_service


@dataclass
class DummyContext:
    run_id: str = "scenario_driver_context_test"
    config: dict[str, Any] = field(default_factory=dict)


def _variant(result: dict[str, Any], label: str) -> dict[str, Any]:
    for item in result["scenario_variants"]:
        if item["label"] == label:
            return item
    raise AssertionError(label)


def _changed(variant: dict[str, Any], path: str) -> dict[str, Any]:
    for item in variant.get("changed_parameters", []):
        if item.get("parameter_path") == path:
            return item
    raise AssertionError(path)


def test_scenario_generation_uses_driver_context_for_cooling_and_ramping() -> None:
    translation_result = {
        "run_id": "scenario_driver_context_test",
        "model_outputs": {
            "steady_state": {"p_mw": 100.0, "q_mvar": 10.0, "power_factor": 0.97},
            "zip_model": {
                "constant_power_fraction": 0.80,
                "constant_current_fraction": 0.10,
                "constant_impedance_fraction": 0.10,
            },
            "ramping": {"max_ramp_up_mw_per_min": 1.0, "max_ramp_down_mw_per_min": 1.0},
        },
        "output_parameters": [
            {"parameter_path": "steady_state.p_mw", "provenance_type": "rule", "dependency_paths": [], "source_field_paths": [], "supporting_snippet_ids": [], "confidence_tag": "HIGH", "confidence_factors": {}, "planner_note": "", "review_note": "", "confidence_explanation": ""},
            {"parameter_path": "steady_state.q_mvar", "provenance_type": "rule", "dependency_paths": [], "source_field_paths": [], "supporting_snippet_ids": [], "confidence_tag": "HIGH", "confidence_factors": {}, "planner_note": "", "review_note": "", "confidence_explanation": ""},
            {"parameter_path": "steady_state.power_factor", "provenance_type": "rule", "dependency_paths": [], "source_field_paths": [], "supporting_snippet_ids": [], "confidence_tag": "HIGH", "confidence_factors": {}, "planner_note": "", "review_note": "", "confidence_explanation": ""},
            {"parameter_path": "zip_model.constant_power_fraction", "provenance_type": "rule", "dependency_paths": [], "source_field_paths": [], "supporting_snippet_ids": [], "confidence_tag": "HIGH", "confidence_factors": {}, "planner_note": "", "review_note": "", "confidence_explanation": ""},
            {"parameter_path": "zip_model.constant_current_fraction", "provenance_type": "rule", "dependency_paths": [], "source_field_paths": [], "supporting_snippet_ids": [], "confidence_tag": "HIGH", "confidence_factors": {}, "planner_note": "", "review_note": "", "confidence_explanation": ""},
            {"parameter_path": "zip_model.constant_impedance_fraction", "provenance_type": "rule", "dependency_paths": [], "source_field_paths": [], "supporting_snippet_ids": [], "confidence_tag": "HIGH", "confidence_factors": {}, "planner_note": "", "review_note": "", "confidence_explanation": ""},
            {"parameter_path": "ramping.max_ramp_up_mw_per_min", "provenance_type": "rule", "dependency_paths": [], "source_field_paths": [], "supporting_snippet_ids": [], "confidence_tag": "HIGH", "confidence_factors": {}, "planner_note": "", "review_note": "", "confidence_explanation": ""},
            {"parameter_path": "ramping.max_ramp_down_mw_per_min", "provenance_type": "rule", "dependency_paths": [], "source_field_paths": [], "supporting_snippet_ids": [], "confidence_tag": "HIGH", "confidence_factors": {}, "planner_note": "", "review_note": "", "confidence_explanation": ""},
        ],
        "assumptions": [],
        "confidence_summary": {"HIGH": 8, "MODERATE": 0, "LOW": 0, "UNRESOLVED": 0},
        "translation_support": {"review_notes": [], "planner_note": "", "missing_info_summary": ""},
        "scenario_driver_context": {
            "cooling_load_share": 0.45,
            "redundancy_architecture": "2N",
            "generator_unit_count": 4,
            "load_ramp_profile_summary": "fast staged pickup",
            "transfer_summary": "instant transfer",
            "telemetry_present": True,
            "telemetry_points_count": 0,
            "protection_summary": "",
        },
    }
    result = run_service(context=DummyContext(), translation_result=translation_result)
    high_cooling = _variant(result, "High Cooling Demand")
    fast_ramping = _variant(result, "Fast Ramping")
    redundancy = _variant(result, "Redundancy Degraded")
    assert high_cooling["confidence"] == "LOW"
    assert _changed(high_cooling, "steady_state.power_factor")["new_value"] < 0.96
    assert _changed(fast_ramping, "ramping.max_ramp_up_mw_per_min")["new_value"] == 1.6
    assert _changed(redundancy, "zip_model.constant_power_fraction")["new_value"] >= 0.85
    assert result["scenario_driver_context"]["generator_unit_count"] == 4
