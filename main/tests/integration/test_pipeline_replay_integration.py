from __future__ import annotations

import pytest
import json
import subprocess
import sys
from pathlib import Path

from tests.integration.helpers import prepare_writable_workspace


ALLOWED_PIPELINE_OUTCOMES = {"SUCCESS", "SUCCESS_FINAL", "SUCCESS_PROVISIONAL", "BLOCKED_PENDING_INTERVIEW", "BLOCKED_REVIEW_REQUIRED"}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.integration
def test_pipeline_replay_integration(tmp_path: Path) -> None:
    project_root = prepare_writable_workspace(tmp_path)
    output_root = project_root / "runs"
    base_run_id = "replay_source_smoke_test"
    replay_run_id = "replay_child_smoke_test"

    base_result = subprocess.run(
        [sys.executable, "-m", "app.main", "--run-id", base_run_id, "--output-dir", str(output_root)],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert base_result.returncode == 0, (
        f"Base pipeline failed.\nSTDOUT:\n{base_result.stdout}\nSTDERR:\n{base_result.stderr}"
    )

    replay_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.main",
            "--run-id",
            replay_run_id,
            "--replay-run-id",
            base_run_id,
            "--replay-stage-boundary",
            "validation",
            "--output-dir",
            str(output_root),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert replay_result.returncode == 0, (
        f"Replay pipeline failed.\nSTDOUT:\n{replay_result.stdout}\nSTDERR:\n{replay_result.stderr}"
    )

    replay_run_dir = output_root / replay_run_id
    assert replay_run_dir.exists()

    replay_summary = _load_json(replay_run_dir / "pipeline_summary.json")
    replay_context = _load_json(replay_run_dir / "run_context.json")
    replay_manifest = _load_json(replay_run_dir / "replay_manifest.json")
    replay_plan = _load_json(replay_run_dir / "replay_plan.json")
    replay_metadata = _load_json(replay_run_dir / "run_metadata.json")
    replay_lineage = _load_json(replay_run_dir / "lineage.json")
    replay_snapshot_manifest = _load_json(
        replay_run_dir / "snapshots" / "snapshot_manifest.json"
    )

    assert replay_summary["run_id"] == replay_run_id
    assert replay_summary["status"] in ALLOWED_PIPELINE_OUTCOMES
    assert replay_summary["execution_mode"] == "REPLAY"
    assert replay_summary["replay_source_run_id"] == base_run_id
    assert replay_summary["replay_stage_boundary"] == "validation"

    replay_summary_block = replay_summary["replay_summary"]
    assert replay_summary_block["source_run_id"] == base_run_id
    assert replay_summary_block["requested_stage_boundary"] == "validation"
    assert replay_summary_block["resume_from_stage"] == "canonical_state"
    assert replay_summary_block["reused_stages"] == [
        "ingestion",
        "extraction",
        "normalization",
        "gap_resolution",
        "validation",
    ]
    assert replay_summary_block["rerun_stages"] == ["canonical_state", "translation", "scenarios", "export"]

    assert replay_context["execution_mode"] == "REPLAY"
    assert replay_context["parent_run_id"] == base_run_id
    assert replay_context["replay_source_run_id"] == base_run_id
    assert replay_context["replay_stage_boundary"] == "validation"

    assert replay_manifest["run_id"] == replay_run_id
    assert replay_manifest["status"] == "COMPLETED"
    assert replay_manifest["source_run_id"] == base_run_id
    assert replay_manifest["requested_stage_boundary"] == "validation"
    assert replay_manifest["resume_from_stage"] == "canonical_state"

    assert replay_plan["source_run_id"] == base_run_id
    assert replay_plan["requested_stage_boundary"] == "validation"
    assert replay_plan["resume_from_stage"] == "canonical_state"

    assert replay_metadata["run_id"] == replay_run_id
    assert replay_metadata["status"] in ALLOWED_PIPELINE_OUTCOMES
    assert replay_metadata["execution_mode"] == "REPLAY"
    assert replay_metadata["parent_run_id"] == base_run_id
    assert replay_metadata["replay_source_run_id"] == base_run_id
    assert replay_metadata["replay_stage_boundary"] == "validation"

    assert replay_lineage["run_id"] == replay_run_id
    assert replay_lineage["parent_run_id"] == base_run_id
    assert replay_lineage["replay_source_run_id"] == base_run_id
    assert replay_lineage["replay_stage_boundary"] == "validation"
    assert base_run_id in replay_lineage["ancestry"]
    assert base_run_id in replay_lineage["related_runs"]

    assert replay_snapshot_manifest["run_id"] == replay_run_id
    assert replay_snapshot_manifest["snapshot_count"] >= 3
    labels = [item["label"] for item in replay_snapshot_manifest["snapshots"]]
    assert "replay_initialized" in labels
    assert "after_canonical_state" in labels
    assert "final" in labels

    reused_stage_names = [
        "ingestion",
        "extraction",
        "normalization",
        "gap_resolution",
        "validation",
    ]
    rerun_stage_names = ["canonical_state", "translation", "scenarios", "export"]

    base_run_dir = output_root / base_run_id
    for stage_name in reused_stage_names:
        replay_stage = _load_json(replay_run_dir / "stages" / f"{stage_name}.json")
        base_stage = _load_json(base_run_dir / "stages" / f"{stage_name}.json")
        if stage_name == "gap_resolution":
            replay_retrieval = replay_stage["retrieval"]
            base_retrieval = base_stage["retrieval"]
            assert replay_stage["status"] == base_stage["status"]
            assert replay_stage["run_id"] == replay_run_id
            assert base_stage["run_id"] == base_run_id
            assert replay_retrieval["status"] == base_retrieval["status"]
            assert replay_retrieval["knowledge_family_route"] == base_retrieval["knowledge_family_route"]
            assert replay_retrieval["requested_field_paths"] == base_retrieval["requested_field_paths"]
            assert replay_retrieval["review_required_field_paths"] == base_retrieval["review_required_field_paths"]
            assert replay_retrieval["out_of_scope_missing_field_paths"] == base_retrieval["out_of_scope_missing_field_paths"]
            assert replay_retrieval["resolution_backlog_summary"] == base_retrieval["resolution_backlog_summary"]
            assert replay_retrieval["evidence_gap"] == base_retrieval["evidence_gap"]
            assert replay_retrieval["official_web_lookup_required"] == base_retrieval["official_web_lookup_required"]
            assert replay_retrieval["field_support_summary"] == base_retrieval["field_support_summary"]
            assert replay_retrieval["equipment_reference_resolution_used"] == base_retrieval["equipment_reference_resolution_used"]
            assert replay_retrieval["gap_fill_strategy"] == base_retrieval["gap_fill_strategy"]
            assert replay_retrieval["trigger_summary"] == base_retrieval["trigger_summary"]
            assert replay_retrieval["errors"] == base_retrieval["errors"]
            assert [snippet["source_ref"] for snippet in replay_retrieval["snippets"]] == [snippet["source_ref"] for snippet in base_retrieval["snippets"]]
            assert replay_retrieval["llm_assistance"]["status"] == base_retrieval["llm_assistance"]["status"]
            continue
        if stage_name in {"ingestion", "extraction", "normalization", "validation"}:
            replay_comparable = {key: value for key, value in replay_stage.items() if key not in {"run_id", "resolved_at", "generated_at", "created_at", "timestamp"}}
            base_comparable = {key: value for key, value in base_stage.items() if key not in {"run_id", "resolved_at", "generated_at", "created_at", "timestamp"}}
            assert replay_comparable == base_comparable
            assert replay_stage["run_id"] == base_run_id
            assert base_stage["run_id"] == base_run_id
            continue
        assert replay_stage == base_stage

    for stage_name in rerun_stage_names:
        replay_stage = _load_json(replay_run_dir / "stages" / f"{stage_name}.json")
        assert replay_stage["run_id"] == replay_run_id


