from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from services.field_resolution_service.service import build_field_resolution_result
from services.retrieval_service.service import run_service


@dataclass(slots=True)
class DummyConfig:
    retrieval_config: dict | None = None


@dataclass(slots=True)
class DummyContext:
    run_id: str
    config: DummyConfig
    run_dir: Path | None = None


def test_retrieval_prefers_official_interconnection_evidence_for_poi_voltage(monkeypatch) -> None:
    context = DummyContext(
        run_id="retrieval_rank_001",
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
        "vendor_documents": [
            {
                "corpus": "vendor_documents",
                "source_ref": "vendor_pointer.txt",
                "text": "A vendor reference mentions POI voltage options around 138 kV in a general brochure.",
                "lowered_text": "a vendor reference mentions poi voltage options around 138 kv in a general brochure.",
                "metadata": {
                    "document_type": "vendor_pdf_pointer",
                    "source_kind": "vendor_document",
                    "evidence_tier": "vendor_document_pointer",
                    "source_priority": "vendor_documents",
                },
            }
        ],
        "modeling_references": [],
        "equipment_catalog": [],
        "vendor_specs": [],
        "modeling_refs": [],
    }

    monkeypatch.setattr("services.retrieval_service.service._load_corpora", lambda: corpora)

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result={"ontology": []},
    )

    poi_snippets = [
        snippet
        for snippet in result["snippets"]
        if snippet.get("metadata", {}).get("target_field") == "facility.poi_voltage_kv"
    ]
    assert poi_snippets
    assert poi_snippets[0]["source_ref"] == "poi_official.txt"
    assert poi_snippets[0]["metadata"]["source_hierarchy"] == "official_interconnection_source"

    support = result["field_support_summary"]["facility.poi_voltage_kv"]
    assert support["official_source_count"] >= 1
    assert support["support_strength"] == "HIGH"


def test_field_resolution_prefers_exact_model_support_over_family_match() -> None:
    canonical_state = {
        "source_candidate_inputs": {
            "retrieval_candidates": [
                {
                    "field_path": "facility.generators.ratings",
                    "value": 3125,
                    "confidence": 0.84,
                    "manufacturer": "Cummins",
                    "model": "QSK60",
                    "equipment_family": "generator",
                    "source_type": "vendor_document",
                    "source_ref": "cummins_qsk60_datasheet.pdf",
                    "source_priority": "model_specific",
                    "source_kind": "vendor_document",
                    "document_type": "official_vendor_document",
                    "evidence_tier": "official_vendor_document",
                    "match_reason": "exact_model_match",
                },
                {
                    "field_path": "facility.generators.ratings",
                    "value": 3000,
                    "confidence": 0.86,
                    "manufacturer": "Cummins",
                    "model": "QSK family",
                    "equipment_family": "generator",
                    "source_type": "vendor_document",
                    "source_ref": "cummins_family_brochure.pdf",
                    "source_priority": "vendor_documents",
                    "source_kind": "vendor_document",
                    "document_type": "vendor_pdf_pointer",
                    "evidence_tier": "vendor_document_pointer",
                    "match_reason": "family_match",
                },
            ],
            "field_support_summary": {
                "facility.generators.ratings": {
                    "support_strength": "HIGH",
                    "exact_model_support_count": 1,
                    "official_source_count": 1,
                    "weak_support_only": False,
                    "best_source_hierarchy": "manufacturer_model_specific_spec",
                    "best_specificity": "exact_model_match",
                }
            },
        }
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")

    assert entry["accepted_value"] == 3125
    assert entry["accepted_specificity"] == "exact_model_match"
    assert entry["accepted_source_hierarchy"] == "manufacturer_model_specific_spec"


def test_field_resolution_demotes_weak_retrieval_only_support_for_planner_critical_field() -> None:
    canonical_state = {
        "source_candidate_inputs": {
            "retrieval_candidates": [
                {
                    "field_path": "telemetry_points_list_present",
                    "value": True,
                    "confidence": 0.91,
                    "source_type": "vendor_document",
                    "source_ref": "brochure_pointer.txt",
                    "source_priority": "vendor_documents",
                    "source_kind": "vendor_document",
                    "document_type": "vendor_pdf_pointer",
                    "evidence_tier": "vendor_document_pointer",
                    "match_reason": "context_inferred",
                }
            ],
            "field_support_summary": {
                "telemetry_points_list_present": {
                    "support_strength": "LOW",
                    "exact_model_support_count": 0,
                    "official_source_count": 0,
                    "weak_support_only": True,
                    "best_source_hierarchy": "vendor_pdf",
                    "best_specificity": "context_inferred",
                }
            },
        }
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "telemetry_points_list_present")

    assert entry["accepted_value"] is True
    assert entry["accepted_status"] == "review_required"
    assert entry["planner_review_flag"] is True
    assert entry["candidate_summary"]["weak_support_only"] is True
