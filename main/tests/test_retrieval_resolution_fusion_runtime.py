from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from services.canonical_state_service.service import build_canonical_state
from services.retrieval_service.service import run_service as run_retrieval_service
from services.field_resolution_service.service import build_field_resolution_result


@dataclass(slots=True)
class DummyConfig:
    retrieval_config: dict | None = None
    schema_version_input: str = "0.1.0"
    schema_version_output: str = "0.1.0"
    project_name: str = "GridSenpAI Test Project"


@dataclass(slots=True)
class DummyContext:
    run_id: str
    run_dir: Path
    config: DummyConfig


def test_retrieval_service_emits_field_support_summary(tmp_path: Path) -> None:
    context = DummyContext(
        run_id="retrieval_support_001",
        run_dir=tmp_path / "retrieval_support_001",
        config=DummyConfig(retrieval_config={"top_k": 3, "rerank": False}),
    )

    normalization_result = {
        "normalized_input": {"facility": {"ups": {"topology": None}}},
        "validation_report": {"missing_fields": ["facility.ups.topology"]},
    }
    extraction_result = {"ontology": []}
    retrieval_result = run_retrieval_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )

    summary = retrieval_result["field_support_summary"]
    assert isinstance(summary, dict) and summary
    item = summary["facility.ups.topology"]
    assert item["field_path"] == "facility.ups.topology"
    assert "support_strength" in item
    assert "source_refs" in item
    assert isinstance(item["weak_support_only"], bool)


def test_canonical_state_preserves_retrieval_candidate_metadata_for_field_resolution(tmp_path: Path) -> None:
    context = DummyContext(
        run_id="retrieval_support_002",
        run_dir=tmp_path / "retrieval_support_002",
        config=DummyConfig(),
    )

    retrieval_result = {
        "run_id": context.run_id,
        "status": "EVIDENCE_RETRIEVED",
        "snippets": [],
        "equipment_reference_resolution": {
            "candidate_fields": [
                {
                    "equipment_family": "generators",
                    "manufacturer": "Cummins",
                    "model": "C3000D6EB",
                    "spec_field": "rated_power_kw",
                    "matched_field_key": "generator_rated_kw_per_unit",
                    "canonical_field_key": "generator_rated_kw_per_unit",
                    "value": 3000,
                    "source_type": "knowledge_library_match",
                    "source_ref": "knowledge/vendor/cummins/c3000.json",
                    "source_url": "https://example.com/c3000",
                    "confidence": 0.86,
                    "confidence_reason": "Exact manufacturer and model match from structured library.",
                    "source_priority": "manufacturer_model_specific_spec",
                    "source_kind": "equipment_catalog",
                    "document_type": "official_vendor_document",
                    "document_path": "knowledge/vendor/cummins/c3000.json",
                    "evidence_tier": "official_vendor_document",
                    "match_reason": "exact_model_match",
                    "evidence_text": "Rated power: 3000 kW standby",
                    "review_required": False,
                }
            ],
            "unresolved_missing_fields": [],
            "matched_records": [],
            "pdf_repository_candidates": [],
            "pdf_lookup_plans": [],
            "official_source_candidates": [],
            "web_lookup_plans": [],
            "lookup_strategy": "library_then_pdf_then_official_web",
        },
    }

    canonical = build_canonical_state(
        context=context,
        ingestion_result={"run_id": context.run_id, "status": "ARTIFACTS_INGESTED", "artifacts": []},
        extraction_result={"run_id": context.run_id, "status": "EXTRACTED", "entities": [], "topology_cues": [], "source_anchors": []},
        interview_result={"run_id": context.run_id, "status": "QUESTIONS_GENERATED", "answers_confirmed": [], "clarifications": []},
        normalization_result={
            "run_id": context.run_id,
            "status": "NORMALIZED",
            "normalized_input": {"run_id": context.run_id, "schema_version": "0.1.0", "facility": {"project_name": "GridSenpAI Test Project"}},
            "validation_report": {"errors": [], "warnings": [], "missing_fields": [], "conflicts": [], "schema_valid": False},
            "followup_questions": [],
        },
        retrieval_result=retrieval_result,
        translation_result={"run_id": context.run_id, "status": "TRANSLATED", "model_outputs": {"schema_version": "0.1.0"}, "output_parameters": [], "assumptions": []},
    )

    candidate_inputs = canonical["canonical_state"]["source_candidate_inputs"]
    retrieval_candidates = candidate_inputs["retrieval_candidates"]
    assert retrieval_candidates
    candidate = retrieval_candidates[0]
    assert candidate["source_priority"] == "manufacturer_model_specific_spec"
    assert candidate["document_type"] == "official_vendor_document"
    assert candidate["evidence_tier"] == "official_vendor_document"
    assert candidate["match_reason"] == "exact_model_match"

    resolution = build_field_resolution_result(canonical["canonical_state"])
    entry = next(item for item in resolution["ledger"] if item["field_id"] == "generator_rated_kw_per_unit")
    assert entry["accepted_source_hierarchy"] == "manufacturer_model_specific_spec"
    assert entry["accepted_specificity"] == "exact_model_match"
    assert entry["accepted_value"] == 3000
