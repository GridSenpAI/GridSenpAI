import json
from pathlib import Path

from shared.planner_registry import (
    build_inputs_schema_from_registry,
    build_outputs_schema_from_registry,
    planner_registry_integrity_snapshot,
    planner_schema_alignment_summary,
)


def test_derived_input_output_schemas_align_with_planner_required_fields() -> None:
    summary = planner_schema_alignment_summary()

    assert summary["registry_field_count"] >= 524
    assert summary["input_schema_aligned"] is True
    assert summary["output_schema_aligned"] is True
    assert summary["missing_from_input_schema"] == []
    assert summary["missing_from_output_schema"] == []


def test_derived_schema_files_expose_registry_backed_contract_metadata() -> None:
    inputs_schema = build_inputs_schema_from_registry()
    outputs_schema = build_outputs_schema_from_registry()
    registry_version = inputs_schema["properties"]["planner_required_fields_version"]["const"]

    assert inputs_schema["x-derived-from"] == "shared/schemas/planner_required_fields.json"
    assert outputs_schema["x-derived-from"] == "shared/schemas/planner_required_fields.json"
    assert inputs_schema["x-derived-from-version"] == registry_version
    assert outputs_schema["x-derived-from-version"] == registry_version

    input_field_values = inputs_schema["properties"]["field_values"]["properties"]
    accepted_field_values = outputs_schema["properties"]["accepted_field_values"]["properties"]

    for field_id in [
        "project_name",
        "point_of_interconnection_voltage_kv",
        "generator_unit_count",
        "ups_topology",
        "peak_demand_mw",
    ]:
        assert field_id in input_field_values
        assert field_id in accepted_field_values


def test_derived_schema_files_are_full_drop_in_json_documents() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    input_schema_path = repo_root / "shared" / "schemas" / "gridsenpai_inputs_schema.json"
    output_schema_path = repo_root / "shared" / "schemas" / "gridsenpai_outputs_schema.json"

    input_payload = json.loads(input_schema_path.read_text())
    output_payload = json.loads(output_schema_path.read_text())

    assert input_payload["title"] == "GridSenpAI Inputs Schema"
    assert output_payload["title"] == "GridSenpAI Outputs Schema"
    assert "field_resolution" in output_payload["properties"]
    assert "planner_packet" in output_payload["properties"]
