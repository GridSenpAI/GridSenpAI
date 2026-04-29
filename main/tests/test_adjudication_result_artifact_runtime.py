from __future__ import annotations

from shared.adjudication_result import build_adjudication_result_from_canonical


def test_adjudication_result_artifact_surfaces_required_failure_status() -> None:
    payload = build_adjudication_result_from_canonical(
        run_id="run_test",
        canonical_state_result={
            "canonical_state": {
                "field_resolution": {
                    "adjudication_status": "ADJUDICATION_REQUIRED_BUT_FAILED",
                    "summary": {"planner_review_count": 2},
                    "adjudication_packet_plan": {
                        "status": "ADJUDICATION_PACKETS_READY",
                        "target_count": 2,
                        "packet_count": 1,
                    },
                    "adjudication_support": {
                        "completed_packet_count": 0,
                        "blocked_packet_count": 0,
                        "error_packet_count": 1,
                        "packet_results": [{"status": "ERROR"}],
                    },
                }
            }
        },
    )

    assert payload["status"] == "ADJUDICATION_REQUIRED_BUT_FAILED"
    assert payload["required"] is True
    assert payload["target_count"] == 2
    assert payload["packet_count"] == 1
    assert payload["error_packet_count"] == 1
    assert payload["planner_critical_failed"] is True
    assert payload["release_impact"] == "manual_review_required"
    assert payload["packet_result_statuses"] == ["ERROR"]


def test_adjudication_result_artifact_marks_clean_skip_without_blocking_export() -> None:
    payload = build_adjudication_result_from_canonical(
        run_id="run_test",
        canonical_state_result={
            "canonical_state": {
                "field_resolution": {
                    "adjudication_status": "ADJUDICATION_SKIPPED_NO_CONFLICTS",
                    "summary": {"planner_review_count": 0},
                    "adjudication_packet_plan": {
                        "status": "ADJUDICATION_SKIPPED_NO_CONFLICTS",
                        "target_count": 0,
                        "packet_count": 0,
                    },
                }
            }
        },
    )

    assert payload["status"] == "ADJUDICATION_SKIPPED_NO_CONFLICTS"
    assert payload["required"] is False
    assert payload["planner_critical_failed"] is False
    assert payload["release_impact"] == "no_global_export_block"
