from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_marks_review_required_when_applicant_conflicts_with_stronger_document() -> None:
    canonical_state = {
        "field_records": [],
        "source_candidate_inputs": {
            "extraction_candidates": [
                {
                    "field_path": "generator_rated_kw_per_unit",
                    "value": 3000,
                    "confidence": 0.92,
                    "unit": "kW",
                    "source_method": "table_deterministic",
                    "source_ref": ["one_line.pdf"],
                    "source_artifact_id": "one_line.pdf",
                    "page_number": 12,
                    "metadata": {"specificity": "direct_field_match"},
                }
            ],
            "retrieval_candidates": [],
            "interview_candidates": [
                {
                    "field_path": "generator_rated_kw_per_unit",
                    "value": 3125,
                    "question_id": "q_generator_rating",
                    "source_context": "Applicant confirmed standby rating",
                    "confirmed_by": "applicant",
                }
            ],
        },
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")

    assert entry["accepted_value"] in {3000, 3125}
    assert entry["accepted_status"] == "conflicting"
    assert entry["planner_review_flag"] is True
    assert entry["needs_applicant_confirmation"] is True
    assert entry["applicant_answer_state"] in {"applicant_conflicts_with_winner", "applicant_override_selected"}
    assert entry["contradiction_summary"]
    assert entry["decision_basis"] == "accepted_with_applicant_contradiction"
    assert entry["alternatives"]
    assert entry["alternatives"][0]["not_accepted_reason"]


class _ResolutionContext:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


def test_field_resolution_persists_adjudication_support_notes_on_ledger_entries(monkeypatch) -> None:
    canonical_state = {
        "field_records": [],
        "source_candidate_inputs": {
            "retrieval_candidates": [
                {
                    "field_path": "generator_rated_kw_per_unit",
                    "value": 3125,
                    "confidence": 0.91,
                    "source_type": "vendor_document",
                    "source_ref": ["cummins_xyz.pdf"],
                    "metadata": {
                        "source_lookup_strategy": "manufacturer_model_specific_spec",
                        "source_priority": "manufacturer_model_specific_spec",
                        "specificity": "exact_model_match",
                    },
                }
            ],
            "extraction_candidates": [
                {
                    "field_path": "generator_rated_kw_per_unit",
                    "value": 3000,
                    "confidence": 0.88,
                    "source_ref": ["one_line.pdf"],
                    "metadata": {"specificity": "direct_field_match"},
                }
            ],
            "interview_candidates": [
                {
                    "field_path": "generator_rated_kw_per_unit",
                    "value": 3000,
                    "question_id": "q_generator_rating",
                    "source_context": "Applicant stated prime rating",
                    "confirmed_by": "applicant",
                }
            ],
        },
    }

    def _fake_run_agent(*, context, request):
        return {
            "status": "COMPLETED",
            "structured_output": {
                "adjudication_summary": "conflict remains",
                "recommended_interview_targets": ["facility.generators.rated_kw_per_unit"],
                "priority_conflicts": [],
                "priority_planner_review_fields": [],
                "ask_applicant_recommendation": True,
                "downgrade_recommendation": True,
                "per_field_adjudication": [
                    {
                        "field_id": "generator_rated_kw_per_unit",
                        "field_path": "facility.generators.ratings",
                        "stronger_candidate_reasoning": "Generator rated kW per unit accepted 3125 because manufacturer_model_specific_spec ranked strongest.",
                        "runner_up_summary": "Runner-up candidate 3000 was retained for planner visibility (one_line.pdf:p12).",
                        "hidden_conflict_flags": ["Prime versus standby rating conflict remains."],
                        "ask_applicant_recommendation": True,
                        "downgrade_recommendation": True,
                        "evidence_route_rationale": "Accepted search path relied on manufacturer model specific spec evidence with exact model match support instead of the runner-up route behind 3000.",
                        "source_quality_comparison": "Accepted candidate had a stronger source-quality tier (manufacturer model specific spec) than the runner-up (applicant direct document).",
                        "specificity_comparison": "Accepted candidate had a stronger specificity tier (exact model match) than the runner-up (direct field match).",
                        "why_search_path_was_trusted": "Accepted search path relied on manufacturer model specific spec evidence with exact model match support instead of the runner-up route behind 3000. Accepted candidate had a stronger source-quality tier (manufacturer model specific spec) than the runner-up (applicant direct document). Accepted candidate had a stronger specificity tier (exact model match) than the runner-up (direct field match).",
                    }
                ],
            },
        }

    monkeypatch.setattr("services.field_resolution_service.service.run_agent", _fake_run_agent)

    result = build_field_resolution_result(canonical_state, context=_ResolutionContext("field-resolution-adjudication"))
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")

    assert entry["stronger_candidate_reasoning"]
    assert entry["runner_up_summary"]
    assert entry["hidden_conflict_flags"]
    assert entry["ask_applicant_recommendation"] is True
    assert entry["downgrade_recommendation"] is True
    assert entry["evidence_route_rationale"]
    assert entry["source_quality_comparison"]
    assert entry["specificity_comparison"]
    assert entry["why_search_path_was_trusted"]
    assert any("planner visibility" in note for note in entry["adjudication_notes"])


def test_field_resolution_attaches_first_class_evidence_route_record_to_ledger(monkeypatch) -> None:
    canonical_state = {
        "field_records": [],
        "source_candidate_inputs": {
            "retrieval_candidates": [
                {
                    "field_path": "generator_rated_kw_per_unit",
                    "value": 3125,
                    "confidence": 0.91,
                    "source_type": "vendor_document",
                    "source_ref": ["cummins_xyz.pdf"],
                    "source_priority": "manufacturer_model_specific_spec",
                    "source_kind": "vendor_document",
                    "document_type": "official_vendor_document",
                    "evidence_tier": "official_vendor_document",
                    "match_reason": "exact_model_match",
                }
            ],
            "extraction_candidates": [
                {
                    "field_path": "generator_rated_kw_per_unit",
                    "value": 3000,
                    "confidence": 0.88,
                    "source_ref": ["one_line.pdf"],
                    "metadata": {"specificity": "direct_field_match"},
                }
            ],
            "interview_candidates": [],
            "field_support_summary": {
                "generator_rated_kw_per_unit": {
                    "support_strength": "HIGH",
                    "best_source_hierarchy": "manufacturer_model_specific_spec",
                    "best_specificity": "exact_model_match",
                    "exact_model_support_count": 1,
                    "official_source_count": 1,
                }
            },
            "evidence_route_records": [
                {
                    "field_path": "facility.generators.ratings",
                    "route_status": "supported",
                    "query_sources": ["missing_field", "evidence_resolution_agent"],
                    "preferred_corpora": ["vendor_specs", "interconnection_guidance"],
                    "best_source_hierarchy": "manufacturer_model_specific_spec",
                    "best_specificity": "exact_model_match",
                    "support_strength": "HIGH",
                    "why_route_was_selected": "Route favored manufacturer_model_specific_spec evidence with exact_model_match specificity support.",
                }
            ],
        },
    }

    def _fake_run_agent(*, context, request):
        return {
            "status": "COMPLETED",
            "structured_output": {
                "adjudication_summary": "conflict remains",
                "recommended_interview_targets": [],
                "priority_conflicts": [],
                "priority_planner_review_fields": [],
                "ask_applicant_recommendation": False,
                "downgrade_recommendation": False,
                "per_field_adjudication": [
                    {
                        "field_id": "generator_rated_kw_per_unit",
                        "field_path": "facility.generators.ratings",
                        "stronger_candidate_reasoning": "Generator rated kW per unit accepted 3125 because manufacturer_model_specific_spec ranked strongest after a supported retrieval route.",
                        "runner_up_summary": "Runner-up candidate 3000 was retained for planner visibility.",
                        "hidden_conflict_flags": [],
                        "ask_applicant_recommendation": False,
                        "downgrade_recommendation": False,
                        "evidence_route_rationale": "Accepted search path relied on manufacturer model specific spec evidence with exact model match support via missing_field, evidence_resolution_agent across preferred corpora vendor_specs, interconnection_guidance instead of the runner-up route behind 3000.",
                        "source_quality_comparison": "Accepted candidate had a stronger source-quality tier (manufacturer model specific spec) than the runner-up (unspecified).",
                        "specificity_comparison": "Accepted candidate had a stronger specificity tier (exact model match) than the runner-up (unspecified).",
                        "why_search_path_was_trusted": "Route favored manufacturer model specific spec evidence with exact model match specificity support.",
                    }
                ],
            },
        }

    monkeypatch.setattr("services.field_resolution_service.service.run_agent", _fake_run_agent)
    result = build_field_resolution_result(canonical_state, context=_ResolutionContext("field-resolution-route-record"))
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")

    assert entry["evidence_route_record"]["route_status"] == "supported"
    assert entry["evidence_route_record"]["best_source_hierarchy"] == "manufacturer_model_specific_spec"
    assert "evidence_resolution_agent" in entry["evidence_route_record"]["query_sources"]
    assert entry["evidence_route_rationale"]
