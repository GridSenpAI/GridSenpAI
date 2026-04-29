from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_prefers_confirmed_interview_candidate_when_supported() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "doc-1",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3000,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.80,
                "evidence_strength": "STRONG",
                "metadata": {
                    "artifact_name": "one_line.pdf",
                    "page_number": 5,
                    "section_label": "Generator Schedule",
                    "source_method": "table_deterministic",
                    "specificity": "direct_field_match",
                    "unit": "kW",
                },
            },
            {
                "field_record_id": "int-1",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3125,
                "source_stage": "interview",
                "source_type": "interview_answer",
                "confidence_score": 0.96,
                "evidence_strength": "STRONG",
                "metadata": {
                    "source_method": "confirmed_interview",
                    "specificity": "direct_field_match",
                    "question_id": "generator_rating_confirm",
                    "source_name": "facility_intake.json",
                    "unit": "kW",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")

    assert entry["accepted_value"] == 3125
    assert entry["accepted_source_hierarchy"] == "applicant_confirmed_answer"
    assert any("Applicant-confirmed interview evidence" in reason for reason in entry["why_accepted"])
    assert entry["candidate_evidence_appendix"]


def test_field_resolution_applicant_confirmation_outranks_inferred_document() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "doc-1",
                "field_path": "generator_prime_or_standby_rating_basis",
                "value": "prime",
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.92,
                "evidence_strength": "MODERATE",
                "metadata": {
                    "source_method": "contextual_inference",
                    "specificity": "context_inferred",
                },
            },
            {
                "field_record_id": "int-1",
                "field_path": "generator_prime_or_standby_rating_basis",
                "value": "standby",
                "source_stage": "interview",
                "source_type": "interview_answer",
                "confidence_score": 0.94,
                "evidence_strength": "STRONG",
                "metadata": {
                    "source_method": "confirmed_interview",
                    "specificity": "direct_field_match",
                    "question_id": "generator_rating_basis",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_prime_or_standby_rating_basis")

    assert entry["accepted_value"] == "standby"
    assert entry["accepted_source_hierarchy"] == "applicant_confirmed_answer"
