from __future__ import annotations

from services.validation_service.engineering_checks import run_engineering_validation


def test_engineering_validation_flags_invalid_zip_and_power_factor_values() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 60,
                "poi_voltage_kv": 138.0,
                "load_schedule": {"phase_1_mw": 80.0},
                "generators": {"present": False, "count": 0},
                "transformers": {"count": 1, "ratings_mva": [100.0]},
            }
        },
        "field_resolution": {
            "accepted_field_index": {
                "net_power_factor_at_poi": {"accepted_value": 1.2},
                "steady_state_zip_fraction_z": {"accepted_value": 0.20},
                "steady_state_zip_fraction_i": {"accepted_value": 0.30},
                "steady_state_zip_fraction_p": {"accepted_value": 1.10},
            }
        },
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    assert result["status"] == "FAILED"
    error_codes = {issue["code"] for issue in result["errors"]}
    assert "INVALID_NET_POWER_FACTOR_AT_POI" in error_codes
    assert "INVALID_ZIP_FRACTION_VALUE" in error_codes


def test_engineering_validation_flags_zip_sum_redundancy_and_telemetry_dependency_gaps() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 60,
                "poi_voltage_kv": 138.0,
                "load_schedule": {"phase_1_mw": 120.0},
                "generators": {"present": False, "count": 0},
                "transformers": {"count": 2, "ratings_mva": [100.0, 100.0]},
            }
        },
        "field_resolution": {
            "accepted_field_index": {
                "steady_state_zip_fraction_z": {"accepted_value": 0.20},
                "steady_state_zip_fraction_i": {"accepted_value": 0.20},
                "steady_state_zip_fraction_p": {"accepted_value": 0.20},
                "redundancy_architecture": {"accepted_value": "2N"},
                "ups_topology": {"accepted_value": "N+1"},
                "mw_mvar_telemetry_present": {"accepted_value": True},
                "telemetry_points_list_present": {"accepted_value": False},
                "voltage_frequency_telemetry_present": {"accepted_value": True},
                "protection_scheme_summary": {"accepted_value": ""},
            }
        },
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    assert result["status"] == "REVIEW_REQUIRED"
    warning_codes = {issue["code"] for issue in result["warnings"]}
    assert "ZIP_FRACTIONS_DO_NOT_SUM_TO_ONE" in warning_codes
    assert "UPS_TOPOLOGY_REDUNDANCY_MISMATCH" in warning_codes
    assert "TELEMETRY_PRESENT_WITHOUT_POINTS_LIST" in warning_codes
    assert "TELEMETRY_WITHOUT_PROTECTION_SUMMARY" in warning_codes
    assert result["review_flags"]


def test_engineering_validation_flags_generator_standby_rating_mapping_issue() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 60,
                "poi_voltage_kv": 138.0,
                "load_schedule": {"phase_1_mw": 50.0},
                "generators": {"present": True, "count": 2},
                "transformers": {"count": 1, "ratings_mva": [75.0]},
            }
        },
        "engineering_model": {
            "backup_power_system": {
                "generator_units": [
                    {
                        "count": {"value": 2},
                        "rating_mw": {"value": 3.0},
                        "standby_rating_mw": {"value": 2.5},
                    }
                ]
            }
        },
        "field_resolution": {
            "accepted_field_index": {
                "generator_prime_or_standby_rating_basis": {"accepted_value": "standby"},
            }
        },
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    assert result["status"] == "REVIEW_REQUIRED"
    assert any(issue["code"] == "GENERATOR_STANDBY_RATING_BELOW_PRIME" for issue in result["warnings"])
    assert any(flag["field_path"].startswith("engineering_model.backup_power_system.generator_units") for flag in result["review_flags"])
