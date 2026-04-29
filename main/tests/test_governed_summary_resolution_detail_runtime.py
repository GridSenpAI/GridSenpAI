from __future__ import annotations

from shared.governed_summary import summarize_canonical_governance


def test_governed_summary_surfaces_value_kind_and_attention_counts() -> None:
    canonical_state = {
        "field_resolution": {
            "accepted_field_index": {
                "generator_rated_kw_per_unit": {
                    "field_id": "generator_rated_kw_per_unit",
                    "accepted_status": "accepted",
                    "accepted_value": 3000,
                    "accepted_confidence": 0.92,
                    "accepted_value_kind": "direct_fact",
                    "planner_attention_tier": "normal",
                },
                "generator_prime_or_standby_rating_basis": {
                    "field_id": "generator_prime_or_standby_rating_basis",
                    "accepted_status": "review_required",
                    "accepted_value": "standby",
                    "accepted_confidence": 0.66,
                    "accepted_value_kind": "applicant_confirmed",
                    "planner_attention_tier": "review",
                    "needs_applicant_confirmation": True,
                    "planner_review_flag": True,
                },
            },
            "summary": {
                "accepted_field_index_count": 2,
                "applicant_confirmation_needed_count": 1,
                "planner_review_count": 1,
            },
        }
    }
    summary = summarize_canonical_governance(canonical_state, None)
    assert summary["planner_registry_backed"] is True
    assert summary["value_kind_counts"]["direct_fact"] == 1
    assert summary["value_kind_counts"]["applicant_confirmed"] == 1
    assert summary["attention_tier_counts"]["normal"] == 1
    assert summary["attention_tier_counts"]["review"] == 1
    assert summary["governed_distinction_summary"]["value_kind_counts"]["direct_fact"] == 1
