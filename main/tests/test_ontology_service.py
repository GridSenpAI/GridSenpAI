from __future__ import annotations

from services.ontology_service.service import classify_artifacts, classify_single_artifact


def test_classify_single_artifact_detects_one_line_diagram() -> None:
    artifact = {
        "artifact_id": "artifact_001",
        "file_name": "Main One-Line Diagram.pdf",
        "file_suffix": ".pdf",
        "classification": "UNCLASSIFIED",
    }

    result = classify_single_artifact(
        artifact,
        text_content="Bus arrangement, breaker lineup, transformer, point of interconnection at 138 kV.",
    )

    assert result["artifact_id"] == "artifact_001"
    assert result["document_type"] == "ONE_LINE_DIAGRAM"
    assert result["confidence"] in {"MODERATE", "HIGH"}
    assert "poi_voltage" in result["retrieval_domains"]
    assert "facility.poi_voltage_kv" in result["likely_fields"]


def test_classify_artifacts_returns_multiple_document_types() -> None:
    artifacts = [
        {
            "artifact_id": "artifact_001",
            "file_name": "ups_spec_sheet.txt",
            "file_suffix": ".txt",
            "classification": "UNCLASSIFIED",
        },
        {
            "artifact_id": "artifact_002",
            "file_name": "load_schedule.csv",
            "file_suffix": ".csv",
            "classification": "UNCLASSIFIED",
        },
    ]

    results = classify_artifacts(
        artifacts,
        text_by_artifact_id={
            "artifact_001": "UPS inverter battery bypass static switch double conversion",
            "artifact_002": "Phase 1 MW Phase 2 MW buildout load schedule ramp",
        },
    )

    assert len(results) == 2

    by_id = {item["artifact_id"]: item for item in results}
    assert by_id["artifact_001"]["document_type"] == "UPS_SPECIFICATION"
    assert by_id["artifact_002"]["document_type"] == "LOAD_SCHEDULE"


def test_classify_single_artifact_surfaces_role_family_and_worker_bias() -> None:
    artifact = {
        "artifact_id": "artifact_schedule",
        "file_name": "switchgear_schedule.csv",
        "file_suffix": ".csv",
        "classification": "UNCLASSIFIED",
    }

    result = classify_single_artifact(
        artifact,
        text_content="switchgear schedule bus rating interrupting rating nameplate",
    )

    assert result["document_role"] == "equipment_schedule"
    assert result["document_family"] == "schedule"
    assert "table_worker" in result["worker_bias"]
