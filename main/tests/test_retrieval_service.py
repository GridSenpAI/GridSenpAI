from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.config import CONFIG
from services.retrieval_service.domain import _candidate_official_web_plan
from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent
from services.retrieval_service.service import (
    _build_agent_generated_queries,
    run_service,
)


@dataclass(slots=True)
class DummyConfig:
    retrieval_config: dict | None = None


@dataclass(slots=True)
class DummyContext:
    run_id: str
    config: DummyConfig
    run_dir: Path | None = None
    input_dir: Path | None = None


def test_retrieval_service_builds_intent_queries_from_missing_fields() -> None:
    context = DummyContext(
        run_id="retrieval_test_001",
        config=DummyConfig(retrieval_config={"top_k": 5, "rerank": False}),
    )

    normalization_result = {
        "normalized_input": {
            "facility": {
                "poi_voltage_kv": None,
                "load_schedule": {
                    "phase_1_mw": None,
                },
                "ups": {
                    "topology": None,
                },
            }
        },
        "validation_report": {
            "missing_fields": [
                "facility.poi_voltage_kv",
                "facility.load_schedule.phase_1_mw",
                "facility.ups.topology",
            ]
        },
    }

    extraction_result = {
        "ontology": [
            {
                "artifact_id": "artifact_001",
                "document_type": "ONE_LINE_DIAGRAM",
                "retrieval_domains": ["poi_voltage", "transformer"],
                "likely_fields": ["facility.poi_voltage_kv"],
            }
        ]
    }

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )

    assert result["run_id"] == "retrieval_test_001"
    assert result["status"] == "EVIDENCE_RETRIEVED"
    assert isinstance(result["queries"], list)
    assert result["queries"]

    intents = {item["intent"] for item in result["queries"]}
    assert "poi_voltage" in intents
    assert "load_schedule" in intents
    assert "ups_topology" in intents


def test_retrieval_service_includes_llm_assistance_block() -> None:
    context = DummyContext(
        run_id="retrieval_test_002",
        config=DummyConfig(retrieval_config={"top_k": 5, "rerank": False}),
    )

    normalization_result = {
        "normalized_input": {"facility": {}},
        "validation_report": {"missing_fields": []},
    }

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result={"ontology": []},
    )

    assert "llm_assistance" in result
    assert isinstance(result["llm_assistance"], dict)
    assert "recommended_next_request" in result


def test_retrieval_service_returns_deterministic_snippet_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = DummyContext(
        run_id="retrieval_test_003",
        config=DummyConfig(retrieval_config={"top_k": 3, "rerank": False}),
    )

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

    extraction_result = {
        "ontology": [
            {
                "artifact_id": "artifact_001",
                "document_type": "ONE_LINE_DIAGRAM",
                "retrieval_domains": ["poi_voltage"],
                "likely_fields": ["facility.poi_voltage_kv"],
            },
            {
                "artifact_id": "artifact_002",
                "document_type": "UPS_SPECIFICATION",
                "retrieval_domains": ["ups_topology", "zip_behavior"],
                "likely_fields": ["facility.ups.topology"],
            },
        ]
    }

    corpora = {
        "interconnection_guidance": [
            {
                "corpus": "interconnection_guidance",
                "source_ref": "poi_guidance.txt",
                "path": Path("/tmp/poi_guidance.txt"),
                "text": "Point of interconnection voltage is documented on the one-line diagram at 138 kV bus.",
                "lowered_text": "point of interconnection voltage is documented on the one-line diagram at 138 kv bus.",
            }
        ],
        "vendor_specs": [
            {
                "corpus": "vendor_specs",
                "source_ref": "ups_spec.txt",
                "path": Path("/tmp/ups_spec.txt"),
                "text": "UPS topology uses double conversion with battery bypass and inverter sections.",
                "lowered_text": "ups topology uses double conversion with battery bypass and inverter sections.",
            }
        ],
        "modeling_refs": [
            {
                "corpus": "modeling_refs",
                "source_ref": "zip_modeling.txt",
                "path": Path("/tmp/zip_modeling.txt"),
                "text": "Constant power UPS behavior is commonly used in ZIP load modeling.",
                "lowered_text": "constant power ups behavior is commonly used in zip load modeling.",
            }
        ],
    }

    monkeypatch.setattr(
        "services.retrieval_service.service._load_corpora",
        lambda: corpora,
    )

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )

    assert result["status"] == "EVIDENCE_RETRIEVED"
    assert isinstance(result["snippets"], list)
    assert result["snippets"]

    snippet_ids: set[str] = set()
    for snippet in result["snippets"]:
        assert isinstance(snippet, dict)
        assert snippet["snippet_id"].startswith("retrieval_test_003_snip_")
        assert snippet["snippet_id"] not in snippet_ids
        snippet_ids.add(snippet["snippet_id"])

        assert isinstance(snippet["corpus"], str) and snippet["corpus"].strip()
        assert isinstance(snippet["source_ref"], str) and snippet["source_ref"].strip()
        assert isinstance(snippet["text"], str) and snippet["text"].strip()
        assert isinstance(snippet["score"], (int, float))
        assert 0.0 < float(snippet["score"]) <= 1.0

        metadata = snippet.get("metadata")
        assert isinstance(metadata, dict)
        assert isinstance(metadata.get("topic"), str) and metadata["topic"].strip()
        assert isinstance(metadata.get("matched_keywords"), list)
        assert metadata["matched_keywords"]
        assert all(isinstance(item, str) and item.strip() for item in metadata["matched_keywords"])

        target_field = metadata.get("target_field")
        assert isinstance(target_field, str) and target_field.strip()

        query_intent = metadata.get("query_intent")
        assert isinstance(query_intent, str) and query_intent.strip()

        query_source = metadata.get("query_source")
        assert isinstance(query_source, str) and query_source.strip()

        source_artifact_ids = metadata.get("source_artifact_ids")
        assert isinstance(source_artifact_ids, list)
        assert all(isinstance(item, str) and item.strip() for item in source_artifact_ids)

    snippet_fields = {
        snippet["metadata"]["target_field"]
        for snippet in result["snippets"]
        if isinstance(snippet.get("metadata"), dict)
    }
    assert "facility.poi_voltage_kv" in snippet_fields
    assert "facility.ups.topology" in snippet_fields


def test_retrieval_service_uses_fallback_queries_when_no_missing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = DummyContext(
        run_id="retrieval_test_004",
        config=DummyConfig(retrieval_config={"top_k": 5, "rerank": False}),
    )

    normalization_result = {
        "normalized_input": {"facility": {}},
        "validation_report": {"missing_fields": []},
    }

    corpora = {
        "interconnection_guidance": [
            {
                "corpus": "interconnection_guidance",
                "source_ref": "poi_fallback.txt",
                "path": Path("/tmp/poi_fallback.txt"),
                "text": "The point of interconnection voltage and substation bus are documented here.",
                "lowered_text": "the point of interconnection voltage and substation bus are documented here.",
            }
        ],
        "vendor_specs": [
            {
                "corpus": "vendor_specs",
                "source_ref": "ups_fallback.txt",
                "path": Path("/tmp/ups_fallback.txt"),
                "text": "UPS battery and inverter topology details are provided in this vendor specification.",
                "lowered_text": "ups battery and inverter topology details are provided in this vendor specification.",
            }
        ],
        "modeling_refs": [
            {
                "corpus": "modeling_refs",
                "source_ref": "load_fallback.txt",
                "path": Path("/tmp/load_fallback.txt"),
                "text": "Load schedule and phase 1 MW buildout guidance are included here.",
                "lowered_text": "load schedule and phase 1 mw buildout guidance are included here.",
            }
        ],
    }

    monkeypatch.setattr(
        "services.retrieval_service.service._load_corpora",
        lambda: corpora,
    )

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result={"ontology": []},
    )

    assert result["status"] == "EVIDENCE_RETRIEVED"
    assert isinstance(result["queries"], list)
    assert result["queries"]

    intents = {item["intent"] for item in result["queries"]}
    assert "ups_topology" in intents
    assert "poi_voltage" in intents
    assert "load_schedule" in intents

    query_sources = {item["query_source"] for item in result["queries"]}
    assert "fallback" in query_sources

    assert isinstance(result["snippets"], list)
    assert result["snippets"]


def test_retrieval_service_enriches_queries_from_ontology_without_duplicate_intents() -> None:
    context = DummyContext(
        run_id="retrieval_test_005",
        config=DummyConfig(retrieval_config={"top_k": 5, "rerank": False}),
    )

    normalization_result = {
        "normalized_input": {
            "facility": {
                "poi_voltage_kv": None,
            }
        },
        "validation_report": {
            "missing_fields": [
                "facility.poi_voltage_kv",
            ]
        },
    }

    extraction_result = {
        "ontology": [
            {
                "artifact_id": "artifact_001",
                "document_type": "ONE_LINE_DIAGRAM",
                "retrieval_domains": ["poi_voltage", "transformer"],
                "likely_fields": ["facility.poi_voltage_kv"],
            },
            {
                "artifact_id": "artifact_002",
                "document_type": "ONE_LINE_DIAGRAM",
                "retrieval_domains": ["poi_voltage"],
                "likely_fields": ["facility.poi_voltage_kv"],
            },
        ]
    }

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )

    assert result["status"] == "EVIDENCE_RETRIEVED"
    assert isinstance(result["queries"], list)
    assert result["queries"]

    poi_queries = [
        item
        for item in result["queries"]
        if item["intent"] == "poi_voltage"
    ]
    assert poi_queries

    unique_keys = {
        (
            item["intent"],
            item.get("target_field", ""),
            item.get("query_source", ""),
        )
        for item in poi_queries
    }
    assert len(unique_keys) == len(poi_queries)

    ontology_queries = [
        item
        for item in result["queries"]
        if item.get("query_source") in {"ontology", "missing_field+ontology"}
    ]
    assert ontology_queries


def test_retrieval_service_preserves_provenance_ready_snippet_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = DummyContext(
        run_id="retrieval_test_006",
        config=DummyConfig(retrieval_config={"top_k": 5, "rerank": False}),
    )

    normalization_result = {
        "normalized_input": {
            "facility": {
                "ups": {"topology": None},
            }
        },
        "validation_report": {
            "missing_fields": [
                "facility.ups.topology",
            ]
        },
    }

    extraction_result = {
        "ontology": [
            {
                "artifact_id": "artifact_ups_001",
                "document_type": "UPS_SPECIFICATION",
                "retrieval_domains": ["ups_topology", "zip_behavior"],
                "likely_fields": ["facility.ups.topology"],
            }
        ]
    }

    corpora = {
        "vendor_specs": [
            {
                "corpus": "vendor_specs",
                "source_ref": "ups_enterprise_spec.txt",
                "path": Path("/tmp/ups_enterprise_spec.txt"),
                "text": "UPS topology is double conversion with battery backup and bypass inverter sections.",
                "lowered_text": "ups topology is double conversion with battery backup and bypass inverter sections.",
            }
        ],
        "modeling_refs": [
            {
                "corpus": "modeling_refs",
                "source_ref": "ups_zip_behavior.txt",
                "path": Path("/tmp/ups_zip_behavior.txt"),
                "text": "Constant power UPS behavior influences ZIP load assumptions.",
                "lowered_text": "constant power ups behavior influences zip load assumptions.",
            }
        ],
        "interconnection_guidance": [],
    }

    monkeypatch.setattr(
        "services.retrieval_service.service._load_corpora",
        lambda: corpora,
    )

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )

    assert result["status"] == "EVIDENCE_RETRIEVED"
    assert result["snippets"]

    for snippet in result["snippets"]:
        metadata = snippet["metadata"]
        assert isinstance(metadata, dict)

        assert "topic" in metadata
        assert "matched_keywords" in metadata
        assert "target_field" in metadata
        assert "query_intent" in metadata
        assert "query_source" in metadata
        assert "source_artifact_ids" in metadata
        assert "source_document_types" in metadata

        assert metadata["target_field"] == "facility.ups.topology"
        assert isinstance(metadata["source_artifact_ids"], list)
        assert metadata["source_artifact_ids"] == ["artifact_ups_001"]
        assert isinstance(metadata["source_document_types"], list)
        assert "UPS_SPECIFICATION" in metadata["source_document_types"]


def test_build_agent_generated_queries_maps_knowledge_families_and_query_plan() -> None:
    queries = _build_agent_generated_queries(
        suggested_query_topics=[
            "UPS topology and operating mode",
            "phase 1 MW buildout schedule",
        ],
        knowledge_family_route=[
            "equipment_references",
            "modeling_references",
        ],
        suggested_queries=[
            {
                "intent": "ups_topology_agent",
                "target_field": "facility.ups.topology",
                "query_text": "UPS topology and operating mode",
                "keywords": ["UPS", "topology", "operating", "mode"],
                "topic": "facility.ups.topology",
            },
            {
                "intent": "load_schedule_agent",
                "query_text": "phase 1 MW buildout schedule",
                "keywords": ["phase", "1", "MW", "buildout", "schedule"],
                "topic": "facility.load_schedule.phase_1_mw",
            },
        ],
        query_plan={
            "missing_fields": [
                "facility.ups.topology",
                "facility.load_schedule.phase_1_mw",
            ]
        },
    )

    assert len(queries) >= 2
    assert all(query["query_source"] == "retrieval_planning_agent" for query in queries)
    assert all("vendor_specs" in query["preferred_corpora"] for query in queries)
    assert all("modeling_refs" in query["preferred_corpora"] for query in queries)
    assert any(query["target_field"] == "facility.ups.topology" for query in queries)
    assert any(query["target_field"] == "facility.load_schedule.phase_1_mw" for query in queries)


def test_retrieval_service_uses_retrieval_planning_agent_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = DummyContext(
            run_id="retrieval_planning_agent_live_test",
            config=DummyConfig(retrieval_config={"top_k": 3, "rerank": False}),
            run_dir=tmp_path / "retrieval_planning_agent_live_test",
        )

        normalization_result = {
            "normalized_input": {
                "facility": {
                    "ups": {"topology": None},
                    "load_schedule": {"phase_1_mw": None},
                }
            },
            "validation_report": {
                "missing_fields": [
                    "facility.ups.topology",
                    "facility.load_schedule.phase_1_mw",
                ]
            },
        }

        extraction_result = {
            "ontology": [
                {
                    "artifact_id": "artifact_001",
                    "document_type": "SUPPORTING_DOCUMENT",
                    "retrieval_domains": ["ups_topology"],
                    "likely_fields": ["facility.ups.topology"],
                }
            ]
        }

        corpora = {
            "interconnection_guidance": [],
            "vendor_specs": [],
            "modeling_refs": [],
        }

        monkeypatch.setattr(
            "services.retrieval_service.service._load_corpora",
            lambda: corpora,
        )

        result = run_service(
            context=context,
            normalization_result=normalization_result,
            extraction_result=extraction_result,
        )

        assert result["status"] == "EVIDENCE_RETRIEVED"
        assert isinstance(result["queries"], list)
        assert isinstance(result["snippets"], list)
        assert isinstance(result["llm_assistance"], dict)

        llm_assistance = result["llm_assistance"]
        assert llm_assistance.get("agent_id") == "retrieval_planning_agent"

        structured_output = llm_assistance.get("structured_output", {})
        assert isinstance(structured_output, dict)
        assert structured_output.get("agent_role") == "retrieval_planning"
        assert "query_plan" in structured_output
        assert "suggested_queries" in structured_output
        assert "recommended_next_request" in structured_output

        evidence_agent = llm_assistance.get("evidence_resolution_agent", {})
        assert isinstance(evidence_agent, dict)
        evidence_structured_output = evidence_agent.get("structured_output", {})
        assert isinstance(evidence_structured_output, dict)
        assert evidence_structured_output.get("agent_role") == "evidence_resolution"
        assert "evidence_findings" in evidence_structured_output

        policy = llm_assistance.get("policy", {})
        assert isinstance(policy, dict)
        assert policy.get("allowed") is True

        warnings = result.get("warnings", [])
        assert isinstance(warnings, list)
        assert result.get("recommended_next_request")

        query_sources = {
            str(query.get("query_source", "")).strip()
            for query in result["queries"]
            if isinstance(query, dict)
        }
        assert "retrieval_planning_agent" in query_sources or "missing_field" in query_sources
        assert "evidence_resolution_agent" in query_sources or "retrieval_planning_agent" in query_sources
    finally:
        CONFIG.model.allow_model_assistance = original_flag

def test_retrieval_service_applies_document_field_pack_suppression(tmp_path: Path) -> None:
    input_dir = tmp_path / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "Attachment_I_Interconnection_Study_Report.pdf").write_text("placeholder", encoding="utf-8")

    context = DummyContext(
        run_id="retrieval_test_005",
        config=DummyConfig(retrieval_config={"top_k": 5, "rerank": False}),
        run_dir=tmp_path / "runs" / "retrieval_test_005",
        input_dir=input_dir,
    )

    normalization_result = {
        "normalized_input": {"facility": {}},
        "validation_report": {
            "missing_fields": [
                "facility.generators.count",
                "facility.generators.ratings",
                "facility.ups.count",
                "facility.ups.topology",
                "facility.transformers.count",
                "facility.relay_settings",
            ]
        },
    }

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result={"ontology": []},
    )

    assert result["status"] == "EVIDENCE_RETRIEVED"
    assert result["document_field_pack"]["field_pack_active"] is True
    assert "interconnection_study" in result["document_field_pack"]["document_classes"]
    assert "facility.generators.count" in result["document_field_pack"]["suppressed_field_paths"]
    assert "facility.ups.topology" in result["document_field_pack"]["suppressed_field_paths"]
    assert "facility.generators.count" not in result["requested_field_paths"]
    assert "facility.ups.topology" not in result["requested_field_paths"]
    assert "facility.transformers.count" in result["requested_field_paths"]
    assert "facility.relay_settings" in result["requested_field_paths"]


def test_retrieval_service_executes_official_web_retrieval_for_official_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = DummyContext(
        run_id="retrieval_test_004",
        config=DummyConfig(retrieval_config={"top_k": 3, "rerank": False}),
    )

    normalization_result = {
        "normalized_input": {"facility": {"poi_voltage_kv": None}},
        "validation_report": {"missing_fields": ["facility.poi_voltage_kv"]},
    }

    extraction_result = {
        "ontology": [
            {
                "artifact_id": "artifact_001",
                "document_type": "INTERCONNECTION_STUDY",
                "retrieval_domains": ["poi_voltage"],
                "likely_fields": ["facility.poi_voltage_kv"],
            }
        ]
    }

    corpora = {
        "interconnection_guidance": [
            {
                "corpus": "interconnection_guidance",
                "source_ref": "pjm_manual_14c",
                "path": Path("/tmp/pjm_manual_14c.txt"),
                "text": "PJM guidance discusses point of interconnection voltage and station configuration.",
                "lowered_text": "pjm guidance discusses point of interconnection voltage and station configuration.",
                "metadata": {
                    "source_kind": "official_interconnection",
                    "document_type": "manual",
                    "document_label": "PJM Manual 14C",
                    "source_domain": "www.pjm.com",
                    "source_url": "https://www.pjm.com/-/media/documents/manuals/m14c.ashx",
                    "source_priority": "official_interconnection",
                    "evidence_tier": "official_interconnection_source",
                    "trust_level": "high",
                    "matched_target_fields": ["facility.poi_voltage_kv"],
                },
            }
        ]
    }

    monkeypatch.setattr(
        "services.retrieval_service.service._load_corpora",
        lambda: corpora,
    )
    monkeypatch.setattr(
        "services.retrieval_service.domain.resolve_equipment_references",
        lambda **kwargs: {
            "snippets": [],
            "warnings": [],
            "official_source_candidates": [],
            "pdf_lookup_plans": [],
            "web_lookup_plans": [],
            "review_required_fields": [],
            "unresolved_missing_fields": [],
            "out_of_scope_missing_fields": [],
            "web_lookup_required": False,
        },
    )
    monkeypatch.setattr(
        "services.retrieval_service.domain._fetch_official_web_text",
        lambda url: "Point of interconnection voltage is 138 kV at the service bus.",
    )

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )

    execution = result["executed_official_web_retrieval"]
    assert execution["attempted_count"] >= 1
    assert execution["executed_count"] >= 1
    assert any(record["field_path"] == "facility.poi_voltage_kv" for record in execution["records"])

    official_web_snippets = [
        item for item in result["snippets"]
        if item.get("corpus") == "official_web"
    ]
    assert official_web_snippets
    metadata = official_web_snippets[0]["metadata"]
    assert metadata["query_source"] == "official_web_execution"
    assert metadata["source_url"] == "https://www.pjm.com/-/media/documents/manuals/m14c.ashx"
    assert metadata["target_field"] == "facility.poi_voltage_kv"


def test_candidate_official_web_plan_dedupes_alias_field_targets_against_canonical_field_path() -> None:
    snippets = [
        {
            "source_ref": "plan_snippet_alias",
            "score": 0.82,
            "metadata": {
                "target_field": "rated_kw",
                "source_url": "https://www.eaton.com/us/en-us/catalog/backup-power-ups-surge-it-power-distribution/93pm-ups.html",
                "source_hierarchy": "official_website",
                "evidence_tier": "official_vendor_document",
                "source_kind": "official_web",
                "document_type": "product_page",
                "document_label": "Eaton 93PM UPS",
            },
        },
        {
            "source_ref": "plan_snippet_canonical",
            "score": 0.76,
            "metadata": {
                "target_field": "facility.ups.rated_kw",
                "source_url": "https://www.eaton.com/us/en-us/catalog/backup-power-ups-surge-it-power-distribution/93pm-ups.html#specifications",
                "source_hierarchy": "official_website",
                "evidence_tier": "official_vendor_document",
                "source_kind": "official_web",
                "document_type": "product_page",
                "document_label": "Eaton 93PM UPS Specs",
            },
        },
    ]
    equipment_result = {
        "candidate_fields": [
            {
                "equipment_family": "ups",
                "canonical_field_key": "facility.ups.rated_kw",
                "matched_field_key": "rated_kw",
            }
        ],
        "equipment_family_order": ["ups"],
        "web_lookup_plans": [
            {
                "missing_fields": ["facility.ups.rated_kw"],
                "allowed_urls": [
                    "https://www.eaton.com/us/en-us/catalog/backup-power-ups-surge-it-power-distribution/93pm-ups.html"
                ],
            }
        ],
    }

    plans = _candidate_official_web_plan(
        snippets=snippets,
        equipment_result=equipment_result,
        field_support_summary={
            "facility.ups.rated_kw": {
                "support_strength": "MODERATE",
            }
        },
        requested_field_paths=["facility.ups.rated_kw"],
        official_web_lookup_required=False,
    )

    assert len(plans) == 1
    assert plans[0]["field_path"] == "facility.ups.rated_kw"
    assert plans[0]["target_field_aliases"] == ["facility.ups.rated_kw", "rated_kw"]
    assert plans[0]["url"] == "https://www.eaton.com/us/en-us/catalog/backup-power-ups-surge-it-power-distribution/93pm-ups.html"


def test_retrieval_service_prefers_exact_model_vendor_evidence_for_capacity_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = DummyContext(
        run_id="retrieval_test_007",
        config=DummyConfig(retrieval_config={"top_k": 2, "rerank": False}),
    )

    normalization_result = {
        "normalized_input": {"facility": {"generators": {"rated_kw": None}}},
        "validation_report": {"missing_fields": ["facility.generators.rated_kw"]},
    }

    extraction_result = {
        "ontology": [
            {
                "artifact_id": "artifact_gen_001",
                "document_type": "GENERATOR_SPECIFICATION",
                "retrieval_domains": ["transformer"],
                "likely_fields": ["facility.generators.rated_kw"],
                "manufacturer": "Cummins",
                "model": "QSK60",
                "equipment_family": "generator",
            }
        ]
    }

    corpora = {
        "vendor_documents": [
            {
                "corpus": "vendor_documents",
                "source_ref": "cummins_qsk60_datasheet.pdf",
                "text": "Cummins QSK60 exact model generator rated power 3000 kW standby output.",
                "lowered_text": "cummins qsk60 exact model generator rated power 3000 kw standby output.",
                "metadata": {
                    "manufacturer": "Cummins",
                    "model": "QSK60",
                    "source_kind": "vendor_document",
                    "document_type": "official_vendor_document",
                    "evidence_tier": "official_vendor_document",
                    "source_priority": "manufacturer_model_specific_spec",
                    "match_reason": "exact_model_match",
                    "matched_target_fields": ["facility.generators.rated_kw"],
                },
            },
            {
                "corpus": "vendor_documents",
                "source_ref": "cummins_family_brochure.pdf",
                "text": "Cummins generator family brochure lists 2750 kW to 3000 kW options.",
                "lowered_text": "cummins generator family brochure lists 2750 kw to 3000 kw options.",
                "metadata": {
                    "manufacturer": "Cummins",
                    "model": "QSK family",
                    "source_kind": "vendor_document",
                    "document_type": "vendor_pdf_pointer",
                    "evidence_tier": "vendor_document_pointer",
                    "source_priority": "vendor_documents",
                    "match_reason": "family_match",
                    "matched_target_fields": ["facility.generators.rated_kw"],
                },
            },
        ],
        "equipment_catalog": [],
        "interconnection_guidance": [],
        "modeling_references": [],
    }

    monkeypatch.setattr("services.retrieval_service.service._load_corpora", lambda: corpora)

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )

    generator_snippets = [
        snippet for snippet in result["snippets"]
        if snippet.get("metadata", {}).get("target_field") == "facility.generators.rated_kw"
    ]
    assert generator_snippets
    assert generator_snippets[0]["source_ref"] == "cummins_qsk60_datasheet.pdf"
    assert generator_snippets[0]["metadata"]["specificity"] == "exact_model_match"


def test_retrieval_planning_agent_returns_source_priority_summary(tmp_path: Path) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = DummyContext(
            run_id="retrieval_test_008",
            config=DummyConfig(retrieval_config={"top_k": 3, "rerank": False}),
            run_dir=tmp_path / "retrieval_test_008",
        )

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="retrieval_planning_agent",
                stage_name="gap_resolution::retrieval",
                task_name="query_review",
                inputs={
                    "queries": [{"query_text": "POI voltage", "keywords": ["poi", "voltage"]}],
                    "snippets": [],
                    "warnings": [],
                    "normalized_input": {"facility": {}},
                    "validation_report": {"missing_fields": ["facility.poi_voltage_kv", "facility.ups.topology"]},
                    "equipment_reference_resolution": {},
                },
            ),
        )

        summary = result["structured_output"]["source_priority_summary"]
        assert isinstance(summary, list)
        assert any(item["field_path"] == "facility.poi_voltage_kv" for item in summary)
        poi_entry = next(item for item in summary if item["field_path"] == "facility.poi_voltage_kv")
        assert poi_entry["preferred_sources"]
    finally:
        CONFIG.model.allow_model_assistance = original_flag
