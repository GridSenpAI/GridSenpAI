from types import SimpleNamespace

from services.normalization_service.service import normalize_inputs


class _Config(SimpleNamespace):
    project_name: str = "Registry Migration Project"
    schema_version_input: str = "1.0.0"


def test_normalization_missing_fields_are_registry_backed() -> None:
    context = SimpleNamespace(
        run_id="run-normalization-registry",
        config=_Config(),
    )

    result = normalize_inputs(
        context=context,
        extraction_result={"entities": [], "topology_cues": [], "canonical_state": {}},
        interview_result=None,
        retrieval_result=None,
    )

    missing_fields = result["validation_report"]["missing_fields"]
    followups = result["followup_questions"]

    field_ids = {item.get("field_id") for item in missing_fields if isinstance(item, dict)}
    followup_field_ids = {item.get("field_id") for item in followups if isinstance(item, dict)}

    assert "point_of_interconnection_voltage_kv" in field_ids
    assert "peak_demand_mw" in field_ids
    assert "ups_topology" in field_ids
    assert "interconnection_transformer_unit_count" in field_ids

    poi_followup = next(
        item for item in followups if item.get("field_id") == "point_of_interconnection_voltage_kv"
    )
    assert poi_followup["planner_critical"] is True
    assert poi_followup["severity"] == "HIGH"
    assert poi_followup["label"]
    assert poi_followup["search_keywords"]
    assert poi_followup["suggested_sources"]
    assert "point_of_interconnection_voltage_kv" in followup_field_ids



def test_normalization_schema_validation_is_registry_backed() -> None:
    context = SimpleNamespace(
        run_id="run-normalization-registry-schema",
        config=_Config(),
    )

    result = normalize_inputs(
        context=context,
        extraction_result={"entities": [], "topology_cues": [], "canonical_state": {}},
        interview_result=None,
        retrieval_result=None,
    )

    schema_validation = result["validation_report"]["schema_validation"]
    assert schema_validation["planner_registry_backed"] is True
    assert schema_validation["validation_mode"] == "planner_required_fields.normalization_runtime"
    assert schema_validation["required_field_count"] >= 1
    assert schema_validation["missing_required_field_count"] >= 1
