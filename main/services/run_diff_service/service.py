from __future__ import annotations

from pathlib import Path
from typing import Any

from shared.runtime_stage_contract import ordered_stage_status

from services.run_diff_service.models import FieldDiffRecord, RunDiffSummary
from services.run_diff_service.utils import (
    build_conflict_index,
    build_field_index,
    build_review_flag_index,
    load_canonical_state,
    load_pipeline_summary,
    utc_now_iso,
    value_fingerprint,
    write_json,
)


def load_run_diff_inputs(
    *,
    output_dir: str | Path,
    baseline_run_id: str,
    candidate_run_id: str,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    baseline_run_dir = output_path / baseline_run_id
    candidate_run_dir = output_path / candidate_run_id

    if not baseline_run_dir.exists():
        raise FileNotFoundError(f"Baseline run directory not found: {baseline_run_dir}")
    if not candidate_run_dir.exists():
        raise FileNotFoundError(f"Candidate run directory not found: {candidate_run_dir}")

    baseline_state = load_canonical_state(baseline_run_dir)
    candidate_state = load_canonical_state(candidate_run_dir)

    if not baseline_state:
        raise FileNotFoundError(
            f"Baseline canonical state not found or invalid: {baseline_run_dir / 'state' / 'canonical_facility_state.json'}"
        )
    if not candidate_state:
        raise FileNotFoundError(
            f"Candidate canonical state not found or invalid: {candidate_run_dir / 'state' / 'canonical_facility_state.json'}"
        )

    return {
        "baseline_run_dir": baseline_run_dir,
        "candidate_run_dir": candidate_run_dir,
        "baseline_state": baseline_state,
        "candidate_state": candidate_state,
        "baseline_summary": load_pipeline_summary(baseline_run_dir),
        "candidate_summary": load_pipeline_summary(candidate_run_dir),
    }


def _compare_field_records(
    baseline_state: dict[str, Any],
    candidate_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    baseline_index = build_field_index(
        baseline_state.get("field_records", []) if isinstance(baseline_state.get("field_records", []), list) else []
    )
    candidate_index = build_field_index(
        candidate_state.get("field_records", []) if isinstance(candidate_state.get("field_records", []), list) else []
    )

    all_paths = sorted(set(baseline_index.keys()) | set(candidate_index.keys()))
    diffs: list[dict[str, Any]] = []

    counts = {
        "added": 0,
        "removed": 0,
        "changed": 0,
        "unchanged": 0,
    }

    for field_path in all_paths:
        baseline_item = baseline_index.get(field_path)
        candidate_item = candidate_index.get(field_path)

        if baseline_item is None and candidate_item is not None:
            candidate_record = candidate_item
            counts["added"] += 1
            diffs.append(
                FieldDiffRecord(
                    field_path=field_path,
                    change_type="ADDED",
                    baseline_value=None,
                    candidate_value=candidate_record.get("value"),
                    baseline_record_ids=[],
                    candidate_record_ids=list(candidate_record.get("record_ids", [])),
                    metadata={
                        "baseline_present": False,
                        "candidate_present": True,
                    },
                ).to_dict()
            )
            continue

        if baseline_item is not None and candidate_item is None:
            baseline_record = baseline_item
            counts["removed"] += 1
            diffs.append(
                FieldDiffRecord(
                    field_path=field_path,
                    change_type="REMOVED",
                    baseline_value=baseline_record.get("value"),
                    candidate_value=None,
                    baseline_record_ids=list(baseline_record.get("record_ids", [])),
                    candidate_record_ids=[],
                    metadata={
                        "baseline_present": True,
                        "candidate_present": False,
                    },
                ).to_dict()
            )
            continue

        if baseline_item is None or candidate_item is None:
            continue

        baseline_record = baseline_item
        candidate_record = candidate_item

        baseline_value = baseline_record.get("value")
        candidate_value = candidate_record.get("value")

        if value_fingerprint(baseline_value) == value_fingerprint(candidate_value):
            counts["unchanged"] += 1
            continue

        counts["changed"] += 1
        diffs.append(
            FieldDiffRecord(
                field_path=field_path,
                change_type="CHANGED",
                baseline_value=baseline_value,
                candidate_value=candidate_value,
                baseline_record_ids=list(baseline_record.get("record_ids", [])),
                candidate_record_ids=list(candidate_record.get("record_ids", [])),
                metadata={
                    "baseline_present": True,
                    "candidate_present": True,
                },
            ).to_dict()
        )

    return diffs, counts


def _compare_conflicts(
    baseline_state: dict[str, Any],
    candidate_state: dict[str, Any],
) -> dict[str, Any]:
    baseline_index = build_conflict_index(
        baseline_state.get("conflict_records", []) if isinstance(baseline_state.get("conflict_records", []), list) else []
    )
    candidate_index = build_conflict_index(
        candidate_state.get("conflict_records", []) if isinstance(candidate_state.get("conflict_records", []), list) else []
    )

    added = sorted(set(candidate_index.keys()) - set(baseline_index.keys()))
    removed = sorted(set(baseline_index.keys()) - set(candidate_index.keys()))
    persistent = sorted(set(baseline_index.keys()) & set(candidate_index.keys()))

    return {
        "baseline_count": len(baseline_index),
        "candidate_count": len(candidate_index),
        "delta": len(candidate_index) - len(baseline_index),
        "added": added,
        "removed": removed,
        "persistent": persistent,
    }


def _compare_review_flags(
    baseline_state: dict[str, Any],
    candidate_state: dict[str, Any],
) -> dict[str, Any]:
    baseline_index = build_review_flag_index(
        baseline_state.get("review_flags", []) if isinstance(baseline_state.get("review_flags", []), list) else []
    )
    candidate_index = build_review_flag_index(
        candidate_state.get("review_flags", []) if isinstance(candidate_state.get("review_flags", []), list) else []
    )

    added = sorted(set(candidate_index.keys()) - set(baseline_index.keys()))
    removed = sorted(set(baseline_index.keys()) - set(candidate_index.keys()))
    persistent = sorted(set(baseline_index.keys()) & set(candidate_index.keys()))

    return {
        "baseline_count": len(baseline_index),
        "candidate_count": len(candidate_index),
        "delta": len(candidate_index) - len(baseline_index),
        "added": added,
        "removed": removed,
        "persistent": persistent,
    }


def compare_run_states(
    *,
    output_dir: str | Path,
    baseline_run_id: str,
    candidate_run_id: str,
    write_artifact: bool = True,
) -> dict[str, Any]:
    inputs = load_run_diff_inputs(
        output_dir=output_dir,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
    )

    baseline_state = inputs["baseline_state"]
    candidate_state = inputs["candidate_state"]
    baseline_run_dir = inputs["baseline_run_dir"]
    candidate_run_dir = inputs["candidate_run_dir"]

    field_diffs, field_counts = _compare_field_records(baseline_state, candidate_state)
    conflict_comparison = _compare_conflicts(baseline_state, candidate_state)
    review_flag_comparison = _compare_review_flags(baseline_state, candidate_state)

    summary = RunDiffSummary(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        created_at=utc_now_iso(),
        field_diff_count=len(field_diffs),
        added_field_count=field_counts["added"],
        removed_field_count=field_counts["removed"],
        changed_field_count=field_counts["changed"],
        unchanged_field_count=field_counts["unchanged"],
        conflict_delta=int(conflict_comparison["delta"]),
        review_flag_delta=int(review_flag_comparison["delta"]),
    )

    result = {
        "status": "RUN_DIFF_COMPLETED",
        "summary": summary.to_dict(),
        "baseline": {
            "run_id": baseline_run_id,
            "run_dir": str(baseline_run_dir),
            "pipeline_summary": inputs["baseline_summary"],
            "ordered_stage_status": ordered_stage_status(inputs["baseline_summary"].get("stage_status", {})) if isinstance(inputs["baseline_summary"], dict) else {},
        },
        "candidate": {
            "run_id": candidate_run_id,
            "run_dir": str(candidate_run_dir),
            "pipeline_summary": inputs["candidate_summary"],
            "ordered_stage_status": ordered_stage_status(inputs["candidate_summary"].get("stage_status", {})) if isinstance(inputs["candidate_summary"], dict) else {},
        },
        "field_diffs": field_diffs,
        "conflict_comparison": conflict_comparison,
        "review_flag_comparison": review_flag_comparison,
    }

    if write_artifact:
        diff_dir = candidate_run_dir / "diffs"
        artifact_path = diff_dir / f"diff_vs_{baseline_run_id}.json"
        write_json(artifact_path, result)
        result["artifact_path"] = str(artifact_path)

    return result