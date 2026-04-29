def _normalized_path(value: str) -> str:
    return value.replace("\\", "/")

from shared.runtime_stage_contract import replay_contract_summary


def test_runtime_contract_reports_registry_derived_schema_alignment() -> None:
    summary = replay_contract_summary()
    alignment = summary["derived_schema_alignment"]

    assert alignment["input_schema_aligned"] is True
    assert alignment["output_schema_aligned"] is True
    assert alignment["registry_field_count"] >= 524
    assert _normalized_path(alignment["input_schema_path"]).endswith("shared/schemas/gridsenpai_inputs_schema.json")
    assert _normalized_path(alignment["output_schema_path"]).endswith("shared/schemas/gridsenpai_outputs_schema.json")
