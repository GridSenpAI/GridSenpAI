from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_uses_direct_source_candidate_inputs_without_field_records() -> None:
    canonical_state = {
        "field_records": [],
        "source_candidate_inputs": {
            "extraction_candidates": [
                {
                    "field_path": "generator_rated_kw_per_unit",
                    "value": 3000,
                    "confidence": 0.82,
                    "unit": "kW",
                    "source_method": "table_deterministic",
                    "source_anchor_ids": ["anchor-1"],
                    "source_ref": ["one_line"],
                    "source_artifact_id": "one_line.pdf",
                    "page_number": 12,
                    "worker_name": "table_worker",
                    "region_type": "table",
                    "metadata": {"specificity": "direct_field_match"},
                }
            ],
            "retrieval_candidates": [
                {
                    "field_path": "generator_rated_kw_per_unit",
                    "value": 3125,
                    "confidence": 0.76,
                    "manufacturer": "Cummins",
                    "model": "XYZ",
                    "equipment_family": "generator",
                    "source_type": "manufacturer_model_specific_spec",
                    "source_ref": "cummins_xyz.pdf",
                    "confidence_reason": "Exact model datasheet match",
                    "lookup_strategy": "vendor_pdf_then_official_web",
                }
            ],
            "interview_candidates": [],
        },
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")

    assert entry["accepted_value"] in {3000, 3125}
    assert entry["candidates"]
    assert {item["source_stage"] for item in entry["candidates"]} == {"extraction", "retrieval"}
    assert entry["alternatives"]
    assert entry["source_anchors"]


def test_field_resolution_uses_direct_interview_source_candidate_inputs() -> None:
    canonical_state = {
        "field_records": [],
        "source_candidate_inputs": {
            "extraction_candidates": [],
            "retrieval_candidates": [],
            "interview_candidates": [
                {
                    "field_path": "generator_model",
                    "value": "XYZ-9000",
                    "question_id": "q_gen_model",
                    "source_context": "Applicant confirmed installed generator model",
                    "confirmed_by": "applicant",
                }
            ],
        },
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_model")

    assert entry["accepted_value"] == "XYZ-9000"
    assert entry["accepted_source_hierarchy"] == "applicant_confirmed_answer"
    assert any("Applicant-confirmed" in reason for reason in entry["why_accepted"])
