from __future__ import annotations

from services.retrieval_service.service import _compact_queries_for_agent, _compact_snippets_for_agent


def test_retrieval_agent_payload_is_tightly_bounded_and_prioritized() -> None:
    queries = [{"intent": f"intent_{index}", "target_field": "facility.poi_voltage_kv" if index == 0 else f"field_{index}", "query_text": "point of interconnection voltage substation bus interconnect kv and additional context text", "keywords": ["poi", "point of interconnection", "voltage", "substation", "bus", "kv", "extra"], "topic": "facility.poi_voltage_kv", "preferred_corpora": ["interconnection_guidance", "vendor_documents", "modeling_references"], "query_source": "missing_field+ontology" if index == 0 else "fallback"} for index in range(8)]
    snippets = [{"corpus": "interconnection_guidance", "source_ref": f"source_{index}.txt", "text": "Official utility interconnection source text " * 20, "score": 0.9 - (index * 0.01), "metadata": {"target_field": "facility.poi_voltage_kv" if index == 0 else f"field_{index}", "query_intent": "poi_voltage", "query_source": "missing_field+ontology" if index == 0 else "fallback", "matched_keywords": ["poi", "voltage", "substation", "bus", "kv", "extra"], "evidence_tier": "official_interconnection_source", "source_hierarchy": "official_interconnection_source" if index == 0 else "vendor_pdf"}} for index in range(10)]
    compact_queries = _compact_queries_for_agent(queries)
    compact_snippets = _compact_snippets_for_agent(snippets)
    assert len(compact_queries) <= 4
    assert len(compact_snippets) <= 6
    assert compact_queries[0]["target_field"] == "facility.poi_voltage_kv"
    assert compact_snippets[0]["target_field"] == "facility.poi_voltage_kv"
    assert len(compact_queries[0]["query_text"]) <= 96
    assert len(compact_snippets[0]["text"]) <= 160
