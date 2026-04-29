from types import SimpleNamespace

from services.extraction_service.service import run_service


def _build_context() -> SimpleNamespace:
    return SimpleNamespace(run_id="test_run_001")


def test_extraction_service_merges_drawing_candidates_into_entities() -> None:
    context = _build_context()

    ingestion_result = {
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "artifact_type": "one_line_diagram",
                "classification": "one_line_diagram",
                "file_name": "facility_one_line.pdf",
                "relative_path": "facility_one_line.pdf",
                "text": "TX-1 TX-2 GEN-1 UPS-1 ring bus",
            }
        ]
    }

    result = run_service(
        context=context,
        ingestion_result=ingestion_result,
        document_parser_result=None,
        layout_analysis_result=None,
        ocr_result=None,
    )

    entities = result["entities"]
    topology_cues = result["topology_cues"]
    source_anchors = result["source_anchors"]

    assert result["status"] == "EXTRACTED"
    assert isinstance(entities, list)
    assert isinstance(topology_cues, list)
    assert isinstance(source_anchors, list)

    field_paths = {
        entity["attributes"].get("parameter_path")
        for entity in entities
        if isinstance(entity, dict)
        and isinstance(entity.get("attributes"), dict)
    }

    assert "facility.transformers.count" in field_paths
    assert "facility.generators.count" in field_paths
    assert "facility.ups.count" in field_paths

    drawing_entities = [
        entity
        for entity in entities
        if entity.get("attributes", {}).get("extraction_method") == "drawing_interpretation"
    ]
    assert drawing_entities

    drawing_topology = [
        cue for cue in topology_cues if cue.get("source") == "drawing_interpretation"
    ]
    assert drawing_topology

    drawing_anchor_ids = {
        anchor["anchor_id"]
        for anchor in source_anchors
        if isinstance(anchor, dict) and "anchor_id" in anchor
    }
    assert drawing_anchor_ids


def test_extraction_service_preserves_existing_text_extraction_when_no_drawing_match() -> None:
    context = _build_context()

    ingestion_result = {
        "artifacts": [
            {
                "artifact_id": "artifact_002",
                "artifact_type": "equipment_schedule",
                "classification": "equipment_schedule",
                "file_name": "equipment_schedule.pdf",
                "relative_path": "equipment_schedule.pdf",
                "text": "Service voltage 138 kV and peak load 75 MW.",
            }
        ]
    }

    result = run_service(
        context=context,
        ingestion_result=ingestion_result,
        document_parser_result=None,
        layout_analysis_result=None,
        ocr_result=None,
    )

    entities = result["entities"]

    assert result["status"] == "EXTRACTED"
    assert isinstance(entities, list)
    assert entities

    drawing_entities = [
        entity
        for entity in entities
        if entity.get("attributes", {}).get("extraction_method") == "drawing_interpretation"
    ]
    assert drawing_entities == []