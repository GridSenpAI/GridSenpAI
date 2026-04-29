from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.ui.workflow import (
    load_pending_interview_resume_bundle,
    load_interview_ui_state,
    mark_interview_ui_skipped,
    resolve_interview_session_path,
    save_interview_ui_state,
)
from services.interview_service.service import _project_id_from_context


def _write_interview_stage(output_dir: Path, run_id: str, session_path: Path) -> None:
    stages = output_dir / run_id / "stages"
    stages.mkdir(parents=True, exist_ok=True)
    stages.joinpath("gap_resolution__interview.json").write_text(
        json.dumps(
            {
                "session_path": str(session_path),
                "questions": [
                    {
                        "question_id": "q1",
                        "field_path": "facility.poi_voltage_kv",
                        "question": "Confirm POI voltage.",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_ui_writes_skip_state_to_service_session_path_from_run_artifact(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"
    run_id = "run_20260427_120906"
    session_path = tmp_path / "runs" / "interview_sessions" / "unresolved_project_run_20260427_120906_interview_session.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps({"project_id": f"UNRESOLVED_PROJECT::{run_id}", "questions": []}, indent=2),
        encoding="utf-8",
    )
    _write_interview_stage(output_dir, run_id, session_path)

    resolved = resolve_interview_session_path(
        project_root=tmp_path,
        project_name="",
        run_id=run_id,
        output_dir=output_dir,
    )
    assert resolved == session_path

    mark_interview_ui_skipped(
        project_root=tmp_path,
        project_name="",
        run_id=run_id,
        questions=[{"question_id": "q1"}],
        answers_by_question_id={},
        current_question_index=0,
        decision_reason="User skipped for now.",
        output_dir=output_dir,
    )

    payload = json.loads(session_path.read_text(encoding="utf-8"))
    assert payload["ui_state"]["status"] == "SKIPPED_BY_USER"
    assert payload["ui_state"]["run_id"] == run_id
    assert not (tmp_path / "runs" / "interview_sessions" / "gridsenpai_project_interview_session.json").exists()

    state = load_interview_ui_state(tmp_path, "", run_id=run_id, output_dir=output_dir)
    assert state["status"] == "SKIPPED_BY_USER"


def test_pending_resume_scans_run_bound_session_not_legacy_project_path(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"
    run_id = "run_20260427_120906"
    session_path = tmp_path / "runs" / "interview_sessions" / "unresolved_project_run_20260427_120906_interview_session.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps({"project_id": f"UNRESOLVED_PROJECT::{run_id}"}), encoding="utf-8")
    _write_interview_stage(output_dir, run_id, session_path)

    save_interview_ui_state(
        project_root=tmp_path,
        project_name="",
        run_id=run_id,
        questions=[{"question_id": "q1"}],
        answers_by_question_id={"q1": "138"},
        current_question_index=0,
        output_dir=output_dir,
    )

    bundle = load_pending_interview_resume_bundle(
        project_root=tmp_path,
        project_name="",
        output_dir=output_dir,
    )
    assert bundle["run_id"] == run_id
    assert bundle["session_path"] == session_path
    assert bundle["answer_drafts"] == {"q1": "138"}


def test_replay_interview_project_id_uses_source_run_not_child_run() -> None:
    context = SimpleNamespace(
        config=SimpleNamespace(project_name=""),
        run_id="run_child",
        parent_run_id="run_parent",
        replay_source_run_id="run_source",
    )
    assert _project_id_from_context(context) == "UNRESOLVED_PROJECT::run_source"

    context.replay_source_run_id = None
    assert _project_id_from_context(context) == "UNRESOLVED_PROJECT::run_parent"
