from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.config import CONFIG
from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent
from shared.runtime_stage_contract import GAP_RESOLUTION_RETRIEVAL_STAGE
from shared.planner_registry import build_followup_profile, preferred_corpora_for_field
from shared.document_field_pack_registry import build_document_field_pack

from services.equipment_reference_resolution_service.service import resolve_equipment_references
from services.retrieval_service import service as retrieval_service_module
from services.retrieval_service.models import RetrievalExtractionResult
from services.retrieval_service.utils import (
    coerce_retrieval_llm_value,
    get_artifact_text,
    infer_dynamic_model_available,
    infer_pscad_model_package,
    is_retrieval_artifact,
)


def _normalized_field_key(value: Any) -> str:
    return str(value or "").strip().lower()


OFFICIAL_HOST_KEYWORDS: tuple[str, ...] = (
    "pjm.com",
    "ferc.gov",
    "epri.com",
    "ercot.com",
    "iso-ne.com",
    "caiso.com",
    "misoenergy.org",
    "spp.org",
    "duke-energy.com",
    "dominionenergy.com",
    "schneider-electric.com",
    "se.com",
    "eaton.com",
    "gevernova.com",
    "abb.com",
    "siemens.com",
)


def _is_official_url(url: str) -> bool:
    cleaned = str(url or "").strip()
    if not cleaned:
        return False
    try:
        hostname = urlparse(cleaned).netloc.lower()
    except Exception:
        return False
    if not hostname:
        return False
    return any(keyword in hostname for keyword in OFFICIAL_HOST_KEYWORDS)


def _fetch_official_web_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "GridSenpAI-Retrieval/1.0"})
    with urlopen(request, timeout=8) as response:  # nosec - URLs are restricted to official/trusted domains
        payload = response.read(1_500_000)
        content_type = str(response.headers.get("Content-Type", "")).lower()
    if "pdf" in content_type or cleaned_url_endswith_pdf(url):
        try:
            import pdfplumber  # type: ignore
            with pdfplumber.open(io.BytesIO(payload)) as pdf:
                parts: list[str] = []
                for page in pdf.pages[:6]:
                    extracted = page.extract_text() or ""
                    cleaned = re.sub(r"\s+", " ", extracted).strip()
                    if cleaned:
                        parts.append(cleaned)
                return " ".join(parts).strip()
        except Exception:
            return ""
    text = payload.decode("utf-8", errors="ignore")
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def cleaned_url_endswith_pdf(url: str) -> bool:
    return str(url or "").split("?", 1)[0].lower().endswith(".pdf")


def _normalized_url_key(url: Any) -> str:
    cleaned = str(url or "").strip()
    if not cleaned:
        return ""
    return cleaned.split("#", 1)[0].rstrip("/").lower()


def _candidate_official_web_plan(
    *,
    snippets: list[dict[str, Any]],
    equipment_result: dict[str, Any] | None,
    field_support_summary: dict[str, dict[str, Any]],
    requested_field_paths: list[str],
    official_web_lookup_required: bool,
) -> list[dict[str, Any]]:
    canonical_requested_field_paths = _canonicalize_field_collection(requested_field_paths, equipment_result)
    requested = {
        _normalized_field_key(item)
        for item in canonical_requested_field_paths
        if str(item or "").strip()
    }
    plans_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    def _support_for_field(field_path: str) -> dict[str, Any]:
        support = field_support_summary.get(field_path, {}) if isinstance(field_support_summary.get(field_path), dict) else {}
        if support:
            return support
        for existing_field_path, existing_support in field_support_summary.items():
            canonical_existing = _canonicalize_backlog_field_path(existing_field_path, equipment_result)
            if _normalized_field_key(canonical_existing) == _normalized_field_key(field_path) and isinstance(existing_support, dict):
                return existing_support
        return {}

    def _register_plan(plan: dict[str, Any], raw_field_path: str) -> None:
        canonical_field_path = _canonicalize_backlog_field_path(raw_field_path, equipment_result)
        normalized_canonical_field_path = _normalized_field_key(canonical_field_path)
        normalized_url = _normalized_url_key(plan.get("url", ""))
        if not canonical_field_path or not normalized_url or normalized_canonical_field_path not in requested:
            return
        key = (normalized_canonical_field_path, normalized_url)
        existing = plans_by_key.get(key)
        materialized = dict(plan)
        materialized["field_path"] = canonical_field_path
        aliases = [canonical_field_path]
        raw_cleaned = str(raw_field_path or "").strip()
        if raw_cleaned and _normalized_field_key(raw_cleaned) != normalized_canonical_field_path:
            aliases.append(raw_cleaned)
        if existing is not None:
            aliases.extend(existing.get("target_field_aliases", []))
        deduped_aliases: list[str] = []
        seen_aliases: set[str] = set()
        for item in aliases:
            cleaned = str(item or "").strip()
            normalized_item = _normalized_field_key(cleaned)
            if cleaned and normalized_item not in seen_aliases:
                deduped_aliases.append(cleaned)
                seen_aliases.add(normalized_item)
        materialized["target_field_aliases"] = deduped_aliases
        if existing is None or float(materialized.get("priority_score", 0.0) or 0.0) > float(existing.get("priority_score", 0.0) or 0.0):
            plans_by_key[key] = materialized
        else:
            existing_aliases = existing.get("target_field_aliases", []) if isinstance(existing.get("target_field_aliases"), list) else []
            for item in materialized["target_field_aliases"]:
                normalized_item = _normalized_field_key(item)
                if normalized_item and normalized_item not in {_normalized_field_key(alias) for alias in existing_aliases}:
                    existing_aliases.append(item)
            existing["target_field_aliases"] = existing_aliases
            plans_by_key[key] = existing

    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        metadata = snippet.get("metadata", {}) if isinstance(snippet.get("metadata"), dict) else {}
        raw_field_path = str(metadata.get("target_field", "")).strip()
        url = str(metadata.get("source_url", "")).strip()
        source_hierarchy = str(metadata.get("source_hierarchy", "")).strip().lower()
        evidence_tier = str(metadata.get("evidence_tier", "")).strip().lower()
        canonical_field_path = _canonicalize_backlog_field_path(raw_field_path, equipment_result)
        if not canonical_field_path or _normalized_field_key(canonical_field_path) not in requested:
            continue
        if not _is_official_url(url):
            continue
        support = _support_for_field(canonical_field_path)
        support_strength = str(support.get("support_strength", "LOW")).strip().upper()
        should_fetch = official_web_lookup_required or _normalized_field_key(canonical_field_path) in requested
        if not should_fetch and support_strength != "HIGH":
            should_fetch = True
        if not should_fetch:
            continue
        if source_hierarchy not in {"official_interconnection_source", "official_website"} and evidence_tier not in {"official_interconnection_source", "official_vendor_document"}:
            continue
        _register_plan({
            "field_path": canonical_field_path,
            "url": url,
            "source_ref": str(snippet.get("source_ref", "")).strip() or url,
            "source_hierarchy": source_hierarchy or ("official_interconnection_source" if "pjm" in url.lower() or "ferc" in url.lower() else "official_website"),
            "evidence_tier": evidence_tier or ("official_interconnection_source" if "pjm" in url.lower() or "ferc" in url.lower() else "official_vendor_document"),
            "source_kind": str(metadata.get("source_kind", "")).strip() or "official_web",
            "document_type": str(metadata.get("document_type", "")).strip() or "official_web_reference",
            "document_label": str(metadata.get("document_label", "")).strip() or str(snippet.get("source_ref", "")).strip() or url,
            "priority_score": float(snippet.get("score", 0.0) or 0.0),
        }, raw_field_path)

    if isinstance(equipment_result, dict):
        for item in equipment_result.get("web_lookup_plans", []):
            if not isinstance(item, dict):
                continue
            missing_fields = [str(field).strip() for field in item.get("missing_fields", []) if str(field).strip()]
            allowed_urls = [str(url).strip() for url in item.get("allowed_urls", []) if _is_official_url(str(url).strip())]
            if not missing_fields or not allowed_urls:
                continue
            for raw_field_path in missing_fields:
                canonical_field_path = _canonicalize_backlog_field_path(raw_field_path, equipment_result)
                if _normalized_field_key(canonical_field_path) not in requested:
                    continue
                support = _support_for_field(canonical_field_path)
                support_strength = str(support.get("support_strength", "LOW")).strip().upper()
                if support_strength == "HIGH" and not official_web_lookup_required:
                    continue
                for url in allowed_urls[:2]:
                    _register_plan({
                        "field_path": canonical_field_path,
                        "url": url,
                        "source_ref": url,
                        "source_hierarchy": "official_website",
                        "evidence_tier": "official_vendor_document",
                        "source_kind": "official_web",
                        "document_type": "official_web_lookup",
                        "document_label": f"Official web lookup for {canonical_field_path}",
                        "priority_score": 0.7,
                    }, raw_field_path)

    plans = list(plans_by_key.values())
    plans.sort(key=lambda item: (-float(item.get("priority_score", 0.0) or 0.0), str(item.get("field_path", "")), str(item.get("url", ""))))
    return plans[:8]


def _execute_official_web_retrieval(
    *,
    context: Any,
    plans: list[dict[str, Any]],
    starting_snippet_index: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    snippets: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    snippet_index = starting_snippet_index

    for plan in plans:
        if not isinstance(plan, dict):
            continue
        field_path = str(plan.get("field_path", "")).strip()
        url = str(plan.get("url", "")).strip()
        if not field_path or not _is_official_url(url):
            continue
        try:
            text = _fetch_official_web_text(url)
        except Exception as exc:
            warnings.append(f"Executed official web retrieval failed for {url}: {exc}")
            records.append({
                "field_path": field_path,
                "url": url,
                "status": "failed",
                "error": str(exc),
            })
            continue
        cleaned_text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not cleaned_text:
            warnings.append(f"Executed official web retrieval returned no usable text for {url}.")
            records.append({
                "field_path": field_path,
                "url": url,
                "status": "empty",
            })
            continue
        snippet = {
            "snippet_id": f"{context.run_id}_snip_{snippet_index:03d}",
            "corpus": "official_web",
            "source_ref": str(plan.get("source_ref", "")).strip() or url,
            "text": cleaned_text[:4000],
            "score": round(max(0.66, min(0.92, float(plan.get("priority_score", 0.72) or 0.72))), 4),
            "metadata": {
                "topic": field_path,
                "matched_keywords": [],
                "target_field": field_path,
                "query_intent": "official_web_retrieval",
                "query_source": "official_web_execution",
                "source_artifact_ids": [],
                "source_document_types": [str(plan.get("document_type", "official_web_lookup")).strip() or "official_web_lookup"],
                "source_kind": str(plan.get("source_kind", "official_web")).strip() or "official_web",
                "document_type": str(plan.get("document_type", "official_web_lookup")).strip() or "official_web_lookup",
                "document_label": str(plan.get("document_label", "")).strip() or url,
                "document_path": "",
                "source_domain": urlparse(url).netloc.lower(),
                "source_url": url,
                "evidence_tier": str(plan.get("evidence_tier", "official_vendor_document")).strip() or "official_vendor_document",
                "trust_level": "high",
                "specificity": "direct_field_match",
                "source_hierarchy": str(plan.get("source_hierarchy", "official_website")).strip() or "official_website",
                "source_priority": "official_web_executed",
                "matched_target_fields": [field_path],
                "retrieval_priority": "high",
            },
        }
        snippets.append(snippet)
        records.append({
            "field_path": field_path,
            "url": url,
            "status": "executed",
            "snippet_id": snippet["snippet_id"],
            "source_ref": snippet["source_ref"],
            "source_domain": urlparse(url).netloc.lower(),
            "retrieved_chars": len(cleaned_text),
        })
        snippet_index += 1

    summary = {
        "attempted_count": len(plans),
        "executed_count": sum(1 for item in records if str(item.get("status", "")) == "executed"),
        "records": records,
    }
    return snippets, summary, warnings


def _candidate_lookup_from_equipment_result(equipment_result: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(equipment_result, dict):
        return lookup
    for item in equipment_result.get("candidate_fields", []):
        if not isinstance(item, dict):
            continue
        canonical_field_key = str(item.get("canonical_field_key", item.get("spec_field", ""))).strip()
        if not canonical_field_key:
            continue
        lookup.setdefault(_normalized_field_key(canonical_field_key), []).append({
            "value": item.get("value"),
            "manufacturer": str(item.get("manufacturer", "")).strip(),
            "model": str(item.get("model", "")).strip(),
            "confidence": item.get("confidence"),
            "source_type": str(item.get("source_type", "")).strip(),
            "source_ref": str(item.get("source_ref", "")).strip(),
            "source_url": str(item.get("source_url", "")).strip(),
        })
    return lookup


def _matched_identity_labels(equipment_result: dict[str, Any] | None) -> list[str]:
    labels: list[str] = []
    if not isinstance(equipment_result, dict):
        return labels
    for item in equipment_result.get("identity_candidates", []):
        if not isinstance(item, dict):
            continue
        manufacturer = str(item.get("manufacturer", "")).strip()
        model = str(item.get("model", "")).strip()
        label = " ".join(part for part in (manufacturer, model) if part).strip()
        if label and label not in labels:
            labels.append(label)
    return labels




def _equipment_family_order(equipment_result: dict[str, Any] | None) -> list[str]:
    ordered: list[str] = []
    if not isinstance(equipment_result, dict):
        return ordered

    planner_guidance = equipment_result.get("planner_guidance", {})
    if isinstance(planner_guidance, dict):
        for item in planner_guidance.get("families", []):
            cleaned = str(item).strip()
            if cleaned and cleaned not in ordered:
                ordered.append(cleaned)

    for item in equipment_result.get("matched_records", []):
        if not isinstance(item, dict):
            continue
        cleaned = str(item.get("equipment_family", "")).strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)

    for item in equipment_result.get("identity_candidates", []):
        if not isinstance(item, dict):
            continue
        cleaned = str(item.get("equipment_family", "")).strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)

    return ordered


def _canonical_backlog_field_lookup(equipment_result: dict[str, Any] | None) -> dict[str, str]:
    lookup: dict[str, str] = {}
    if not isinstance(equipment_result, dict):
        return lookup

    family_order = _equipment_family_order(equipment_result)
    planner_guidance = equipment_result.get("planner_guidance", {})
    family_targets = planner_guidance.get("family_targets", {}) if isinstance(planner_guidance, dict) else {}

    def register(field_path: Any, family: str | None = None) -> None:
        cleaned = str(field_path or "").strip()
        if not cleaned:
            return
        normalized = _normalized_field_key(cleaned)
        if normalized and normalized not in lookup:
            lookup[normalized] = cleaned
        suffix = cleaned.split(".")[-1].strip().lower()
        if not suffix:
            return
        if suffix not in lookup:
            lookup[suffix] = cleaned
        elif family and family_order and family == family_order[0]:
            lookup[suffix] = cleaned

    if isinstance(family_targets, dict):
        for family in family_order:
            raw_fields = family_targets.get(family, [])
            if not isinstance(raw_fields, list):
                continue
            for field_path in raw_fields:
                register(field_path, family)

    for collection_name in ("target_missing_fields", "unresolved_missing_fields", "out_of_scope_missing_fields", "review_required_fields"):
        raw_fields = equipment_result.get(collection_name, [])
        if not isinstance(raw_fields, list):
            continue
        for field_path in raw_fields:
            register(field_path)

    for item in equipment_result.get("candidate_fields", []):
        if not isinstance(item, dict):
            continue
        family = str(item.get("equipment_family", "")).strip() or None
        for key_name in ("canonical_field_key", "matched_field_key"):
            register(item.get(key_name), family)

    return lookup


def _canonicalize_backlog_field_path(field_path: Any, equipment_result: dict[str, Any] | None) -> str:
    cleaned = str(field_path or "").strip()
    if not cleaned:
        return ""
    if "." in cleaned:
        return cleaned

    lookup = _canonical_backlog_field_lookup(equipment_result)
    normalized = _normalized_field_key(cleaned)
    mapped = lookup.get(normalized, "")
    if mapped:
        return mapped

    family_order = _equipment_family_order(equipment_result)
    if family_order:
        primary_family = str(family_order[0]).strip()
        if primary_family:
            return f"facility.{primary_family}.{cleaned}"
    return cleaned


def _canonicalize_field_collection(field_paths: list[str], equipment_result: dict[str, Any] | None) -> list[str]:
    canonicalized: list[str] = []
    seen: set[str] = set()
    for item in field_paths:
        cleaned = _canonicalize_backlog_field_path(item, equipment_result)
        normalized = _normalized_field_key(cleaned)
        if cleaned and normalized not in seen:
            canonicalized.append(cleaned)
            seen.add(normalized)
    return canonicalized


def _dedupe_field_paths(field_paths: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in field_paths:
        cleaned = str(item or '').strip()
        normalized = _normalized_field_key(cleaned)
        if cleaned and normalized not in seen:
            ordered.append(cleaned)
            seen.add(normalized)
    return ordered


def _subtract_field_paths(primary: list[str], excluded: list[str]) -> list[str]:
    excluded_keys = {_normalized_field_key(item) for item in excluded if str(item or '').strip()}
    return [item for item in primary if _normalized_field_key(item) not in excluded_keys]


def _initial_retrieval_scope_field_paths(
    *,
    initial_requested_field_paths: list[str],
    extraction_result: dict[str, Any] | None,
    equipment_result: dict[str, Any] | None,
) -> list[str]:
    """Return the explicit field scope that started retrieval.

    Equipment/reference resolution may surface related sibling fields. Those are
    useful for backlog and follow-up planning, but they must not pollute
    provenance snippets for a narrower missing-field request. The explicit
    retrieval scope is therefore the current normalization gaps plus any
    ontology likely_fields extracted from the applicant artifact itself.
    """
    scoped: list[str] = []
    scoped.extend(str(item).strip() for item in initial_requested_field_paths if str(item or '').strip())
    try:
        ontology_items = retrieval_service_module._ontology_items(extraction_result)
    except Exception:
        ontology_items = []
    for item in ontology_items:
        likely_fields = item.get('likely_fields', []) if isinstance(item, dict) else []
        if not isinstance(likely_fields, list):
            continue
        scoped.extend(str(field).strip() for field in likely_fields if str(field or '').strip())
    return _canonicalize_field_collection(scoped, equipment_result)


def _filter_snippets_to_explicit_retrieval_scope(
    snippets: list[dict[str, Any]],
    *,
    allowed_field_paths: list[str],
) -> list[dict[str, Any]]:
    """Drop provenance snippets that target fields outside the explicit request.

    This prevents a topology-only retrieval request from returning sibling UPS
    modeling snippets as if they were evidence for topology. Untargeted snippets
    are retained because some legacy retrieval records do not carry target_field
    metadata.
    """
    allowed_keys = {_normalized_field_key(item) for item in allowed_field_paths if str(item or '').strip()}
    if not allowed_keys:
        return snippets
    filtered: list[dict[str, Any]] = []
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        metadata = snippet.get('metadata', {}) if isinstance(snippet.get('metadata'), dict) else {}
        target_field = str(metadata.get('target_field', '')).strip()
        if not target_field or _normalized_field_key(target_field) in allowed_keys:
            filtered.append(snippet)
    return filtered


def _candidate_summary_for_field(field_path: str, candidate_lookup: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return list(candidate_lookup.get(_normalized_field_key(field_path), []))[:3]


def _build_resolution_backlog(
    *,
    requested_field_paths: list[str],
    review_required_field_paths: list[str],
    out_of_scope_field_paths: list[str],
    equipment_result: dict[str, Any] | None,
    gap_fill_strategy: str,
    official_web_lookup_required: bool,
    default_reason: str,
) -> list[dict[str, Any]]:
    backlog: list[dict[str, Any]] = []
    candidate_lookup = _candidate_lookup_from_equipment_result(equipment_result)
    matched_identities = _matched_identity_labels(equipment_result)

    def _registry_attempted_steps(field_path: str, fallback_steps: list[str]) -> list[str]:
        preferred = preferred_corpora_for_field(field_path)
        attempted: list[str] = []
        for item in preferred:
            cleaned = str(item).strip()
            if cleaned and cleaned not in attempted:
                attempted.append(cleaned)
        for item in fallback_steps:
            cleaned = str(item).strip()
            if cleaned and cleaned not in attempted:
                attempted.append(cleaned)
        if official_web_lookup_required and 'official_web' not in attempted:
            attempted.append('official_web')
        return attempted or list(fallback_steps)

    def _backlog_priority(field_path: str, category: str) -> str:
        profile = build_followup_profile(field_path)
        if bool(profile.get('planner_critical', False)):
            return 'HIGH'
        requiredness = str(profile.get('requiredness', 'optional')).strip().lower()
        if requiredness in {'required', 'conditional', 'scenario_required'}:
            return 'MODERATE' if category == 'retrieval_deferred' else 'HIGH'
        return 'LOW' if category == 'retrieval_deferred' else 'MODERATE'

    def _append(field_path: str, category: str, reason: str, fallback_steps: list[str], resolution_scope: str) -> None:
        cleaned = str(field_path).strip()
        if not cleaned:
            return
        profile = build_followup_profile(cleaned)
        attempted_steps = _registry_attempted_steps(cleaned, fallback_steps)
        backlog.append({
            "field_id": profile.get("field_id", ""),
            "field_path": str(profile.get("field_path", cleaned)).strip() or cleaned,
            "label": profile.get("label", cleaned),
            "category": category,
            "priority": _backlog_priority(cleaned, category),
            "planner_critical": bool(profile.get("planner_critical", False)),
            "requiredness": profile.get("requiredness", "optional"),
            "preferred_sources": list(profile.get("preferred_sources", [])) if isinstance(profile.get("preferred_sources"), list) else [],
            "search_keywords": list(profile.get("search_keywords", [])) if isinstance(profile.get("search_keywords"), list) else [],
            "reason": reason,
            "attempted_resolution_steps": attempted_steps,
            "gap_fill_strategy": gap_fill_strategy,
            "matched_equipment_identities": matched_identities[:3],
            "candidate_values": _candidate_summary_for_field(cleaned, candidate_lookup),
            "resolution_scope": resolution_scope,
        })

    attempted_equipment = ["equipment_catalog", "vendor_documents"] + (["official_web"] if official_web_lookup_required else [])
    for field_path in requested_field_paths:
        _append(
            field_path,
            "retrieval_gap",
            default_reason or "Grounded retrieval could not fully resolve this field from structured library, vendor documents, or official vendor web sources.",
            attempted_equipment,
            "vendor_resolvable_or_equipment_adjacent",
        )
    for field_path in review_required_field_paths:
        _append(
            field_path,
            "retrieval_confirmation",
            "Grounded retrieval found a candidate value that still requires applicant confirmation before acceptance.",
            attempted_equipment,
            "confirmation_required",
        )
    for field_path in out_of_scope_field_paths:
        _append(
            field_path,
            "retrieval_deferred",
            "This field is outside vendor-spec resolution scope and should be confirmed from applicant documents, project inputs, or direct applicant follow-up.",
            ["applicant_documents", "canonical_inputs", "interview"],
            "non_vendor_project_specific",
        )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in backlog:
        key = (str(item.get("field_path", "")).strip(), str(item.get("category", "")).strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _build_resolution_backlog_summary(backlog: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {"total": len(backlog), "by_category": {}, "high_priority": [], "confirmation_required": []}
    by_category = summary["by_category"]
    for item in backlog:
        category = str(item.get("category", "unknown")).strip() or "unknown"
        by_category[category] = int(by_category.get(category, 0)) + 1
        if str(item.get("priority", "")).upper() == "HIGH":
            summary["high_priority"].append(str(item.get("field_path", "")).strip())
        if category == "retrieval_confirmation":
            summary["confirmation_required"].append(str(item.get("field_path", "")).strip())
    return summary





def _field_support_bucket(field_path: str) -> dict[str, Any]:
    return {
        "field_path": field_path,
        "candidate_count": 0,
        "strong_candidate_count": 0,
        "official_source_count": 0,
        "exact_model_support_count": 0,
        "family_support_count": 0,
        "weak_support_count": 0,
        "top_confidence": 0.0,
        "top_score": 0.0,
        "best_source_priority": "",
        "best_source_hierarchy": "",
        "best_specificity": "",
        "_best_priority_rank": -1,
        "_best_hierarchy_rank": -1,
        "_best_specificity_rank": -1,
        "support_strength": "LOW",
        "match_reasons": [],
        "source_refs": [],
    }


def _hierarchy_rank(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    ranks = {
        "applicant_document_direct": 100,
        "applicant_document_indirect": 90,
        "applicant_confirmed_answer": 85,
        "manufacturer_model_specific_spec": 80,
        "official_interconnection_source": 75,
        "official_website": 70,
        "manufacturer_family_spec": 60,
        "vendor_pdf": 40,
        "secondary_web_material": 20,
    }
    return ranks.get(normalized, 0)


def _specificity_rank(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    ranks = {
        "exact_model_match": 100,
        "direct_field_match": 90,
        "family_match": 70,
        "category_match": 50,
        "context_inferred": 20,
    }
    return ranks.get(normalized, 0)


def _source_priority_rank(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return 0
    if "direct_document" in normalized:
        return 100
    if "official_interconnection" in normalized:
        return 90
    if "model_specific" in normalized or "exact_model" in normalized:
        return 85
    if normalized.startswith("equipment_catalog"):
        return 65
    if normalized.startswith("vendor"):
        return 40
    return 10


def _maybe_promote_best_marker(bucket: dict[str, Any], key: str, value: Any, rank: int, rank_key: str) -> None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return
    if rank > int(bucket.get(rank_key, -1) or -1):
        bucket[key] = cleaned
        bucket[rank_key] = rank


def _strength_from_summary(bucket: dict[str, Any]) -> str:
    if int(bucket.get("exact_model_support_count", 0) or 0) > 0:
        return "HIGH"
    if int(bucket.get("official_source_count", 0) or 0) > 0 and int(bucket.get("strong_candidate_count", 0) or 0) > 0:
        return "HIGH"
    if float(bucket.get("top_confidence", 0.0) or 0.0) >= 0.85 or float(bucket.get("top_score", 0.0) or 0.0) >= 0.90:
        return "HIGH"
    if int(bucket.get("strong_candidate_count", 0) or 0) > 0 or int(bucket.get("family_support_count", 0) or 0) > 0:
        return "MODERATE"
    return "LOW"


def _append_unique(values: list[str], item: Any, limit: int = 6) -> None:
    cleaned = str(item or "").strip()
    if cleaned and cleaned not in values and len(values) < limit:
        values.append(cleaned)




def _normalized_field_collection(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for item in values:
        cleaned = str(item or "").strip()
        normalized = _normalized_field_key(cleaned)
        if cleaned and normalized not in seen:
            ordered.append(cleaned)
            seen.add(normalized)
    return ordered


def _extend_unique(target: list[str], values: Any, *, limit: int = 8) -> None:
    if not isinstance(values, list):
        return
    for item in values:
        cleaned = str(item or "").strip()
        if cleaned and cleaned not in target:
            target.append(cleaned)
        if len(target) >= limit:
            break


def _build_evidence_route_records(
    *,
    queries: list[dict[str, Any]],
    snippets: list[dict[str, Any]],
    field_support_summary: dict[str, dict[str, Any]],
    equipment_result: dict[str, Any] | None = None,
    agent_result: dict[str, Any] | None = None,
    evidence_agent_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    records_by_field: dict[str, dict[str, Any]] = {}

    def bucket(field_path: str) -> dict[str, Any]:
        cleaned = str(field_path or "").strip()
        if not cleaned:
            return {}
        existing = records_by_field.get(cleaned)
        if existing is None:
            support = field_support_summary.get(cleaned, {}) if isinstance(field_support_summary.get(cleaned), dict) else {}
            existing = {
                "field_path": cleaned,
                "query_sources": [],
                "query_intents": [],
                "preferred_corpora": [],
                "agent_contributors": [],
                "knowledge_family_route": [],
                "snippet_count": 0,
                "matched_source_refs": [],
                "route_status": "planned",
                "support_strength": str(support.get("support_strength", "")).strip() or "LOW",
                "best_source_hierarchy": str(support.get("best_source_hierarchy", "")).strip(),
                "best_specificity": str(support.get("best_specificity", "")).strip(),
                "official_source_count": int(support.get("official_source_count", 0) or 0),
                "exact_model_support_count": int(support.get("exact_model_support_count", 0) or 0),
                "family_support_count": int(support.get("family_support_count", 0) or 0),
                "weak_support_only": bool(support.get("weak_support_only", False)),
                "query_count": 0,
            }
            records_by_field[cleaned] = existing
        return existing

    for field_path, support in field_support_summary.items():
        if isinstance(support, dict):
            bucket(field_path)

    for query in queries:
        if not isinstance(query, dict):
            continue
        field_path = str(query.get("target_field", "")).strip()
        record = bucket(field_path)
        if not record:
            continue
        record["query_count"] = int(record.get("query_count", 0) or 0) + 1
        _extend_unique(record["query_sources"], [query.get("query_source")])
        _extend_unique(record["query_intents"], [query.get("intent")])
        _extend_unique(record["preferred_corpora"], query.get("preferred_corpora"))
        if record["query_count"] > 0 and str(record.get("route_status", "")).strip() == "planned":
            record["route_status"] = "queried"

    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        metadata = snippet.get("metadata", {}) if isinstance(snippet.get("metadata"), dict) else {}
        field_path = str(metadata.get("target_field", "")).strip()
        record = bucket(field_path)
        if not record:
            continue
        record["snippet_count"] = int(record.get("snippet_count", 0) or 0) + 1
        _extend_unique(record["query_sources"], [metadata.get("query_source")])
        _extend_unique(record["query_intents"], [metadata.get("query_intent")])
        _extend_unique(record["matched_source_refs"], [snippet.get("source_ref")], limit=12)
        if str(metadata.get("source_hierarchy", "")).strip() and not str(record.get("best_source_hierarchy", "")).strip():
            record["best_source_hierarchy"] = str(metadata.get("source_hierarchy", "")).strip()
        if str(metadata.get("specificity", "")).strip() and not str(record.get("best_specificity", "")).strip():
            record["best_specificity"] = str(metadata.get("specificity", "")).strip()
        record["route_status"] = "supported"

    if isinstance(equipment_result, dict):
        _extend_unique(
            next(iter(records_by_field.values()), {}).get("knowledge_family_route", []),
            []
        )
        planner_guidance = equipment_result.get("planner_guidance", {}) if isinstance(equipment_result.get("planner_guidance"), dict) else {}
        family_targets = planner_guidance.get("family_targets", {}) if isinstance(planner_guidance, dict) else {}
        routed_families = _normalized_field_collection(equipment_result.get("target_missing_fields", []))
        for record in records_by_field.values():
            if isinstance(family_targets, dict):
                for family, field_paths in family_targets.items():
                    normalized_targets = {_normalized_field_key(item) for item in field_paths if str(item or "").strip()} if isinstance(field_paths, list) else set()
                    if _normalized_field_key(str(record.get("field_path", "")).strip()) in normalized_targets:
                        _extend_unique(record["knowledge_family_route"], [str(family).strip()])
            if routed_families and str(record.get("field_path", "")).strip() in routed_families:
                _extend_unique(record["agent_contributors"], ["equipment_reference_resolution"])

    def _merge_agent_route(agent_payload: dict[str, Any] | None, agent_id: str) -> None:
        if not isinstance(agent_payload, dict):
            return
        structured = agent_payload.get("structured_output", {}) if isinstance(agent_payload.get("structured_output"), dict) else {}
        if not isinstance(structured, dict):
            return
        route_families = structured.get("knowledge_family_route", [])
        topics = structured.get("suggested_query_topics", [])
        query_plan = structured.get("query_plan", {}) if isinstance(structured.get("query_plan"), dict) else {}
        target_fields = _normalized_field_collection(query_plan.get("target_fields", []))
        if not target_fields:
            target_fields = []
            for topic in topics if isinstance(topics, list) else []:
                cleaned = str(topic or "").strip()
                if cleaned in field_support_summary or cleaned in records_by_field:
                    target_fields.append(cleaned)
        for field_path in target_fields:
            record = bucket(field_path)
            if not record:
                continue
            _extend_unique(record["agent_contributors"], [agent_id])
            _extend_unique(record["knowledge_family_route"], route_families)
            if str(record.get("route_status", "")).strip() == "planned":
                record["route_status"] = "agent_routed"

    _merge_agent_route(agent_result, "retrieval_planning_agent")
    _merge_agent_route(evidence_agent_result, "evidence_resolution_agent")

    for record in records_by_field.values():
        support_strength = str(record.get("support_strength", "")).strip().upper()
        if int(record.get("snippet_count", 0) or 0) > 0 and support_strength in {"MODERATE", "HIGH"}:
            record["route_status"] = "supported"
        elif int(record.get("snippet_count", 0) or 0) > 0:
            record["route_status"] = "thin_support"
        elif int(record.get("query_count", 0) or 0) > 0:
            record["route_status"] = "queried"
        record["why_route_was_selected"] = (
            f"Route favored {record.get('best_source_hierarchy') or 'available'} evidence with {record.get('best_specificity') or 'current'} specificity support"
            if str(record.get("best_source_hierarchy", "")).strip() or str(record.get("best_specificity", "")).strip()
            else "Route selected from active missing-field retrieval plan"
        )
    return sorted(records_by_field.values(), key=lambda item: str(item.get("field_path", "")))
def _build_field_support_summary(
    *,
    snippets: list[dict[str, Any]],
    equipment_result: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}

    def bucket_for(field_path: str) -> dict[str, Any]:
        if field_path not in summary:
            summary[field_path] = _field_support_bucket(field_path)
        return summary[field_path]

    if isinstance(equipment_result, dict):
        for item in equipment_result.get("candidate_fields", []):
            if not isinstance(item, dict):
                continue
            field_path = str(item.get("canonical_field_key") or item.get("matched_field_key") or item.get("spec_field") or item.get("field_path") or "").strip()
            if not field_path:
                continue
            bucket = bucket_for(field_path)
            bucket["candidate_count"] = int(bucket.get("candidate_count", 0) or 0) + 1
            confidence = float(item.get("confidence", 0.0) or 0.0)
            bucket["top_confidence"] = max(float(bucket.get("top_confidence", 0.0) or 0.0), confidence)
            source_priority = str(item.get("source_priority", "")).strip()
            source_type = str(item.get("source_type", "")).strip().lower()
            evidence_tier = str(item.get("evidence_tier", "")).strip().lower()
            match_reason = str(item.get("match_reason", "")).strip()
            if source_priority:
                _maybe_promote_best_marker(
                    bucket,
                    "best_source_priority",
                    source_priority,
                    _source_priority_rank(source_priority),
                    "_best_priority_rank",
                )
            if match_reason and not bucket.get("best_specificity"):
                lowered = match_reason.lower()
                if "exact_model" in lowered or "exact model" in lowered or "model_specific" in lowered:
                    _maybe_promote_best_marker(bucket, "best_specificity", "exact_model_match", _specificity_rank("exact_model_match"), "_best_specificity_rank")
                elif "family" in lowered:
                    _maybe_promote_best_marker(bucket, "best_specificity", "family_match", _specificity_rank("family_match"), "_best_specificity_rank")
            if any(token in source_priority.lower() for token in ("model_specific", "official_interconnection", "direct_document")) or evidence_tier in {"official_vendor_document", "structured_catalog", "official_interconnection_source"}:
                bucket["strong_candidate_count"] = int(bucket.get("strong_candidate_count", 0) or 0) + 1
            if any(token in source_priority.lower() for token in ("model_specific", "exact_model")) or "exact model" in match_reason.lower():
                bucket["exact_model_support_count"] = int(bucket.get("exact_model_support_count", 0) or 0) + 1
                _maybe_promote_best_marker(bucket, "best_specificity", "exact_model_match", _specificity_rank("exact_model_match"), "_best_specificity_rank")
            elif "family" in match_reason.lower():
                bucket["family_support_count"] = int(bucket.get("family_support_count", 0) or 0) + 1
                _maybe_promote_best_marker(bucket, "best_specificity", "family_match", _specificity_rank("family_match"), "_best_specificity_rank")
            if source_type in {"official_source_index", "official_web_candidate"} or evidence_tier == "official_interconnection_source" or "official" in source_type:
                bucket["official_source_count"] = int(bucket.get("official_source_count", 0) or 0) + 1
                _maybe_promote_best_marker(bucket, "best_source_hierarchy", "official_interconnection_source", _hierarchy_rank("official_interconnection_source"), "_best_hierarchy_rank")
            elif source_priority.lower().startswith("equipment_catalog"):
                _maybe_promote_best_marker(bucket, "best_source_hierarchy", "manufacturer_family_spec", _hierarchy_rank("manufacturer_family_spec"), "_best_hierarchy_rank")
            elif source_priority.lower().startswith("vendor"):
                _maybe_promote_best_marker(bucket, "best_source_hierarchy", "vendor_pdf", _hierarchy_rank("vendor_pdf"), "_best_hierarchy_rank")
            if evidence_tier in {"vendor_document_pointer", "reference"} and confidence < 0.75:
                bucket["weak_support_count"] = int(bucket.get("weak_support_count", 0) or 0) + 1
            _append_unique(bucket["match_reasons"], match_reason)
            _append_unique(bucket["source_refs"], item.get("source_ref"))
            _append_unique(bucket["source_refs"], item.get("source_url"))

    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        metadata = snippet.get("metadata", {}) if isinstance(snippet.get("metadata"), dict) else {}
        field_path = str(metadata.get("target_field", "")).strip()
        if not field_path:
            continue
        bucket = bucket_for(field_path)
        score = float(snippet.get("score", 0.0) or 0.0)
        bucket["top_score"] = max(float(bucket.get("top_score", 0.0) or 0.0), score)
        evidence_tier = str(metadata.get("evidence_tier", "")).strip().lower()
        specificity = str(metadata.get("specificity", "")).strip()
        source_hierarchy = str(metadata.get("source_hierarchy", "")).strip()
        source_priority = str(metadata.get("source_priority", "")).strip()
        if specificity:
            _maybe_promote_best_marker(bucket, "best_specificity", specificity, _specificity_rank(specificity), "_best_specificity_rank")
        if source_hierarchy:
            _maybe_promote_best_marker(bucket, "best_source_hierarchy", source_hierarchy, _hierarchy_rank(source_hierarchy), "_best_hierarchy_rank")
        if source_priority:
            _maybe_promote_best_marker(bucket, "best_source_priority", source_priority, _source_priority_rank(source_priority), "_best_priority_rank")
        if evidence_tier in {"official_vendor_document", "official_interconnection_source", "structured_catalog"} or source_hierarchy == "official_interconnection_source":
            bucket["strong_candidate_count"] = int(bucket.get("strong_candidate_count", 0) or 0) + 1
        if specificity == "exact_model_match":
            bucket["exact_model_support_count"] = int(bucket.get("exact_model_support_count", 0) or 0) + 1
        elif specificity == "family_match":
            bucket["family_support_count"] = int(bucket.get("family_support_count", 0) or 0) + 1
        if source_hierarchy in {"official_interconnection_source", "official_website"}:
            bucket["official_source_count"] = int(bucket.get("official_source_count", 0) or 0) + 1
        if evidence_tier in {"vendor_document_pointer", "reference"} and score < 0.75:
            bucket["weak_support_count"] = int(bucket.get("weak_support_count", 0) or 0) + 1
        _append_unique(bucket["source_refs"], snippet.get("source_ref"))

    for field_path, bucket in summary.items():
        bucket.pop("_best_priority_rank", None)
        bucket.pop("_best_hierarchy_rank", None)
        bucket.pop("_best_specificity_rank", None)
        bucket["support_strength"] = _strength_from_summary(bucket)
        if bucket.get("weak_support_count") and not bucket.get("strong_candidate_count") and not bucket.get("exact_model_support_count"):
            bucket["weak_support_only"] = True
        else:
            bucket["weak_support_only"] = False

    return summary



def _renumber_retrieval_snippets(context: Any, snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return snippets with stable, unique run-scoped snippet IDs.

    Base retrieval, equipment retrieval, and agent-generated retrieval can each
    independently materialize snippets. Some paths start numbering from one, so
    the final merged evidence bundle must be renumbered once before downstream
    support summaries, route records, and planner artifacts consume it.
    """
    renumbered: list[dict[str, Any]] = []
    run_id = str(getattr(context, "run_id", "run")).strip() or "run"
    for index, snippet in enumerate((item for item in snippets if isinstance(item, dict)), start=1):
        materialized = dict(snippet)
        previous_id = str(materialized.get("snippet_id", "")).strip()
        if previous_id:
            metadata = materialized.get("metadata", {})
            if isinstance(metadata, dict):
                materialized["metadata"] = {**metadata, "previous_snippet_id": previous_id}
        materialized["snippet_id"] = f"{run_id}_snip_{index:03d}"
        renumbered.append(materialized)
    return renumbered


class RetrievalDomainCoordinator:
    """Authoritative retrieval-domain owner for Wave 3 consolidation."""

    def run_retrieval(
        self,
        *,
        context: Any,
        normalization_result: dict[str, Any] | None = None,
        extraction_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        retrieval_config = retrieval_service_module._retrieval_config(context)
        corpora = retrieval_service_module._load_corpora()

        initial_requested_field_paths = retrieval_service_module._missing_fields(normalization_result)
        document_field_pack = build_document_field_pack(
            input_dir=getattr(context, "input_dir", None),
            requested_field_paths=initial_requested_field_paths,
        )
        suppressed_field_paths = set(document_field_pack.suppressed_field_paths)

        base_queries = retrieval_service_module._build_queries(
            normalization_result=normalization_result,
            extraction_result=extraction_result,
        )
        if suppressed_field_paths:
            base_queries = [
                query
                for query in base_queries
                if str(query.get("target_field", "")).strip() not in suppressed_field_paths
            ]
        base_snippets = retrieval_service_module._build_snippets(
            context=context,
            queries=base_queries,
            corpora=corpora,
            top_k=int(retrieval_config["top_k"]),
        )

        equipment_result = resolve_equipment_references(
            context=context,
            normalization_result=normalization_result,
            extraction_result=extraction_result,
        )

        planning_inputs = list(base_snippets)
        equipment_snippets = equipment_result.get("snippets", []) if isinstance(equipment_result, dict) else []
        if isinstance(equipment_snippets, list) and equipment_snippets:
            planning_inputs.extend(equipment_snippets)

        trigger_summary = retrieval_service_module._retrieval_trigger_summary(
            normalization_result=normalization_result,
            snippets=planning_inputs,
            equipment_reference_resolution=equipment_result if isinstance(equipment_result, dict) else None,
        )

        agent_result = retrieval_service_module._run_retrieval_planning_agent(
            context=context,
            queries=base_queries,
            snippets=planning_inputs,
            normalization_result=normalization_result,
            equipment_reference_resolution=equipment_result if isinstance(equipment_result, dict) else None,
        )
        evidence_agent_result = retrieval_service_module._run_evidence_resolution_agent(
            context=context,
            queries=base_queries,
            snippets=planning_inputs,
            normalization_result=normalization_result,
            equipment_reference_resolution=equipment_result if isinstance(equipment_result, dict) else None,
        )

        final_queries = list(base_queries)
        final_snippets = list(base_snippets)
        warnings: list[str] = []
        recommended_next_request = ""
        knowledge_family_route: list[str] = []
        requested_field_paths = [
            field_path
            for field_path in initial_requested_field_paths
            if field_path not in suppressed_field_paths
        ]
        review_required_field_paths: list[str] = []
        out_of_scope_field_paths: list[str] = []
        evidence_gap = bool(trigger_summary.get("evidence_gap", False)) if isinstance(trigger_summary, dict) else False
        official_web_lookup_required = False

        if isinstance(equipment_result, dict):
            equipment_warning_items = equipment_result.get("warnings", [])
            library_summary = equipment_result.get("library_summary", {})
            if isinstance(library_summary, dict) and library_summary:
                resolved_count = int(library_summary.get("candidate_field_count", 0) or 0)
                unresolved_count = int(library_summary.get("unresolved_missing_field_count", 0) or 0)
                warnings.append(
                    f"Equipment reference library-first pass produced {resolved_count} candidate fixed-spec fields and left {unresolved_count} unresolved equipment spec fields."
                )
            if isinstance(equipment_warning_items, list):
                warnings.extend(
                    str(item).strip()
                    for item in equipment_warning_items
                    if isinstance(item, str) and item.strip()
                )
            if isinstance(equipment_snippets, list):
                next_snippet_index = len(final_snippets) + 1
                allowed_equipment_snippet_fields = {
                    _normalized_field_key(field_path)
                    for field_path in [
                        *initial_requested_field_paths,
                        *(str(query.get("target_field", "")).strip() for query in final_queries if isinstance(query, dict)),
                    ]
                    if str(field_path or "").strip()
                }
                appended_equipment_snippet = False
                for snippet in equipment_snippets:
                    if not isinstance(snippet, dict):
                        continue
                    metadata = snippet.get("metadata", {}) if isinstance(snippet.get("metadata"), dict) else {}
                    target_field = str(metadata.get("target_field", snippet.get("target_field", ""))).strip()
                    if allowed_equipment_snippet_fields and _normalized_field_key(target_field) not in allowed_equipment_snippet_fields:
                        continue
                    materialized = dict(snippet)
                    materialized.setdefault("snippet_id", f"{context.run_id}_snip_{next_snippet_index:03d}")
                    next_snippet_index += 1
                    appended_equipment_snippet = True
                    final_snippets.append(materialized)
                if appended_equipment_snippet:
                    knowledge_family_route.extend(["equipment_catalog", "vendor_documents"])

            official_sources = equipment_result.get("official_source_candidates", [])
            if isinstance(official_sources, list) and official_sources:
                warnings.append("Official-source equipment references are available for unresolved or partially populated vendor-fixed fields.")
                if not recommended_next_request:
                    recommended_next_request = "Review indexed official vendor sources for remaining unresolved equipment specifications."
                knowledge_family_route.extend(["equipment_catalog", "vendor_documents"])

            pdf_lookup_plans = equipment_result.get("pdf_lookup_plans", [])
            if isinstance(pdf_lookup_plans, list) and pdf_lookup_plans:
                warnings.append("Agent 4 may search the matched vendor PDF repository for unresolved equipment specs after the structured library-first pass.")
                knowledge_family_route.append("vendor_documents")
            web_lookup_plans = equipment_result.get("web_lookup_plans", [])
            if isinstance(web_lookup_plans, list) and web_lookup_plans:
                warnings.append("Agent 4 may perform official-source-only web lookups for unresolved equipment specs after the library and PDF passes.")
            review_required_items = equipment_result.get("review_required_fields", [])
            if isinstance(review_required_items, list):
                review_required_field_paths.extend(
                    str(item).strip()
                    for item in review_required_items
                    if isinstance(item, str) and str(item).strip()
                )
            unresolved_missing = equipment_result.get("unresolved_missing_fields", [])
            if isinstance(unresolved_missing, list):
                requested_field_paths.extend(
                    str(item).strip()
                    for item in unresolved_missing
                    if isinstance(item, str) and str(item).strip()
                )
            out_of_scope_missing = equipment_result.get("out_of_scope_missing_fields", [])
            if isinstance(out_of_scope_missing, list):
                out_of_scope_field_paths.extend(
                    str(item).strip()
                    for item in out_of_scope_missing
                    if isinstance(item, str) and str(item).strip()
                )
            official_web_lookup_required = bool(equipment_result.get("web_lookup_required", False))
            if official_web_lookup_required:
                warnings.append("Official-source-only web lookup is required for unresolved equipment specifications that remain after the structured library and PDF passes.")

        if isinstance(trigger_summary, dict):
            trigger_reasons = trigger_summary.get("reasons", [])
            if isinstance(trigger_reasons, list):
                warnings.extend(
                    f"Retrieval planning trigger: {str(item).strip()}"
                    for item in trigger_reasons
                    if isinstance(item, str) and str(item).strip()
                )

        def _apply_agent_query_output(agent_payload: dict[str, Any] | None, *, default_query_source: str) -> None:
            nonlocal recommended_next_request, evidence_gap, official_web_lookup_required
            if not isinstance(agent_payload, dict):
                return
            structured_output = agent_payload.get("structured_output", {})
            if not isinstance(structured_output, dict):
                return

            review_notes = structured_output.get("review_notes", [])
            if isinstance(review_notes, list):
                warnings.extend(
                    str(item).strip()
                    for item in review_notes
                    if isinstance(item, str) and item.strip()
                )

            priority_summary = structured_output.get("source_priority_summary", [])
            if isinstance(priority_summary, list):
                warnings.extend(
                    str(item).strip()
                    for item in priority_summary
                    if isinstance(item, str) and item.strip()
                )

            agent_recommended_next_request = str(structured_output.get("recommended_next_request", "")).strip()
            if agent_recommended_next_request:
                if not recommended_next_request:
                    recommended_next_request = agent_recommended_next_request
                warnings.append(agent_recommended_next_request)

            suggested_query_topics = structured_output.get("suggested_query_topics", [])
            routed_families = structured_output.get("knowledge_family_route", [])
            suggested_queries = structured_output.get("suggested_queries", [])
            query_plan = structured_output.get("query_plan", {})
            evidence_gap = bool(structured_output.get("evidence_gap_flag", evidence_gap))
            official_web_lookup_required = bool(structured_output.get("web_lookup_required", official_web_lookup_required))

            if isinstance(routed_families, list):
                knowledge_family_route.extend(
                    str(item).strip()
                    for item in routed_families
                    if isinstance(item, str) and str(item).strip()
                )

            if not isinstance(suggested_query_topics, list):
                suggested_query_topics = []
            if not isinstance(routed_families, list):
                routed_families = []

            generated_queries = retrieval_service_module._build_agent_generated_queries(
                suggested_query_topics=[
                    str(item).strip()
                    for item in suggested_query_topics
                    if isinstance(item, str) and item.strip()
                ],
                knowledge_family_route=[
                    str(item).strip()
                    for item in knowledge_family_route
                    if isinstance(item, str) and item.strip()
                ],
                suggested_queries=suggested_queries if isinstance(suggested_queries, list) else None,
                query_plan=query_plan if isinstance(query_plan, dict) else None,
                query_source=default_query_source,
            )

            if generated_queries:
                existing_keys = {
                    (
                        str(query.get("intent", "")).strip(),
                        str(query.get("target_field", "")).strip(),
                        str(query.get("query_source", "")).strip(),
                    )
                    for query in final_queries
                }

                existing_queries_by_target_field: dict[str, dict[str, Any]] = {}
                for existing_query in final_queries:
                    if not isinstance(existing_query, dict):
                        continue
                    target_field = str(existing_query.get("target_field", "")).strip()
                    if target_field and target_field not in existing_queries_by_target_field:
                        existing_queries_by_target_field[target_field] = existing_query

                appended_queries: list[dict[str, Any]] = []
                allowed_agent_target_fields = {
                    _normalized_field_key(field_path)
                    for field_path in [
                        *requested_field_paths,
                        *review_required_field_paths,
                        *(str(existing_query.get("target_field", "")).strip() for existing_query in final_queries if isinstance(existing_query, dict)),
                    ]
                    if str(field_path or "").strip()
                }
                for query in generated_queries:
                    key = (
                        str(query.get("intent", "")).strip(),
                        str(query.get("target_field", "")).strip(),
                        str(query.get("query_source", "")).strip(),
                    )
                    if key in existing_keys:
                        continue
                    materialized_query = dict(query)
                    target_field = str(materialized_query.get("target_field", "")).strip()
                    if allowed_agent_target_fields and _normalized_field_key(target_field) not in allowed_agent_target_fields:
                        continue
                    existing_keys.add(key)
                    inherited_query = existing_queries_by_target_field.get(target_field, {})
                    inherited_artifact_ids = inherited_query.get("source_artifact_ids", []) if isinstance(inherited_query, dict) else []
                    inherited_document_types = inherited_query.get("source_document_types", []) if isinstance(inherited_query, dict) else []
                    if isinstance(inherited_artifact_ids, list) and inherited_artifact_ids:
                        materialized_query["source_artifact_ids"] = list(inherited_artifact_ids)
                    if isinstance(inherited_document_types, list) and inherited_document_types:
                        materialized_query["source_document_types"] = list(inherited_document_types)
                    appended_queries.append(materialized_query)

                if appended_queries:
                    final_queries.extend(appended_queries)
                    agent_snippets = retrieval_service_module._build_snippets(
                        context=context,
                        queries=appended_queries,
                        corpora=corpora,
                        top_k=int(retrieval_config["top_k"]),
                    )
                    final_snippets.extend(agent_snippets)

        _apply_agent_query_output(agent_result, default_query_source="retrieval_planning_agent")
        _apply_agent_query_output(evidence_agent_result, default_query_source="evidence_resolution_agent")

        llm_assistance_payload = dict(agent_result or {})
        if isinstance(evidence_agent_result, dict):
            llm_assistance_payload["evidence_resolution_agent"] = evidence_agent_result
        if isinstance(equipment_result, dict):
            llm_assistance_payload["equipment_reference_resolution"] = equipment_result

        deduped_warnings: list[str] = []
        for item in warnings:
            cleaned = str(item).strip()
            if cleaned and cleaned not in deduped_warnings:
                deduped_warnings.append(cleaned)

        if document_field_pack.suppressed_field_paths:
            deduped_warnings.append(
                "Document-aware field-pack routing suppressed low-yield backlog fields for this intake bundle: "
                + ", ".join(document_field_pack.suppressed_field_paths)
            )

        out_of_scope_field_paths = _canonicalize_field_collection(out_of_scope_field_paths, equipment_result if isinstance(equipment_result, dict) else None)
        requested_field_paths = _canonicalize_field_collection(requested_field_paths, equipment_result if isinstance(equipment_result, dict) else None)
        review_required_field_paths = _canonicalize_field_collection(review_required_field_paths, equipment_result if isinstance(equipment_result, dict) else None)

        out_of_scope_field_paths = sorted(_dedupe_field_paths(out_of_scope_field_paths))
        requested_field_paths = sorted(_subtract_field_paths(_dedupe_field_paths(requested_field_paths), out_of_scope_field_paths))
        review_required_field_paths = sorted(_subtract_field_paths(_dedupe_field_paths(review_required_field_paths), out_of_scope_field_paths))
        review_required_field_paths = sorted(_subtract_field_paths(review_required_field_paths, requested_field_paths))

        if suppressed_field_paths:
            requested_field_paths = [field_path for field_path in requested_field_paths if field_path not in suppressed_field_paths]
            review_required_field_paths = [field_path for field_path in review_required_field_paths if field_path not in suppressed_field_paths]
            out_of_scope_field_paths = [field_path for field_path in out_of_scope_field_paths if field_path not in suppressed_field_paths]

        active_query_targets = [
            str(query.get("target_field", "")).strip()
            for query in final_queries
            if (
                isinstance(query, dict)
                and str(query.get("target_field", "")).strip()
                and str(query.get("target_field", "")).strip() not in suppressed_field_paths
            )
        ]
        requested_field_paths = sorted(_dedupe_field_paths([*active_query_targets, *requested_field_paths]))
        review_required_field_paths = sorted(_dedupe_field_paths(review_required_field_paths))
        out_of_scope_field_paths = sorted(_dedupe_field_paths(out_of_scope_field_paths))

        if suppressed_field_paths:
            requested_field_paths = [field_path for field_path in requested_field_paths if field_path not in suppressed_field_paths]
            review_required_field_paths = [field_path for field_path in review_required_field_paths if field_path not in suppressed_field_paths]
            out_of_scope_field_paths = [field_path for field_path in out_of_scope_field_paths if field_path not in suppressed_field_paths]

        explicit_retrieval_scope_field_paths = _initial_retrieval_scope_field_paths(
            initial_requested_field_paths=initial_requested_field_paths,
            extraction_result=extraction_result,
            equipment_result=equipment_result if isinstance(equipment_result, dict) else None,
        )
        final_snippets = _filter_snippets_to_explicit_retrieval_scope(
            final_snippets,
            allowed_field_paths=explicit_retrieval_scope_field_paths,
        )
        final_snippets = _renumber_retrieval_snippets(context, final_snippets)

        preliminary_field_support_summary = _build_field_support_summary(
            snippets=final_snippets,
            equipment_result=equipment_result if isinstance(equipment_result, dict) else None,
        )
        official_web_plans = _candidate_official_web_plan(
            snippets=final_snippets,
            equipment_result=equipment_result if isinstance(equipment_result, dict) else None,
            field_support_summary=preliminary_field_support_summary,
            requested_field_paths=sorted(_dedupe_field_paths([*requested_field_paths, *review_required_field_paths])),
            official_web_lookup_required=official_web_lookup_required,
        )
        executed_official_web_retrieval = {"attempted_count": 0, "executed_count": 0, "records": []}
        if official_web_plans:
            official_web_snippets, executed_official_web_retrieval, official_web_warnings = _execute_official_web_retrieval(
                context=context,
                plans=official_web_plans,
                starting_snippet_index=len(final_snippets) + 1,
            )
            if official_web_snippets:
                final_snippets.extend(official_web_snippets)
                deduped_warnings.append(
                    f"Executed official web retrieval captured {executed_official_web_retrieval.get('executed_count', 0)} official-source evidence record(s)."
                )
            for item in official_web_warnings:
                cleaned = str(item).strip()
                if cleaned and cleaned not in deduped_warnings:
                    deduped_warnings.append(cleaned)

        evidence_gap_reason = recommended_next_request or (deduped_warnings[0] if deduped_warnings else "")
        evidence_gap_payload = {
            "status": "UNRESOLVED" if evidence_gap or requested_field_paths else "RESOLVED",
            "reason": evidence_gap_reason,
        }
        resolution_backlog = _build_resolution_backlog(
            requested_field_paths=requested_field_paths,
            review_required_field_paths=review_required_field_paths,
            out_of_scope_field_paths=out_of_scope_field_paths,
            equipment_result=equipment_result if isinstance(equipment_result, dict) else None,
            gap_fill_strategy="library_then_pdf_then_official_web",
            official_web_lookup_required=official_web_lookup_required,
            default_reason=evidence_gap_reason,
        )
        resolution_backlog_summary = _build_resolution_backlog_summary(resolution_backlog)
        field_support_summary = _build_field_support_summary(
            snippets=final_snippets,
            equipment_result=equipment_result if isinstance(equipment_result, dict) else None,
        )
        evidence_route_records = _build_evidence_route_records(
            queries=final_queries,
            snippets=final_snippets,
            field_support_summary=field_support_summary,
            equipment_result=equipment_result if isinstance(equipment_result, dict) else None,
            agent_result=agent_result,
            evidence_agent_result=evidence_agent_result,
        )

        return {
            "run_id": context.run_id,
            "status": "EVIDENCE_RETRIEVED",
            "retrieved_at": retrieval_service_module.utc_now_iso(),
            "retrieval_config": retrieval_config,
            "queries": final_queries,
            "snippets": final_snippets,
            "llm_assistance": llm_assistance_payload,
            "warnings": deduped_warnings,
            "recommended_next_request": recommended_next_request,
            "knowledge_family_route": sorted({item for item in knowledge_family_route if isinstance(item, str) and item.strip()}),
            "document_field_pack": document_field_pack.to_dict(),
            "requested_field_paths": requested_field_paths,
            "review_required_field_paths": review_required_field_paths,
            "out_of_scope_missing_field_paths": out_of_scope_field_paths,
            "resolution_backlog": resolution_backlog,
            "resolution_backlog_summary": resolution_backlog_summary,
            "evidence_gap": evidence_gap_payload,
            "official_web_lookup_required": official_web_lookup_required,
            "executed_official_web_retrieval": executed_official_web_retrieval,
            "field_support_summary": field_support_summary,
            "evidence_route_records": evidence_route_records,
            "equipment_reference_resolution_used": bool(isinstance(equipment_result, dict) and equipment_result),
            "gap_fill_strategy": "library_then_pdf_then_official_web",
            "equipment_reference_resolution": equipment_result if isinstance(equipment_result, dict) else {},
            "trigger_summary": trigger_summary if isinstance(trigger_summary, dict) else {},
            "errors": [],
        }

    def _llm_enabled(self) -> bool:
        config = getattr(CONFIG, "llm_runtime", None)
        if config is None:
            return False
        return bool(getattr(config, "enabled", False)) and bool(str(getattr(config, "model_path", "") or "").strip())

    def _ensure_runtime(self) -> None:
        from services.llm_runtime_service.models import LLMRuntimeConfig
        from services.llm_runtime_service.service import initialize_runtime

        config = CONFIG.llm_runtime
        initialize_runtime(
            LLMRuntimeConfig(
                model_path=str(config.model_path),
                model_alias=str(config.model_alias),
                n_ctx=int(config.n_ctx),
                n_threads=int(config.n_threads),
                n_batch=int(config.n_batch),
                n_gpu_layers=int(config.n_gpu_layers),
                temperature=float(config.temperature),
                top_p=float(config.top_p),
                max_tokens=int(config.max_tokens),
            )
        )

    def _can_run_agent(self, context: Any | None) -> bool:
        if context is None:
            return False
        run_id = getattr(context, "run_id", None)
        return isinstance(run_id, str) and bool(run_id.strip())

    def _legacy_llm_extract(
        self,
        *,
        artifact: Dict[str, Any],
        field_path: str,
        text: str,
        deterministic_value: Optional[Any],
        deterministic_confidence: float,
    ) -> tuple[Optional[Any], float, str]:
        if not self._llm_enabled() or (deterministic_value is not None and deterministic_confidence >= 0.72) or not text.strip():
            return deterministic_value, deterministic_confidence, "retrieval_service_extraction"

        try:
            from services.llm_runtime_service.models import LLMTaskRequest
            from services.llm_runtime_service.service import run_llm_task

            self._ensure_runtime()
            request = LLMTaskRequest(
                task_name="retrieval_artifact_interpretation",
                prompt_template_id="phase4.retrieval_worker.v1",
                system_prompt=(
                    "You are a bounded engineering retrieval interpretation worker. "
                    "Return only valid JSON and only assert support when evidence is present."
                ),
                user_prompt=(
                    f"Field path: {field_path}\n"
                    f"Deterministic value: {deterministic_value!r}\n"
                    f"Artifact text:\n{text}\n\n"
                    "Return JSON with a single key named value."
                ),
                response_schema={
                    "type": "object",
                    "properties": {
                        "value": {"type": ["boolean", "null"]},
                    },
                    "required": ["value"],
                },
                json_mode=True,
                metadata={
                    "service": "retrieval_service",
                    "artifact_id": artifact.get("artifact_id"),
                    "field_path": field_path,
                },
            )
            runtime_result = run_llm_task(
                run_id=str(artifact.get("artifact_id", "retrieval_service")),
                request=request,
            )
        except Exception:
            return deterministic_value, deterministic_confidence, "retrieval_service_extraction"

        payload = runtime_result.parsed_json if isinstance(runtime_result.parsed_json, dict) else {}
        coerced_value = coerce_retrieval_llm_value(payload.get("value"))
        if coerced_value is None:
            return deterministic_value, deterministic_confidence, "retrieval_service_extraction"

        return coerced_value, max(deterministic_confidence, 0.74), "retrieval_service_extraction_llm"

    def _agent_extract(
        self,
        *,
        artifact: Dict[str, Any],
        field_path: str,
        text: str,
        deterministic_value: Optional[Any],
        deterministic_confidence: float,
        context: Any,
    ) -> tuple[Optional[Any], float, str]:
        if (deterministic_value is not None and deterministic_confidence >= 0.72) or not text.strip():
            return deterministic_value, deterministic_confidence, "retrieval_service_extraction"

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="retrieval_planning_agent",
                stage_name=GAP_RESOLUTION_RETRIEVAL_STAGE,
                task_name="query_review",
                inputs={
                    "queries": [],
                    "snippets": [],
                    "normalized_input": {
                        "field_path": field_path,
                        "artifact_text_present": True,
                    },
                    "validation_report": {
                        "missing_fields": [field_path],
                    },
                    "warnings": [],
                    "artifact_text": text,
                    "artifact_id": artifact.get("artifact_id"),
                    "deterministic_value": deterministic_value,
                    "deterministic_confidence": deterministic_confidence,
                },
                metadata={
                    "service": "retrieval_service",
                    "artifact_id": artifact.get("artifact_id"),
                },
                trigger_reason="retrieval_worker_low_confidence_or_unresolved",
                associated_field_paths=[field_path],
                evidence_anchors=[
                    {
                        "anchor_type": "retrieval_artifact",
                        "artifact_id": str(artifact.get("artifact_id", "")).strip(),
                        "section": artifact.get("section"),
                        "page": artifact.get("page"),
                    }
                ],
                suggested_output_fields=[
                    "evidence_gap_flag",
                    "recommended_next_request",
                    "rationale",
                    "confidence",
                ],
            ),
        )

        structured_output = result.get("structured_output", {})
        if not isinstance(structured_output, dict):
            structured_output = {}

        evidence_gap_flag = structured_output.get("evidence_gap_flag")
        if evidence_gap_flag is True:
            return deterministic_value, deterministic_confidence, "retrieval_service_extraction_agent"

        heuristic_bool = (
            infer_dynamic_model_available(text)
            if "dynamic_model_available" in field_path
            else infer_pscad_model_package(text)
        )
        if heuristic_bool is not None:
            return heuristic_bool, max(deterministic_confidence, 0.74), "retrieval_service_extraction_agent"

        return deterministic_value, deterministic_confidence, "retrieval_service_extraction_agent"

    def _maybe_assisted_extract(
        self,
        *,
        artifact: Dict[str, Any],
        field_path: str,
        text: str,
        deterministic_value: Optional[Any],
        deterministic_confidence: float,
        context: Any | None,
    ) -> tuple[Optional[Any], float, str]:
        if self._can_run_agent(context):
            try:
                return self._agent_extract(
                    artifact=artifact,
                    field_path=field_path,
                    text=text,
                    deterministic_value=deterministic_value,
                    deterministic_confidence=deterministic_confidence,
                    context=context,
                )
            except Exception:
                return self._legacy_llm_extract(
                    artifact=artifact,
                    field_path=field_path,
                    text=text,
                    deterministic_value=deterministic_value,
                    deterministic_confidence=deterministic_confidence,
                )

        return self._legacy_llm_extract(
            artifact=artifact,
            field_path=field_path,
            text=text,
            deterministic_value=deterministic_value,
            deterministic_confidence=deterministic_confidence,
        )

    def extract_artifact_fields(
        self,
        *,
        artifacts: List[Dict[str, Any]],
        field_paths: List[str],
        context: Any | None = None,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for artifact in artifacts:
            if not is_retrieval_artifact(artifact):
                continue

            artifact_id = artifact.get("artifact_id", "unknown_artifact")
            text = get_artifact_text(artifact)

            for field_path in field_paths:
                value: Optional[Any] = None
                confidence = 0.0
                method = "retrieval_service_extraction"

                if field_path in {"facility.modeling.dynamic_model_available", "facility.dynamic_model_available"}:
                    value = infer_dynamic_model_available(text)
                    confidence = 0.72 if value is not None else 0.0

                elif field_path in {"facility.modeling.pscad_model_package", "facility.pscad_model_package"}:
                    value = infer_pscad_model_package(text)
                    confidence = 0.76 if value is not None else 0.0

                value, confidence, method = self._maybe_assisted_extract(
                    artifact=artifact,
                    field_path=field_path,
                    text=text,
                    deterministic_value=value,
                    deterministic_confidence=confidence,
                    context=context,
                )

                extraction_result = RetrievalExtractionResult(
                    field_path=field_path,
                    value=value,
                    confidence=confidence,
                    source_artifact_id=str(artifact_id),
                    method=method,
                    evidence={
                        "page": artifact.get("page"),
                        "section": artifact.get("section"),
                    },
                )
                results.append(
                    {
                        "field_path": extraction_result.field_path,
                        "value": extraction_result.value,
                        "confidence": extraction_result.confidence,
                        "source_artifact_id": extraction_result.source_artifact_id,
                        "method": extraction_result.method,
                        "evidence": extraction_result.evidence,
                    }
                )

        return results

    def extract(
        self,
        artifacts: List[Dict[str, Any]],
        field_paths: List[str],
        context: Any | None = None,
    ) -> List[Dict[str, Any]]:
        return self.extract_artifact_fields(
            artifacts=artifacts,
            field_paths=field_paths,
            context=context,
        )
