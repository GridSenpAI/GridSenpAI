from __future__ import annotations

import json
from pathlib import Path

from services.run_diff_service.service import compare_run_states


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_run(
    output_dir: Path,
    run_id: str,
    *,
    field_records: list[dict],
    conflict_records: list[dict] | None = None,
    review_flags: list[dict] | None = None,
) -> None:
    run_dir = output_dir / run_id
    _write_json(
        run_dir / "state" / "canonical_facility_state.json",
        {
            "run_id": run_id,
            "state_version": "0.2.0",
            "governance_version": "phase_two",
            "field_records": field_records,
            "conflict_records": conflict_records or [],
            "review_flags": review_flags or [],
        },
    )
    _write_json(
        run_dir / "pipeline_summary.json",
        {
            "run_id": run_id,
            "status": "SUCCESS",
        },
    )


def test_compare_run_states_detects_added_removed_and_changed_fields(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"

    _seed_run(
        output_dir,
        "baseline_run",
        field_records=[
            {
                "field_record_id": "field_00001",
                "field_path": "facility.poi_voltage_kv",
                "value": 138.0,
            },
            {
                "field_record_id": "field_00002",
                "field_path": "facility.ups.topology",
                "value": "2N",
            },
        ],
        conflict_records=[],
        review_flags=[
            {"review_flag_id": "review_00001", "category": "LOW_CONFIDENCE"},
        ],
    )

    _seed_run(
        output_dir,
        "candidate_run",
        field_records=[
            {
                "field_record_id": "field_10001",
                "field_path": "facility.poi_voltage_kv",
                "value": 115.0,
            },
            {
                "field_record_id": "field_10002",
                "field_path": "facility.generators.count",
                "value": 4,
            },
        ],
        conflict_records=[
            {"conflict_id": "conflict_00001", "field_path": "facility.poi_voltage_kv"},
        ],
        review_flags=[
            {"review_flag_id": "review_00001", "category": "LOW_CONFIDENCE"},
            {"review_flag_id": "review_00002", "category": "CONFLICT"},
        ],
    )

    result = compare_run_states(
        output_dir=output_dir,
        baseline_run_id="baseline_run",
        candidate_run_id="candidate_run",
        write_artifact=True,
    )

    assert result["status"] == "RUN_DIFF_COMPLETED"
    summary = result["summary"]

    assert summary["baseline_run_id"] == "baseline_run"
    assert summary["candidate_run_id"] == "candidate_run"
    assert summary["field_diff_count"] == 3
    assert summary["added_field_count"] == 1
    assert summary["removed_field_count"] == 1
    assert summary["changed_field_count"] == 1
    assert summary["unchanged_field_count"] == 0
    assert summary["conflict_delta"] == 1
    assert summary["review_flag_delta"] == 1

    diff_by_path = {item["field_path"]: item for item in result["field_diffs"]}
    assert diff_by_path["facility.poi_voltage_kv"]["change_type"] == "CHANGED"
    assert diff_by_path["facility.ups.topology"]["change_type"] == "REMOVED"
    assert diff_by_path["facility.generators.count"]["change_type"] == "ADDED"

    artifact_path = Path(result["artifact_path"])
    assert artifact_path.exists()


def test_compare_run_states_handles_unchanged_runs(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"

    identical_records = [
        {
            "field_record_id": "field_00001",
            "field_path": "facility.poi_voltage_kv",
            "value": 138.0,
        }
    ]

    _seed_run(output_dir, "run_a", field_records=identical_records)
    _seed_run(output_dir, "run_b", field_records=identical_records)

    result = compare_run_states(
        output_dir=output_dir,
        baseline_run_id="run_a",
        candidate_run_id="run_b",
        write_artifact=False,
    )

    assert result["status"] == "RUN_DIFF_COMPLETED"
    assert result["field_diffs"] == []
    assert result["summary"]["field_diff_count"] == 0
    assert result["summary"]["unchanged_field_count"] == 1