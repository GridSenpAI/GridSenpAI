from shared.governed_summary import summarize_canonical_governance


def test_governed_summary_tracks_source_stream_counts_from_packet_rows() -> None:
    canonical_state = {
        "planner_packet_field_rows": {"site_and_interconnection_context": [
            {
                "field_id": "a",
                "status": "resolved",
                "accepted_value_kind": "direct_fact",
                "planner_attention_tier": "normal",
                "decision_basis": "accepted_from_governed_adjudication",
                "source_stream_counts": {"applicant_document": 1, "vendor_pdf": 2},
            },
            {
                "field_id": "b",
                "status": "resolved",
                "accepted_value_kind": "evidence_backed_inferred",
                "planner_attention_tier": "review",
                "decision_basis": "accepted_after_conflict_review",
                "source_stream_counts": {"official_web": 1},
            },
        ]}
    }
    summary = summarize_canonical_governance(canonical_state, {})
    assert summary["source_stream_counts"]["applicant_document"] == 1
    assert summary["source_stream_counts"]["vendor_pdf"] == 2
    assert summary["source_stream_counts"]["official_web"] == 1
    assert summary["governed_distinction_summary"]["source_stream_counts"]["vendor_pdf"] == 2
