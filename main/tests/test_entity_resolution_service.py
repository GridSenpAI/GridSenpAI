from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_builds_accepted_value_alternatives_and_backlog() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "doc-1",
                "field_path": "facility.generators.ratings",
                "value": 3000,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.82,
                "evidence_strength": "STRONG",
                "source_ref": ["one_line"],
                "metadata": {
                    "page_number": 12,
                    "section_label": "Generator Schedule",
                    "artifact_name": "one_line.pdf",
                    "source_method": "applicant_direct_document",
                    "specificity": "direct_field_match",
                    "unit": "kW",
                },
                "is_primary": True,
            },
            {
                "field_record_id": "vendor-1",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3125,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.78,
                "evidence_strength": "MODERATE",
                "source_ref": ["cummins datasheet"],
                "metadata": {
                    "artifact_name": "cummins_xyz.pdf",
                    "source_method": "manufacturer_model_specific_spec",
                    "specificity": "exact_model_match",
                    "unit": "kW",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)

    generator_entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")
    assert generator_entry["accepted_value"] == 3125
    assert generator_entry["alternatives"]
    assert generator_entry["why_accepted"]
    assert generator_entry["accepted_source_hierarchy"] == "manufacturer_model_specific_spec"
    assert result["backlog_count"] > 0



def test_field_resolution_escalates_material_conflicts_and_tracks_margin() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "doc-1",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3000,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.91,
                "evidence_strength": "STRONG",
                "source_ref": ["one_line"],
                "metadata": {
                    "artifact_name": "one_line.pdf",
                    "source_method": "applicant_direct_document",
                    "specificity": "direct_field_match",
                    "unit": "kW",
                },
            },
            {
                "field_record_id": "vendor-1",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3600,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.90,
                "evidence_strength": "STRONG",
                "source_ref": ["datasheet"],
                "metadata": {
                    "artifact_name": "vendor.pdf",
                    "source_method": "manufacturer_model_specific_spec",
                    "specificity": "exact_model_match",
                    "unit": "kW",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)

    generator_entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")
    assert generator_entry["accepted_status"] == "conflicting"
    assert generator_entry["conflict_materiality"] == "high"
    assert generator_entry["acceptance_margin"] > 0
    assert generator_entry["unresolved_reason"]
    assert result["high_materiality_conflict_count"] >= 1
    assert result["planner_review_queue_count"] >= 1
