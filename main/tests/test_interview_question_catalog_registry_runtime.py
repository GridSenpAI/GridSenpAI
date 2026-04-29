from __future__ import annotations

from services.interview_service.question_catalog import (
    LEGACY_QUESTION_CATALOG,
    build_question_metadata,
    get_question_by_field_path,
    get_question_by_id,
    get_question_catalog,
)


def test_registry_backed_question_catalog_avoids_legacy_only_fallback_questions() -> None:
    catalog = get_question_catalog()
    assert catalog
    assert all(bool(question.metadata.get("registry_backed", False)) for question in catalog)

    registry_field_paths = {question.field_path for question in catalog}
    legacy_only_paths = {
        question.field_path
        for question in LEGACY_QUESTION_CATALOG
        if question.field_path not in registry_field_paths
    }
    assert legacy_only_paths
    assert all(get_question_by_field_path(field_path) is None for field_path in legacy_only_paths)


def test_legacy_question_ids_alias_to_registry_backed_questions_when_field_path_matches() -> None:
    aliased = get_question_by_id("FACILITY_POI_VOLTAGE_KV")
    assert aliased is not None
    assert aliased.field_path == "facility.poi_voltage_kv"
    assert aliased.metadata.get("registry_backed", False) is True


def test_build_question_metadata_prefers_registry_catalog() -> None:
    question_id, prompt = build_question_metadata("facility.poi_voltage_kv")
    assert question_id
    lowered = prompt.lower()
    assert "voltage" in lowered and "required for the planner packet" in lowered
