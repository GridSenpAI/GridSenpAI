from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services.ingestion_service.service import _project_id_from_context
from services.ingestion_service.utils import classify_artifact, derive_tags, requirement_ids_for_classification


def test_generalized_artifact_classification_for_grid_application_packet_names(tmp_path: Path) -> None:
    cases = {
        "Prairie Horizon Large Load Request Form.pdf": "large_load_request_form",
        "PHDC Single-Line Diagram Rev C.pdf": "one_line_diagram",
        "Construction Phasing and Energization Schedule.pdf": "construction_phasing_plan",
        "Metering SCADA Telemetry Package.pdf": "metering_scada_telemetry",
        "Protection and Controls Relay Settings.pdf": "protection_controls",
        "Facilities Study Memo.pdf": "facilities_study_memo",
        "Project Summary Load Ramp Schedule.pdf": "project_summary_load_schedule",
    }
    for filename, expected in cases.items():
        path = tmp_path / filename
        path.write_text("placeholder", encoding="utf-8")
        assert classify_artifact(path) == expected
        assert f"source_role:{expected}" in derive_tags(expected, path)


def test_new_classifications_map_to_requirement_ids() -> None:
    assert "standalone_large_load_energization_request_package" in requirement_ids_for_classification("large_load_request_form")
    assert "telemetry_nomcr_and_operations_model_package" in requirement_ids_for_classification("metering_scada_telemetry")
    assert "protection_and_controls_package" in requirement_ids_for_classification("protection_controls")


def test_ingestion_project_id_is_stable_for_replay_runs() -> None:
    context = SimpleNamespace(
        config=SimpleNamespace(project_name=""),
        run_id="run_child",
        parent_run_id="run_parent",
        replay_source_run_id="run_source",
    )
    assert _project_id_from_context(context) == "UNRESOLVED_PROJECT::run_source"
