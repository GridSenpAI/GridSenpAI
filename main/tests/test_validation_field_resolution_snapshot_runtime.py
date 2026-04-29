from pathlib import Path
from types import SimpleNamespace

from services.validation_service.service import run_service


def test_validation_persists_field_resolution_snapshots(tmp_path: Path, monkeypatch) -> None:
    context = SimpleNamespace(run_id="run-validation-resolution", run_dir=tmp_path)
    canonical_state_result = {
        "run_id": "run-validation-resolution",
        "canonical_state": {
            "run_id": "run-validation-resolution",
            "field_records": [],
            "conflict_records": [],
            "review_flags": [],
            "stage_status": {"normalization": "NORMALIZED"},
        },
    }

    monkeypatch.setattr(
        "services.validation_service.service.run_engineering_validation",
        lambda canonical_state: {"status": "COMPLETED", "issues": [], "validated_model": {}, "summary": {}},
    )
    monkeypatch.setattr(
        "services.validation_service.service.run_calibration_comparison_service",
        lambda context, canonical_state, calibration_datasets, engineering_payload=None: {"status": "SKIPPED", "comparison_run_id": "cmp-1", "compared_at": "now", "summary": {}},
    )

    result = run_service(context, canonical_state_result=canonical_state_result)
    updated = result["canonical_state"]
    summary = result["validation_report"]["summary"]

    assert isinstance(updated.get("accepted_planner_field_index"), dict)
    assert isinstance(updated.get("planner_packet_field_rows"), dict) and updated["planner_packet_field_rows"]
    assert summary["field_resolution_accepted_field_count"] == 0
    assert summary["field_resolution_backlog_count"] >= 1
    assert isinstance(summary["field_resolution_top_backlog_field_ids"], list)
