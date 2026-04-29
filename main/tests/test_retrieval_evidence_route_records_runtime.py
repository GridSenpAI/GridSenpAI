from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from services.retrieval_service.service import run_service


@dataclass(slots=True)
class DummyConfig:
    retrieval_config: dict | None = None


@dataclass(slots=True)
class DummyContext:
    run_id: str
    config: DummyConfig
    run_dir: Path | None = None


def test_retrieval_service_builds_per_field_evidence_route_records(monkeypatch) -> None:
    context = DummyContext(
        run_id="retrieval_route_record_001",
        config=DummyConfig(retrieval_config={"top_k": 3, "rerank": False}),
    )
    normalization_result = {
        "normalized_input": {"facility": {"poi_voltage_kv": None}},
        "validation_report": {"missing_fields": ["facility.poi_voltage_kv"]},
    }
    corpora = {
        "interconnection_guidance": [
            {
                "corpus": "interconnection_guidance",
                "source_ref": "poi_official.txt",
                "text": "Official utility interconnection guide states the point of interconnection is 138 kV.",
                "lowered_text": "official utility interconnection guide states the point of interconnection is 138 kv.",
                "metadata": {
                    "document_type": "official_interconnection_guide",
                    "source_kind": "official_web",
                    "evidence_tier": "official_interconnection_source",
                    "source_priority": "official_interconnection",
                    "trust_level": "high",
                },
            }
        ],
        "vendor_specs": [],
        "vendor_documents": [],
        "modeling_refs": [],
        "modeling_references": [],
        "equipment_catalog": [],
    }
    monkeypatch.setattr("services.retrieval_service.service._load_corpora", lambda: corpora)

    result = run_service(context=context, normalization_result=normalization_result, extraction_result={"ontology": []})

    route = next(item for item in result["evidence_route_records"] if item["field_path"] == "facility.poi_voltage_kv")
    assert route["route_status"] == "supported"
    assert route["best_source_hierarchy"] == "official_interconnection_source"
    assert route["support_strength"] == "HIGH"
    assert "missing_field" in route["query_sources"]
    assert route["query_count"] >= 1
    assert route["snippet_count"] >= 1
    assert route["why_route_was_selected"]
