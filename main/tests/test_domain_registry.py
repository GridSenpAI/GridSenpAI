from __future__ import annotations

from shared.schemas.domain_registry import (
    build_registry_summary,
    get_documents_for_field,
    get_extraction_field,
    get_extraction_fields_for_document,
    get_intake_question,
    get_planner_document,
    load_extraction_blueprint,
    load_intake_question_specs,
    load_planner_document_specs,
)


def test_domain_registry_loads_new_shared_json_sources() -> None:
    extraction_fields = load_extraction_blueprint()
    intake_questions = load_intake_question_specs()
    planner_documents = load_planner_document_specs()

    assert extraction_fields
    assert intake_questions
    assert planner_documents

    summary = build_registry_summary()
    assert summary["extraction_field_count"] == len(extraction_fields)
    assert summary["intake_question_count"] == len(intake_questions)
    assert summary["planner_document_count"] == len(planner_documents)
    assert summary["mapped_field_path_count"] > 0
    assert summary["unmapped_field_path_count"] >= 0


def test_domain_registry_supports_lookup_by_field_and_document() -> None:
    extraction_field = get_extraction_field("service_delivery_point_voltage_kv")
    assert extraction_field is not None
    assert extraction_field.field_id == "service_delivery_point_voltage_kv"
    assert extraction_field.field_path == "facility.poi_voltage_kv"

    intake_question = get_intake_question("requested_peak_demand_mw")
    assert intake_question is not None
    assert intake_question.question_id == "REQUESTED_PEAK_DEMAND_MW"
    assert intake_question.question

    planner_document = get_planner_document("Completed utility/ISO load information form")
    assert planner_document is not None
    assert "requested_peak_demand_mw" in planner_document.data_fields_provided

    documents = get_documents_for_field("requested_peak_demand_mw")
    assert documents
    assert any(
        item.document_name == "Completed utility/ISO load information form"
        for item in documents
    )

    extraction_fields = get_extraction_fields_for_document("Completed utility/ISO load information form")
    assert extraction_fields
    assert any(item.field_id == "requested_peak_demand_mw" for item in extraction_fields)