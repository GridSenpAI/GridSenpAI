from __future__ import annotations

from services.validation_service.engineering_checks import run_engineering_validation


def test_engineering_validation_detects_invalid_frequency_and_negative_load() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 55,
                "poi_voltage_kv": 138.0,
                "load_schedule": {
                    "phase_1_mw": 50.0,
                    "phase_2_mw": -10.0,
                    "phase_3_mw": 25.0,
                },
                "generators": {"present": False, "count": 0},
                "transformers": {"count": 1, "ratings_mva": [50.0]},
            }
        }
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    assert result["status"] == "FAILED"
    error_codes = {issue["code"] for issue in result["errors"]}
    assert "INVALID_FREQUENCY" in error_codes
    assert "NEGATIVE_LOAD_VALUE" in error_codes
    assert any(
        issue["code"] == "NEGATIVE_LOAD_VALUE"
        and issue["field_path"] == "facility.load_schedule.phase_2_mw"
        for issue in result["errors"]
    )


def test_engineering_validation_warns_on_generator_count_and_transformer_rating_gaps() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 60,
                "poi_voltage_kv": 138.0,
                "load_schedule": {"phase_1_mw": 25.0},
                "generators": {"present": True, "count": 0},
                "transformers": {"count": 2, "ratings_mva": []},
            }
        }
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    assert result["status"] == "REVIEW_REQUIRED"
    warning_codes = {issue["code"] for issue in result["warnings"]}
    assert "GENERATOR_PRESENT_WITHOUT_COUNT" in warning_codes
    assert "TRANSFORMERS_WITHOUT_RATINGS" in warning_codes
    assert result["review_flags"]
    assert any(flag["category"] == "ENGINEERING_REVIEW_REQUIRED" for flag in result["review_flags"])


def test_engineering_validation_detects_invalid_transformer_rating() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 60,
                "poi_voltage_kv": 138.0,
                "load_schedule": {"phase_1_mw": 40.0},
                "generators": {"present": False, "count": 0},
                "transformers": {"count": 1, "ratings_mva": [0]},
            }
        }
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    assert result["status"] == "FAILED"
    assert any(issue["code"] == "INVALID_TRANSFORMER_RATING" for issue in result["errors"])
