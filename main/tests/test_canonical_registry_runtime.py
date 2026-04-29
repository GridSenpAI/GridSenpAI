from types import SimpleNamespace

from services.canonical_state_service.service import build_canonical_state


def test_canonical_state_build_includes_planner_registry_coverage_summary() -> None:
    context = SimpleNamespace(run_id="run-123")
    normalization_result = {
        "normalized_input": {
            "facility": {
                "load_schedule": {"phase_1_mw": 42.0},
                "ups": {"topology": "double-conversion"},
            }
        },
        "validation_report": {"missing_fields": []},
        "followup_questions": [],
    }
    translation_result = {
        "model_outputs": {
            "steady_state": {"p_mw": 42.0, "q_mvar": 0.0},
            "zip_model": {
                "constant_power_fraction": 0.8,
                "constant_current_fraction": 0.1,
                "constant_impedance_fraction": 0.1,
            },
            "ramping": {
                "max_ramp_up_mw_per_min": 1.0,
                "max_ramp_down_mw_per_min": 1.0,
            },
        },
        "output_parameters": [
            {
                "parameter_path": "steady_state.p_mw",
                "value": 42.0,
                "units": "MW",
                "provenance_type": "normalized_input",
                "provenance_ref": "facility.load_schedule.phase_1_mw",
                "dependency_paths": ["facility.load_schedule.phase_1_mw"],
                "source_field_paths": ["facility.load_schedule.phase_1_mw"],
                "supporting_snippet_ids": [],
                "confidence_score": 0.9,
                "confidence_tag": "HIGH",
                "confidence_factors": {},
                "planner_note": "",
                "review_note": "",
                "confidence_explanation": "",
            }
        ],
        "assumptions": [],
    }

    result = build_canonical_state(
        context=context,
        normalization_result=normalization_result,
        translation_result=translation_result,
    )

    coverage = result["canonical_state"]["planner_registry_coverage"]
    summary = result["build_summary"]

    assert coverage["total_field_count"] > 0
    assert summary["planner_registry_total_field_count"] == coverage["total_field_count"]
    assert "sections" in coverage
