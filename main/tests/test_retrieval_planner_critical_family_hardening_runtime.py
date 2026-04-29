from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result
from services.retrieval_service.domain import _build_field_support_summary


def test_field_support_summary_prefers_official_and_exact_model_signal_over_weaker_first_seen_entries() -> None:
    snippets = [
        {
            "source_ref": "weak_vendor_pointer.txt",
            "score": 0.61,
            "metadata": {
                "target_field": "facility.poi_voltage_kv",
                "source_hierarchy": "vendor_pdf",
                "source_priority": "vendor_documents",
                "specificity": "context_inferred",
                "evidence_tier": "vendor_document_pointer",
            },
        },
        {
            "source_ref": "official_poi_guide.txt",
            "score": 0.88,
            "metadata": {
                "target_field": "facility.poi_voltage_kv",
                "source_hierarchy": "official_interconnection_source",
                "source_priority": "official_interconnection",
                "specificity": "direct_field_match",
                "evidence_tier": "official_interconnection_source",
            },
        },
    ]

    summary = _build_field_support_summary(snippets=snippets, equipment_result=None)
    support = summary["facility.poi_voltage_kv"]

    assert support["best_source_hierarchy"] == "official_interconnection_source"
    assert support["best_specificity"] == "direct_field_match"
    assert support["support_strength"] == "HIGH"


def test_field_resolution_uses_field_family_policy_to_keep_applicant_answer_as_winner_for_generator_rating_basis() -> None:
    canonical_state = {
        "source_candidate_inputs": {
            "retrieval_candidates": [
                {
                    "field_path": "generator_prime_or_standby_rating_basis",
                    "value": "prime",
                    "confidence": 0.92,
                    "source_type": "vendor_document",
                    "source_ref": "general_generator_blog.txt",
                    "source_priority": "vendor_documents",
                    "source_kind": "vendor_document",
                    "document_type": "vendor_pdf_pointer",
                    "evidence_tier": "vendor_document_pointer",
                    "match_reason": "context_inferred",
                }
            ],
            "interview_candidates": [
                {
                    "field_path": "generator_prime_or_standby_rating_basis",
                    "value": "standby",
                    "question_id": "q_generator_rating_basis",
                    "source_context": "Applicant confirmed standby rating basis",
                    "confirmed_by": "applicant",
                }
            ],
            "field_support_summary": {
                "generator_prime_or_standby_rating_basis": {
                    "support_strength": "LOW",
                    "exact_model_support_count": 0,
                    "official_source_count": 0,
                    "weak_support_only": True,
                    "best_source_hierarchy": "vendor_pdf",
                    "best_specificity": "context_inferred",
                }
            },
        }
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_prime_or_standby_rating_basis")

    assert entry["accepted_value"] == "standby"
    assert entry["accepted_source_hierarchy"] == "applicant_confirmed_answer"
    assert entry["accepted_status"] == "conflicting"
    assert entry["planner_review_flag"] is True


def test_field_resolution_demotes_planner_critical_voltage_with_only_contextual_vendor_support() -> None:
    canonical_state = {
        "source_candidate_inputs": {
            "retrieval_candidates": [
                {
                    "field_path": "facility.poi_voltage_kv",
                    "value": 138,
                    "confidence": 0.94,
                    "source_type": "vendor_document",
                    "source_ref": "vendor_brochure.txt",
                    "source_priority": "vendor_documents",
                    "source_kind": "vendor_document",
                    "document_type": "vendor_pdf_pointer",
                    "evidence_tier": "vendor_document_pointer",
                    "match_reason": "context_inferred",
                }
            ],
            "field_support_summary": {
                "facility.poi_voltage_kv": {
                    "support_strength": "LOW",
                    "exact_model_support_count": 0,
                    "official_source_count": 0,
                    "weak_support_only": True,
                    "best_source_hierarchy": "vendor_pdf",
                    "best_specificity": "context_inferred",
                }
            },
        }
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "point_of_interconnection_voltage_kv")

    assert entry["accepted_value"] == 138
    assert entry["accepted_status"] == "review_required"
    assert entry["planner_review_flag"] is True
    assert entry["accepted_source_hierarchy"] == "vendor_pdf"
