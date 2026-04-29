from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.translation_service.service import run_service


@dataclass(slots=True)
class _TestConfig:
    schema_version_output: str = "1.0.0"


@dataclass(slots=True)
class _TestContext:
    run_id: str = "translation_field_resolution_runtime"
    config: _TestConfig = field(default_factory=_TestConfig)


def _get_parameter(result: dict[str, Any], parameter_path: str) -> dict[str, Any]:
    parameters = result.get("output_parameters", [])
    assert isinstance(parameters, list)
    for parameter in parameters:
        assert isinstance(parameter, dict)
        if parameter.get("parameter_path") == parameter_path:
            return parameter
    raise AssertionError(f"Parameter '{parameter_path}' not found.")


def test_translation_prefers_governed_field_resolution_for_peak_demand() -> None:
    context = _TestContext(run_id="translation_field_resolution_peak_case")
    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {
                "facility": {
                    "load_schedule": {"phase_1_mw": 40.0},
                }
            },
            "validation_report": {
                "schema_valid": True,
                "missing_fields": [],
                "conflicts": [],
                "interview_summary": {"confirmed_field_paths": []},
            },
            "evidence_snippets": [],
            "field_resolution": {
                "accepted_field_index": {
                    "accepted_peak_demand_mw": {
                        "accepted_value": 55.0,
                        "accepted_status": "resolved",
                        "accepted_confidence": 0.91,
                        "confidence_band": "HIGH",
                        "why_accepted": ["Applicant one-line and schedule agreed on 55 MW."],
                        "source_anchors": ["one_line.pdf / page 3 / load schedule"],
                        "planner_review_flag": False,
                        "needs_applicant_confirmation": False,
                        "decision_basis": "direct applicant evidence dominated weaker alternatives",
                    }
                }
            },
        }
    }

    result = run_service(context=context, canonical_state_result=canonical_state_result)

    p_mw = _get_parameter(result, "steady_state.p_mw")
    assert p_mw["value"] == 55.0
    assert p_mw["provenance_type"] == "field_resolution"
    assert p_mw["dependency_paths"] == ["accepted_peak_demand_mw"]
    assert p_mw["source_field_paths"] == ["accepted_peak_demand_mw"]
    assert p_mw["confidence_score"] == 0.91
    assert p_mw["confidence_tag"] == "HIGH"
    assert "Field resolution basis" in p_mw["planner_note"]
    assert "Why accepted" in p_mw["confidence_explanation"]


def test_translation_uses_resolved_power_factor_for_reactive_power() -> None:
    context = _TestContext(run_id="translation_field_resolution_pf_case")
    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {
                "facility": {
                    "load_schedule": {"phase_1_mw": 60.0},
                }
            },
            "validation_report": {
                "schema_valid": True,
                "missing_fields": [],
                "conflicts": [],
                "interview_summary": {"confirmed_field_paths": []},
            },
            "evidence_snippets": [],
            "field_resolution": {
                "accepted_field_index": {
                    "accepted_peak_demand_mw": {
                        "accepted_value": 60.0,
                        "accepted_status": "resolved",
                        "accepted_confidence": 0.86,
                        "confidence_band": "HIGH",
                        "why_accepted": ["Peak demand reconciled across applicant evidence."],
                        "source_anchors": ["schedule.pdf / page 2"],
                        "planner_review_flag": False,
                        "needs_applicant_confirmation": False,
                        "decision_basis": "reconciled demand package",
                    },
                    "net_power_factor_at_poi": {
                        "accepted_value": 0.8,
                        "accepted_status": "resolved",
                        "accepted_confidence": 0.74,
                        "confidence_band": "MODERATE",
                        "why_accepted": ["PF provided in applicant load information form."],
                        "source_anchors": ["load_form.pdf / page 1"],
                        "planner_review_flag": False,
                        "needs_applicant_confirmation": False,
                        "decision_basis": "validated applicant answer",
                    },
                }
            },
        }
    }

    result = run_service(context=context, canonical_state_result=canonical_state_result)

    q_mvar = _get_parameter(result, "steady_state.q_mvar")
    assert q_mvar["value"] == 45.0
    assert q_mvar["provenance_type"] == "field_resolution"
    assert q_mvar["dependency_paths"] == ["net_power_factor_at_poi", "accepted_peak_demand_mw"]
    assert q_mvar["confidence_score"] == 0.74
    assert q_mvar["confidence_tag"] == "MODERATE"
    assert "validated applicant answer" in q_mvar["confidence_explanation"]


def test_translation_uses_gap_resolution_retrieval_payload_when_provided() -> None:
    context = _TestContext(run_id="translation_gap_resolution_retrieval_case")
    normalization_result = {
        "normalized_input": {
            "facility": {
                "load_schedule": {"phase_1_mw": 80.0},
            }
        },
        "validation_report": {
            "schema_valid": True,
            "missing_fields": [],
            "conflicts": [],
            "interview_summary": {"confirmed_field_paths": ["facility.load_schedule.phase_1_mw"]},
        },
    }
    gap_resolution_result = {
        "retrieval": {
            "snippets": [
                {
                    "snippet_id": "snippet_load_1",
                    "text": "The load schedule states 80 MW peak demand.",
                    "metadata": {"topic": "Load schedule"},
                }
            ]
        },
        "interview": {},
    }

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        gap_resolution_result=gap_resolution_result,
    )

    p_mw = _get_parameter(result, "steady_state.p_mw")
    assert p_mw["provenance_type"] == "rule"
    assert p_mw["supporting_snippet_ids"] == ["snippet_load_1"]
    assert p_mw["confidence_tag"] == "HIGH"


def test_translation_holds_blocked_field_resolution_from_modeled_output() -> None:
    context = _TestContext(run_id="translation_field_resolution_blocked_case")
    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {
                "facility": {
                    "load_schedule": {"phase_1_mw": 40.0},
                }
            },
            "validation_report": {
                "schema_valid": True,
                "missing_fields": [],
                "conflicts": [],
                "interview_summary": {"confirmed_field_paths": []},
            },
            "evidence_snippets": [],
            "field_resolution": {
                "accepted_field_index": {
                    "accepted_peak_demand_mw": {
                        "accepted_value": 55.0,
                        "accepted_status": "conflicting",
                        "accepted_confidence": 0.41,
                        "confidence_band": "LOW",
                        "why_accepted": ["Best current value exists but must be held for review."],
                        "source_anchors": ["one_line.pdf / page 3 / load schedule"],
                        "planner_review_flag": True,
                        "needs_applicant_confirmation": True,
                        "decision_basis": "material conflict remains unresolved",
                        "field_release_profile": {
                            "release_state": "BLOCKED",
                            "translation_use_policy": "hold_from_modeled_output",
                            "scenario_use_policy": "hold_for_review_variant_only",
                            "planner_packet_use_policy": "show_as_provisional_with_blocker",
                            "export_readiness_tier": "blocked",
                        },
                    }
                }
            },
        }
    }

    result = run_service(context=context, canonical_state_result=canonical_state_result)

    p_mw = _get_parameter(result, "steady_state.p_mw")
    assert p_mw["value"] == 40.0
    assert p_mw["provenance_type"] == "rule"
    assert p_mw["planner_review_flag"] is True
    assert p_mw["needs_applicant_confirmation"] is True
    assert p_mw["field_release_state"] == "BLOCKED"
    assert p_mw["translation_use_policy"] == "hold_from_modeled_output"
    assert p_mw["scenario_use_policy"] == "hold_for_review_variant_only"
    assert p_mw["planner_packet_use_policy"] == "show_as_provisional_with_blocker"
    assert p_mw["confidence_tag"] == "LOW"
    assert "held from modeled output" in p_mw["review_note"]
