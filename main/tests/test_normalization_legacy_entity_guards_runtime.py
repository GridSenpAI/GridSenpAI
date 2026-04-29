from __future__ import annotations

from types import SimpleNamespace

from services.normalization_service.service import normalize_inputs


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(run_id="legacy_guard_test", config=SimpleNamespace(schema_version_input="test-schema"))


def test_explicit_schedule_counts_are_not_incremented_by_legacy_entities() -> None:
    result = normalize_inputs(
        _ctx(),
        {
            "schema_field_candidates": [
                {
                    "field_path": "generator_unit_count",
                    "value": 60,
                    "confidence": "HIGH",
                    "method": "major equipment schedule campus quantity units total",
                    "document_role": "equipment_schedule",
                },
                {
                    "field_path": "interconnection_transformer_unit_count",
                    "value": 3,
                    "confidence": "HIGH",
                    "method": "major equipment schedule campus quantity units total",
                    "document_role": "equipment_schedule",
                },
            ],
            "entities": [
                {"type": "generator", "name": "GEN-001 drawing label", "confidence": "HIGH", "attributes": {}},
                {"type": "generator", "name": "GEN-002 drawing label", "confidence": "HIGH", "attributes": {}},
                {"type": "transformer", "name": "T-1 drawing label", "confidence": "HIGH", "attributes": {}},
            ],
            "topology_cues": [],
            "canonical_state": {},
        },
    )

    facility = result["normalized_input"]["facility"]
    assert facility["generators"]["count"] == 60
    assert facility["transformers"]["count"] == 3
    rejected_decisions = [item["decision"] for item in result["rejected_updates"]]
    assert "REJECTED_LEGACY_ENTITY_INFERENCE" in rejected_decisions


def test_generic_voltage_and_mw_entities_do_not_override_explicit_field_candidates() -> None:
    result = normalize_inputs(
        _ctx(),
        {
            "schema_field_candidates": [
                {
                    "field_path": "nominal_poi_voltage_kv",
                    "value": 138,
                    "confidence": "HIGH",
                    "method": "electrical characteristics nominal service voltage point of interconnection",
                    "document_role": "application_request_form",
                },
                {
                    "field_path": "facility.load_schedule.phase_1_mw",
                    "value": 60,
                    "confidence": "HIGH",
                    "method": "project summary load schedule phase 1 demand mw",
                    "document_role": "project_summary_load_schedule",
                },
            ],
            "entities": [
                {
                    "type": "voltage_value",
                    "name": "main switchgear campus medium-voltage distribution 13.8 kV",
                    "confidence": "HIGH",
                    "attributes": {"value": 13.8},
                },
                {
                    "type": "mw_value",
                    "name": "generator rating 180 MW",
                    "confidence": "HIGH",
                    "attributes": {"value": 180},
                },
            ],
            "topology_cues": [],
            "canonical_state": {},
        },
    )

    facility = result["normalized_input"]["facility"]
    assert facility["poi_voltage_kv"] == 138
    assert facility["load_schedule"]["phase_1_mw"] == 60
    rejected_reasons = " ".join(item["reason"] for item in result["rejected_updates"])
    assert "generic voltage entity" in rejected_reasons
    assert "generic MW entity" in rejected_reasons
