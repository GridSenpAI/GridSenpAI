from __future__ import annotations


def _normalized_path(value: str) -> str:
    return value.replace("\\", "/")

from shared.runtime_stage_contract import replay_contract_summary


def test_replay_contract_summary_exposes_planner_registry_as_primary_contract() -> None:
    summary = replay_contract_summary()

    assert _normalized_path(summary["primary_planner_contract_path"]).endswith("shared/schemas/planner_required_fields.json")
    assert summary["planner_required_fields_path"] == summary["primary_planner_contract_path"]
    assert _normalized_path(summary["legacy_input_schema_path"]).endswith("shared/schemas/gridsenpai_inputs_schema.json")
    assert _normalized_path(summary["legacy_output_schema_path"]).endswith("shared/schemas/gridsenpai_outputs_schema.json")
