from shared.ledger_native_translation import build_ledger_first_translation_inputs


def _row(field_path: str, value: object, *, status: str = "ACCEPTED", confidence: float = 0.92) -> dict:
    return {
        "field_id": field_path,
        "field_path": field_path,
        "field_label": field_path,
        "accepted_value": value,
        "normalized_value": value,
        "status": status,
        "confidence_score": confidence,
        "confidence_band": "HIGH" if confidence >= 0.85 else "LOW",
        "source_document": "test.pdf",
        "source_section": "known-answer fixture",
        "release_state": "ACCEPTED",
        "translation_use_policy": "use_for_modeling",
        "scenario_use_policy": "use_for_scenarios",
        "planner_packet_use_policy": "show_as_accepted",
        "export_readiness_tier": "ready",
    }


def test_ledger_native_translation_maps_accepted_peak_demand_to_p_mw():
    result = build_ledger_first_translation_inputs({
        "planner_field_contract": {
            "planner_field_ledger": [
                _row("peak_demand_mw", 180.0),
            ]
        }
    })

    assert result["used_ledger_native_primary"] is True
    assert result["model_outputs"]["steady_state"]["p_mw"] == 180.0
    parameter = next(item for item in result["output_parameters"] if item["parameter_path"] == "steady_state.p_mw")
    assert parameter["value"] == 180.0
    assert parameter["ledger_native_status_class"] == "accepted"


def test_ledger_native_translation_blocks_unsafe_zip_fractions():
    result = build_ledger_first_translation_inputs({
        "planner_field_contract": {
            "planner_field_ledger": [
                _row("steady_state_zip_fraction_p", 2.0),
                _row("steady_state_zip_fraction_i", 2.0),
                _row("steady_state_zip_fraction_z", 2.0),
            ]
        }
    })

    safety = result["translation_model_safety"]
    assert safety["zip_model_status"] == "BLOCKED_UNSAFE_ZIP_FRACTIONS"
    assert safety["zip_model_safe"] is False
    assert "zip_model" not in result["model_outputs"] or result["model_outputs"].get("zip_model") == {}
    zip_parameters = [item for item in result["output_parameters"] if item["parameter_path"].startswith("zip_model.")]
    assert len(zip_parameters) == 3
    assert all(item["value"] is None for item in zip_parameters)
    assert all(item["field_release_state"] == "BLOCKED" for item in zip_parameters)
