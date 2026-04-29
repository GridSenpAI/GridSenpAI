from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_prefers_exact_model_specific_candidate_when_document_is_weak() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "doc-weak",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3000,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.41,
                "evidence_strength": "WEAK",
                "source_ref": ["one_line"],
                "metadata": {
                    "artifact_name": "one_line.pdf",
                    "section_label": "General Notes",
                    "specificity": "context_inferred",
                    "manufacturer": "Cummins",
                },
            },
            {
                "field_record_id": "vendor-strong",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3125,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.83,
                "evidence_strength": "STRONG",
                "source_ref": ["cummins xyz datasheet"],
                "metadata": {
                    "artifact_name": "cummins_xyz.pdf",
                    "source_method": "manufacturer_model_specific_spec",
                    "specificity": "exact_model_match",
                    "manufacturer": "Cummins",
                    "model": "XYZ",
                    "field_id": "generator_rated_kw_per_unit",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")
    assert entry["accepted_value"] == 3125
    assert entry["why_accepted"]
    assert entry["candidates"][0]["source_hierarchy"] == "manufacturer_model_specific_spec"


def test_field_resolution_records_context_consistency_notes_for_family_mismatch() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "gen-mfr",
                "field_path": "generator_manufacturer",
                "value": "Cummins",
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.8,
                "evidence_strength": "STRONG",
                "metadata": {"manufacturer": "Cummins", "field_id": "generator_manufacturer"},
            },
            {
                "field_record_id": "gen-rating-1",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3000,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.74,
                "evidence_strength": "MODERATE",
                "metadata": {
                    "manufacturer": "OtherBrand",
                    "model": "ABC",
                    "field_id": "generator_rated_kw_per_unit",
                    "source_method": "manufacturer_model_specific_spec",
                },
            },
        ]
    }
    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")
    notes = entry["candidates"][0]["consistency_notes"]
    assert notes
    assert any("differs" in note.lower() for note in notes)
