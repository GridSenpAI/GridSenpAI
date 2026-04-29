from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services.extraction_service.service import run_service


def _build_context(*, project_root: Path, input_dir: Path, run_id: str, project_name: str):
    run_dir = project_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        run_id=run_id,
        project_root=project_root,
        input_dir=input_dir,
        output_dir=run_dir / "outputs",
        run_dir=run_dir,
        config=SimpleNamespace(project_name=project_name),
    )


def test_extraction_service_emits_structured_entities_and_source_anchors(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = input_dir / "facility_one_line.txt"
    artifact_path.write_text(
        "\n".join(
            [
                "Point of Interconnection: North POI 138 kV",
                "Peak demand 125 MW",
                "2 transformers rated 50 MVA each",
                "Generator count 6",
                "UPS topology double conversion",
            ]
        ),
        encoding="utf-8",
    )

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_entity_observation_001",
        project_name="Test Project",
    )

    ingestion_result = {
        "run_id": context.run_id,
        "status": "ARTIFACTS_INGESTED",
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "file_name": artifact_path.name,
                "file_path": str(artifact_path),
                "classification": "one_line_diagram",
            }
        ],
    }

    result = run_service(context=context, ingestion_result=ingestion_result)

    assert result["status"] == "EXTRACTED"
    assert result["entities"]
    assert result["source_anchors"]
    assert result["schema_field_candidates"]

    entity_types = {str(item.get("type", "")).lower() for item in result["entities"] if isinstance(item, dict)}
    assert "voltage_value" in entity_types
    assert "mw_value" in entity_types
    assert "transformer_rating" in entity_types

    field_paths = {item["field_path"] for item in result["schema_field_candidates"]}
    assert "facility.transformers.count" in field_paths
    assert "facility.ups.count" in field_paths
    ontology_field_hints = {field for item in result["ontology"] for field in item.get("likely_fields", []) if isinstance(item, dict)}
    assert "facility.poi_voltage_kv" in ontology_field_hints
    assert "facility.transformers.ratings_mva" in ontology_field_hints
    assert any(anchor.get("artifact_id") == "artifact_001" for anchor in result["source_anchors"])
