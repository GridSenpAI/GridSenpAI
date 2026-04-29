from shared.planner_registry import summarize_field_resolution_governance


def test_summarize_field_resolution_governance_uses_packet_rows_and_backlog():
    canonical_state = {
        "field_resolution": {
            "summary": {
                "accepted_field_index_count": 2,
                "applicant_confirmation_needed_count": 1,
                "planner_review_count": 2,
                "review_required_count": 1,
                "conflicting_count": 0,
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
                    "packet_section": "generation",
                    "packet_section_label": "Generation",
                },
                "generator_model": {
                    "field_id": "generator_model",
                    "accepted_value": None,
                    "accepted_status": "missing",
                    "confidence_band": "UNRESOLVED",
                    "planner_review_flag": True,
                    "needs_applicant_confirmation": True,
                    "packet_section": "generation",
                    "packet_section_label": "Generation",
                },
            },
        }
    }
    summary = summarize_field_resolution_governance(canonical_state)
    assert summary["planner_registry_backed"] is True
    assert summary["accepted_planner_field_count"] == 2
    assert summary["applicant_confirmation_needed_count"] == 1
    assert summary["planner_review_count"] == 2
    assert isinstance(summary["sections"], list)
    assert "top_backlog_field_ids" in summary
