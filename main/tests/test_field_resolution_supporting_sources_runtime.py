from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_collects_supporting_sources_from_multi_source_hub() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "fr-1",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3125,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "source_ref": ["cummins_xyz.pdf"],
                "confidence_score": 0.81,
                "evidence_strength": "MODERATE",
                "metadata": {
                    "manufacturer": "Cummins",
                    "model": "XYZ",
                    "field_id": "generator_rated_kw_per_unit",
                    "source_type_detail": "manufacturer_model_specific_spec",
                },
            }
        ],
        "source_candidate_inputs": {
            "knowledge_library_sources": [
                {
                    "equipment_family": "generator",
                    "manufacturer": "Cummins",
                    "model": "XYZ",
                    "source_ref": "knowledge/generators/cummins_xyz.json",
                    "source_url": "",
                    "target_fields": ["generator_rated_kw_per_unit"],
                    "source_type": "knowledge_library_match",
                }
            ],
            "vendor_pdf_sources": [
                {
                    "equipment_family": "generator",
                    "manufacturer": "Cummins",
                    "model": "XYZ",
                    "source_ref": "vendor/cummins_xyz_datasheet.pdf",
                    "source_url": "",
                    "target_fields": ["generator_rated_kw_per_unit"],
                    "source_type": "vendor_pdf_lookup_plan",
                }
            ],
            "official_web_sources": [
                {
                    "equipment_family": "generator",
                    "manufacturer": "Cummins",
                    "model": "XYZ",
                    "source_ref": "https://www.cummins.com/generators/xyz",
                    "source_url": "https://www.cummins.com/generators/xyz",
                    "target_fields": ["generator_rated_kw_per_unit"],
                    "source_type": "official_web_lookup_plan",
                }
            ],
        },
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")

    assert entry["supporting_sources"]
    streams = {item["source_stream"] for item in entry["supporting_sources"]}
    assert streams == {"knowledge_library", "vendor_pdf", "official_web"}
    assert entry["source_stream_counts"]["vendor_pdf"] >= 1
    assert entry["source_stream_counts"]["official_web"] >= 1
