from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_summary_uses_unique_field_count_and_governance_posture() -> None:
    canonical_state = {
        "field_records": [],
        "source_candidate_inputs": {
            "extraction_candidates": [
                {
                    "field_path": "facility.generators.count",
                    "value": 10,
                    "confidence": 0.74,
                    "source_method": "table_deterministic",
                    "source_anchor_ids": ["anchor-1"],
                    "source_ref": ["one_line"],
                    "source_artifact_id": "one_line.pdf",
                    "page_number": 2,
                    "worker_name": "table_worker",
                    "region_type": "table",
                    "metadata": {"specificity": "direct_field_match"},
                }
            ],
            "retrieval_candidates": [
                {
                    "field_path": "facility.poi_voltage_kv",
                    "value": 138,
                    "confidence": 0.93,
                    "source_type": "official_interconnection_source",
                    "source_ref": "utility_study.pdf:p4",
                    "confidence_reason": "Utility interconnection study direct field match",
                    "lookup_strategy": "official_interconnection_then_vendor",
                },
                {
                    "field_path": "facility.generators.count",
                    "value": 12,
                    "confidence": 0.72,
                    "manufacturer": "Cummins",
                    "model": "XYZ",
                    "equipment_family": "generator",
                    "source_type": "manufacturer_model_specific_spec",
                    "source_ref": "vendor_spec.pdf:p8",
                    "confidence_reason": "Model family spec",
                    "lookup_strategy": "vendor_pdf_then_official_web",
                },
            ],
            "interview_candidates": [],
        },
    }

    result = build_field_resolution_result(canonical_state)
    summary = result["summary"]
    posture = result["governance_posture_summary"]

    assert summary["accepted_field_index_count"] == 2
    assert summary["accepted_field_lookup_key_count"] > summary["accepted_field_index_count"]
    assert summary["blocked_field_count"] == posture["blocked_field_count"]
    assert summary["meaningful_alternative_field_count"] >= 1
    assert posture["release_state_counts"]["BLOCKED"] >= 1
    assert posture["release_state_counts"]["READY"] >= 1
    assert posture["accepted_source_hierarchy_counts"]["official_interconnection_source"] == 1
    assert posture["policy_outcome_counts"]["blocked_conflict"] >= 1
