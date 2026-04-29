from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from services.normalization_service.service import run_service


@dataclass(slots=True)
class _Config:
    schema_version_input: str = "0.1.0"
    project_name: str = "GridSenpAI Test Project"


@dataclass(slots=True)
class _Context:
    run_id: str
    run_dir: Path
    config: _Config = field(default_factory=_Config)


def _run(tmp_path: Path, candidates: list[dict]) -> dict:
    return run_service(
        context=_Context(run_id="field_aware_norm", run_dir=tmp_path / "field_aware_norm"),
        extraction_result={"schema_field_candidates": candidates, "entities": [], "topology_cues": [], "canonical_state": {}},
        interview_result=None,
        retrieval_result=None,
    )


def test_poi_voltage_prefers_service_voltage_over_internal_distribution_context(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {
                "field_path": "facility.poi_voltage_kv",
                "value": 13.8,
                "confidence": 0.95,
                "method": "table_worker.row_value",
                "source_artifact_id": "equipment_schedule",
                "evidence": [{"text": "Main switchgear campus medium-voltage distribution voltage 13.8 kV", "metadata": {"document_role": "equipment_schedule"}}],
            },
            {
                "field_path": "facility.poi_voltage_kv",
                "value": 138,
                "confidence": 0.88,
                "method": "table_worker.row_value",
                "source_artifact_id": "load_request",
                "evidence": [{"text": "Electrical Characteristics Nominal service voltage 138 kV at point of interconnection", "metadata": {"document_role": "application_request_form"}}],
            },
        ],
    )

    assert result["normalized_input"]["facility"]["poi_voltage_kv"] == 138.0


def test_equipment_counts_prefer_quantity_schedule_over_repeated_drawing_labels(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {
                "field_path": "generator_unit_count",
                "value": 64,
                "confidence": 0.92,
                "method": "drawing_symbol_counter",
                "source_artifact_id": "one_line",
                "evidence": [{"text": "Drawing label repeated device numbers and typical generator symbols", "metadata": {"document_role": "one_line"}}],
            },
            {
                "field_path": "generator_unit_count",
                "value": 60,
                "confidence": 0.86,
                "method": "table_worker.row_value",
                "source_artifact_id": "equipment_schedule",
                "evidence": [{"text": "Standby Generation Platform Campus quantity units total 60", "metadata": {"document_role": "equipment_schedule"}}],
            },
        ],
    )

    assert result["normalized_input"]["facility"]["generators"]["count"] == 60


def test_requested_service_date_rejects_drawing_title_block_date(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {
                "field_path": "requested_in_service_date",
                "value": "04/2026",
                "confidence": 0.96,
                "method": "drawing_title_block",
                "source_artifact_id": "single_line",
                "evidence": [{"text": "Title block drawing date 04/2026 revision A", "metadata": {"document_role": "one_line"}}],
            },
            {
                "field_path": "requested_in_service_date",
                "value": "2028-06-15",
                "confidence": 0.82,
                "method": "table_worker.row_value",
                "source_artifact_id": "phasing_plan",
                "evidence": [{"text": "Construction phasing target energization requested initial in-service 2028-06-15", "metadata": {"document_role": "phasing_energization_plan"}}],
            },
        ],
    )

    assert result["normalized_input"]["facility"]["requested_in_service_date"] == "2028-06-15"
