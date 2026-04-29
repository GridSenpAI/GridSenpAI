# tests/test_export_outputs.py

from __future__ import annotations

import pytest
from pathlib import Path

from app.orchestration.run_pipeline import GridSenpAIPipeline, RunConfig, RunContext


ALLOWED_PIPELINE_OUTCOMES = {"SUCCESS", "SUCCESS_FINAL", "SUCCESS_PROVISIONAL", "BLOCKED_PENDING_INTERVIEW", "BLOCKED_REVIEW_REQUIRED"}
ALLOWED_EXPORT_STATUSES = {"EXPORTED", "EXPORTED_PROVISIONAL", "EXPORTED_BLOCKED"}


def _create_sample_artifacts(input_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "sample_one-line.txt").write_text(
        "Sample one-line diagram placeholder text.",
        encoding="utf-8",
    )
    (input_dir / "ups_spec.txt").write_text(
        "UPS specification placeholder text.",
        encoding="utf-8",
    )


@pytest.mark.integration
def test_export_manifest_and_planner_packet(tmp_path: Path) -> None:
    project_root = tmp_path
    input_dir = tmp_path / "sample_data"
    output_dir = tmp_path / "runs"
    run_id = "run_export_test_001"

    _create_sample_artifacts(input_dir)

    context = RunContext(
        run_id=run_id,
        project_root=project_root,
        input_dir=input_dir,
        output_dir=output_dir,
        run_dir=output_dir / run_id,
        config=RunConfig(
            project_name="GridSenpAI Export Test",
            schema_version_input="0.1.0",
            schema_version_output="0.1.0",
            prompt_template_version="test-template",
            model_version="test-model",
            retrieval_config={"top_k": 5, "rerank": False},
        ),
    )

    pipeline = GridSenpAIPipeline(context)
    summary = pipeline.run()

    assert summary["status"] in ALLOWED_PIPELINE_OUTCOMES

    exports_dir = context.run_dir / "exports"
    canonical_state_path = exports_dir / "canonical_facility_state.json"
    translated_parameters_path = exports_dir / "translated_parameters.json"
    scenario_set_path = exports_dir / "scenario_set.json"
    planner_packet_pdf_path = exports_dir / "planner_packet.pdf"
    planner_packet_markdown_path = exports_dir / "planner_packet.md"
    run_manifest_path = exports_dir / "run_manifest.json"

    assert canonical_state_path.exists()
    assert translated_parameters_path.exists()
    assert scenario_set_path.exists()
    assert planner_packet_pdf_path.exists()
    assert not planner_packet_markdown_path.exists()
    assert run_manifest_path.exists()

    manifest = run_manifest_path.read_text(encoding="utf-8")
    assert "canonical_facility_state.json" in manifest
    assert "translated_parameters.json" in manifest
    assert "scenario_set.json" in manifest
    assert "planner_packet.pdf" in manifest

    pipeline_summary_path = context.run_dir / "pipeline_summary.json"
    assert pipeline_summary_path.exists()


