from shared.governed_summary import summarize_canonical_governance


def test_governed_summary_surfaces_field_resolution_counts() -> None:
    canonical_state = {
        "field_records": [],
        "field_resolution": {
            "summary": {
                "accepted_field_index_count": 12,
                "applicant_confirmation_needed_count": 3,
                "planner_review_count": 2,
                "review_required_count": 4,
                "conflicting_count": 1,
                "missing_count": 5,
            }
        },
        "review_flags": [],
    }

    summary = summarize_canonical_governance(canonical_state, {"validation_report": {}})

    assert summary["accepted_planner_field_count"] == 12
    assert summary["applicant_confirmation_needed_count"] == 3
    assert summary["planner_review_count"] == 2
    assert summary["review_required_count"] == 4
    assert summary["conflicting_count"] == 1
    assert summary["missing_count"] == 5
