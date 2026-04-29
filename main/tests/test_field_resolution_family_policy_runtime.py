from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def _entry(result: dict, field_id: str) -> dict:
    return next(item for item in result["ledger"] if item["field_id"] == field_id)


def test_interconnection_voltage_prefers_official_source_over_vendor_equipment_source() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "poi-official",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 138,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.72,
                "evidence_strength": "STRONG",
                "source_ref": ["ercot planning guide"],
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "source_method": "official_interconnection_source",
                    "artifact_name": "ercot_guide.pdf",
                },
            },
            {
                "field_record_id": "poi-vendor",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 34.5,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.86,
                "evidence_strength": "STRONG",
                "source_ref": ["vendor brochure"],
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "source_method": "manufacturer_model_specific_spec",
                    "artifact_name": "vendor.pdf",
                    "manufacturer": "OEM",
                    "model": "ABC",
                    "specificity": "exact_model_match",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = _entry(result, "point_of_interconnection_voltage_kv")
    assert entry["accepted_value"] == 138
    assert any("official interconnection" in reason.lower() for reason in entry["why_accepted"])


def test_ups_runtime_prefers_exact_model_specific_evidence() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "ups-runtime-doc",
                "field_path": "ups_battery_runtime_minutes",
                "value": 5,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.74,
                "evidence_strength": "MODERATE",
                "metadata": {"field_id": "ups_battery_runtime_minutes"},
            },
            {
                "field_record_id": "ups-runtime-model",
                "field_path": "ups_battery_runtime_minutes",
                "value": 15,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.72,
                "evidence_strength": "STRONG",
                "metadata": {
                    "field_id": "ups_battery_runtime_minutes",
                    "source_method": "manufacturer_model_specific_spec",
                    "manufacturer": "Schneider",
                    "model": "GalaxyVX",
                    "specificity": "exact_model_match",
                },
            },
        ]
    }
    result = build_field_resolution_result(canonical_state)
    entry = _entry(result, "ups_battery_runtime_minutes")
    assert entry["accepted_value"] == 15
    assert entry["accepted_source_hierarchy"] == "manufacturer_model_specific_spec"


def test_generator_rating_basis_prefers_applicant_confirmation_over_secondary_web() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "gen-basis-web",
                "field_path": "generator_prime_or_standby_rating_basis",
                "value": "prime",
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.79,
                "evidence_strength": "MODERATE",
                "metadata": {
                    "field_id": "generator_prime_or_standby_rating_basis",
                    "source_method": "secondary_web",
                },
            },
            {
                "field_record_id": "gen-basis-interview",
                "field_path": "generator_prime_or_standby_rating_basis",
                "value": "standby",
                "source_stage": "interview",
                "source_type": "human_input",
                "confidence_score": 1.0,
                "evidence_strength": "STRONG",
                "metadata": {
                    "field_id": "generator_prime_or_standby_rating_basis",
                    "confirmed_by": "applicant",
                },
            },
        ]
    }
    result = build_field_resolution_result(canonical_state)
    entry = _entry(result, "generator_prime_or_standby_rating_basis")
    assert entry["accepted_value"] == "standby"
    assert entry["applicant_answer_state"] in {"applicant_confirmed_winner", "applicant_override_selected"}
