from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from services.run_governance_service.service import initialize_run_governance


@dataclass(slots=True)
class DummyConfig:
    project_name: str = "GridSenpAI Test Project"
    schema_version_input: str = "0.1.0"
    schema_version_output: str = "0.1.0"
    prompt_template_version: str = "test-template-v1"
    model_version: str = "test-model-v1"


@dataclass(slots=True)
class DummyContext:
    run_id: str
    project_root: Path
    input_dir: Path
    output_dir: Path
    run_dir: Path
    config: DummyConfig
    parent_run_id: str | None = None
    execution_mode: str = "STANDARD"
    replay_source_run_id: str | None = None
    replay_stage_boundary: str | None = None


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def test_run_governance_initializes_metadata_lineage_and_snapshots(tmp_path: Path) -> None:
    context = DummyContext(
        run_id="run_governance_test_001",
        project_root=tmp_path,
        input_dir=tmp_path / "sample_data",
        output_dir=tmp_path / "runs",
        run_dir=tmp_path / "runs" / "run_governance_test_001",
        config=DummyConfig(),
    )

    manager = initialize_run_governance(context)

    metadata_path = context.run_dir / "run_metadata.json"
    lineage_path = context.run_dir / "lineage.json"
    snapshot_manifest_path = context.run_dir / "snapshots" / "snapshot_manifest.json"

    assert metadata_path.exists()
    assert lineage_path.exists()
    assert snapshot_manifest_path.exists()

    metadata = _load_json(metadata_path)
    lineage = _load_json(lineage_path)
    manifest = _load_json(snapshot_manifest_path)

    assert metadata["run_id"] == context.run_id
    assert metadata["status"] == "INITIALIZED"
    assert metadata["execution_mode"] == "STANDARD"
    assert lineage["run_id"] == context.run_id
    assert lineage["lineage_depth"] == 0
    assert manifest["snapshot_count"] == 0
    assert manifest["snapshots"] == []

    canonical_state = {
        "run_id": context.run_id,
        "state_version": "0.2.0",
        "governance_version": "phase_two",
        "field_records": [{"field_record_id": "field_00001"}],
        "conflict_records": [],
        "review_flags": [{"review_flag_id": "review_00001"}],
        "stage_status": {"canonical_state_governance": "GOVERNED"},
    }

    snapshot = manager.snapshot_canonical_state("after_validation", canonical_state)
    assert snapshot["label"] == "after_validation"

    manifest = _load_json(snapshot_manifest_path)
    assert manifest["snapshot_count"] == 1
    assert manifest["snapshots"][0]["label"] == "after_validation"

    governance_result = manager.finalize(
        status="SUCCESS",
        canonical_state_path=context.run_dir / "state" / "canonical_facility_state.json",
        pipeline_summary_path=context.run_dir / "pipeline_summary.json",
        export_manifest_path=context.run_dir / "exports" / "run_manifest.json",
    )

    metadata = _load_json(metadata_path)
    assert governance_result["status"] == "SUCCESS"
    assert metadata["status"] == "SUCCESS"
    assert metadata["snapshot_count"] == 1
    assert metadata["final_canonical_state_path"] == "state/canonical_facility_state.json"
    assert metadata["final_pipeline_summary_path"] == "pipeline_summary.json"
    assert metadata["export_manifest_path"] == "exports/run_manifest.json"


def test_run_governance_builds_parent_lineage_chain(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"
    parent_run_dir = output_dir / "run_parent_001"
    parent_run_dir.mkdir(parents=True, exist_ok=True)

    with (parent_run_dir / "lineage.json").open("w", encoding="utf-8") as file:
        json.dump(
            {
                "run_id": "run_parent_001",
                "parent_run_id": "run_grandparent_001",
                "replay_source_run_id": None,
                "replay_stage_boundary": None,
                "created_at": "2026-03-09T00:00:00+00:00",
                "lineage_depth": 1,
                "ancestry": ["run_grandparent_001"],
                "related_runs": ["run_grandparent_001"],
            },
            file,
            indent=2,
        )

    context = DummyContext(
        run_id="run_child_001",
        project_root=tmp_path,
        input_dir=tmp_path / "sample_data",
        output_dir=output_dir,
        run_dir=output_dir / "run_child_001",
        config=DummyConfig(),
        parent_run_id="run_parent_001",
    )

    initialize_run_governance(context)

    lineage = _load_json(context.run_dir / "lineage.json")
    assert lineage["run_id"] == "run_child_001"
    assert lineage["parent_run_id"] == "run_parent_001"
    assert lineage["lineage_depth"] == 2
    assert lineage["ancestry"] == ["run_grandparent_001", "run_parent_001"]
    assert "run_parent_001" in lineage["related_runs"]