from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from shared.knowledge_routes import (
    KNOWLEDGE_ROOT,
    preferred_equipment_catalog_index,
    preferred_official_source_index,
    preferred_pdf_library_index,
    preferred_pdf_roots,
    resolve_knowledge_path,
)

from .identity_resolution import (
    EquipmentIdentityCandidate,
    canonical_family,
    collect_identity_seeds,
    normalize_token,
    rank_identity_candidates,
)
from .models import EquipmentReferenceResolutionResult, EquipmentSpecCandidate
from .planner_guidance import infer_relevant_families, target_fields_for_families


FIELD_ALIASES: dict[str, list[str]] = {
    "rated_power_kw": ["rated power", "kw", "kilowatts", "power rating", "output power", "real power"],
    "rated_capacity_kva": ["kva", "capacity", "rated kva", "apparent power", "nameplate kva"],
    "rated_power_kva": ["rated kva", "generator kva", "nameplate kva", "apparent power"],
    "voltage_v": ["voltage", "v", "vac", "kv", "line voltage", "rated voltage"],
    "primary_voltage_v": ["primary voltage", "primary v", "high voltage", "input voltage", "hv voltage"],
    "secondary_voltage_v": ["secondary voltage", "secondary v", "low voltage", "output voltage", "lv voltage"],
    "transfer_time_ms": ["transfer time", "ms", "milliseconds", "switching time"],
    "frequency_hz": ["frequency", "hz", "nominal frequency"],
    "fuel_type": ["fuel", "fuel type", "fuel source"],
    "impedance_percent": ["impedance", "percent impedance", "%z", "z percent"],
    "current_a": ["amps", "amperes", "current", "rated current"],
    "efficiency_percent": ["efficiency", "percent efficient", "efficiency %"],
    "step_load_acceptance_percent": ["step load", "step load acceptance", "load acceptance"],
    "startup_delay_seconds": ["startup delay", "start delay", "seconds to start"],
    "power_factor": ["power factor", "pf"],
    "standby_or_prime_rating": ["standby rating", "prime rating", "rating class"],
}

FAMILY_FIELD_ALIASES: dict[str, dict[str, list[str]]] = {
    "ups": {
        "rated_power_kw": ["output power kw", "power module rating", "system output power"],
        "transfer_time_ms": ["battery transfer time", "transfer time"],
        "voltage_v": ["output voltage", "nominal output voltage"],
    },
    "generators": {
        "rated_power_kw": ["standby power", "prime power", "power kw"],
        "rated_power_kva": ["generator kva", "standby kva"],
        "voltage_v": ["generator voltage", "rated voltage"],
        "frequency_hz": ["operating frequency"],
        "fuel_type": ["fuel source"],
        "step_load_acceptance_percent": ["step load acceptance"],
    },
    "transformers": {
        "rated_capacity_kva": ["transformer rating", "nameplate kva"],
        "primary_voltage_v": ["primary voltage", "hv voltage"],
        "secondary_voltage_v": ["secondary voltage", "lv voltage"],
        "impedance_percent": ["impedance percent"],
    },
    "switchgear": {
        "voltage_v": ["rated voltage", "system voltage"],
        "current_a": ["bus current", "rated current"],
    },
}


# ---------- generic helpers ----------

def _safe_read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _normalize_domain(value: Any) -> str:
    host = str(value or "").strip().lower()
    if "@" in host:
        host = host.split("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host.strip(".")


def _is_official_source_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() != "https":
        return False
    return bool(_normalize_domain(parsed.netloc))


def _coerce_missing_fields(normalization_result: dict[str, Any] | None) -> list[str]:
    if not isinstance(normalization_result, dict):
        return []
    report = normalization_result.get("validation_report", {})
    if not isinstance(report, dict):
        return []
    raw = report.get("missing_fields", [])
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if isinstance(item, str) and str(item).strip()]


def _preferred_official_source_index() -> Path:
    return preferred_official_source_index()


def _preferred_pdf_library_index() -> Path:
    return preferred_pdf_library_index()


def _candidate_pdf_roots() -> list[Path]:
    roots = preferred_pdf_roots()
    deduped: list[Path] = []
    for root in roots:
        if root not in deduped:
            deduped.append(root)
    return deduped


def _resolve_spec_path(spec_path_value: str) -> Path | None:
    normalized = str(spec_path_value or "").strip()
    if not normalized:
        return None
    path = Path(normalized)
    if path.is_absolute() and path.exists():
        return path
    for candidate in (
        KNOWLEDGE_ROOT.parents[0] / normalized,
        KNOWLEDGE_ROOT.parent / normalized,
        KNOWLEDGE_ROOT / normalized,
    ):
        if candidate.exists():
            return candidate
    return resolve_knowledge_path(normalized)


# ---------- index loading ----------

def _audit_knowledge_indexes() -> dict[str, Any]:
    catalog_payload = _safe_read_json(preferred_equipment_catalog_index())
    official_index_path = _preferred_official_source_index()
    official_payload = _safe_read_json(official_index_path)
    pdf_index_path = _preferred_pdf_library_index()
    pdf_payload = _safe_read_json(pdf_index_path)

    catalog_records = catalog_payload.get("records", []) if isinstance(catalog_payload, dict) else []
    official_families = official_payload.get("families", []) if isinstance(official_payload, dict) else []
    pdf_records = pdf_payload.get("records", []) if isinstance(pdf_payload, dict) else []

    catalog_missing_paths = 0
    if isinstance(catalog_records, list):
        for item in catalog_records:
            if not isinstance(item, dict):
                continue
            spec_path = _resolve_spec_path(str(item.get("spec_path", "")).strip())
            if spec_path is None:
                catalog_missing_paths += 1

    official_record_count = 0
    if isinstance(official_families, list):
        for family_block in official_families:
            if not isinstance(family_block, dict):
                continue
            records = family_block.get("records", [])
            if isinstance(records, list):
                official_record_count += len(records)

    discovered_pdf_count = 0
    for root in _candidate_pdf_roots():
        if root.exists():
            discovered_pdf_count += sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".pdf", ".txt", ".md", ".html", ".htm"})

    return {
        "catalog_index_path": str(preferred_equipment_catalog_index()),
        "catalog_index_exists": preferred_equipment_catalog_index().exists(),
        "catalog_record_count": len(catalog_records) if isinstance(catalog_records, list) else 0,
        "catalog_missing_spec_paths": catalog_missing_paths,
        "official_source_index_path": str(official_index_path),
        "official_source_index_exists": official_index_path.exists(),
        "official_family_count": len(official_families) if isinstance(official_families, list) else 0,
        "official_record_count": official_record_count,
        "pdf_library_index_path": str(pdf_index_path),
        "pdf_library_index_exists": pdf_index_path.exists(),
        "pdf_library_record_count": len(pdf_records) if isinstance(pdf_records, list) else 0,
        "discovered_pdf_document_count": discovered_pdf_count,
        "pdf_repository_roots": [str(root) for root in _candidate_pdf_roots()],
    }


def _load_spec_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    catalog_payload = _safe_read_json(preferred_equipment_catalog_index())
    if isinstance(catalog_payload, dict):
        raw_records = catalog_payload.get("records", [])
        if isinstance(raw_records, list):
            for item in raw_records:
                if not isinstance(item, dict):
                    continue
                family = str(item.get("equipment_family", "")).strip()
                manufacturer = str(item.get("manufacturer", "")).strip()
                model = str(item.get("model_or_product_line", item.get("model", ""))).strip()
                spec_path = _resolve_spec_path(str(item.get("spec_path", "")).strip())
                if not family or not manufacturer or not model or spec_path is None:
                    continue
                spec_payload = _safe_read_json(spec_path)
                if not isinstance(spec_payload, dict):
                    continue
                spec_payload["__path"] = str(spec_path)
                spec_payload["__manufacturer_key"] = normalize_token(manufacturer)
                spec_payload["__model_key"] = normalize_token(model)
                spec_payload["__family_key"] = normalize_token(canonical_family(family))
                spec_payload.setdefault("equipment_family", family)
                spec_payload.setdefault("manufacturer", manufacturer)
                spec_payload.setdefault("model", model)
                spec_payload.setdefault("record_status", str(item.get("record_status", "")).strip())
                spec_payload.setdefault("source_urls", item.get("source_urls", []))
                records.append(spec_payload)
    return records


def _load_official_source_index() -> list[dict[str, Any]]:
    payload = _safe_read_json(_preferred_official_source_index())
    if not isinstance(payload, dict):
        return []
    flattened: list[dict[str, Any]] = []
    for family_block in payload.get("families", []):
        if not isinstance(family_block, dict):
            continue
        family = str(family_block.get("family", "")).strip()
        for item in family_block.get("records", []):
            if not isinstance(item, dict):
                continue
            manufacturer = str(item.get("manufacturer", "")).strip()
            model = str(item.get("model_or_product_line", item.get("model", ""))).strip()
            urls = [str(url).strip() for url in item.get("source_urls", []) if isinstance(url, str) and str(url).strip()]
            if not manufacturer or not model or not urls:
                continue
            flattened.append(
                {
                    "equipment_family": family,
                    "manufacturer": manufacturer,
                    "model": model,
                    "source_urls": urls,
                    "manufacturer_key": normalize_token(manufacturer),
                    "model_key": normalize_token(model),
                    "family_key": normalize_token(canonical_family(family)),
                }
            )
    return flattened


def _parse_pdf_library_records(payload: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    raw_records = payload.get("records", [])
    if isinstance(raw_records, list):
        return [item for item in raw_records if isinstance(item, dict)]
    for family_block in payload.get("families", []):
        if not isinstance(family_block, dict):
            continue
        family = str(family_block.get("family", "")).strip()
        for manufacturer_block in family_block.get("manufacturers", []):
            if not isinstance(manufacturer_block, dict):
                continue
            manufacturer = str(manufacturer_block.get("manufacturer", "")).strip()
            for model_block in manufacturer_block.get("models", []):
                if not isinstance(model_block, dict):
                    continue
                model = str(model_block.get("model_or_product_line", model_block.get("model", ""))).strip()
                for document in model_block.get("documents", []):
                    if isinstance(document, dict):
                        records.append({"equipment_family": family, "manufacturer": manufacturer, "model": model, **document})
    return records


def _infer_vendor_entries_from_legacy_source_lists() -> list[dict[str, Any]]:
    """Compatibility fallback only when canonical vendor-document indexes are unavailable."""
    payload = _safe_read_json(_preferred_pdf_library_index())
    if isinstance(payload, dict) and isinstance(payload.get("records"), list) and payload.get("records"):
        return []
    return []


def _load_pdf_repository_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    payload = _safe_read_json(_preferred_pdf_library_index())
    parsed_records = _parse_pdf_library_records(payload)
    source_records = parsed_records if parsed_records else _infer_vendor_entries_from_legacy_source_lists()

    for item in source_records:
        family = str(item.get("equipment_family", item.get("family", ""))).strip()
        manufacturer = str(item.get("manufacturer", "")).strip()
        model = str(item.get("model", item.get("model_or_product_line", ""))).strip()
        document_type = str(item.get("document_type", item.get("type", "vendor_pdf"))).strip() or "vendor_pdf"
        relative_path = str(item.get("document_path", item.get("path", item.get("pdf_path", "")))).strip()
        source_url = str(item.get("source_url", "")).strip()
        document_label = str(item.get("document_label", "")).strip() or f"{manufacturer} {model} {document_type}".strip()
        key = (normalize_token(canonical_family(family)), normalize_token(manufacturer), normalize_token(model), document_type.lower(), source_url or relative_path or document_label)
        if key in seen:
            continue
        seen.add(key)
        candidate_path = None
        if relative_path:
            candidate_path = _resolve_spec_path(relative_path)
            if candidate_path is None:
                for root in _candidate_pdf_roots():
                    trial = root / relative_path
                    if trial.exists():
                        candidate_path = trial
                        break
        entries.append(
            {
                "equipment_family": family,
                "manufacturer": manufacturer,
                "model": model,
                "document_type": document_type,
                "document_label": document_label,
                "document_keywords": list(item.get("document_keywords", [])) if isinstance(item.get("document_keywords"), list) else [],
                "pointer_text": str(item.get("pointer_text", "")).strip(),
                "path": str(candidate_path) if candidate_path else relative_path,
                "source_url": source_url,
                "family_key": normalize_token(canonical_family(family)),
                "manufacturer_key": normalize_token(manufacturer),
                "model_key": normalize_token(model),
                "retrieval_priority": str(item.get("retrieval_priority", "medium")).strip().lower() or "medium",
                "source_kind": str(item.get("source_kind", "vendor_document")).strip() or "vendor_document",
                "evidence_tier": str(item.get("evidence_tier", "vendor_document_pointer" if document_type.lower() == "vendor_pdf_pointer" else ("official_vendor_document" if source_url else "vendor_document"))).strip() or "vendor_document",
                "trust_level": str(item.get("trust_level", "medium" if document_type.lower() == "vendor_pdf_pointer" else ("high" if source_url else "medium"))).strip() or "medium",
                "source_domain": _normalize_domain(urlparse(source_url).netloc) if source_url else "",
            }
        )
    return entries

# ---------- field mapping ----------

def _field_alias_terms(field_path: str, equipment_family: str | None = None) -> list[str]:
    path = str(field_path or "").strip().lower()
    if not path:
        return []
    suffix = path.split(".")[-1]
    terms = [path, suffix, suffix.replace("_", " ")]
    terms.extend(FIELD_ALIASES.get(suffix, []))
    family_key = canonical_family(str(equipment_family or "")) if equipment_family else ""
    if family_key:
        terms.extend(FAMILY_FIELD_ALIASES.get(family_key, {}).get(suffix, []))
    deduped: list[str] = []
    for item in terms:
        cleaned = str(item).strip().lower()
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


def _canonical_field_key(field_path: str) -> str:
    path = str(field_path or "").strip().lower()
    return path.split(".")[-1] if path else ""


def _field_name_matches_target(spec_field: str, target_fields: list[str], equipment_family: str | None = None) -> bool:
    normalized_spec = str(spec_field).strip().lower()
    if not normalized_spec:
        return False
    if not target_fields:
        return True
    spec_terms = {normalized_spec, normalized_spec.replace("_", " "), normalize_token(normalized_spec)}
    for target in target_fields:
        lowered_target = str(target).strip().lower()
        if not lowered_target:
            continue
        alias_terms = set(_field_alias_terms(lowered_target, equipment_family=equipment_family))
        alias_terms |= {normalize_token(term) for term in alias_terms}
        if lowered_target.endswith(normalized_spec):
            return True
        if normalized_spec in lowered_target or lowered_target in normalized_spec:
            return True
        if spec_terms & alias_terms:
            return True
    return False


def _iter_structured_spec_sections(record: dict[str, Any]) -> list[tuple[str, dict[str, Any], str]]:
    sections: list[tuple[str, dict[str, Any], str]] = []
    for section_name, source_type in (
        ("fixed_specs", "library_fixed_spec"),
        ("project_specific_fields", "library_project_specific"),
        ("alternate_ratings", "library_alternate_rating"),
    ):
        payload = record.get(section_name, {})
        if not isinstance(payload, dict):
            continue
        for spec_field, spec_payload in payload.items():
            if isinstance(spec_payload, dict):
                sections.append((str(spec_field).strip(), spec_payload, source_type))
    return sections


def _record_field_inventory(record: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for spec_field, _, _ in _iter_structured_spec_sections(record):
        if spec_field not in fields:
            fields.append(spec_field)
    return fields


def _build_candidate_fields(record: dict[str, Any], target_fields: list[str]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    record_family = str(record.get("equipment_family", "")).strip()
    for spec_field, payload, source_type in _iter_structured_spec_sections(record):
        if not _field_name_matches_target(spec_field, target_fields, equipment_family=record_family):
            continue
        value = payload.get("value")
        if value is None:
            continue
        canonical_field_key = spec_field.lower()
        confidence = 0.88
        confidence_reason = "section_match"
        for target in target_fields or [spec_field]:
            alias_terms = _field_alias_terms(target, equipment_family=record_family)
            if spec_field.lower() in {term.lower() for term in alias_terms} or _canonical_field_key(target) == spec_field.lower():
                canonical_field_key = _canonical_field_key(target)
                confidence = 0.98
                confidence_reason = "direct_field_alias_match"
                break
            if _field_name_matches_target(spec_field, [target], equipment_family=record_family):
                canonical_field_key = _canonical_field_key(target)
                confidence = max(confidence, 0.92)
                confidence_reason = "family_alias_field_match"
        source_url = None
        source_documents = record.get("source_documents")
        if isinstance(source_documents, list) and source_documents:
            first_doc = source_documents[0]
            if isinstance(first_doc, dict):
                source_url = str(first_doc.get("source_url", "")).strip() or None
        if source_url is None:
            source_urls = record.get("source_urls")
            if isinstance(source_urls, list) and source_urls:
                source_url = str(source_urls[0]).strip() or None
        candidate = EquipmentSpecCandidate(
            equipment_family=record_family,
            manufacturer=str(record.get("manufacturer", "")).strip(),
            model=str(record.get("model", "")).strip(),
            spec_field=spec_field,
            value=value,
            source_type=source_type,
            source_ref=str(record.get("__path", "")).strip(),
            source_url=source_url,
            confidence=confidence,
            evidence_text=str(payload.get("note", "")).strip() or None,
            review_required=confidence < 0.95,
            confidence_reason=confidence_reason,
            matched_field_key=spec_field,
            canonical_field_key=canonical_field_key,
            source_priority="equipment_catalog",
            source_kind="equipment_catalog",
            document_type="catalog_record",
            document_path=str(record.get("__path", "")).strip() or None,
            evidence_tier="structured_catalog",
            match_reason=confidence_reason,
        )
        selected.append(candidate.to_dict())
    return selected


# ---------- snippets and source planning ----------

def _build_library_snippet(record: dict[str, Any], candidate_fields: list[dict[str, Any]]) -> dict[str, Any]:
    summary = "; ".join(f"{item['spec_field']}={item['value']!r}" for item in candidate_fields[:6]) or "No populated fixed specs found."
    return {
        "corpus": "equipment_catalog",
        "source_ref": str(record.get("__path", "")).strip() or str(record.get("model", "")).strip(),
        "text": f"Equipment catalog match for {record.get('manufacturer')} {record.get('model')}: {summary}",
        "score": 0.95,
        "metadata": {
            "topic": f"{record.get('equipment_family')}.catalog_match",
            "matched_keywords": [str(record.get("manufacturer", "")).strip(), str(record.get("model", "")).strip()],
            "target_field": ",".join(sorted({str(item.get('canonical_field_key', item.get('spec_field', ''))).strip() for item in candidate_fields if str(item.get('spec_field', '')).strip()})),
            "query_intent": "equipment_reference_resolution",
            "query_source": "equipment_catalog",
            "equipment_family": str(record.get("equipment_family", "")).strip(),
            "manufacturer": str(record.get("manufacturer", "")).strip(),
            "model": str(record.get("model", "")).strip(),
            "candidate_fields": candidate_fields,
            "source_kind": "equipment_catalog",
            "document_type": "catalog_record",
            "document_path": str(record.get("__path", "")).strip(),
            "evidence_tier": "structured_catalog",
            "source_priority": "equipment_catalog",
            "match_reason": "library_catalog_match",
            "matched_target_fields": [
                str(item.get('canonical_field_key', item.get('spec_field', ''))).strip()
                for item in candidate_fields
                if str(item.get('spec_field', '')).strip()
            ],
        },
    }


def _build_official_source_candidates(candidate: EquipmentIdentityCandidate, official_index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family_key = normalize_token(canonical_family(candidate.equipment_family))
    manufacturer_key = normalize_token(candidate.manufacturer)
    model_key = normalize_token(candidate.model)
    results: list[dict[str, Any]] = []
    for record in official_index:
        if record.get("family_key") != family_key:
            continue
        record_model_key = str(record.get("model_key", ""))
        record_manufacturer_key = str(record.get("manufacturer_key", ""))
        if manufacturer_key and record_manufacturer_key != manufacturer_key and manufacturer_key not in record_manufacturer_key and record_manufacturer_key not in manufacturer_key:
            continue
        if model_key != record_model_key and model_key not in record_model_key and record_model_key not in model_key:
            continue
        for url in record.get("source_urls", []):
            host = urlparse(url).netloc.lower()
            if host:
                match_reason = "exact_model_match" if model_key == record_model_key else "family_match"
                results.append(
                    {
                        "equipment_family": candidate.equipment_family,
                        "manufacturer": record.get("manufacturer", candidate.manufacturer),
                        "model": record.get("model", candidate.model),
                        "source_url": url,
                        "host": host,
                        "allowed_domain": host,
                        "source_type": "official_source_index",
                        "official": True,
                        "source_kind": "official_web",
                        "document_type": "official_vendor_document",
                        "evidence_tier": "official_vendor_document",
                        "source_priority": "manufacturer_model_specific_spec" if match_reason == "exact_model_match" else "official_web",
                        "match_reason": match_reason,
                    }
                )
    return results


def _build_pdf_lookup_plans(candidate: EquipmentIdentityCandidate, pdf_documents: list[dict[str, Any]], unresolved_missing_fields: list[str]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for document in pdf_documents:
        path = str(document.get("path", "")).strip()
        source_url = str(document.get("source_url", "")).strip()
        terms: list[str] = [candidate.manufacturer, candidate.model, candidate.equipment_family, str(document.get("document_label", "")).strip()]
        for field in unresolved_missing_fields:
            terms.extend(_field_alias_terms(field, candidate.equipment_family)[:4])
        plans.append(
            {
                "lookup_mode": "vendor_pdf_repository",
                "equipment_family": candidate.equipment_family,
                "manufacturer": candidate.manufacturer,
                "model": candidate.model,
                "document_path": path,
                "document_label": str(document.get("document_label", "")).strip(),
                "document_type": str(document.get("document_type", "")).strip(),
                "source_kind": str(document.get("source_kind", "vendor_document")).strip(),
                "source_url": source_url,
                "source_domain": str(document.get("source_domain", "")).strip(),
                "evidence_tier": str(document.get("evidence_tier", "vendor_document")).strip(),
                "retrieval_priority": str(document.get("retrieval_priority", "")).strip(),
                "match_score": float(document.get("match_score", 0.0) or 0.0),
                "match_reasons": list(document.get("match_reasons", [])) if isinstance(document.get("match_reasons"), list) else [],
                "missing_fields": list(unresolved_missing_fields or []),
                "search_terms": [item for item in terms if item],
                "instructions": "Search the matched vendor document for the unresolved fields before attempting any web lookup. Prefer exact manufacturer/model evidence and preserve source metadata.",
            }
        )
    return plans

def _build_web_lookup_plans(candidate: EquipmentIdentityCandidate, official_source_candidates: list[dict[str, Any]], unresolved_missing_fields: list[str]) -> list[dict[str, Any]]:
    if not official_source_candidates:
        return []
    allowed_domains: list[str] = []
    allowed_urls: list[str] = []
    for item in official_source_candidates:
        host = str(item.get("allowed_domain", item.get("host", ""))).strip().lower()
        url = str(item.get("source_url", "")).strip()
        if host and host not in allowed_domains:
            allowed_domains.append(host)
        if url and url not in allowed_urls:
            allowed_urls.append(url)
    search_terms = [candidate.manufacturer, candidate.model, candidate.equipment_family, *unresolved_missing_fields]
    search_terms = [str(item).strip() for item in search_terms if isinstance(item, str) and str(item).strip()]
    return [
        {
            "lookup_mode": "official_source_only",
            "equipment_family": candidate.equipment_family,
            "manufacturer": candidate.manufacturer,
            "model": candidate.model,
            "allowed_domains": allowed_domains,
            "allowed_urls": allowed_urls,
            "search_terms": search_terms,
            "missing_fields": list(unresolved_missing_fields),
            "instructions": "Search only the listed official vendor domains or URLs for missing specification fields. Do not use unofficial sources. Any retrieved candidate must still go through validation before canonical acceptance.",
        }
    ]


def _build_authenticity_guardrails(official_source_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    allowed_domains = []
    allowed_urls = []
    for item in official_source_candidates:
        host = _normalize_domain(item.get("allowed_domain", item.get("host", "")))
        url = str(item.get("source_url", "")).strip()
        if host and host not in allowed_domains:
            allowed_domains.append(host)
        if _is_official_source_url(url) and url not in allowed_urls:
            allowed_urls.append(url)
    return {
        "lookup_mode": "official_source_only",
        "library_first": True,
        "require_https": True,
        "allow_only_listed_domains": True,
        "allow_only_listed_urls_when_present": bool(allowed_urls),
        "reject_unofficial_sources": True,
        "allowed_domains": allowed_domains,
        "allowed_urls": allowed_urls,
        "official_source_index": str(_preferred_official_source_index()),
    }


def _dedupe_str_list(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


# ---------- evidence lookup ----------

def _preferred_pdf_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".html", ".htm", ".json"}:
        return _safe_read_text(path)
    if suffix != ".pdf":
        return ""
    try:
        import pdfplumber  # type: ignore
    except Exception:
        return ""
    try:
        parts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:8]:
                extracted = page.extract_text() or ""
                cleaned = re.sub(r"\s+", " ", extracted).strip()
                if cleaned:
                    parts.append(cleaned)
                if len(" ".join(parts)) > 18000:
                    break
        return " ".join(parts).strip()
    except Exception:
        return ""


def _match_pdf_documents(candidate: EquipmentIdentityCandidate, pdf_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family_key = normalize_token(canonical_family(candidate.equipment_family))
    manufacturer_key = normalize_token(candidate.manufacturer)
    model_key = normalize_token(candidate.model)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in pdf_entries:
        if str(item.get("family_key", "")) != family_key:
            continue
        item_manufacturer_key = str(item.get("manufacturer_key", ""))
        item_model_key = str(item.get("model_key", ""))
        manufacturer_ok = not manufacturer_key or manufacturer_key == item_manufacturer_key or manufacturer_key in item_manufacturer_key or item_manufacturer_key in manufacturer_key
        model_ok = model_key == item_model_key or model_key in item_model_key or item_model_key in model_key
        if not (manufacturer_ok and model_ok):
            continue
        score = 0.5
        reasons: list[str] = []
        if manufacturer_key and manufacturer_key == item_manufacturer_key:
            score += 0.2
            reasons.append("exact_manufacturer")
        elif manufacturer_ok:
            score += 0.08
            reasons.append("compatible_manufacturer")
        if model_key == item_model_key:
            score += 0.24
            reasons.append("exact_model")
        elif model_ok:
            score += 0.12
            reasons.append("compatible_model")
        document_type = str(item.get("document_type", "")).strip().lower()
        evidence_tier = str(item.get("evidence_tier", "")).strip().lower()
        retrieval_priority = str(item.get("retrieval_priority", "")).strip().lower()
        if evidence_tier == "official_vendor_document" or "official" in document_type:
            score += 0.1
            reasons.append("official_vendor_document")
        elif evidence_tier == "vendor_document_pointer":
            score -= 0.05
            reasons.append("pointer_only")
        if retrieval_priority == "high":
            score += 0.06
        elif retrieval_priority == "low":
            score -= 0.03
        label = str(item.get("document_label", "")).strip().lower()
        if candidate.model.lower() in label:
            score += 0.05
            reasons.append("model_in_document_label")
        enriched = dict(item)
        enriched["match_score"] = round(min(0.99, max(0.0, score)), 4)
        enriched["match_reasons"] = reasons
        ranked.append((enriched["match_score"], enriched))
    ranked.sort(key=lambda pair: (-float(pair[0]), str(pair[1].get("document_label", "")), str(pair[1].get("source_url", ""))))
    return [item for _, item in ranked[:8]]

def _text_windows(text: str, search_terms: list[str]) -> list[str]:
    lowered = text.lower()
    windows: list[str] = []
    for term in search_terms:
        cleaned = str(term).strip().lower()
        if not cleaned:
            continue
        idx = lowered.find(cleaned)
        if idx < 0:
            continue
        start = max(0, idx - 180)
        end = min(len(text), idx + 280)
        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
        if snippet and snippet not in windows:
            windows.append(snippet)
    if not windows and text:
        preview = re.sub(r"\s+", " ", text[:320]).strip()
        if preview:
            windows.append(preview)
    return windows[:5]


def _extract_value_from_window(field_path: str, window: str) -> tuple[Any, float, bool]:
    lowered = field_path.lower()
    if "voltage" in lowered:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(kv|v)", window, flags=re.I)
        if match:
            return f"{match.group(1)} {match.group(2).upper()}", 0.73, True
    if "transfer_time" in lowered:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(ms|milliseconds?)", window, flags=re.I)
        if match:
            return f"{match.group(1)} ms", 0.68, True
    if "frequency" in lowered:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(hz)", window, flags=re.I)
        if match:
            return f"{match.group(1)} Hz", 0.74, True
    if any(token in lowered for token in ("power", "kw", "kva", "mva", "mw")):
        match = re.search(r"(\d+(?:\.\d+)?)\s*(kw|kva|mw|mva)", window, flags=re.I)
        if match:
            return f"{match.group(1)} {match.group(2).upper()}", 0.72, True
    if "percent" in lowered or lowered.endswith("_pf") or "power_factor" in lowered:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(%|percent)", window, flags=re.I)
        if match:
            return f"{match.group(1)}%", 0.65, True
    return window.strip(), 0.56, True


def _build_evidence_candidates(*, candidate: EquipmentIdentityCandidate, target_fields: list[str], evidence_text: str, source_type: str, source_ref: str, source_url: str | None = None, document_type: str | None = None, document_path: str | None = None, document_label: str | None = None, evidence_tier: str | None = None, source_kind: str | None = None, match_reason: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []
    review_fields: list[str] = []
    for field_path in target_fields:
        alias_terms = _field_alias_terms(field_path, equipment_family=candidate.equipment_family)
        windows = _text_windows(evidence_text, alias_terms)
        if not windows:
            continue
        value, confidence, review_required = _extract_value_from_window(field_path, windows[0])
        review_fields.append(field_path)
        candidates.append(
            EquipmentSpecCandidate(
                equipment_family=candidate.equipment_family,
                manufacturer=candidate.manufacturer,
                model=candidate.model,
                spec_field=_canonical_field_key(field_path),
                value=value,
                source_type=source_type,
                source_ref=source_ref,
                source_url=source_url,
                confidence=confidence,
                evidence_text=windows[0],
                review_required=review_required,
                confidence_reason="document_window_extraction",
                matched_field_key=_canonical_field_key(field_path),
                canonical_field_key=_canonical_field_key(field_path),
                source_priority="vendor_documents" if source_type.startswith("vendor_") else "official_web",
                source_kind=source_kind,
                document_type=document_type,
                document_path=document_path,
                evidence_tier=evidence_tier,
                match_reason=match_reason,
            ).to_dict()
        )
        snippets.append(
            {
                "corpus": "vendor_documents" if source_type.startswith("vendor_") else "equipment_catalog",
                "source_ref": source_ref,
                "text": windows[0],
                "score": confidence,
                "metadata": {
                    "topic": field_path,
                    "matched_keywords": alias_terms,
                    "target_field": field_path,
                    "source_type": source_type,
                    "source_url": source_url,
                    "source_kind": source_kind,
                    "document_type": document_type,
                    "document_path": document_path,
                    "document_label": document_label,
                    "evidence_tier": evidence_tier,
                    "match_reason": match_reason,
                },
            }
        )
    return candidates, snippets, sorted(set(review_fields))

def _search_pdf_repository(candidate: EquipmentIdentityCandidate, target_fields: list[str], pdf_entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    matched_documents = _match_pdf_documents(candidate, pdf_entries)
    pdf_candidates: list[dict[str, Any]] = []
    pdf_snippets: list[dict[str, Any]] = []
    review_required_fields: list[str] = []
    warnings: list[str] = []
    for item in matched_documents[:4]:
        path_value = str(item.get("path", "")).strip()
        source_url = str(item.get("source_url", "")).strip() or None
        document_type = str(item.get("document_type", "")).strip().lower()
        document_label = str(item.get("document_label", "")).strip() or path_value or (source_url or "vendor_document")
        text = ""
        if path_value:
            path = Path(path_value)
            if path.exists():
                text = _preferred_pdf_text(path)
            elif source_url and document_type != "vendor_pdf_pointer":
                warnings.append(f"Indexed vendor document path is missing on disk: {path_value}")
        if document_type == "vendor_pdf_pointer":
            pointer_text = str(item.get("pointer_text", "")).strip()
            pdf_snippets.append({
                'corpus': 'vendor_documents',
                'source_ref': document_label,
                'text': pointer_text or f"Vendor document pointer for {item.get('manufacturer')} {item.get('model')}: {source_url or path_value}",
                'score': max(0.25, float(item.get('match_score', 0.25) or 0.25)),
                'metadata': {
                    'topic': 'vendor_pdf_pointer',
                    'target_field': ','.join(target_fields),
                    'source_type': 'vendor_pdf_pointer',
                    'source_url': source_url,
                    'source_kind': str(item.get('source_kind', 'vendor_document')).strip(),
                    'document_type': document_type,
                    'document_label': document_label,
                    'document_path': path_value,
                    'evidence_tier': str(item.get('evidence_tier', 'vendor_document_pointer')).strip(),
                    'match_reason': ','.join(item.get('match_reasons', [])) if isinstance(item.get('match_reasons'), list) else '',
                },
            })
            continue
        if not text:
            continue
        candidates, snippets, review_fields = _build_evidence_candidates(
            candidate=candidate,
            target_fields=target_fields,
            evidence_text=text,
            source_type="vendor_pdf_rag",
            source_ref=document_label,
            source_url=source_url,
            document_type=document_type,
            document_path=path_value,
            document_label=document_label,
            evidence_tier=str(item.get("evidence_tier", "vendor_document")).strip() or "vendor_document",
            source_kind=str(item.get("source_kind", "vendor_document")).strip() or "vendor_document",
            match_reason=", ".join(item.get("match_reasons", [])) if isinstance(item.get("match_reasons"), list) else None,
        )
        pdf_candidates.extend(candidates)
        pdf_snippets.extend(snippets)
        review_required_fields.extend(review_fields)
    return matched_documents, pdf_candidates, pdf_snippets, sorted(set(review_required_fields)), warnings

def _fetch_url_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "GridSenpAI-Agent4/1.0"})
    with urlopen(request, timeout=8) as response:  # nosec - URLs are pre-whitelisted from official source index
        payload = response.read(1_500_000)
        content_type = str(response.headers.get("Content-Type", "")).lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        try:
            import pdfplumber  # type: ignore
            with pdfplumber.open(io.BytesIO(payload)) as pdf:
                parts: list[str] = []
                for page in pdf.pages[:8]:
                    extracted = page.extract_text() or ""
                    cleaned = re.sub(r"\s+", " ", extracted).strip()
                    if cleaned:
                        parts.append(cleaned)
                return " ".join(parts).strip()
        except Exception:
            return ""
    text = payload.decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _search_official_sources(candidate: EquipmentIdentityCandidate, target_fields: list[str], official_source_candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    web_candidates: list[dict[str, Any]] = []
    web_snippets: list[dict[str, Any]] = []
    review_required_fields: list[str] = []
    warnings: list[str] = []
    for item in official_source_candidates[:3]:
        url = str(item.get("source_url", "")).strip()
        if not _is_official_source_url(url):
            continue
        try:
            text = _fetch_url_text(url)
        except Exception as exc:
            warnings.append(f"Official source lookup failed for {url}: {exc}")
            continue
        if not text:
            warnings.append(f"Official source lookup returned no usable text for {url}.")
            continue
        candidates, snippets, review_fields = _build_evidence_candidates(
            candidate=candidate,
            target_fields=target_fields,
            evidence_text=text,
            source_type="official_web_lookup",
            source_ref=url,
            source_url=url,
            document_type=str(item.get("document_type", "official_vendor_document")).strip() or "official_vendor_document",
            document_label=url,
            evidence_tier=str(item.get("evidence_tier", "official_vendor_document")).strip() or "official_vendor_document",
            source_kind=str(item.get("source_kind", "official_web")).strip() or "official_web",
            match_reason=str(item.get("match_reason", "exact_model_match")).strip() or "exact_model_match",
        )
        web_candidates.extend(candidates)
        web_snippets.extend(snippets)
        review_required_fields.extend(review_fields)
    return web_candidates, web_snippets, sorted(set(review_required_fields)), warnings


# ---------- summary ----------

def _build_library_summary(*, identities: list[EquipmentIdentityCandidate], matched_records: list[dict[str, Any]], candidate_fields: list[dict[str, Any]], unresolved_missing_fields: list[str], official_source_candidates: list[dict[str, Any]], pdf_repository_candidates: list[dict[str, Any]], pdf_lookup_plans: list[dict[str, Any]], web_lookup_plans: list[dict[str, Any]], review_required_fields: list[str], knowledge_index_status: dict[str, Any], target_missing_fields: list[str], out_of_scope_missing_fields: list[str]) -> dict[str, Any]:
    return {
        "library_first": True,
        "pdf_repository_second": True,
        "official_web_third": True,
        "identity_candidate_count": len(identities),
        "matched_record_count": len(matched_records),
        "candidate_field_count": len(candidate_fields),
        "target_missing_field_count": len(target_missing_fields),
        "out_of_scope_missing_field_count": len(out_of_scope_missing_fields),
        "unresolved_missing_field_count": len(unresolved_missing_fields),
        "review_required_field_count": len(review_required_fields),
        "official_source_candidate_count": len(official_source_candidates),
        "pdf_repository_candidate_count": len(pdf_repository_candidates),
        "pdf_lookup_plan_count": len(pdf_lookup_plans),
        "web_lookup_plan_count": len(web_lookup_plans),
        "catalog_record_count": int(knowledge_index_status.get("catalog_record_count", 0) or 0),
        "official_index_record_count": int(knowledge_index_status.get("official_record_count", 0) or 0),
        "pdf_library_record_count": int(knowledge_index_status.get("pdf_library_record_count", 0) or 0),
        "discovered_pdf_document_count": int(knowledge_index_status.get("discovered_pdf_document_count", 0) or 0),
    }


def _identity_resolution_summary(seeds: list[dict[str, Any]], identities: list[EquipmentIdentityCandidate], planner_guidance: dict[str, Any]) -> dict[str, Any]:
    return {
        "seed_count": len(seeds),
        "seed_sources": _dedupe_str_list([str(seed.get("source", "")).strip() for seed in seeds]),
        "observed_models": _dedupe_str_list([item for seed in seeds for item in seed.get("models", []) if isinstance(item, str)]),
        "observed_manufacturers": _dedupe_str_list([item for seed in seeds for item in seed.get("manufacturers", []) if isinstance(item, str)]),
        "observed_families": _dedupe_str_list([item for seed in seeds for item in seed.get("families", []) if isinstance(item, str)]),
        "resolved_candidate_count": len(identities),
        "resolved_families": list(planner_guidance.get("families", [])),
    }


# ---------- public entry ----------

def resolve_equipment_references(*, context: Any, normalization_result: dict[str, Any] | None = None, extraction_result: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = context
    requested_missing_fields = _coerce_missing_fields(normalization_result)
    knowledge_index_status = _audit_knowledge_indexes()
    spec_records = _load_spec_records()
    official_index = _load_official_source_index()
    pdf_entries = _load_pdf_repository_entries()

    seeds = collect_identity_seeds(extraction_result=extraction_result, normalization_result=normalization_result)
    identities, ranked_records = rank_identity_candidates(seeds=seeds, spec_records=spec_records)

    observed_families = [item.equipment_family for item in identities]
    family_record_fields: dict[str, list[str]] = {}
    for record in ranked_records[:4]:
        family = canonical_family(record.get("equipment_family", ""))
        family_record_fields.setdefault(family, [])
        for field in _record_field_inventory(record):
            if field not in family_record_fields[family]:
                family_record_fields[family].append(field)

    planner_guidance = target_fields_for_families(
        families=infer_relevant_families(missing_fields=requested_missing_fields, observed_families=observed_families),
        requested_missing_fields=requested_missing_fields,
        family_record_fields=family_record_fields,
    )
    target_missing_fields = list(planner_guidance.get("target_fields", requested_missing_fields))
    out_of_scope_missing_fields = list(planner_guidance.get("out_of_scope_requested_fields", []))

    matched_records: list[dict[str, Any]] = []
    candidate_fields: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []
    official_source_candidates: list[dict[str, Any]] = []
    pdf_repository_candidates: list[dict[str, Any]] = []
    pdf_lookup_plans: list[dict[str, Any]] = []
    web_lookup_plans: list[dict[str, Any]] = []
    review_required_fields: list[str] = []
    warnings: list[str] = []

    if not knowledge_index_status.get("catalog_index_exists", False):
        warnings.append("Equipment catalog index is missing; Agent 4 cannot perform the required library-first vendor spec pass.")
    if int(knowledge_index_status.get("catalog_missing_spec_paths", 0) or 0) > 0:
        warnings.append("Equipment catalog index contains spec_path entries that do not resolve on disk.")
    if not knowledge_index_status.get("official_source_index_exists", False):
        warnings.append("Official vendor source index is missing; Agent 4 cannot plan guarded official-source web lookups.")
    if int(knowledge_index_status.get("discovered_pdf_document_count", 0) or 0) == 0:
        warnings.append("Vendor PDF repository is not populated yet; the resolver will use any available vendor document pointers and official-source fallbacks.")
    if not identities:
        warnings.append("No strong equipment identity candidates could be resolved from the current applicant evidence bundle.")
    if out_of_scope_missing_fields:
        warnings.append("Some requested missing fields are outside vendor-spec resolution scope and were deferred to canonical-state, interview, or applicant-document resolution.")

    matched_record_paths: set[str] = set()
    for identity, record in zip(identities, ranked_records[: len(identities)]):
        matched_official = _build_official_source_candidates(identity, official_index)
        official_source_candidates.extend(matched_official)

        library_candidates = _build_candidate_fields(record, target_missing_fields)
        candidate_fields.extend(library_candidates)
        snippets.append(_build_library_snippet(record, library_candidates))

        record_path = str(record.get("__path", "")).strip()
        if record_path not in matched_record_paths:
            matched_record_paths.add(record_path)
            matched_records.append(
                {
                    "equipment_family": str(record.get("equipment_family", "")).strip(),
                    "manufacturer": str(record.get("manufacturer", "")).strip(),
                    "model": str(record.get("model", "")).strip(),
                    "record_path": record_path,
                    "library_readiness": str(record.get("library_readiness", record.get("record_status", ""))).strip(),
                    "identity_confidence": identity.confidence,
                }
            )

        unresolved_for_identity = [
            field for field in target_missing_fields if not any(_field_name_matches_target(str(item.get("canonical_field_key", item.get("spec_field", ""))), [field], identity.equipment_family) for item in library_candidates)
        ]

        matched_pdf_documents, pdf_candidates, pdf_snippets, pdf_review_fields, pdf_warnings = _search_pdf_repository(identity, unresolved_for_identity, pdf_entries)
        pdf_repository_candidates.extend(matched_pdf_documents)
        pdf_lookup_plans.extend(_build_pdf_lookup_plans(identity, matched_pdf_documents, unresolved_for_identity))
        candidate_fields.extend(pdf_candidates)
        snippets.extend(pdf_snippets)
        review_required_fields.extend(pdf_review_fields)
        warnings.extend(pdf_warnings)

        unresolved_for_identity = [
            field for field in unresolved_for_identity if not any(_field_name_matches_target(str(item.get("canonical_field_key", item.get("spec_field", ""))), [field], identity.equipment_family) for item in pdf_candidates)
        ]

        web_candidates, web_snippets, web_review_fields, web_warnings = _search_official_sources(identity, unresolved_for_identity, matched_official)
        candidate_fields.extend(web_candidates)
        snippets.extend(web_snippets)
        review_required_fields.extend(web_review_fields)
        warnings.extend(web_warnings)

        unresolved_for_identity = [
            field for field in unresolved_for_identity if not any(_field_name_matches_target(str(item.get("canonical_field_key", item.get("spec_field", ""))), [field], identity.equipment_family) for item in web_candidates)
        ]

        if unresolved_for_identity:
            web_lookup_plans.extend(_build_web_lookup_plans(identity, matched_official, unresolved_for_identity))
            warnings.append(f"Structured library and vendor follow-up sources for {identity.manufacturer} {identity.model} did not fully populate all target equipment specification fields.")

    # Deduplicate outputs
    def _dedupe_dicts(items: list[dict[str, Any]], key_builder):
        seen = set()
        result = []
        for item in items:
            key = key_builder(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    official_source_candidates = _dedupe_dicts(official_source_candidates, lambda item: (
        str(item.get("equipment_family", "")).lower(),
        str(item.get("manufacturer", "")).lower(),
        str(item.get("model", "")).lower(),
        str(item.get("source_url", "")),
    ))
    pdf_repository_candidates = _dedupe_dicts(pdf_repository_candidates, lambda item: (
        str(item.get("equipment_family", "")).lower(),
        str(item.get("manufacturer", "")).lower(),
        str(item.get("model", "")).lower(),
        str(item.get("path", "")),
        str(item.get("source_url", "")),
    ))
    pdf_lookup_plans = _dedupe_dicts(pdf_lookup_plans, lambda item: (
        str(item.get("equipment_family", "")).lower(),
        str(item.get("manufacturer", "")).lower(),
        str(item.get("model", "")).lower(),
        tuple(sorted(str(v).strip() for v in item.get("missing_fields", []) if str(v).strip())),
        str(item.get("document_path", "")),
    ))
    web_lookup_plans = _dedupe_dicts(web_lookup_plans, lambda item: (
        str(item.get("equipment_family", "")).lower(),
        str(item.get("manufacturer", "")).lower(),
        str(item.get("model", "")).lower(),
        tuple(sorted(str(v).strip() for v in item.get("missing_fields", []) if str(v).strip())),
    ))
    candidate_fields = _dedupe_dicts(candidate_fields, lambda item: (
        str(item.get("equipment_family", "")).lower(),
        str(item.get("manufacturer", "")).lower(),
        str(item.get("model", "")).lower(),
        str(item.get("canonical_field_key", item.get("spec_field", ""))).lower(),
        str(item.get("source_type", "")).lower(),
        str(item.get("source_ref", "")),
        str(item.get("value", "")),
    ))

    unresolved_missing_fields = [
        field for field in target_missing_fields if not any(_field_name_matches_target(str(item.get("canonical_field_key", item.get("spec_field", ""))), [field]) for item in candidate_fields)
    ]

    review_required_fields.extend(
        str(item.get("canonical_field_key", item.get("spec_field", ""))).strip()
        for item in candidate_fields
        if isinstance(item, dict) and bool(item.get("review_required"))
    )
    review_required_fields = sorted({field for field in review_required_fields if field})

    trigger_reasons = _dedupe_str_list([
        "missing_equipment_spec_fields" if target_missing_fields else "",
        "non_vendor_fields_deferred" if out_of_scope_missing_fields else "",
        "partial_identity_resolution" if any(not seed.get("manufacturers") or not seed.get("models") for seed in seeds) else "",
        "pdf_repository_available" if pdf_repository_candidates or pdf_lookup_plans else "",
        "official_source_index_available" if official_source_candidates else "",
        "official_web_lookup_required" if web_lookup_plans else "",
        "review_required_equipment_fields" if review_required_fields else "",
    ])

    result = EquipmentReferenceResolutionResult(
        status="EQUIPMENT_REFERENCE_RESOLVED" if matched_records or official_source_candidates or pdf_repository_candidates else "NO_EQUIPMENT_REFERENCE_MATCH",
        identity_candidates=[item.to_dict() for item in identities],
        identity_resolution_summary=_identity_resolution_summary(seeds, identities, planner_guidance),
        matched_records=matched_records,
        candidate_fields=candidate_fields,
        snippets=snippets,
        official_source_candidates=official_source_candidates,
        pdf_repository_candidates=pdf_repository_candidates,
        pdf_lookup_plans=pdf_lookup_plans,
        web_lookup_plans=web_lookup_plans,
        unresolved_missing_fields=unresolved_missing_fields,
        target_missing_fields=target_missing_fields,
        out_of_scope_missing_fields=out_of_scope_missing_fields,
        planner_guidance=planner_guidance,
        review_required_fields=review_required_fields,
        lookup_strategy="library_then_pdf_then_official_web",
        authenticity_guardrails=_build_authenticity_guardrails(official_source_candidates),
        trigger_reasons=trigger_reasons,
        web_lookup_required=bool(web_lookup_plans),
        evidence_gap=bool(identities) and bool(unresolved_missing_fields),
        knowledge_index_status=knowledge_index_status,
        library_summary=_build_library_summary(
            identities=identities,
            matched_records=matched_records,
            candidate_fields=candidate_fields,
            unresolved_missing_fields=unresolved_missing_fields,
            official_source_candidates=official_source_candidates,
            pdf_repository_candidates=pdf_repository_candidates,
            pdf_lookup_plans=pdf_lookup_plans,
            web_lookup_plans=web_lookup_plans,
            review_required_fields=review_required_fields,
            knowledge_index_status=knowledge_index_status,
            target_missing_fields=target_missing_fields,
            out_of_scope_missing_fields=out_of_scope_missing_fields,
        ),
        warnings=warnings,
        errors=[],
    )
    return result.to_dict()
