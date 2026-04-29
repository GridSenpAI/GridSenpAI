from __future__ import annotations

from pathlib import Path

from app.orchestration.run_pipeline import RunConfig, RunContext, default_normalization, default_translation


def _context(tmp_path: Path) -> RunContext:
    project_root = tmp_path / "project"
    input_dir = project_root / "input"
    output_dir = project_root / "output"
    run_dir = output_dir / "run-test"
    input_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(
        run_id="run-test",
        project_root=project_root,
        input_dir=input_dir,
        output_dir=output_dir,
        run_dir=run_dir,
        config=RunConfig(),
    )


def test_default_normalization_reports_planner_registry_schema_path(tmp_path: Path) -> None:
    context = _context(tmp_path)
    result = default_normalization(context, {}, {}, {})

    assert result["validation_report"]["schema_path"] == "planner_required_fields.normalization_runtime"


def test_default_translation_reports_planner_registry_schema_path(tmp_path: Path) -> None:
    context = _context(tmp_path)
    result = default_translation(context, {}, {}, {})

    assert result["schema_validation"]["schema_path"] == "planner_required_fields.translation_runtime"
