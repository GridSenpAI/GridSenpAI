from services.field_resolution_service.service import build_field_resolution_result


def test_vendor_pdf_exact_model_beats_official_web_generic_for_transformer_capacity():
    state = {
        "field_records": [
            {
                "field_record_id": "a",
                "field_path": "facility.transformers.ratings_mva",
                "value": 50.0,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "source_ref": ["vendor_pdf"],
                "confidence_score": 0.82,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "interconnection_transformer_mva_per_unit", "source_type_detail": "vendor_pdf", "manufacturer": "Acme", "model": "TX-50"},
            },
            {
                "field_record_id": "b",
                "field_path": "facility.transformers.ratings_mva",
                "value": 40.0,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "source_ref": ["official_web"],
                "confidence_score": 0.82,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "interconnection_transformer_mva_per_unit", "source_type_detail": "official_web", "source_method": "web", "lookup_strategy": "official_web"},
            },
        ]
    }
    result = build_field_resolution_result(state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "interconnection_transformer_mva_per_unit")
    assert entry["accepted_value"] == 50.0
