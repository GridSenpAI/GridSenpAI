from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent
from shared.runtime_stage_contract import GAP_RESOLUTION_RETRIEVAL_STAGE
from shared.knowledge_routes import (
    KNOWLEDGE_ROOT,
    canonical_knowledge_family,
    canonical_family_route,
    corpus_source_paths,
    knowledge_route_status,
    preferred_corpora as canonical_preferred_corpora,
)
from shared.knowledge_index import load_corpus_entries
from shared.planner_registry import (
    field_label_for_path,
    field_resolution_field_type,
    normalization_required_field_ids,
    planner_critical_for_path,
    preferred_corpora_for_field,
    preferred_sources_for_field,
    registry_field_id_for_path,
    search_keywords_for_field,
)

AGENT_QUERY_LIMIT = 4
AGENT_SNIPPET_LIMIT = 6
AGENT_QUERY_TEXT_LIMIT = 96
AGENT_SNIPPET_TEXT_LIMIT = 160

FALLBACK_QUERY_SPECS: list[dict[str, Any]] = [
    {
        "intent": "poi_voltage",
        "target_field": "facility.poi_voltage_kv",
        "query_text": "point of interconnection voltage substation bus interconnect kv",
        "keywords": ["poi", "point of interconnection", "voltage", "bus", "substation", "kv"],
        "topic": "facility.poi_voltage_kv",
        "preferred_corpora": ["interconnection_guidance", "modeling_references"],
    },
    {
        "intent": "load_schedule",
        "target_field": "facility.load_schedule.phase_1_mw",
        "query_text": "load schedule phase 1 mw buildout ramp initial demand",
        "keywords": ["load", "schedule", "phase 1", "mw", "buildout", "demand", "ramp"],
        "topic": "facility.load_schedule.phase_1_mw",
        "preferred_corpora": ["modeling_references", "interconnection_guidance"],
    },
    {
        "intent": "ups_topology",
        "target_field": "facility.ups.topology",
        "query_text": "ups topology double conversion battery bypass inverter",
        "keywords": ["ups", "topology", "double conversion", "battery", "bypass", "inverter"],
        "topic": "facility.ups.topology",
        "preferred_corpora": ["equipment_catalog", "vendor_documents", "modeling_references"],
    },
]

FIELD_QUERY_SPECS: dict[str, dict[str, Any]] = {
    "facility.poi_voltage_kv": {
        "intent": "poi_voltage",
        "query_text": "point of interconnection voltage substation bus interconnect kv",
        "keywords": ["poi", "point of interconnection", "voltage", "bus", "substation", "kv"],
        "topic": "facility.poi_voltage_kv",
        "preferred_corpora": ["interconnection_guidance", "modeling_references"],
    },
    "facility.load_schedule.phase_1_mw": {
        "intent": "load_schedule",
        "query_text": "load schedule phase 1 mw buildout ramp initial demand",
        "keywords": ["load", "schedule", "phase 1", "mw", "buildout", "demand", "ramp"],
        "topic": "facility.load_schedule.phase_1_mw",
        "preferred_corpora": ["modeling_references", "interconnection_guidance"],
    },
    "facility.ups.topology": {
        "intent": "ups_topology",
        "query_text": "ups topology double conversion battery bypass inverter",
        "keywords": ["ups", "topology", "double conversion", "battery", "bypass", "inverter"],
        "topic": "facility.ups.topology",
        "preferred_corpora": ["equipment_catalog", "vendor_documents", "modeling_references"],
    },
}

ONTOLOGY_DOMAIN_SPECS: dict[str, dict[str, Any]] = {
    "poi_voltage": {
        "intent": "poi_voltage",
        "target_field": "facility.poi_voltage_kv",
        "query_text": "point of interconnection voltage substation bus interconnect kv",
        "keywords": ["poi", "point of interconnection", "voltage", "bus", "substation", "kv"],
        "topic": "facility.poi_voltage_kv",
        "preferred_corpora": ["interconnection_guidance", "modeling_references"],
    },
    "transformer": {
        "intent": "transformer",
        "target_field": "facility.transformers.ratings_mva",
        "query_text": "transformer rating mva winding substation service transformer",
        "keywords": ["transformer", "mva", "winding", "substation", "service transformer"],
        "topic": "facility.transformers.ratings_mva",
        "preferred_corpora": ["interconnection_guidance", "equipment_catalog"],
    },
    "ups_topology": {
        "intent": "ups_topology",
        "target_field": "facility.ups.topology",
        "query_text": "ups topology double conversion battery bypass inverter",
        "keywords": ["ups", "topology", "double conversion", "battery", "bypass", "inverter"],
        "topic": "facility.ups.topology",
        "preferred_corpora": ["equipment_catalog", "vendor_documents", "modeling_references"],
    },
    "zip_behavior": {
        "intent": "zip_behavior",
        "target_field": "facility.ups.topology",
        "query_text": "constant power ups zip load behavior modeling",
        "keywords": ["constant power", "ups", "zip", "load", "behavior", "modeling"],
        "topic": "facility.ups.topology",
        "preferred_corpora": ["modeling_references", "equipment_catalog", "vendor_documents"],
    },
}




SOURCE_PRIORITY_BOOSTS: dict[str, float] = {
    "official_interconnection": 0.14,
    "official_interconnection_source": 0.14,
    "model_specific": 0.12,
    "manufacturer_model_specific_spec": 0.12,
    "direct_document": 0.10,
    "equipment_catalog": 0.08,
    "official_web": 0.08,
    "vendor_documents": 0.05,
    "family": 0.03,
    "vendor_pdf_pointer": -0.03,
    "secondary_web": -0.06,
}

SPECIFICITY_BOOSTS: dict[str, float] = {
    "exact_model_match": 0.12,
    "exact_instance_match": 0.10,
    "direct_field_match": 0.08,
    "family_match": 0.04,
    "category_match": 0.01,
    "context_inferred": -0.03,
}

SOURCE_HIERARCHY_PRIORITY: dict[str, int] = {
    "official_interconnection_source": 5,
    "manufacturer_model_specific_spec": 4,
    "manufacturer_family_spec": 3,
    "official_website": 2,
    "vendor_pdf": 1,
    "secondary_web": 0,
}

SPECIFICITY_PRIORITY: dict[str, int] = {
    "exact_model_match": 4,
    "exact_instance_match": 3,
    "direct_field_match": 2,
    "family_match": 1,
    "category_match": 0,
    "context_inferred": -1,
}

FIELD_TYPE_SOURCE_PREFERENCES: dict[str, tuple[str, ...]] = {
    "capacity": (
        "manufacturer_model_specific_spec",
        "manufacturer_family_spec",
        "official_website",
        "vendor_pdf",
        "official_interconnection_source",
        "secondary_web",
    ),
    "identity": (
        "manufacturer_model_specific_spec",
        "manufacturer_family_spec",
        "official_website",
        "vendor_pdf",
        "official_interconnection_source",
        "secondary_web",
    ),
    "voltage": (
        "official_interconnection_source",
        "manufacturer_model_specific_spec",
        "manufacturer_family_spec",
        "official_website",
        "vendor_pdf",
        "secondary_web",
    ),
    "topology": (
        "official_interconnection_source",
        "manufacturer_model_specific_spec",
        "manufacturer_family_spec",
        "vendor_pdf",
        "official_website",
        "secondary_web",
    ),
    "protection": (
        "official_interconnection_source",
        "manufacturer_model_specific_spec",
        "vendor_pdf",
        "official_website",
        "secondary_web",
    ),
    "telemetry": (
        "official_interconnection_source",
        "manufacturer_model_specific_spec",
        "vendor_pdf",
        "official_website",
        "secondary_web",
    ),
}


def _target_field_type(target_field: str) -> str:
    field_id = registry_field_id_for_path(target_field)
    return field_resolution_field_type("", field_id, target_field)


def _field_source_preference_order(target_field: str) -> tuple[str, ...]:
    field_type = _target_field_type(target_field)
    preferred = list(FIELD_TYPE_SOURCE_PREFERENCES.get(field_type, (
        "official_interconnection_source",
        "manufacturer_model_specific_spec",
        "manufacturer_family_spec",
        "official_website",
        "vendor_pdf",
        "secondary_web",
    )))
    preferred_sources_blob = " ".join(preferred_sources_for_field(target_field)).lower()
    if any(token in preferred_sources_blob for token in ("utility", "interconnection", "iso", "poi")):
        if "official_interconnection_source" in preferred:
            preferred.remove("official_interconnection_source")
        preferred.insert(0, "official_interconnection_source")
    if any(token in preferred_sources_blob for token in ("manufacturer", "catalog", "vendor model", "nameplate", "datasheet")):
        for source_name in ("manufacturer_model_specific_spec", "manufacturer_family_spec"):
            if source_name in preferred:
                preferred.remove(source_name)
        preferred = ["manufacturer_model_specific_spec", "manufacturer_family_spec", *preferred]
    deduped: list[str] = []
    for item in preferred:
        if item not in deduped:
            deduped.append(item)
    return tuple(deduped)


def _field_policy_alignment_boost(target_field: str, source_hierarchy: str, specificity: str, corpus_name: str) -> float:
    if not target_field:
        return 0.0
    preference_order = _field_source_preference_order(target_field)
    alignment_boost = 0.0
    if source_hierarchy in preference_order:
        position = preference_order.index(source_hierarchy)
        alignment_boost += max(0.0, 0.16 - (position * 0.03))
    elif source_hierarchy == "secondary_web":
        alignment_boost -= 0.04

    field_type = _target_field_type(target_field)
    is_critical = planner_critical_for_path(target_field)
    if is_critical and field_type in {"capacity", "identity"}:
        if source_hierarchy == "manufacturer_model_specific_spec":
            alignment_boost += 0.08
        elif source_hierarchy == "manufacturer_family_spec":
            alignment_boost += 0.03
        elif source_hierarchy in {"vendor_pdf", "secondary_web"}:
            alignment_boost -= 0.05
        if specificity == "exact_model_match":
            alignment_boost += 0.08
        elif specificity == "family_match":
            alignment_boost += 0.02
    elif is_critical and field_type in {"voltage", "topology", "protection", "telemetry"}:
        if source_hierarchy == "official_interconnection_source":
            alignment_boost += 0.08
        elif source_hierarchy == "secondary_web":
            alignment_boost -= 0.06
    if corpus_name == "equipment_catalog" and field_type in {"capacity", "identity"}:
        alignment_boost += 0.03
    return alignment_boost


def _hierarchy_rank_for_query(target_field: str, source_hierarchy: str) -> int:
    preference_order = _field_source_preference_order(target_field)
    if source_hierarchy in preference_order:
        return len(preference_order) - preference_order.index(source_hierarchy)
    return SOURCE_HIERARCHY_PRIORITY.get(source_hierarchy, -1)


def _infer_entry_specificity(entry: dict[str, Any], query: dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    blob = " ".join(
        str(metadata.get(key, "")).strip().lower()
        for key in ("match_reason", "match_specificity", "source_priority", "retrieval_priority")
    )
    if any(token in blob for token in ("exact_model", "exact model", "manufacturer+model", "model_specific")):
        return "exact_model_match"
    if "exact_instance" in blob or "exact instance" in blob:
        return "exact_instance_match"
    if "direct" in blob or "direct_field" in blob or "canonical_field" in blob:
        return "direct_field_match"
    if "family" in blob:
        return "family_match"
    if "category" in blob:
        return "category_match"

    target_field = str(query.get("target_field", "")).strip()
    matched_target_fields = metadata.get("matched_target_fields", [])
    if isinstance(matched_target_fields, list) and target_field and target_field in {str(item).strip() for item in matched_target_fields if str(item).strip()}:
        return "direct_field_match"

    query_text = str(query.get("query_text", "")).strip().lower()
    manufacturer = str(metadata.get("manufacturer", "")).strip().lower()
    model = str(metadata.get("model", "")).strip().lower()
    if manufacturer and model and manufacturer in query_text and model in query_text:
        return "exact_model_match"
    if manufacturer and manufacturer in query_text and model:
        return "family_match"
    return "context_inferred"


def _source_hierarchy_from_entry(entry: dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    corpus = str(entry.get("corpus", "")).strip().lower()
    source_kind = str(metadata.get("source_kind", "")).strip().lower()
    document_type = str(metadata.get("document_type", "")).strip().lower()
    evidence_tier = str(metadata.get("evidence_tier", "")).strip().lower()
    source_priority = str(metadata.get("source_priority", "")).strip().lower()
    blob = " ".join([corpus, source_kind, document_type, evidence_tier, source_priority])
    if any(token in blob for token in ("official_interconnection", "ercot", "iso", "utility")):
        return "official_interconnection_source"
    if any(token in blob for token in ("model_specific", "manufacturer_model_specific_spec", "exact_model")):
        return "manufacturer_model_specific_spec"
    if corpus == "equipment_catalog" or source_kind == "equipment_catalog":
        return "manufacturer_family_spec"
    if evidence_tier == "official_vendor_document" or "official" in document_type:
        return "official_website"
    if corpus == "vendor_documents" or source_kind == "vendor_document":
        return "vendor_pdf"
    if corpus == "modeling_references":
        return "official_interconnection_source"
    return "secondary_web" if "secondary" in blob else "vendor_pdf"

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_whitespace(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _tokenize_query_text(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in str(text or "").replace(",", " ").replace("/", " ").split():
        cleaned = "".join(ch for ch in raw.lower() if ch.isalnum() or ch in {"_", "."})
        if len(cleaned) >= 3 and cleaned not in tokens:
            tokens.append(cleaned)
    return tokens


def _entry_search_text(entry: dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    parts: list[str] = [str(entry.get("lowered_text", "")).strip()]
    if isinstance(metadata, dict):
        for key in (
            "record_name",
            "equipment_family",
            "manufacturer",
            "model",
            "document_type",
            "document_label",
            "source_url",
            "source_domain",
            "source_relative_path",
            "document_path",
            "source_kind",
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.lower())
        fixed_spec_names = metadata.get("fixed_spec_names", [])
        if isinstance(fixed_spec_names, list):
            parts.extend(str(item).strip().lower() for item in fixed_spec_names if isinstance(item, str) and item.strip())
        document_keywords = metadata.get("document_keywords", [])
        if isinstance(document_keywords, list):
            parts.extend(str(item).strip().lower() for item in document_keywords if isinstance(item, str) and item.strip())
    return " ".join(part for part in parts if part)


def _source_evidence_tier(entry: dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    explicit = str(metadata.get("evidence_tier", "")).strip().lower()
    if explicit:
        return explicit
    corpus = str(entry.get("corpus", "")).strip().lower()
    source_kind = str(metadata.get("source_kind", "")).strip().lower()
    document_type = str(metadata.get("document_type", "")).strip().lower()
    if corpus == "equipment_catalog" or source_kind == "equipment_catalog":
        return "structured_catalog"
    if "official" in document_type:
        return "official_vendor_document"
    if "pointer" in document_type:
        return "vendor_document_pointer"
    if corpus == "vendor_documents" or source_kind == "vendor_document":
        return "vendor_document"
    if corpus == "interconnection_guidance":
        return "interconnection_guidance"
    if corpus == "modeling_references":
        return "modeling_reference"
    return "reference"


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _iter_corpus_files(source_path: Path) -> list[Path]:
    if source_path.is_file():
        return [source_path]
    if not source_path.exists():
        return []
    return [path for path in sorted(source_path.rglob("*")) if path.is_file()]


def _load_corpora() -> dict[str, list[dict[str, Any]]]:
    corpora: dict[str, list[dict[str, Any]]] = {}

    route_status = knowledge_route_status()
    corpus_status = route_status.get("corpora", {}) if isinstance(route_status, dict) else {}

    for corpus_name in canonical_preferred_corpora(None):
        entries = load_corpus_entries(corpus_name)
        for entry in entries:
            metadata = entry.get("metadata", {})
            if isinstance(metadata, dict):
                metadata.setdefault("knowledge_route_status", corpus_status.get(corpus_name, {}))
        corpora[corpus_name] = entries

    return corpora


def _missing_fields(normalization_result: dict[str, Any] | None) -> list[str]:
    if not isinstance(normalization_result, dict):
        return []

    validation_report = normalization_result.get("validation_report", {})
    if not isinstance(validation_report, dict):
        return []

    missing_fields = validation_report.get("missing_fields", [])
    if not isinstance(missing_fields, list):
        return []

    normalized: list[str] = []
    for item in missing_fields:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())

    return normalized


def _normalized_field_index(normalization_result: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(normalization_result, dict):
        return {}
    payload = normalization_result.get("normalized_field_index", {})
    if not isinstance(payload, dict):
        return {}
    return {str(key).strip(): value for key, value in payload.items() if isinstance(value, dict) and str(key).strip()}


def _planner_critical_missing_fields(normalization_result: dict[str, Any] | None) -> list[str]:
    field_index = _normalized_field_index(normalization_result)
    ordered: list[str] = []
    seen: set[str] = set()
    for field_id, entry in field_index.items():
        if not planner_critical_for_path(field_id):
            continue
        status = str(entry.get("status", "")).strip().lower()
        field_path = str(entry.get("field_path", "")).strip()
        if not field_path or field_path in seen:
            continue
        if status in {"missing", "conflicting"}:
            ordered.append(field_path)
            seen.add(field_path)
    return ordered


def _ontology_signal_keywords(ontology_items: list[dict[str, Any]]) -> list[str]:
    keywords: list[str] = []
    for item in ontology_items:
        if not isinstance(item, dict):
            continue
        for key in ("manufacturer", "model", "equipment_family", "document_type", "classification"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                keywords.append(value.strip())
        metadata = item.get("metadata", {})
        if isinstance(metadata, dict):
            for key in ("manufacturer", "model", "equipment_family", "document_type"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    keywords.append(value.strip())
    return _unique_keywords(keywords, limit=12)


def _ontology_items(extraction_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(extraction_result, dict):
        return []

    ontology = extraction_result.get("ontology", [])
    if not isinstance(ontology, list):
        return []

    return [item for item in ontology if isinstance(item, dict)]


def _dedupe_queries(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []

    for query in queries:
        intent = str(query.get("intent", "")).strip()
        target_field = str(query.get("target_field", "")).strip()
        query_source = str(query.get("query_source", "")).strip()
        key = (intent, target_field, query_source)
        if not intent or not target_field or not query_source:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query)

    return deduped


def _unique_keywords(values: list[str], *, limit: int = 12) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        normalized = cleaned.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(cleaned)
        if len(deduped) >= limit:
            break
    return deduped


def _field_family_keywords(field_path: str) -> list[str]:
    lowered = str(field_path or "").strip().lower()
    if not lowered:
        return []
    if 'poi' in lowered or 'interconnection' in lowered or 'substation' in lowered:
        return ['one line', 'interconnection study', 'utility letter', 'substation', 'point of interconnection']
    if 'transformer' in lowered:
        return ['transformer schedule', 'mva', 'primary secondary', 'winding', 'substation transformer']
    if 'generator' in lowered:
        return ['generator schedule', 'rated kw', 'prime standby', 'diesel generator', 'genset']
    if '.ups' in lowered or 'ups_' in lowered or 'ups.' in lowered:
        return ['ups schedule', 'one line', 'module rating', 'topology', 'battery']
    if 'load_schedule' in lowered or 'phase_' in lowered or lowered.endswith('_mw'):
        return ['load schedule', 'phase buildout', 'mw demand', 'campus load', 'utility application']
    return []


def _document_type_hint_keywords(document_types: list[str]) -> list[str]:
    hints: list[str] = []
    for item in document_types:
        lowered = str(item or '').strip().lower()
        if not lowered:
            continue
        if 'single' in lowered or 'one_line' in lowered or 'one-line' in lowered:
            hints.extend(['one line', 'single line'])
        if 'study' in lowered:
            hints.extend(['study', 'interconnection study'])
        if 'schedule' in lowered:
            hints.extend(['equipment schedule', 'schedule'])
        if 'datasheet' in lowered or 'spec' in lowered:
            hints.extend(['datasheet', 'specification'])
        if 'drawing' in lowered:
            hints.extend(['drawing', 'diagram'])
    return _unique_keywords(hints, limit=8)


def _query_priority(query: dict[str, Any]) -> tuple[int, int, str]:
    source = str(query.get('query_source', '')).strip().lower()
    target_field = str(query.get('target_field', '')).strip().lower()
    preferred = query.get('preferred_corpora', []) if isinstance(query.get('preferred_corpora'), list) else []
    source_rank = 0 if source == 'missing_field+ontology' else 1 if source == 'missing_field' else 2 if source == 'ontology' else 3
    planner_critical_rank = 0 if any(token in target_field for token in ('poi', 'transformer', 'generator', 'ups', 'telemetry', 'relay', 'breaker', 'phase_1_mw', 'mw')) else 1
    preferred_rank = 0 if preferred and str(preferred[0]).strip() in {'interconnection_guidance', 'vendor_documents', 'equipment_catalog'} else 1
    return (planner_critical_rank, source_rank + preferred_rank, target_field)


def _snippet_priority(item: dict[str, Any]) -> tuple[int, int, str]:
    metadata = item.get('metadata', {}) if isinstance(item.get('metadata'), dict) else {}
    source_hierarchy = str(metadata.get('source_hierarchy', item.get('source_hierarchy', ''))).strip().lower()
    target_field = str(metadata.get('target_field', item.get('target_field', ''))).strip().lower()
    hierarchy_rank = 0 if source_hierarchy == 'official_interconnection_source' else 1 if source_hierarchy == 'manufacturer_model_specific_spec' else 2 if source_hierarchy.startswith('official') else 3
    planner_critical_rank = 0 if any(token in target_field for token in ('poi', 'transformer', 'generator', 'ups', 'telemetry', 'relay', 'breaker', 'phase_1_mw', 'mw')) else 1
    return (planner_critical_rank, hierarchy_rank, str(item.get('source_ref', '')).lower())


def _build_queries_from_missing_fields(missing_fields: list[str], *, ontology_items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    ontology_keywords = _ontology_signal_keywords(ontology_items or [])

    for field_path in missing_fields:
        spec = FIELD_QUERY_SPECS.get(field_path)
        registry_keywords = search_keywords_for_field(field_path)
        registry_corpora = preferred_corpora_for_field(field_path)
        registry_field_id = registry_field_id_for_path(field_path)
        base_keywords = list(registry_keywords) + _field_family_keywords(field_path) + ontology_keywords
        if spec is not None:
            base_keywords.extend(spec['keywords'])
        combined_keywords = _unique_keywords(base_keywords, limit=12)
        if not combined_keywords:
            combined_keywords = _unique_keywords([field_label_for_path(field_path), registry_field_id or field_path], limit=8)

        queries.append({
            'intent': str((spec or {}).get('intent') or registry_field_id or field_path).strip(),
            'target_field': field_path, 'query_text': ' '.join(combined_keywords[:8]),
            'keywords': combined_keywords, 'topic': str((spec or {}).get('topic') or registry_field_id or field_path).strip(),
            'preferred_corpora': list(registry_corpora or list((spec or {}).get('preferred_corpora', [])) or canonical_preferred_corpora(None)), 'query_source': 'missing_field',
            'source_artifact_ids': [], 'source_document_types': [],
        })

    return queries


def _build_queries_from_ontology(
    ontology_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []

    for item in ontology_items:
        artifact_id = str(item.get('artifact_id', '')).strip()
        document_type = str(item.get('document_type', '')).strip()
        retrieval_domains = item.get('retrieval_domains', [])
        normalized_domains = [str(domain).strip() for domain in retrieval_domains if isinstance(domain, str) and domain.strip()] if isinstance(retrieval_domains, list) else []
        document_keywords = _document_type_hint_keywords([document_type])

        for domain in normalized_domains:
            spec = ONTOLOGY_DOMAIN_SPECS.get(domain)
            if spec is None:
                continue
            target_field = spec['target_field']
            keywords = _unique_keywords(list(spec['keywords']) + _field_family_keywords(target_field) + document_keywords, limit=12)
            queries.append({
                'intent': spec['intent'], 'target_field': target_field, 'query_text': ' '.join(keywords[:8]) if keywords else spec['query_text'],
                'keywords': keywords or list(spec['keywords']), 'topic': spec['topic'], 'preferred_corpora': list(spec['preferred_corpora']),
                'query_source': 'ontology', 'source_artifact_ids': [artifact_id] if artifact_id else [], 'source_document_types': [document_type] if document_type else [],
            })

    return queries


def _build_fallback_queries(normalization_result: dict[str, Any] | None, ontology_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fallback_fields = _planner_critical_missing_fields(normalization_result)
    if not fallback_fields:
        field_index = _normalized_field_index(normalization_result)
        seen: set[str] = set()
        for field_id in normalization_required_field_ids():
            if not planner_critical_for_path(field_id):
                continue
            field_path = str((field_index.get(field_id, {}) or {}).get('field_path', '')).strip()
            if not field_path or field_path in seen:
                continue
            seen.add(field_path)
            fallback_fields.append(field_path)
            if len(fallback_fields) >= 6:
                break
    if not fallback_fields:
        fallback_fields = [str(spec.get('target_field', '')).strip() for spec in FALLBACK_QUERY_SPECS if str(spec.get('target_field', '')).strip()]
    queries = _build_queries_from_missing_fields(fallback_fields[:6], ontology_items=ontology_items)
    for query in queries:
        query['query_source'] = 'fallback'
    return queries


def _build_queries(
    normalization_result: dict[str, Any] | None,
    extraction_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    missing_fields = _missing_fields(normalization_result)
    ontology_items = _ontology_items(extraction_result)

    ordered_missing_fields: list[str] = []
    seen: set[str] = set()
    for field_path in _planner_critical_missing_fields(normalization_result) + missing_fields:
        if field_path not in seen:
            ordered_missing_fields.append(field_path)
            seen.add(field_path)

    missing_field_queries = _build_queries_from_missing_fields(ordered_missing_fields, ontology_items=ontology_items)
    ontology_queries = _build_queries_from_ontology(ontology_items)

    ontology_sources_by_target_field: dict[str, dict[str, list[str]]] = {}
    for query in ontology_queries:
        target_field = str(query.get("target_field", "")).strip()
        if not target_field:
            continue
        payload = ontology_sources_by_target_field.setdefault(target_field, {"artifact_ids": [], "document_types": []})
        for item in query.get("source_artifact_ids", []) if isinstance(query.get("source_artifact_ids"), list) else []:
            if isinstance(item, str) and item.strip() and item not in payload["artifact_ids"]:
                payload["artifact_ids"].append(item)
        for item in query.get("source_document_types", []) if isinstance(query.get("source_document_types"), list) else []:
            if isinstance(item, str) and item.strip() and item not in payload["document_types"]:
                payload["document_types"].append(item)

    merged_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for query in missing_field_queries:
        key = (
            str(query.get("intent", "")).strip(),
            str(query.get("target_field", "")).strip(),
        )
        if not key[0] or not key[1]:
            continue
        materialized = dict(query)
        inherited = ontology_sources_by_target_field.get(key[1], {})
        if inherited:
            materialized["source_artifact_ids"] = list(inherited.get("artifact_ids", []))
            materialized["source_document_types"] = list(inherited.get("document_types", []))
            if str(materialized.get("query_source", "")).strip() == "missing_field":
                materialized["query_source"] = "missing_field+ontology"
        merged_by_key[key] = materialized

    for query in ontology_queries:
        key = (
            str(query.get("intent", "")).strip(),
            str(query.get("target_field", "")).strip(),
        )
        if not key[0] or not key[1]:
            continue

        existing = merged_by_key.get(key)
        if existing is None:
            merged_by_key[key] = dict(query)
            continue

        existing_artifact_ids = existing.get("source_artifact_ids", [])
        if not isinstance(existing_artifact_ids, list):
            existing_artifact_ids = []

        ontology_artifact_ids = query.get("source_artifact_ids", [])
        if not isinstance(ontology_artifact_ids, list):
            ontology_artifact_ids = []

        existing_document_types = existing.get("source_document_types", [])
        if not isinstance(existing_document_types, list):
            existing_document_types = []

        ontology_document_types = query.get("source_document_types", [])
        if not isinstance(ontology_document_types, list):
            ontology_document_types = []

        combined_artifact_ids: list[str] = []
        for item in list(existing_artifact_ids) + list(ontology_artifact_ids):
            if isinstance(item, str) and item.strip() and item not in combined_artifact_ids:
                combined_artifact_ids.append(item)

        combined_document_types: list[str] = []
        for item in list(existing_document_types) + list(ontology_document_types):
            if isinstance(item, str) and item.strip() and item not in combined_document_types:
                combined_document_types.append(item)

        existing["source_artifact_ids"] = combined_artifact_ids
        existing["source_document_types"] = combined_document_types

        if str(existing.get("query_source", "")).strip() == "missing_field":
            existing["query_source"] = "missing_field+ontology"

    queries = list(merged_by_key.values())

    if not queries:
        queries.extend(_build_fallback_queries(normalization_result, ontology_items))

    return _dedupe_queries(queries)


def _metadata_score_boost(entry: dict[str, Any], query: dict[str, Any], corpus_name: str) -> float:
    metadata = entry.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    boost = 0.0
    priority = str(metadata.get("retrieval_priority", "")).strip().lower()
    if priority == "high":
        boost += 0.12
    elif priority == "medium":
        boost += 0.06
    elif priority == "low":
        boost -= 0.03

    source_kind = str(metadata.get("source_kind", "")).strip().lower()
    document_type = str(metadata.get("document_type", "")).strip().lower()
    evidence_tier = str(metadata.get("evidence_tier", "")).strip().lower()
    trust_level = str(metadata.get("trust_level", "")).strip().lower()
    source_priority = str(metadata.get("source_priority", "")).strip().lower()
    source_hierarchy = _source_hierarchy_from_entry(entry)
    specificity = _infer_entry_specificity(entry, query)

    if source_kind == "equipment_catalog":
        boost += 0.08
    elif source_kind == "vendor_document":
        boost += 0.04
    if evidence_tier == "official_vendor_document" or "official" in document_type:
        boost += 0.08
    elif evidence_tier == "vendor_document_pointer":
        boost -= 0.02
    if trust_level == "high":
        boost += 0.04
    elif trust_level == "low":
        boost -= 0.02

    for key, value in SOURCE_PRIORITY_BOOSTS.items():
        if key and key in source_priority:
            boost += value
            break
    boost += SPECIFICITY_BOOSTS.get(specificity, 0.0)
    if source_hierarchy == "official_interconnection_source":
        boost += 0.06
    elif source_hierarchy == "manufacturer_model_specific_spec":
        boost += 0.05
    elif source_hierarchy == "secondary_web":
        boost -= 0.05

    target_field = str(query.get("target_field", "")).strip()
    boost += _field_policy_alignment_boost(target_field, source_hierarchy, specificity, corpus_name)
    matched_target_fields = metadata.get("matched_target_fields", [])
    if isinstance(matched_target_fields, list) and target_field and target_field in {str(item).strip() for item in matched_target_fields if str(item).strip()}:
        boost += 0.05

    query_document_types = query.get("source_document_types", [])
    if isinstance(query_document_types, list) and query_document_types:
        normalized_query_document_types = {str(item).strip().lower() for item in query_document_types if str(item).strip()}
        if document_type and document_type.lower() in normalized_query_document_types:
            boost += 0.05

    query_artifact_ids = query.get("source_artifact_ids", [])
    metadata_artifact_id = str(metadata.get("artifact_id", "")).strip()
    if isinstance(query_artifact_ids, list) and metadata_artifact_id and metadata_artifact_id in {str(item).strip() for item in query_artifact_ids if str(item).strip()}:
        boost += 0.05

    preferred_corpora = query.get("preferred_corpora", [])
    if isinstance(preferred_corpora, list) and preferred_corpora:
        if corpus_name == str(preferred_corpora[0]).strip():
            boost += 0.08
        elif corpus_name in preferred_corpora:
            boost += 0.03

    query_tokens = _tokenize_query_text(str(query.get("query_text", "")))
    search_text = _entry_search_text(entry)
    if query_tokens and search_text:
        matched = sum(1 for token in query_tokens if token in search_text)
        boost += min(0.1, matched * 0.015)

    return boost


def _score_entry(entry: dict[str, Any], keywords: list[str]) -> tuple[float, list[str]]:
    search_text = _entry_search_text(entry)
    if not search_text:
        return 0.0, []

    matched_keywords: list[str] = []
    for keyword in keywords:
        normalized_keyword = str(keyword).strip().lower()
        if normalized_keyword and normalized_keyword in search_text:
            matched_keywords.append(keyword)

    if not matched_keywords:
        return 0.0, []

    unique_matches: list[str] = []
    seen: set[str] = set()
    for item in matched_keywords:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_matches.append(item)

    metadata = entry.get("metadata", {})
    metadata_bonus = 0.0
    if isinstance(metadata, dict):
        fixed_spec_names = metadata.get("fixed_spec_names", [])
        if isinstance(fixed_spec_names, list):
            for item in fixed_spec_names:
                cleaned = str(item).strip().lower()
                if cleaned and cleaned in search_text:
                    metadata_bonus += 0.01

    score = min(1.0, 0.32 + (0.1 * len(unique_matches)) + min(0.08, metadata_bonus))
    return score, unique_matches


def _best_entries_for_query(
    query: dict[str, Any],
    corpora: dict[str, list[dict[str, Any]]],
    top_k: int,
) -> list[dict[str, Any]]:
    preferred_corpora = query.get("preferred_corpora", [])
    if not isinstance(preferred_corpora, list):
        preferred_corpora = []

    keywords = query.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []

    ranked: list[tuple[float, dict[str, Any], list[str]]] = []

    corpus_order = [
        str(item).strip()
        for item in preferred_corpora
        if isinstance(item, str) and item.strip()
    ]
    remaining = [name for name in corpora.keys() if name not in corpus_order]
    ordered_corpora = corpus_order + remaining

    for corpus_name in ordered_corpora:
        entries = corpora.get(corpus_name, [])
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            score, matched_keywords = _score_entry(entry, keywords)
            if score <= 0.0:
                continue

            score = min(1.0, score + _metadata_score_boost(entry, query, corpus_name))
            source_hierarchy = _source_hierarchy_from_entry(entry)
            specificity = _infer_entry_specificity(entry, query)
            target_field = str(query.get("target_field", "")).strip()
            ranked.append((
                score,
                _hierarchy_rank_for_query(target_field, source_hierarchy),
                SPECIFICITY_PRIORITY.get(specificity, -1),
                entry,
                matched_keywords,
            ))

    ranked.sort(
        key=lambda item: (
            -float(item[0]),
            -int(item[1]),
            -int(item[2]),
            str(item[3].get("corpus", "")),
            str(item[3].get("source_ref", "")),
        )
    )

    selected: list[dict[str, Any]] = []
    seen_sources: set[tuple[str, str, str]] = set()

    for score, _hierarchy_rank, _specificity_rank, entry, matched_keywords in ranked:
        corpus = str(entry.get("corpus", "")).strip()
        source_ref = str(entry.get("source_ref", "")).strip()
        target_field = str(query.get("target_field", "")).strip()
        selection_key = (corpus, source_ref, target_field)
        if selection_key in seen_sources:
            continue
        seen_sources.add(selection_key)

        selected.append(
            {
                "corpus": corpus,
                "source_ref": source_ref,
                "text": str(entry.get("text", "")).strip(),
                "score": round(float(score), 4),
                "matched_keywords": matched_keywords,
                "target_field": target_field,
                "query_intent": str(query.get("intent", "")).strip(),
                "query_source": str(query.get("query_source", "")).strip(),
                "topic": str(query.get("topic", "")).strip(),
                "source_artifact_ids": list(query.get("source_artifact_ids", [])),
                "source_document_types": list(query.get("source_document_types", [])),
                "metadata": dict(entry.get("metadata", {})) if isinstance(entry.get("metadata"), dict) else {},
                "evidence_tier": _source_evidence_tier(entry),
                "specificity": _infer_entry_specificity(entry, query),
                "source_hierarchy": _source_hierarchy_from_entry(entry),
            }
        )

        if len(selected) >= top_k:
            break

    return selected


def _build_snippets(
    context: Any,
    queries: list[dict[str, Any]],
    corpora: dict[str, list[dict[str, Any]]],
    top_k: int,
) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    snippet_counter = 1

    for query in queries:
        best_entries = _best_entries_for_query(query, corpora, top_k=top_k)
        for item in best_entries:
            snippets.append(
                {
                    "snippet_id": f"{context.run_id}_snip_{snippet_counter:03d}",
                    "corpus": item["corpus"],
                    "source_ref": item["source_ref"],
                    "text": item["text"],
                    "score": item["score"],
                    "metadata": {
                        **(item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}),
                        "topic": item["topic"],
                "retrieval_priority": str((item.get("metadata", {}) or {}).get("retrieval_priority", "")).strip(),
                        "matched_keywords": list(item["matched_keywords"]),
                        "target_field": item["target_field"],
                        "query_intent": item["query_intent"],
                        "query_source": item["query_source"],
                        "source_artifact_ids": list(item["source_artifact_ids"]),
                        "source_document_types": list(item["source_document_types"]),
                        "source_kind": str((item.get("metadata", {}) or {}).get("source_kind", "")).strip(),
                        "document_type": str((item.get("metadata", {}) or {}).get("document_type", "")).strip(),
                        "document_label": str((item.get("metadata", {}) or {}).get("document_label", "")).strip(),
                        "document_path": str((item.get("metadata", {}) or {}).get("document_path", "")).strip(),
                        "source_domain": str((item.get("metadata", {}) or {}).get("source_domain", "")).strip(),
                        "source_url": str((item.get("metadata", {}) or {}).get("source_url", "")).strip(),
                        "evidence_tier": str(item.get("evidence_tier", "")).strip(),
                        "trust_level": str((item.get("metadata", {}) or {}).get("trust_level", "")).strip(),
                        "specificity": str(item.get("specificity", "")).strip(),
                        "source_hierarchy": str(item.get("source_hierarchy", "")).strip(),
                        "source_priority": str((item.get("metadata", {}) or {}).get("source_priority", "")).strip(),
                        "matched_target_fields": list((item.get("metadata", {}) or {}).get("matched_target_fields", [])) if isinstance((item.get("metadata", {}) or {}).get("matched_target_fields", []), list) else [],
                    },
                }
            )
            snippet_counter += 1

    return snippets


def _retrieval_config(context: Any) -> dict[str, Any]:
    config = getattr(context, "config", None)
    if config is None:
        return {"top_k": 5, "rerank": False}

    retrieval_config = getattr(config, "retrieval_config", None)
    if not isinstance(retrieval_config, dict):
        return {"top_k": 5, "rerank": False}

    top_k = retrieval_config.get("top_k", 5)
    rerank = retrieval_config.get("rerank", False)

    try:
        normalized_top_k = max(1, int(top_k))
    except (TypeError, ValueError):
        normalized_top_k = 5

    return {
        "top_k": normalized_top_k,
        "rerank": bool(rerank),
    }


def _can_run_agent(context: Any) -> bool:
    run_id = getattr(context, "run_id", None)
    return isinstance(run_id, str) and bool(run_id.strip())


def _preferred_corpora_for_families(knowledge_family_route: list[str]) -> list[str]:
    preferred = canonical_preferred_corpora(canonical_family_route(knowledge_family_route))
    if "equipment_catalog" in preferred and "vendor_documents" not in preferred:
        equipment_index = preferred.index("equipment_catalog")
        preferred.insert(equipment_index + 1, "vendor_documents")
    if "equipment_catalog" in preferred and "vendor_specs" not in preferred:
        equipment_index = preferred.index("equipment_catalog")
        preferred.insert(equipment_index + 1, "vendor_specs")
    if "modeling_references" in preferred and "modeling_refs" not in preferred:
        preferred.insert(preferred.index("modeling_references") + 1, "modeling_refs")
    return preferred


def _looks_like_field_path(value: str) -> bool:
    normalized = str(value).strip()
    return bool(normalized) and "." in normalized and " " not in normalized


def _resolve_agent_target_field(
    *,
    explicit_target_field: str,
    topic: str,
    query_text: str,
    topic_to_field: dict[str, str],
) -> str:
    if explicit_target_field:
        return explicit_target_field
    if _looks_like_field_path(topic):
        return topic
    if topic in topic_to_field:
        return topic_to_field[topic]
    if query_text in topic_to_field:
        return topic_to_field[query_text]
    return topic or query_text


def _build_agent_generated_queries(
    *,
    suggested_query_topics: list[str],
    knowledge_family_route: list[str],
    suggested_queries: list[dict[str, Any]] | None = None,
    query_plan: dict[str, Any] | None = None,
    query_source: str = "retrieval_planning_agent",
) -> list[dict[str, Any]]:
    preferred_corpora = _preferred_corpora_for_families(knowledge_family_route)

    topic_to_field: dict[str, str] = {}
    if isinstance(query_plan, dict):
        missing_fields = query_plan.get("missing_fields", [])
        if isinstance(missing_fields, list):
            for item in missing_fields:
                if isinstance(item, str) and item.strip():
                    normalized = item.strip()
                    topic_to_field[normalized] = normalized
                    topic_to_field[normalized.replace("_", " ").replace(".", " ")] = normalized

    generated: list[dict[str, Any]] = []

    if isinstance(suggested_queries, list):
        for index, item in enumerate(suggested_queries, start=1):
            if not isinstance(item, dict):
                continue

            query_text = str(item.get("query_text", "")).strip()
            if not query_text:
                continue

            topic = str(item.get("topic", "")).strip()
            keywords_raw = item.get("keywords", [])
            if isinstance(keywords_raw, list):
                keywords = [
                    str(token).strip()
                    for token in keywords_raw
                    if isinstance(token, str) and str(token).strip()
                ]
            else:
                keywords = [token for token in query_text.replace(",", " ").split() if token]

            target_field = _resolve_agent_target_field(
                explicit_target_field=str(item.get("target_field", "")).strip(),
                topic=topic,
                query_text=query_text,
                topic_to_field=topic_to_field,
            )

            preferred = item.get("preferred_corpora", [])
            preferred_corpora_value = (
                list(preferred)
                if isinstance(preferred, list) and preferred
                else preferred_corpora
            )

            generated.append(
                {
                    "intent": str(item.get("intent", "")).strip() or f"agent_generated_{index}",
                    "target_field": target_field,
                    "query_text": query_text,
                    "keywords": keywords,
                    "topic": topic or query_text,
                    "preferred_corpora": preferred_corpora_value,
                    "query_source": query_source,
                    "source_artifact_ids": [],
                    "source_document_types": [],
                }
            )

    if suggested_query_topics:
        for topic in suggested_query_topics:
            normalized_topic = str(topic).strip()
            if not normalized_topic:
                continue

            keywords = [token for token in normalized_topic.replace(",", " ").split() if token]
            if not keywords:
                continue

            target_field = _resolve_agent_target_field(
                explicit_target_field="",
                topic=normalized_topic,
                query_text=normalized_topic,
                topic_to_field=topic_to_field,
            )
            generated.append(
                {
                    "intent": "agent_generated",
                    "target_field": target_field,
                    "query_text": normalized_topic,
                    "keywords": keywords,
                    "topic": normalized_topic,
                    "preferred_corpora": preferred_corpora,
                    "query_source": query_source,
                    "source_artifact_ids": [],
                    "source_document_types": [],
                }
            )

    return _dedupe_queries(generated)


def _snippet_field_coverage(snippets: list[dict[str, Any]]) -> dict[str, int]:
    coverage: dict[str, int] = {}
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        metadata = snippet.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        target_field = str(metadata.get("target_field", "")).strip()
        if not target_field:
            continue
        coverage[target_field] = coverage.get(target_field, 0) + 1
    return coverage


def _retrieval_trigger_summary(
    *,
    normalization_result: dict[str, Any] | None,
    snippets: list[dict[str, Any]],
    equipment_reference_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing_fields = _missing_fields(normalization_result)
    coverage = _snippet_field_coverage(snippets)
    reasons: list[str] = []

    if missing_fields:
        reasons.append("missing_fields_present")

    uncovered_missing_fields = [field for field in missing_fields if coverage.get(field, 0) <= 0]
    weakly_covered_missing_fields = [field for field in missing_fields if coverage.get(field, 0) <= 1]
    if uncovered_missing_fields:
        reasons.append("missing_fields_without_snippets")
    elif weakly_covered_missing_fields:
        reasons.append("missing_fields_with_thin_snippet_coverage")

    if not snippets:
        reasons.append("no_snippets_returned")

    evidence_gap = False
    official_web_lookup_required = False
    if isinstance(equipment_reference_resolution, dict):
        if bool(equipment_reference_resolution.get("evidence_gap", False)):
            evidence_gap = True
            reasons.append("equipment_reference_evidence_gap")
        if bool(equipment_reference_resolution.get("web_lookup_required", False)):
            official_web_lookup_required = True
            reasons.append("official_source_only_web_lookup_required")
        unresolved_equipment = equipment_reference_resolution.get("unresolved_missing_fields", [])
        if isinstance(unresolved_equipment, list) and unresolved_equipment:
            reasons.append("unresolved_equipment_spec_fields")

    return {
        "should_run_agent": bool(reasons),
        "reasons": reasons,
        "missing_fields": missing_fields,
        "uncovered_missing_fields": uncovered_missing_fields,
        "weakly_covered_missing_fields": weakly_covered_missing_fields,
        "snippet_count": len(snippets),
        "evidence_gap": evidence_gap or bool(uncovered_missing_fields) or not snippets,
        "official_web_lookup_required": official_web_lookup_required,
    }


def _should_run_retrieval_planning_agent(
    *,
    context: Any,
    normalization_result: dict[str, Any] | None,
    snippets: list[dict[str, Any]],
    equipment_reference_resolution: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not _can_run_agent(context):
        return False, {"should_run_agent": False, "reasons": ["agent_runtime_unavailable"]}
    trigger_summary = _retrieval_trigger_summary(
        normalization_result=normalization_result,
        snippets=snippets,
        equipment_reference_resolution=equipment_reference_resolution,
    )
    return bool(trigger_summary.get("should_run_agent", False)), trigger_summary




def _compact_queries_for_agent(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in sorted((query for query in queries if isinstance(query, dict)), key=_query_priority)[:AGENT_QUERY_LIMIT]:
        compact.append({
            'intent': str(item.get('intent', '')).strip(), 'target_field': str(item.get('target_field', '')).strip(),
            'query_text': str(item.get('query_text', '')).strip()[:AGENT_QUERY_TEXT_LIMIT],
            'keywords': list(item.get('keywords', []))[:6] if isinstance(item.get('keywords'), list) else [],
            'topic': str(item.get('topic', '')).strip()[:80],
            'preferred_corpora': list(item.get('preferred_corpora', []))[:4] if isinstance(item.get('preferred_corpora'), list) else [],
            'query_source': str(item.get('query_source', '')).strip(),
        })
    return compact


def _compact_snippets_for_agent(snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    ordered_snippets = sorted((item for item in snippets if isinstance(item, dict)), key=_snippet_priority)[:AGENT_SNIPPET_LIMIT]
    for item in ordered_snippets:
        metadata = item.get('metadata', {}) if isinstance(item.get('metadata'), dict) else {}
        compact.append({
            'corpus': str(item.get('corpus', '')).strip(), 'source_ref': str(item.get('source_ref', '')).strip()[:120],
            'text': str(item.get('text', '')).strip()[:AGENT_SNIPPET_TEXT_LIMIT], 'score': item.get('score', 0.0),
            'target_field': str(metadata.get('target_field', item.get('target_field', ''))).strip(),
            'query_intent': str(metadata.get('query_intent', item.get('query_intent', ''))).strip(),
            'query_source': str(metadata.get('query_source', item.get('query_source', ''))).strip(),
            'matched_keywords': list(metadata.get('matched_keywords', item.get('matched_keywords', [])))[:6] if isinstance(metadata.get('matched_keywords', item.get('matched_keywords', [])), list) else [],
            'evidence_tier': str(metadata.get('evidence_tier', item.get('evidence_tier', ''))).strip(),
            'source_hierarchy': str(metadata.get('source_hierarchy', item.get('source_hierarchy', ''))).strip(),
        })
    return compact


def _compact_normalized_input_for_agent(normalization_result: dict[str, Any] | None) -> dict[str, Any]:
    missing_fields = _missing_fields(normalization_result)
    facility = {}
    field_index_summary: list[dict[str, Any]] = []
    if isinstance(normalization_result, dict):
        normalized_input = normalization_result.get("normalized_input", {})
        if isinstance(normalized_input, dict):
            raw_facility = normalized_input.get("facility", {})
            if isinstance(raw_facility, dict):
                for key in ("poi_voltage_kv", "ups", "load_schedule", "transformers", "generators", "interconnection", "protection", "telemetry"):
                    value = raw_facility.get(key)
                    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
                        facility[key] = value
        field_index = _normalized_field_index(normalization_result)
        prioritized = sorted((item for item in field_index.values() if isinstance(item, dict)), key=lambda item: (0 if bool(item.get('planner_critical', False)) else 1, 0 if str(item.get('status', '')).strip().lower() in {'missing', 'conflicting'} else 1, str(item.get('field_path', ''))))[:12]
        for item in prioritized:
            field_index_summary.append({
                'field_id': str(item.get('field_id', '')).strip(),
                'field_path': str(item.get('field_path', '')).strip(),
                'label': str(item.get('label', '')).strip(),
                'group': str(item.get('group', '')).strip(),
                'planner_critical': bool(item.get('planner_critical', False)),
                'status': str(item.get('status', '')).strip(),
                'value': item.get('value'),
            })
    return {'facility': facility, 'missing_fields': missing_fields[:8], 'normalized_field_index': field_index_summary}


def _compact_equipment_resolution_for_agent(equipment_reference_resolution: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(equipment_reference_resolution, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("evidence_gap", "web_lookup_required"):
        value = equipment_reference_resolution.get(key)
        if isinstance(value, (str, int, float, bool, dict)) or value is None:
            compact[key] = value
    for key in ("unresolved_missing_fields", "review_required_fields"):
        value = equipment_reference_resolution.get(key)
        if isinstance(value, list):
            compact[key] = value[:4]
            compact[f"{key}_count"] = len(value)
    warnings = equipment_reference_resolution.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        compact["warnings"] = [str(item).strip() for item in warnings[:2] if str(item).strip()]
    return compact



def _build_retrieval_agent_inputs(
    *,
    queries: list[dict[str, Any]],
    snippets: list[dict[str, Any]],
    normalization_result: dict[str, Any] | None,
    equipment_reference_resolution: dict[str, Any] | None,
    missing_fields: list[str],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    equipment_resolution = _compact_equipment_resolution_for_agent(equipment_reference_resolution)
    suppressed_fields = []
    if isinstance(equipment_resolution, dict):
        suppressed_fields = [str(item) for item in equipment_resolution.get("suppressed_field_paths", []) if str(item).strip()]
    return {
        "query_candidates": _compact_queries_for_agent(queries),
        "evidence_snippets": _compact_snippets_for_agent(snippets),
        "warnings": list(warnings or []),
        "missing_field_summary": {
            "missing_field_count": len(missing_fields),
            "missing_fields": missing_fields[:60],
            "planner_critical_missing_fields": [field for field in missing_fields if any(token in field for token in ("poi", "voltage", "mw", "generator", "transformer", "ups", "ramp"))][:40],
        },
        "normalized_input_summary": _compact_normalized_input_for_agent(normalization_result),
        "equipment_reference_resolution": equipment_resolution,
        "document_field_pack_suppression": {
            "suppressed_field_paths": suppressed_fields[:80],
            "suppressed_field_count": len(suppressed_fields),
        },
        "chunking_domains": [
            "equipment_reference_lookup",
            "interconnection_guidance",
            "modeling_reference_lookup",
            "official_web_lookup",
            "vendor_pdf_lookup",
            "unresolved_applicant_fields",
        ],
    }

def _run_evidence_resolution_agent(
    *,
    context: Any,
    queries: list[dict[str, Any]],
    snippets: list[dict[str, Any]],
    normalization_result: dict[str, Any] | None,
    equipment_reference_resolution: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not _can_run_agent(context):
        return None

    missing_fields = _missing_fields(normalization_result)
    return run_agent(
        context=context,
        request=AgentRequest(
            agent_id="evidence_resolution_agent",
            stage_name=GAP_RESOLUTION_RETRIEVAL_STAGE,
            task_name="evidence_resolution",
            inputs=_build_retrieval_agent_inputs(
                queries=queries,
                snippets=snippets,
                normalization_result=normalization_result,
                equipment_reference_resolution=equipment_reference_resolution,
                missing_fields=missing_fields,
            ),
            metadata={
                "service": "retrieval_service",
            },
            trigger_reason="bounded_evidence_resolution_requested",
            associated_field_paths=missing_fields,
            evidence_anchors=[
                {
                    "anchor_type": "retrieval_query",
                    "target_field": str(query.get("target_field", "")).strip(),
                    "query_source": str(query.get("query_source", "")).strip(),
                    "intent": str(query.get("intent", "")).strip(),
                }
                for query in queries
                if isinstance(query, dict)
            ],
            suggested_output_fields=[
                "evidence_findings",
                "source_priority_summary",
                "suggested_queries",
                "knowledge_family_route",
                "web_lookup_recommendations",
                "evidence_gap_flag",
                "recommended_next_request",
                "rationale",
                "confidence",
            ],
        ),
    )


def _run_retrieval_planning_agent(
    *,
    context: Any,
    queries: list[dict[str, Any]],
    snippets: list[dict[str, Any]],
    normalization_result: dict[str, Any] | None,
    equipment_reference_resolution: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not _can_run_agent(context):
        return None

    validation_report: dict[str, Any] = {}
    missing_fields = _missing_fields(normalization_result)
    if isinstance(normalization_result, dict):
        raw_validation_report = normalization_result.get("validation_report", {})
        if isinstance(raw_validation_report, dict):
            validation_report = raw_validation_report

    return run_agent(
        context=context,
        request=AgentRequest(
            agent_id="retrieval_planning_agent",
            stage_name=GAP_RESOLUTION_RETRIEVAL_STAGE,
            task_name="query_review",
            inputs=_build_retrieval_agent_inputs(
                queries=queries,
                snippets=snippets,
                normalization_result=normalization_result,
                equipment_reference_resolution=equipment_reference_resolution,
                missing_fields=missing_fields,
                warnings=[],
            ),
            metadata={
                "service": "retrieval_service",
            },
            trigger_reason="missing_field_or_evidence_gap_retrieval_planning",
            associated_field_paths=missing_fields,
            evidence_anchors=[
                {
                    "anchor_type": "retrieval_query",
                    "target_field": str(query.get("target_field", "")).strip(),
                    "query_source": str(query.get("query_source", "")).strip(),
                    "intent": str(query.get("intent", "")).strip(),
                }
                for query in queries
                if isinstance(query, dict)
            ],
            suggested_output_fields=[
                "query_plan",
                "suggested_queries",
                "suggested_query_topics",
                "knowledge_family_route",
                "web_lookup_recommendations",
                "source_priority_summary",
                "evidence_gap_flag",
                "rationale",
                "confidence",
            ],
        ),
    )


def run_service(
    context: Any,
    normalization_result: dict[str, Any] | None = None,
    extraction_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.retrieval_service.domain import RetrievalDomainCoordinator

    coordinator = RetrievalDomainCoordinator()
    return coordinator.run_retrieval(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )


def retrieve_evidence(

    context: Any,
    normalization_result: dict[str, Any] | None = None,
    extraction_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )