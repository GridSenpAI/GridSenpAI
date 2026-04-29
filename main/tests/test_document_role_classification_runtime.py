from __future__ import annotations

from services.ontology_service.service import classify_single_artifact


def test_request_form_classifies_from_headings_without_filename_hint() -> None:
    result = classify_single_artifact(
        {
            "artifact_id": "artifact_request",
            "file_name": "artifact_001.pdf",
            "file_suffix": ".pdf",
            "classification": "UNCLASSIFIED",
        },
        text_content=(
            "Project Identification Primary Contacts Electrical Characteristics "
            "Nominal service voltage 138 kV Requested in-service date Transmission Provider Applicant Owner"
        ),
    )

    assert result["document_type"] == "LARGE_LOAD_REQUEST_FORM"
    assert result["document_role"] == "application_request_form"
    assert result["metadata"]["source_authority_hint"] == "applicant_direct_document"
    assert "facility.poi_voltage_kv" in result["likely_fields"]


def test_equipment_schedule_classifies_from_table_vocabulary_without_filename_hint() -> None:
    result = classify_single_artifact(
        {
            "artifact_id": "artifact_equipment",
            "file_name": "attachment_b.pdf",
            "file_suffix": ".pdf",
            "classification": "UNCLASSIFIED",
        },
        text_content=(
            "Major Equipment Schedule and Technical Particulars Planning item Assumed value "
            "Main Power Transformers Campus quantity Units total Standby Generation Platform UPS Platform"
        ),
    )

    assert result["document_type"] == "EQUIPMENT_SCHEDULE"
    assert result["document_role"] == "equipment_schedule"
    assert "table_worker" in result["worker_bias"]
    assert "facility.transformers.count" in result["likely_fields"]


def test_one_line_diagram_classifies_from_drawing_signals_without_filename_hint() -> None:
    result = classify_single_artifact(
        {
            "artifact_id": "artifact_drawing",
            "file_name": "sheet_05.pdf",
            "file_suffix": ".pdf",
            "classification": "UNCLASSIFIED",
        },
        text_content=(
            "Single Line Diagram 138 kV Point of Interconnection Device 52 breaker CT PT bus "
            "transformer feeder switchyard substation"
        ),
    )

    assert result["document_type"] == "ONE_LINE_DIAGRAM"
    assert result["document_role"] == "one_line"
    assert result["document_family"] == "drawing"
    assert result["metadata"]["source_authority_hint"] == "applicant_direct_drawing"


def test_metering_scada_and_phasing_roles_are_distinct() -> None:
    metering = classify_single_artifact(
        {"artifact_id": "m", "file_name": "control.pdf", "file_suffix": ".pdf"},
        text_content="Revenue meter RTU gateway telemetry SCADA point list control center metering cabinet",
    )
    phasing = classify_single_artifact(
        {"artifact_id": "p", "file_name": "milestones.pdf", "file_suffix": ".pdf"},
        text_content="Construction phasing energization plan target date commissioning deliverables initial energization",
    )

    assert metering["document_type"] == "METERING_SCADA_TELEMETRY"
    assert metering["document_role"] == "metering_scada"
    assert phasing["document_type"] == "PHASING_ENERGIZATION_PLAN"
    assert phasing["document_role"] == "phasing_energization_plan"
