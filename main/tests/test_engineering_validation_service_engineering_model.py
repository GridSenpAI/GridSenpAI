from __future__ import annotations

from services.validation_service.engineering_checks import run_engineering_validation


def test_engineering_validation_prefers_engineering_model_frequency_and_poi_voltage() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 55,
                "poi_voltage_kv": -138.0,
                "load_schedule": {"phase_1_mw": 25.0},
                "generators": {"present": False, "count": 0},
                "transformers": {"count": 1, "ratings_mva": [50.0]},
            }
        },
        "engineering_model": {
            "project_context": {"frequency_hz": {"value": 60}},
            "interconnection_context": {
                "point_of_interconnection": {"poi_voltage_kv": {"value": 138.0}}
            },
            "load_system": {
                "load_blocks": [
                    {"name": "phase_1_mw", "connected_load_mw": {"value": 25.0}},
                ]
            },
            "facility_electrical_system": {
                "transformers": [
                    {
                        "primary_voltage_kv": {"value": 138.0},
                        "secondary_voltage_kv": {"value": 34.5},
                        "rating_mva": {"value": 50.0},
                    }
                ]
            },
        },
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    assert result["status"] == "PASSED"
    error_codes = {issue["code"] for issue in result["errors"]}
    assert "INVALID_FREQUENCY" not in error_codes
    assert "NONPOSITIVE_POI_VOLTAGE" not in error_codes


def test_engineering_validation_prefers_engineering_model_transformer_values() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 60,
                "poi_voltage_kv": 138.0,
                "load_schedule": {"phase_1_mw": 20.0},
                "generators": {"present": False, "count": 0},
                "transformers": {"count": 1, "ratings_mva": [0]},
            }
        },
        "engineering_model": {
            "project_context": {"frequency_hz": {"value": 60}},
            "interconnection_context": {
                "point_of_interconnection": {"poi_voltage_kv": {"value": 138.0}}
            },
            "load_system": {
                "load_blocks": [
                    {"name": "phase_1_mw", "connected_load_mw": {"value": 20.0}},
                ]
            },
            "facility_electrical_system": {
                "transformers": [
                    {
                        "primary_voltage_kv": {"value": 138.0},
                        "secondary_voltage_kv": {"value": 34.5},
                        "rating_mva": {"value": 50.0},
                    }
                ]
            },
        },
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    assert result["status"] == "PASSED"
    assert all(issue["code"] != "INVALID_TRANSFORMER_RATING" for issue in result["errors"])
    assert any(issue["code"] == "ENGINEERING_VALIDATION_EXECUTED" for issue in result["info"])
