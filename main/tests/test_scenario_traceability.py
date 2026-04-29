from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.scenario_service.service import run_service


@dataclass
class _TestContext:
    run_id: str = "scenario_traceability_test"
    config: dict[str, Any] = field(default_factory=dict)


def _build_translation_result() -> dict[str, Any]:
    return {
        "run_id": "scenario_traceability_test",
        "model_outputs": {
            "steady_state": {
                "p_mw": 100.0,
                "q_mvar": 10.0,
                "power_factor": 0.98,
            },
            "zip_model": {
                "constant_power_fraction": 0.80,
                "constant_current_fraction": 0.10,
                "constant_impedance_fraction": 0.10,
            },
            "ramping": {
                "max_ramp_up_mw_per_min": 1.0,
                "max_ramp_down_mw_per_min": 1.0,
            },
        },
        "output_parameters": [
            {
                "parameter_path": "steady_state.p_mw",
                "value": 100.0,
                "units": "MW",
                "provenance_type": "rule",
                "dependency_paths": ["facility.load_schedule.phase_1_mw"],
                "source_field_paths": ["facility.load_schedule.phase_1_mw"],
                "supporting_snippet_ids": ["snippet_load_1"],
                "confidence_tag": "HIGH",
                "confidence_factors": {
                    "missing_dependency": False,
                },
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "steady_state.q_mvar",
                "value": 10.0,
                "units": "MVAR",
                "provenance_type": "rule",
                "dependency_paths": ["facility.load_schedule.phase_1_mw"],
                "source_field_paths": ["facility.load_schedule.phase_1_mw"],
                "supporting_snippet_ids": [],
                "confidence_tag": "MODERATE",
                "confidence_factors": {
                    "missing_dependency": False,
                },
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "steady_state.power_factor",
                "value": 0.98,
                "units": "fraction",
                "provenance_type": "rule",
                "dependency_paths": ["facility.ups.topology"],
                "source_field_paths": ["facility.ups.topology"],
                "supporting_snippet_ids": ["snippet_ups_pf"],
                "confidence_tag": "MODERATE",
                "confidence_factors": {
                    "missing_dependency": False,
                },
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "zip_model.constant_power_fraction",
                "value": 0.80,
                "units": "fraction",
                "provenance_type": "rule",
                "dependency_paths": ["facility.ups.topology"],
                "source_field_paths": ["facility.ups.topology"],
                "supporting_snippet_ids": ["snippet_ups_1"],
                "confidence_tag": "MODERATE",
                "confidence_factors": {
                    "missing_dependency": False,
                },
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "zip_model.constant_current_fraction",
                "value": 0.10,
                "units": "fraction",
                "provenance_type": "rule",
                "dependency_paths": ["facility.ups.topology"],
                "source_field_paths": ["facility.ups.topology"],
                "supporting_snippet_ids": ["snippet_ups_1"],
                "confidence_tag": "MODERATE",
                "confidence_factors": {
                    "missing_dependency": False,
                },
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "zip_model.constant_impedance_fraction",
                "value": 0.10,
                "units": "fraction",
                "provenance_type": "rule",
                "dependency_paths": ["facility.ups.topology"],
                "source_field_paths": ["facility.ups.topology"],
                "supporting_snippet_ids": ["snippet_ups_1"],
                "confidence_tag": "MODERATE",
                "confidence_factors": {
                    "missing_dependency": False,
                },
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "ramping.max_ramp_up_mw_per_min",
                "value": 1.0,
                "units": "MW/min",
                "provenance_type": "rule",
                "dependency_paths": ["facility.load_schedule.phase_1_mw"],
                "source_field_paths": ["facility.load_schedule.phase_1_mw"],
                "supporting_snippet_ids": ["snippet_load_1"],
                "confidence_tag": "MODERATE",
                "confidence_factors": {
                    "missing_dependency": False,
                },
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "ramping.max_ramp_down_mw_per_min",
                "value": 1.0,
                "units": "MW/min",
                "provenance_type": "rule",
                "dependency_paths": ["facility.load_schedule.phase_1_mw"],
                "source_field_paths": ["facility.load_schedule.phase_1_mw"],
                "supporting_snippet_ids": ["snippet_load_1"],
                "confidence_tag": "MODERATE",
                "confidence_factors": {
                    "missing_dependency": False,
                },
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
        ],
        "assumptions": [
            {
                "assumption_id": "assumption_steady_state_load",
                "parameter_path": "steady_state.p_mw",
            }
        ],
        "confidence_summary": {
            "HIGH": 1,
            "MODERATE": 7,
            "LOW": 0,
            "UNRESOLVED": 0,
        },
        "translation_support": {
            "review_notes": [
                "One or more translated parameters remain low-confidence.",
                "One or more translated parameters are assumption-backed.",
            ],
            "planner_note": "Review low-confidence and assumption-backed parameters before external publication.",
            "missing_info_summary": "Additional upstream evidence or interview confirmation is recommended before relying on low-confidence parameters.",
        },
        "status": "TRANSLATED",
    }


def _get_variant(
    scenario_result: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    variants = scenario_result["scenario_variants"]
    assert isinstance(variants, list)

    for variant in variants:
        assert isinstance(variant, dict)
        if variant.get("label") == label:
            return variant

    raise AssertionError(f"Scenario variant '{label}' was not produced.")


def _get_changed_parameter(
    scenario_variant: dict[str, Any],
    parameter_path: str,
) -> dict[str, Any]:
    changed_parameters = scenario_variant["changed_parameters"]
    assert isinstance(changed_parameters, list)

    for item in changed_parameters:
        assert isinstance(item, dict)
        if item.get("parameter_path") == parameter_path:
            return item

    raise AssertionError(f"Changed parameter '{parameter_path}' not found in scenario variant '{scenario_variant.get('label')}'.")


def test_scenario_service_generates_expanded_bounded_families() -> None:
    result = run_service(
        context=_TestContext(),
        translation_result=_build_translation_result(),
    )

    assert result["status"] == "SCENARIOS_GENERATED"
    assert result["run_id"] == "scenario_traceability_test"

    scenarios = result["scenarios"]
    assert set(scenarios.keys()) == {
        "Typical",
        "Conservative",
        "Best-case",
        "Buildout Phase",
        "Redundancy Degraded",
        "High Cooling Demand",
        "Fast Ramping",
    }

    scenario_families = result["scenario_families"]
    assert scenario_families["baseline"] == ["Typical"]
    assert set(scenario_families["core_bounds"]) == {"Conservative", "Best-case"}
    assert scenario_families["buildout_phase"] == ["Buildout Phase"]
    assert scenario_families["redundancy_state"] == ["Redundancy Degraded"]
    assert scenario_families["cooling_condition"] == ["High Cooling Demand"]
    assert scenario_families["ramping_behavior"] == ["Fast Ramping"]


def test_conservative_variant_preserves_traceability() -> None:
    result = run_service(
        context=_TestContext(),
        translation_result=_build_translation_result(),
    )

    conservative = _get_variant(result, "Conservative")
    assert conservative["metadata"]["scenario_family"] == "core_bounds"
    assert conservative["metadata"]["scenario_dimensions"]["operating_assumption"] == "risk_sensitive"
    assert conservative["metadata"]["translation_support_note"]

    cp_change = _get_changed_parameter(conservative, "zip_model.constant_power_fraction")
    assert cp_change["baseline_value"] == 0.80
    assert cp_change["new_value"] == 0.85
    assert cp_change["units"] == "fraction"
    assert cp_change["change_reason"] == "bounded_conservative_adjustment"
    assert cp_change["source_field_paths"] == ["facility.ups.topology"]
    assert cp_change["supporting_snippet_ids"] == ["snippet_ups_1"]

    ramp_change = _get_changed_parameter(conservative, "ramping.max_ramp_up_mw_per_min")
    assert ramp_change["baseline_value"] == 1.0
    assert ramp_change["new_value"] == 0.5
    assert ramp_change["units"] == "MW/min"
    assert ramp_change["change_reason"] == "bounded_conservative_adjustment"


def test_high_cooling_demand_variant_adjusts_power_factor_and_zip() -> None:
    result = run_service(
        context=_TestContext(),
        translation_result=_build_translation_result(),
    )

    high_cooling = _get_variant(result, "High Cooling Demand")
    assert high_cooling["metadata"]["scenario_family"] == "cooling_condition"
    assert high_cooling["metadata"]["scenario_dimensions"]["cooling_condition"] == "peak"

    pf_change = _get_changed_parameter(high_cooling, "steady_state.power_factor")
    assert pf_change["baseline_value"] == 0.98
    assert pf_change["new_value"] == 0.97
    assert pf_change["change_reason"] == "high_cooling_demand_adjustment"

    cp_change = _get_changed_parameter(high_cooling, "zip_model.constant_power_fraction")
    assert cp_change["new_value"] > cp_change["baseline_value"]


def test_fast_ramping_variant_only_changes_ramping_parameters() -> None:
    result = run_service(
        context=_TestContext(),
        translation_result=_build_translation_result(),
    )

    fast_ramping = _get_variant(result, "Fast Ramping")
    assert fast_ramping["metadata"]["scenario_family"] == "ramping_behavior"
    assert fast_ramping["metadata"]["scenario_dimensions"]["ramping_profile"] == "accelerated"

    changed_paths = {
        item["parameter_path"]
        for item in fast_ramping["changed_parameters"]
        if isinstance(item, dict)
    }
    assert changed_paths == {
        "ramping.max_ramp_up_mw_per_min",
        "ramping.max_ramp_down_mw_per_min",
    }

    up_change = _get_changed_parameter(fast_ramping, "ramping.max_ramp_up_mw_per_min")
    down_change = _get_changed_parameter(fast_ramping, "ramping.max_ramp_down_mw_per_min")
    assert up_change["new_value"] == 1.35
    assert down_change["new_value"] == 1.35