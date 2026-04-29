from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from services.replay_service.service import build_replay_plan, initialize_replay_manager


@dataclass(slots=True)
class DummyContext:
    run_id: str
    output_dir: Path
    run_dir: Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_source_run(output_dir: Path, source_run_id: str) -> Path:
    source_run_dir = output_dir / source_run_id
    source_run_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        source_run_dir / "pipeline_summary.json",
        {
            "run_id": source_run_id,
            "status": "SUCCESS",
        },
    )
    _write_json(
        source_run_dir / "run_metadata.json",
        {
            "run_id": source_run_id,
            "status": "SUCCESS",
        },
    )
    _write_json(
        source_run_dir / "lineage.json",
        {
            "run_id": source_run_id,
            "lineage_depth": 0,
            "ancestry": [],
            "related_runs": [],
        },
    )
    _write_json(
        source_run_dir / "snapshots" / "snapshot_manifest.json",
        {
            "run_id": source_run_id,
            "snapshot_count": 1,
            "snapshots": [],
        },
    )
    _write_json(
        source_run_dir / "state" / "canonical_facility_state.json",
        {
            "run_id": source_run_id,
            "governance_version": "phase_two",
            "field_records": [],
            "conflict_records": [],
            "review_flags": [],
        },
    )

    stages = {
        "ingestion": {"run_id": source_run_id, "status": "ARTIFACTS_INGESTED"},
        "extraction": {"run_id": source_run_id, "status": "EXTRACTED"},
        "normalization": {"run_id": source_run_id, "status": "NORMALIZED"},
        "gap_resolution": {
            "run_id": source_run_id,
            "status": "GAP_RESOLUTION_COMPLETED",
            "retrieval": {"status": "EVIDENCE_RETRIEVED"},
            "interview": {"status": "QUESTIONS_GENERATED"},
        },
        "validation": {
            "run_id": source_run_id,
            "status": "VALIDATED",
            "canonical_state": {
                "run_id": source_run_id,
                "governance_version": "phase_two",
                "field_records": [],
                "conflict_records": [],
                "review_flags": [],
            },
        },
        "canonical_state": {
            "run_id": source_run_id,
            "status": "CANONICAL_STATE_BUILT",
            "canonical_state": {
                "run_id": source_run_id,
                "governance_version": "phase_two",
                "field_records": [],
                "conflict_records": [],
                "review_flags": [],
            },
        },
        "translation": {"run_id": source_run_id, "status": "TRANSLATED"},
        "scenarios": {"run_id": source_run_id, "status": "SCENARIOS_GENERATED"},
        "export": {"run_id": source_run_id, "status": "EXPORTED"},
    }

    for stage_name, payload in stages.items():
        _write_json(source_run_dir / "stages" / f"{stage_name}.json", payload)

    _write_json(
        source_run_dir / "stages" / "gap_resolution__retrieval.json",
        {
            "run_id": source_run_id,
            "status": "EVIDENCE_RETRIEVED",
            "snippets": [{"field_path": "facility.poi_voltage_kv", "text": "138 kV"}],
        },
    )
    _write_json(
        source_run_dir / "stages" / "gap_resolution__interview.json",
        {
            "run_id": source_run_id,
            "status": "QUESTIONS_GENERATED",
            "questions": [{"question_id": "q1"}],
        },
    )

    return source_run_dir


def test_build_replay_plan_reuses_boundary_and_prior_stages(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"
    source_run_id = "source_run_001"
    _seed_source_run(output_dir, source_run_id)

    context = DummyContext(
        run_id="replay_run_001",
        output_dir=output_dir,
        run_dir=output_dir / "replay_run_001",
    )

    plan = build_replay_plan(
        context=context,
        replay_source_run_id=source_run_id,
        replay_stage_boundary="validation",
    )

    assert plan["source_run_id"] == source_run_id
    assert plan["requested_stage_boundary"] == "validation"
    assert plan["resume_from_stage"] == "canonical_state"
    assert plan["reused_stages"] == [
        "ingestion",
        "extraction",
        "normalization",
        "gap_resolution",
        "validation",
    ]
    assert plan["rerun_stages"] == ["canonical_state", "translation", "scenarios", "export"]
    assert plan["source_canonical_state"]["run_id"] == source_run_id
    assert "gap_resolution" in plan["reused_stage_outputs"]
    assert plan["reused_stage_outputs"]["gap_resolution"]["retrieval"]["status"] == "EVIDENCE_RETRIEVED"



def test_build_replay_plan_can_resume_after_retrieval_substage(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"
    source_run_id = "source_run_retrieval_boundary"
    _seed_source_run(output_dir, source_run_id)

    context = DummyContext(
        run_id="post_interview_replay_run",
        output_dir=output_dir,
        run_dir=output_dir / "post_interview_replay_run",
    )

    plan = build_replay_plan(
        context=context,
        replay_source_run_id=source_run_id,
        replay_stage_boundary="gap_resolution::retrieval",
    )

    assert plan["requested_stage_boundary"] == "gap_resolution::retrieval"
    assert plan["resume_from_stage"] == "gap_resolution"
    assert plan["reused_stages"] == ["ingestion", "extraction", "normalization"]
    assert plan["rerun_stages"] == ["gap_resolution", "validation", "canonical_state", "translation", "scenarios", "export"]
    assert plan["reused_gap_resolution_substages"] == ["gap_resolution::retrieval"]
    assert plan["reused_gap_resolution_substage_outputs"]["gap_resolution::retrieval"]["status"] == "EVIDENCE_RETRIEVED"

def test_initialize_replay_manager_writes_manifest_and_plan(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"
    source_run_id = "source_run_002"
    _seed_source_run(output_dir, source_run_id)

    context = DummyContext(
        run_id="replay_run_002",
        output_dir=output_dir,
        run_dir=output_dir / "replay_run_002",
    )

    manager = initialize_replay_manager(
        context=context,
        replay_source_run_id=source_run_id,
        replay_stage_boundary="canonical_state",
    )
    manager.persist_plan()

    replay_manifest_path = context.run_dir / "replay_manifest.json"
    replay_plan_path = context.run_dir / "replay_plan.json"

    assert replay_manifest_path.exists()
    assert replay_plan_path.exists()

    manifest = json.loads(replay_manifest_path.read_text(encoding="utf-8"))
    plan = json.loads(replay_plan_path.read_text(encoding="utf-8"))

    assert manifest["run_id"] == "replay_run_002"
    assert manifest["status"] == "INITIALIZED"
    assert manifest["source_run_id"] == source_run_id
    assert manifest["requested_stage_boundary"] == "canonical_state"
    assert manifest["resume_from_stage"] == "translation"

    assert plan["source_run_id"] == source_run_id
    assert plan["requested_stage_boundary"] == "canonical_state"
    assert plan["resume_from_stage"] == "translation"
    assert plan["gap_resolution_substage_order"] == [
        "gap_resolution::retrieval",
        "gap_resolution::interview",
    ]

    manager.mark_completed()
    manifest = json.loads(replay_manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED"
