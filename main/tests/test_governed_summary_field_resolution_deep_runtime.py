from shared.governed_summary import summarize_canonical_governance


def test_governed_summary_prefers_field_resolution_ledger_counts():
    canonical_state = {
        "field_records": [
            {"field_path": "legacy.a", "status": "missing", "is_primary": True},
            {"field_path": "legacy.b", "status": "conflicting", "is_primary": True},
        ],
        "field_resolution": {
            "summary": {
                "accepted_field_index_count": 3,
                "applicant_confirmation_needed_count": 2,
                "planner_review_count": 4,
                "review_required_count": 4,
                "conflicting_count": 2,
                "missing_count": 1,
            },
            "accepted_field_index": {
                "generator_unit_count": {
                    "field_id": "generator_unit_count",
                    "accepted_value": 24,
                    "accepted_status": "confirmed",
                    "confidence_band": "HIGH",
                    "planner_review_flag": False,
                    "needs_applicant_confirmation": False,
                },
                "generator_manufacturer": {
                    "field_id": "generator_manufacturer",
                    "accepted_value": "Cummins",
                    "accepted_status": "review_required",
                    "confidence_band": "MODERATE",
                    "planner_review_flag": True,
                    "needs_applicant_confirmation": True,
                },
                "generator_model": {
                    "field_id": "generator_model",
                    "accepted_value": None,
                    "accepted_status": "missing",
                    "confidence_band": "UNRESOLVED",
                    "planner_review_flag": True,
                    "needs_applicant_confirmation": True,
                },
            },
        },
        "review_flags": [{"flag": 1}],
    }
    validation_result = {"validation_report": {"missing_fields": [{"field": "x"}], "conflicts": [{"field": "y"}]}}

    summary = summarize_canonical_governance(canonical_state, validation_result)

    assert summary["planner_registry_backed"] is True
    assert summary["accepted_planner_field_count"] == 3
    assert summary["applicant_confirmation_needed_count"] == 2
    assert summary["planner_review_count"] == 4
    assert summary["missing_count"] == 1
    assert summary["conflicting_count"] == 2
    assert summary["review_required_count"] == 4
    assert summary["governed_distinction_summary"]["missing"] == 1
    assert summary["governed_distinction_summary"]["conflicting"] == 2
