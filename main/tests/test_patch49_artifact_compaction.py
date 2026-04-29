from __future__ import annotations

from app.orchestration.run_pipeline import _compact_large_artifact_payload


def test_compacts_large_repeated_evidence_lists_without_losing_count_marker() -> None:
    payload = {
        "planner_field_ledger": [
            {
                "field_path": f"field_{index}",
                "candidates": [{"value": value, "evidence_snippet": "x" * 2000} for value in range(40)],
            }
            for index in range(2)
        ]
    }
    compacted = _compact_large_artifact_payload(payload)
    first_candidates = compacted["planner_field_ledger"][0]["candidates"]
    assert len(first_candidates) == 26
    assert first_candidates[-1]["_truncated"] is True
    assert first_candidates[-1]["original_count"] == 40
    assert len(first_candidates[0]["evidence_snippet"]) < 900


def test_deep_lists_are_capped_to_prevent_validation_snapshot_explosion() -> None:
    payload = {"a": {"b": {"c": {"d": {"e": {"f": list(range(500))}}}}}}
    compacted = _compact_large_artifact_payload(payload)
    retained = compacted["a"]["b"]["c"]["d"]["e"]["f"]
    assert len(retained) == 301
    assert retained[-1]["_truncated"] is True
