from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.scenario_service.service import run_service


@dataclass
class _TestContext:
    run_id: str = "scenario_field_resolution_runtime"
    config: dict[str, Any] = field(default_factory=dict)


def _get_variant(result: dict[str, Any], label: str) -> dict[str, Any]:
    variants = result["scenario_variants"]
    assert isinstance(variants, list)
    for variant in variants:
        assert isinstance(variant, dict)
        if variant.get("label") == label:
            return variant
    raise AssertionError(f"Scenario variant '{label}' was not produced.")


def _get_changed_parameter(variant: dict[str, Any], parameter_path: str) -> dict[str, Any]:
    changed_parameters = variant["changed_parameters"]
    assert isinstance(changed_parameters, list)
    for item in changed_parameters:
        assert isinstance(item, dict)
        if item.get("parameter_path") == parameter_path:
            return item
    raise AssertionError(f"Changed parameter '{parameter_path}' not found.")


def test_scenarios_preserve_field_resolution_context_from_translation_outputs() -> None:
    translation_result = {
        "run_id": "scenario_field_resolution_runtime",
        "model_outputs": {
            "steady_state": {"p_mw": 120.0, "q_mvar": 30.0, "power_factor": 0.97},
            "zip_model": {
                "constant_power_fraction": 0.80,
                "constant_current_fraction": 0.10,
                "constant_impedance_fraction": 0.10,
            },
            "ramping": {"max_ramp_up_mw_per_min": 1.0, "max_ramp_down_mw_per_min": 1.0},
        },
        "output_parameters": [
            {
                "parameter_path": "zip_model.constant_power_fraction",
                "value": 0.80,
                "units": "fraction",
                "provenance_type": "field_resolution",
                "provenance_ref": ["ups_schedule.pdf:p4"],
                "dependency_paths": ["steady_state_zip_fraction_p"],
                "source_field_paths": ["steady_state_zip_fraction_p"],
                "supporting_snippet_ids": ["snippet_zip_1"],
                "confidence_tag": "MODERATE",
                "confidence_score": 0.74,
                "planner_note": "",
                "review_note": "Planner review required before export.",
                "confidence_explanation": "Field resolution basis: conflicting UPS evidence.",
                "planner_review_flag": True,
                "needs_applicant_confirmation": True,
                "decision_basis": "accepted_from_governed_adjudication",
                "accepted_value_kind": "reconciled_inferred_value",
                "planner_attention_tier": "critical_review",
                "field_resolution_field_key": "steady_state_zip_fraction_p",
                "field_release_state": "PROVISIONAL",
                "translation_use_policy": "use_with_provisional_tag",
                "scenario_use_policy": "use_with_review_variant",
                "source_anchors": ["ups_schedule.pdf:p4"],
                "why_accepted": ["UPS schedule matched applicant clarification."],
                "alternatives_count": 2,
            },
            {
                "parameter_path": "zip_model.constant_current_fraction",
                "value": 0.10,
                "units": "fraction",
                "provenance_type": "rule",
                "provenance_ref": "RULE.ZIP.DEFAULTS.v1",
                "dependency_paths": ["facility.ups.topology"],
                "source_field_paths": ["facility.ups.topology"],
                "supporting_snippet_ids": ["snippet_zip_1"],
                "confidence_tag": "MODERATE",
                "confidence_score": 0.65,
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "zip_model.constant_impedance_fraction",
                "value": 0.10,
                "units": "fraction",
                "provenance_type": "rule",
                "provenance_ref": "RULE.ZIP.DEFAULTS.v1",
                "dependency_paths": ["facility.ups.topology"],
                "source_field_paths": ["facility.ups.topology"],
                "supporting_snippet_ids": ["snippet_zip_1"],
                "confidence_tag": "MODERATE",
                "confidence_score": 0.65,
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "ramping.max_ramp_up_mw_per_min",
                "value": 1.0,
                "units": "MW/min",
                "provenance_type": "rule",
                "provenance_ref": "RULE.RAMP.DEFAULTS.v1",
                "dependency_paths": ["facility.load_schedule.phase_1_mw"],
                "source_field_paths": ["facility.load_schedule.phase_1_mw"],
                "supporting_snippet_ids": ["snippet_ramp_1"],
                "confidence_tag": "HIGH",
                "confidence_score": 0.85,
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
            {
                "parameter_path": "ramping.max_ramp_down_mw_per_min",
                "value": 1.0,
                "units": "MW/min",
                "provenance_type": "rule",
                "provenance_ref": "RULE.RAMP.DEFAULTS.v1",
                "dependency_paths": ["facility.load_schedule.phase_1_mw"],
                "source_field_paths": ["facility.load_schedule.phase_1_mw"],
                "supporting_snippet_ids": ["snippet_ramp_1"],
                "confidence_tag": "HIGH",
                "confidence_score": 0.85,
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            },
        ],
        "assumptions": [],
        "confidence_summary": {"HIGH": 2, "MODERATE": 3, "LOW": 0, "UNRESOLVED": 0},
        "translation_support": {"planner_note": "Watch review-required ZIP assumptions."},
        "status": "TRANSLATED",
    }

    result = run_service(context=_TestContext(), translation_result=translation_result)
    conservative = _get_variant(result, "Conservative")

    assert conservative["confidence"] == "LOW"
    summary = conservative["metadata"]["translation_resolution_summary"]
    assert summary["field_resolution_backed_parameter_count"] == 1
    assert summary["planner_review_flag_count"] == 1
    assert summary["needs_applicant_confirmation_count"] == 1
    assert summary["needs_review_parameter_count"] == 1

    cp_change = _get_changed_parameter(conservative, "zip_model.constant_power_fraction")
    assert cp_change["baseline_provenance_type"] == "field_resolution"
    assert cp_change["planner_review_flag"] is True
    assert cp_change["needs_applicant_confirmation"] is True
    assert cp_change["decision_basis"] == "accepted_from_governed_adjudication"
    assert cp_change["accepted_value_kind"] == "reconciled_inferred_value"
    assert cp_change["planner_attention_tier"] == "critical_review"
    assert cp_change["field_resolution_field_key"] == "steady_state_zip_fraction_p"
    assert cp_change["field_release_state"] == "PROVISIONAL"
    assert cp_change["translation_use_policy"] == "use_with_provisional_tag"
    assert cp_change["scenario_use_policy"] == "use_with_review_variant"
    assert cp_change["source_anchors"] == ["ups_schedule.pdf:p4"]
    assert cp_change["why_accepted"] == ["UPS schedule matched applicant clarification."]
    assert cp_change["alternatives_count"] == 2
