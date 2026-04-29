from __future__ import annotations

from services.validation_service.engineering_checks import run_engineering_validation
from services.field_resolution_service.service import build_field_resolution_result


def test_engineering_validation_flags_generator_voltage_and_cooling_ramp_cross_field_gaps() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 60,
                "poi_voltage_kv": 138.0,
                "load_schedule": {"phase_1_mw": 120.0},
                "generators": {"present": True, "count": 1},
                "transformers": {"count": 1, "ratings_mva": [150.0]},
            }
        },
        "field_resolution": {
            "accepted_field_index": {
                "generator_unit_count": {"accepted_value": 1},
                "generator_rated_kw_per_unit": {"accepted_value": 80_000},
                "peak_demand_mw": {"accepted_value": 120.0},
                "redundancy_architecture": {"accepted_value": "2N"},
                "main_bus_nominal_voltage_kv": {"accepted_value": 13.8},
                "interconnection_transformer_lv_kv": {"accepted_value": 4.16},
                "generator_terminal_voltage_kv": {"accepted_value": 0.48},
                "cooling_load_share_percent_of_total": {"accepted_value": 65.0},
                "cooling_architecture_summary": {"accepted_value": ""},
                "load_ramp_profile_summary": {"accepted_value": ""},
            }
        },
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    warning_codes = {issue["code"] for issue in result["warnings"]}
    assert "GENERATOR_CAPACITY_BELOW_PEAK_DEMAND" in warning_codes
    assert "REDUNDANCY_ARCHITECTURE_UNIT_COUNT_TENSION" in warning_codes
    assert "MAIN_BUS_TRANSFORMER_LV_MISMATCH" in warning_codes
    assert "GENERATOR_TERMINAL_MAIN_BUS_MISMATCH" in warning_codes
    assert "HIGH_COOLING_SHARE_WITHOUT_ARCHITECTURE_SUMMARY" in warning_codes
    assert "LARGE_LOAD_WITHOUT_RAMP_SUMMARY" in warning_codes
    assert result["review_flags"]


def test_engineering_validation_rejects_invalid_cooling_load_share_percent() -> None:
    canonical_state = {
        "normalized_input": {
            "facility": {
                "frequency_hz": 60,
                "poi_voltage_kv": 138.0,
                "load_schedule": {"phase_1_mw": 40.0},
                "generators": {"present": False, "count": 0},
                "transformers": {"count": 1, "ratings_mva": [75.0]},
            }
        },
        "field_resolution": {
            "accepted_field_index": {
                "cooling_load_share_percent_of_total": {"accepted_value": 140.0},
            }
        },
    }

    result = run_engineering_validation(canonical_state=canonical_state)

    assert result["status"] == "FAILED"
    error_codes = {issue["code"] for issue in result["errors"]}
    assert "INVALID_COOLING_LOAD_SHARE_PERCENT" in error_codes


def test_field_resolution_demotes_generator_capacity_winner_on_cross_field_validation_warning() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "gen-kw",
                "field_path": "generator_rated_kw_per_unit",
                "value": 80000,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.94,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "generator_rated_kw_per_unit"},
            }
        ]
    }
    validation_report = {
        "errors": [],
        "warnings": [
            {
                "code": "GENERATOR_CAPACITY_BELOW_PEAK_DEMAND",
                "severity": "warning",
                "message": "Resolved generator capacity is below the resolved peak demand baseline.",
                "field_path": "field_resolution.accepted_field_index.generator_rated_kw_per_unit.accepted_value",
                "recommendation": "Confirm generator sizing.",
                "metadata": {},
            }
        ],
        "info": [],
        "review_flags": [],
    }

    result = build_field_resolution_result(canonical_state, validation_report)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")

    assert entry["accepted_status"] == "review_required"
    assert entry["planner_review_flag"] is True
    assert entry["needs_applicant_confirmation"] is True
    assert entry["candidate_summary"]["validation_impact_count"] >= 1
    assert any("Validation requires follow-up" in note for note in entry["why_accepted"])
