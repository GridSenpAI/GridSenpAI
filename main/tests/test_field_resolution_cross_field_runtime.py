from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def test_transformer_capacity_candidate_prefers_peak_aligned_option() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "peak",
                "field_path": "peak_demand_mw",
                "value": 80,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.9,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "peak_demand_mw"},
            },
            {
                "field_record_id": "tx-count",
                "field_path": "interconnection_transformer_unit_count",
                "value": 2,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.9,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "interconnection_transformer_unit_count"},
            },
            {
                "field_record_id": "tx-small",
                "field_path": "interconnection_transformer_mva_per_unit",
                "value": 20,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.78,
                "evidence_strength": "MODERATE",
                "metadata": {
                    "field_id": "interconnection_transformer_mva_per_unit",
                    "source_method": "manufacturer_model_specific_spec",
                    "specificity": "exact_model_match",
                },
            },
            {
                "field_record_id": "tx-right",
                "field_path": "interconnection_transformer_mva_per_unit",
                "value": 50,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.74,
                "evidence_strength": "MODERATE",
                "metadata": {
                    "field_id": "interconnection_transformer_mva_per_unit",
                    "source_method": "manufacturer_family_spec",
                    "specificity": "family_match",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "interconnection_transformer_mva_per_unit")
    assert entry["accepted_value"] == 50
    assert any("capacity" in note.lower() for note in entry["candidates"][0]["consistency_notes"])


def test_interconnection_voltage_candidate_prefers_related_voltage_alignment() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "poi-known",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 138,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.88,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "point_of_interconnection_voltage_kv"},
            },
            {
                "field_record_id": "main-bus-known",
                "field_path": "main_bus_nominal_voltage_kv",
                "value": 13.8,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.86,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "main_bus_nominal_voltage_kv"},
            },
            {
                "field_record_id": "hv-right",
                "field_path": "interconnection_transformer_hv_kv",
                "value": 138,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.72,
                "evidence_strength": "MODERATE",
                "metadata": {
                    "field_id": "interconnection_transformer_hv_kv",
                    "source_method": "manufacturer_family_spec",
                    "specificity": "family_match",
                },
            },
            {
                "field_record_id": "hv-wrong",
                "field_path": "interconnection_transformer_hv_kv",
                "value": 34.5,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.80,
                "evidence_strength": "STRONG",
                "metadata": {
                    "field_id": "interconnection_transformer_hv_kv",
                    "source_method": "vendor_pdf",
                    "specificity": "category_match",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "interconnection_transformer_hv_kv")
    assert entry["accepted_value"] == 138
    assert any("voltage aligns" in note.lower() for note in entry["candidates"][0]["consistency_notes"])
