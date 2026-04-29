from __future__ import annotations

from shared.governed_summary import summarize_canonical_governance


def test_governed_summary_prefers_packet_rows_for_trust_counts() -> None:
    canonical_state = {
        "planner_packet_field_rows": {
            "site_and_interconnection_context": [
                {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "status": "resolved",
                    "accepted_value_kind": "direct_document_fact",
                    "planner_attention_tier": "critical_resolved",
                    "decision_basis": "accepted_from_governed_adjudication",
                    "contradiction_summary": "115 kV alternative rejected in favor of official 138 kV evidence",
                    "source_anchors": ["poi_one_line.pdf:p2"],
                    "alternatives": [{"value": 115}],
                }
            ]
        },
        "field_records": [],
        "field_resolution": {"accepted_field_index": {}, "summary": {}},
    }

    summary = summarize_canonical_governance(canonical_state, None)

    assert summary["planner_packet_row_count"] == 1
    assert summary["contradiction_count"] == 1
    assert summary["anchored_field_count"] == 1
    assert summary["runner_up_field_count"] == 1
    assert summary["value_kind_counts"]["direct_document_fact"] == 1
    assert summary["attention_tier_counts"]["critical_resolved"] == 1
    assert summary["decision_basis_counts"]["accepted_from_governed_adjudication"] == 1
