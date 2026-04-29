from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result
from services.interview_service.service import _build_questions_from_registry_resolution_backlog


def test_field_resolution_holds_planner_critical_field_for_review_when_runner_up_value_has_broader_cross_source_support() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "vendor-exact",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3125,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.84,
                "evidence_strength": "STRONG",
                "source_ref": ["cummins_qsk60_datasheet.pdf"],
                "metadata": {
                    "source_method": "manufacturer_model_specific_spec",
                    "specificity": "exact_model_match",
                    "manufacturer": "Cummins",
                    "model": "QSK60",
                    "field_id": "generator_rated_kw_per_unit",
                },
            },
            {
                "field_record_id": "doc-direct",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3000,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.81,
                "evidence_strength": "STRONG",
                "source_ref": ["one_line_schedule.pdf"],
                "metadata": {
                    "field_id": "generator_rated_kw_per_unit",
                    "source_method": "table_extract",
                },
            },
            {
                "field_record_id": "doc-normalized",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3000,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.78,
                "evidence_strength": "MODERATE",
                "source_ref": ["normalized_generator_schedule"],
                "metadata": {
                    "field_id": "generator_rated_kw_per_unit",
                    "source_method": "normalized_schedule_alignment",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")

    assert entry["accepted_value"] == 3000
    assert entry["accepted_status"] == "conflicting"
    assert entry["needs_applicant_confirmation"] is True
    assert entry["dominance_profile"]["winner_group_independent_source_count"] >= 2
    assert entry["candidate_summary"]["runner_up_group_independent_source_count"] == 1
    assert any("clustered across" in reason.lower() for reason in entry["why_accepted"])


def test_interview_backlog_reason_includes_dominance_posture_for_narrow_or_single_source_winner() -> None:
    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "backlog": [
                    {
                        "field_id": "generator_rated_kw_per_unit",
                        "field_path": "generator_rated_kw_per_unit",
                        "label": "Generator rated kW per unit",
                        "accepted_status": "review_required",
                        "status": "review_required",
                        "accepted_value": 3125,
                        "alternatives": [{"value": 3000}],
                        "why_accepted": ["Selected candidate had exact model match evidence."],
                        "dominance_profile": {
                            "dominance_level": "single_source",
                            "winner_group_independent_source_count": 1,
                        },
                        "resolution_priority": 1,
                        "requiredness": "required",
                        "planner_critical": True,
                    }
                ]
            }
        }
    }

    questions = _build_questions_from_registry_resolution_backlog(canonical_state_result, set())
    assert questions
    reason = questions[0]["reason"].lower()
    assert "dominance posture is single source" in reason
    assert "1 independent source trace" in reason
