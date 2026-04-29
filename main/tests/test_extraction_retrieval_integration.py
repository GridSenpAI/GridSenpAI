from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from services.extraction_service.service import run_service as run_extraction_service
from services.retrieval_service.service import run_service as run_retrieval_service


class _DummyConfig(SimpleNamespace):
    retrieval_config: dict | None = None


def _build_context(*, project_root: Path, input_dir: Path, run_id: str, project_name: str):
    run_dir = project_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        run_id=run_id,
        project_root=project_root,
        input_dir=input_dir,
        output_dir=run_dir / "outputs",
        run_dir=run_dir,
        config=_DummyConfig(project_name=project_name, retrieval_config={"top_k": 3, "rerank": False}),
    )


def test_extraction_and_retrieval_coordinate_for_missing_planner_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = input_dir / "facility_one_line.txt"
    artifact_path.write_text(
        "Point of Interconnection: North POI 138 kV\nGenerator count 6\n",
        encoding="utf-8",
    )

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_extract_retrieve_001",
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

    extraction_result = run_extraction_service(context=context, ingestion_result=ingestion_result)

    corpora = {
        "interconnection_guidance": [
            {
                "corpus": "interconnection_guidance",
                "source_ref": "poi_guidance.txt",
                "path": Path("/tmp/poi_guidance.txt"),
                "text": "Point of interconnection voltage is documented on the one-line diagram at 138 kV bus.",
                "lowered_text": "point of interconnection voltage is documented on the one-line diagram at 138 kv bus.",
                "metadata": {"source_kind": "interconnection_guidance"},
            }
        ],
        "vendor_documents": [
            {
                "corpus": "vendor_documents",
                "source_ref": "ups_spec.txt",
                "path": Path("/tmp/ups_spec.txt"),
                "text": "UPS topology uses double conversion with battery bypass and inverter sections.",
                "lowered_text": "ups topology uses double conversion with battery bypass and inverter sections.",
                "metadata": {"source_kind": "vendor_document", "document_type": "official_vendor_document"},
            }
        ],
        "modeling_references": [
            {
                "corpus": "modeling_references",
                "source_ref": "zip_modeling.txt",
                "path": Path("/tmp/zip_modeling.txt"),
                "text": "Constant power UPS behavior is commonly used in ZIP load modeling.",
                "lowered_text": "constant power ups behavior is commonly used in zip load modeling.",
                "metadata": {"source_kind": "modeling_reference"},
            }
        ],
        "equipment_catalog": [],
    }
    monkeypatch.setattr("services.retrieval_service.service._load_corpora", lambda: corpora)

    normalization_result = {
        "normalized_input": {
            "facility": {
                "poi_voltage_kv": None,
                "ups": {"topology": None},
            }
        },
        "validation_report": {
            "missing_fields": [
                "facility.poi_voltage_kv",
                "facility.ups.topology",
            ]
        },
    }

    retrieval_result = run_retrieval_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )

    assert extraction_result["schema_field_candidates"]
    assert retrieval_result["status"] == "EVIDENCE_RETRIEVED"
    assert retrieval_result["queries"]
    assert retrieval_result["snippets"]

    intents = {item["intent"] for item in retrieval_result["queries"]}
    assert "poi_voltage" in intents
    assert "ups_topology" in intents

    target_fields = {snippet["metadata"]["target_field"] for snippet in retrieval_result["snippets"]}
    assert "facility.poi_voltage_kv" in target_fields
    assert "facility.ups.topology" in target_fields
