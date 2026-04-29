from __future__ import annotations

from shared.ledger_native_translation import build_ledger_native_translation_contract


def test_ledger_native_translation_projects_model_outputs_from_governed_parameters() -> None:
    contract = build_ledger_native_translation_contract(
        [
            {
                "parameter_path": "steady_state.p_mw",
                "value": 60,
                "units": "MW",
                "provenance_type": "field_resolution",
                "used_planner_field_ledger": True,
                "confidence_score": 0.94,
                "confidence_tag": "HIGH",
                "field_resolution_field_key": "facility.load_schedule.phase_1_mw",
            },
            {
                "parameter_path": "steady_state.q_mvar",
                "value": 6,
                "units": "MVAR",
                "provenance_type": "rule",
                "confidence_score": 0.7,
                "confidence_tag": "MODERATE",
            },
        ],
        {"steady_state": {"p_mw": 0, "q_mvar": 0}},
    )

    assert contract["ledger_native_model_outputs"]["steady_state"]["p_mw"] == 60.0
    assert contract["ledger_native_model_outputs"]["steady_state"]["q_mvar"] == 6.0
    assert contract["ledger_backed_parameter_count"] == 1
    assert contract["scenario_use_policy"] == "accepted_for_scenario_generation"


def test_ledger_native_translation_marks_blocked_parameters_for_scenario_review() -> None:
    contract = build_ledger_native_translation_contract(
        [
            {
                "parameter_path": "steady_state.p_mw",
                "value": 180,
                "units": "MW",
                "provenance_type": "field_resolution",
                "field_release_state": "BLOCKED",
                "ledger_downstream_gated": True,
                "confidence_tag": "LOW",
                "review_note": "Blocked by unresolved planner ledger conflict.",
            }
        ],
        {"steady_state": {"p_mw": 0}},
    )

    assert contract["ledger_native_model_outputs"]["steady_state"]["p_mw"] == 0
    assert contract["blocked_parameter_count"] == 1
    assert contract["projected_parameters"][0]["status"] == "BLOCKED"
    assert contract["scenario_use_policy"] == "review_required"

from shared.ledger_native_translation import build_ledger_first_translation_inputs


def test_ledger_first_translation_uses_planner_ledger_as_primary_source() -> None:
    canonical_state = {
        "planner_field_contract": {
            "planner_field_ledger": [
                {
                    "field_path": "facility.load_schedule.phase_1_mw",
                    "field_id": "accepted_peak_demand_mw",
                    "field_label": "Accepted peak demand MW",
                    "accepted_value": "60 MW",
                    "normalized_value": "60",
                    "confidence_score": 0.94,
                    "status": "ACCEPTED",
                    "source_document": "01_request.pdf",
                    "source_page": "1",
                    "source_section": "Load table",
                    "translation_use_policy": "use_for_modeled_output",
                    "scenario_use_policy": "use_for_scenario_generation",
                    "release_state": "ACCEPTED",
                },
                {
                    "field_path": "net_power_factor_at_poi",
                    "field_id": "net_power_factor_at_poi",
                    "field_label": "Power factor at POI",
                    "accepted_value": "0.95",
                    "normalized_value": "0.95",
                    "confidence_score": 0.9,
                    "status": "ACCEPTED",
                    "source_document": "01_request.pdf",
                    "source_page": "1",
                    "translation_use_policy": "use_for_modeled_output",
                    "scenario_use_policy": "use_for_scenario_generation",
                    "release_state": "ACCEPTED",
                },
                {
                    "field_path": "facility.dynamic_behavior.max_ramp_up_mw_per_min",
                    "field_id": "load_ramp_profile_summary",
                    "field_label": "Ramp up",
                    "accepted_value": "UNRESOLVED",
                    "normalized_value": "UNRESOLVED",
                    "confidence_score": 0.0,
                    "status": "BLOCKED_BY_MISSING_SOURCE",
                    "source_document": "No direct source found",
                    "translation_use_policy": "do_not_use",
                    "scenario_use_policy": "do_not_use",
                    "release_state": "BLOCKED",
                },
            ]
        }
    }

    contract = build_ledger_first_translation_inputs(canonical_state)

    assert contract["used_ledger_native_primary"] is True
    assert contract["fallback_allowed"] is False
    assert contract["model_outputs_source"] == "planner_field_ledger"
    assert contract["model_outputs"]["steady_state"]["p_mw"] == 60.0
    assert contract["model_outputs"]["steady_state"]["power_factor"] == 0.95
    assert "q_mvar" in contract["model_outputs"]["steady_state"]
    assert "ramping" not in contract["model_outputs"] or "max_ramp_up_mw_per_min" not in contract["model_outputs"].get("ramping", {})
    assert contract["fallback_rows_used"] == 0
    assert any(item["parameter_path"] == "ramping.max_ramp_up_mw_per_min" for item in contract["excluded_parameters"])
