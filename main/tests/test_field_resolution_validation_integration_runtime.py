from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_demotes_resolved_voltage_winner_when_validation_error_matches_field() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "poi-good",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 138,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.92,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "point_of_interconnection_voltage_kv"},
            }
        ]
    }
    validation_report = {
        "errors": [
            {
                "code": "POI_TRANSFORMER_VOLTAGE_MISMATCH",
                "severity": "error",
                "message": "POI voltage conflicts with transformer HV voltage.",
                "field_path": "point_of_interconnection_voltage_kv",
                "recommendation": "Confirm POI and transformer high-side voltage alignment.",
                "metadata": {},
            }
        ],
        "warnings": [],
        "info": [],
        "review_flags": [],
    }

    result = build_field_resolution_result(canonical_state, validation_report)
    entry = next(item for item in result["ledger"] if item["field_id"] == "point_of_interconnection_voltage_kv")

    assert entry["accepted_value"] == 138
    assert entry["accepted_status"] == "conflicting"
    assert entry["planner_review_flag"] is True
    assert entry["needs_applicant_confirmation"] is True
    assert entry["accepted_confidence"] is not None and entry["accepted_confidence"] <= 0.59
    assert entry["candidate_summary"]["validation_error_count"] >= 1
    assert any("Validation flagged this field" in note for note in entry["why_accepted"])
    assert entry["unresolved_reason"]


def test_field_resolution_demotes_high_confidence_zip_fraction_on_validation_warning() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "zip-p",
                "field_path": "steady_state_zip_fraction_p",
                "value": 0.9,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.91,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "steady_state_zip_fraction_p"},
            }
        ]
    }
    validation_report = {
        "errors": [],
        "warnings": [
            {
                "code": "ZIP_FRACTIONS_DO_NOT_SUM_TO_ONE",
                "severity": "warning",
                "message": "ZIP fractions do not sum to one.",
                "field_path": "steady_state_zip_fraction_p",
                "recommendation": "Confirm ZIP composition before export.",
                "metadata": {},
            }
        ],
        "info": [],
        "review_flags": [],
    }

    result = build_field_resolution_result(canonical_state, validation_report)
    entry = next(item for item in result["ledger"] if item["field_id"] == "steady_state_zip_fraction_p")

    assert entry["accepted_status"] == "review_required"
    assert entry["planner_review_flag"] is True
    assert entry["accepted_confidence"] is not None and entry["accepted_confidence"] <= 0.79
    assert entry["confidence_band"] in {"MODERATE", "LOW"}
    assert entry["candidate_summary"]["validation_impact_count"] >= 1
