from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from shared.knowledge_routes import (
    KNOWLEDGE_ROOT,
    preferred_equipment_catalog_index,
    preferred_official_source_index,
    preferred_pdf_library_index,
    resolve_knowledge_path,
    runtime_corpus_source_paths,
)

_META_FILENAMES = {"readme.txt", "reference_index.json", "catalog_index.json", "official_source_index.json", "pdf_library_index.json"}


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _normalize_text(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _normalize_token(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    return "".join(ch for ch in lowered if ch.isalnum())


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(str(url or "").strip()).netloc.lower().strip()
    except Exception:
        return ""


def _path_terms(path_value: str) -> list[str]:
    path = str(path_value or "").strip()
    if not path:
        return []
    stem = Path(path).stem.replace("_", " ").replace("-", " ").strip()
    return [term for term in [path, stem] if term]


def _iter_scan_files(source_path: Path) -> list[Path]:
    if source_path.is_file():
        return [source_path]
    if not source_path.exists():
        return []
    return [path for path in sorted(source_path.rglob("*")) if path.is_file() and path.name.lower() not in _META_FILENAMES]


def _record_entry(*, corpus_name: str, source_path: Path, resolved: Path, source_ref: str, retrieval_priority: str, extra_metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
    text = _normalize_text(_safe_read_text(resolved))
    if not text:
        return None
    try:
        source_relative_path = str(resolved.relative_to(source_path))
    except ValueError:
        try:
            source_relative_path = str(resolved.relative_to(KNOWLEDGE_ROOT))
        except ValueError:
            source_relative_path = resolved.name
    metadata = {
        "knowledge_family": corpus_name,
        "source_kind": corpus_name,
        "source_root": str(source_path.relative_to(KNOWLEDGE_ROOT)) if source_path.exists() and source_path.is_relative_to(KNOWLEDGE_ROOT) else str(source_path),
        "source_relative_path": source_relative_path,
        "retrieval_priority": retrieval_priority,
        "indexed_record": True,
    }
    if isinstance(extra_metadata, dict):
        metadata.update(extra_metadata)
    return {
        "corpus": corpus_name,
        "source_ref": source_ref,
        "path": resolved,
        "text": text,
        "lowered_text": text.lower(),
        "metadata": metadata,
    }


def _indexed_entries_for_source(corpus_name: str, source_path: Path) -> list[dict[str, Any]]:
    if not source_path.exists() or not source_path.is_dir():
        return []
    index_path = source_path / "reference_index.json"
    payload = _safe_read_json(index_path)
    if not payload:
        return []
    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        return []

    entries: list[dict[str, Any]] = []
    for item in raw_records:
        if not isinstance(item, dict):
            continue
        record_path_value = item.get("path") or item.get("document_path") or item.get("source_path")
        resolved = resolve_knowledge_path(record_path_value, extra_roots=[source_path])
        if resolved is None or not resolved.exists() or not resolved.is_file():
            continue
        entry = _record_entry(
            corpus_name=corpus_name,
            source_path=source_path,
            resolved=resolved,
            source_ref=str(item.get("name", resolved.name)).strip() or resolved.name,
            retrieval_priority=str(item.get("retrieval_priority", "")).strip().lower() or "normal",
            extra_metadata={"record_name": str(item.get("name", resolved.name)).strip() or resolved.name},
        )
        if entry is not None:
            entries.append(entry)
    return entries


def _equipment_catalog_entries() -> list[dict[str, Any]]:
    index_path = preferred_equipment_catalog_index()
    payload = _safe_read_json(index_path)
    if not payload:
        return []
    records = payload.get("records", [])
    if not isinstance(records, list):
        return []
    source_root = index_path.parent
    entries: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        spec_path = item.get("spec_path")
        resolved = resolve_knowledge_path(spec_path, extra_roots=[source_root])
        if resolved is None or not resolved.exists() or not resolved.is_file():
            continue
        source_ref = f"{item.get('manufacturer','')} {item.get('model_or_product_line','')}".strip() or resolved.name
        entry = _record_entry(
            corpus_name="equipment_catalog",
            source_path=source_root,
            resolved=resolved,
            source_ref=source_ref,
            retrieval_priority="high" if str(item.get("record_status", "")).strip() else "normal",
            extra_metadata={
                "equipment_family": str(item.get("equipment_family", "")).strip(),
                "manufacturer": str(item.get("manufacturer", "")).strip(),
                "model": str(item.get("model_or_product_line", "")).strip(),
                "fixed_spec_names": list(item.get("fixed_spec_names", [])) if isinstance(item.get("fixed_spec_names"), list) else [],
                "record_status": str(item.get("record_status", "")).strip(),
                "source_kind": "equipment_catalog",
                "evidence_tier": "structured_catalog",
                "trust_level": "high",
            },
        )
        if entry is not None:
            entries.append(entry)
    return entries


def _legacy_pointer_records() -> list[dict[str, Any]]:
    """Compatibility fallback only when the canonical vendor-doc index is unavailable."""
    pdf_records = _vendor_pdf_index_records()
    if pdf_records:
        return []
    return []


def _vendor_pdf_index_records() -> list[dict[str, Any]]:

    pdf_index = _safe_read_json(preferred_pdf_library_index()) or {}
    pdf_records = pdf_index.get("records", []) if isinstance(pdf_index, dict) else []
    return [item for item in pdf_records if isinstance(item, dict)] if isinstance(pdf_records, list) else []


def _vendor_document_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    pdf_records = _vendor_pdf_index_records()
    source_records = pdf_records if pdf_records else _legacy_pointer_records()

    for item in source_records:
        family = str(item.get("equipment_family", item.get("family", ""))).strip()
        manufacturer = str(item.get("manufacturer", "")).strip()
        model = str(item.get("model", item.get("model_or_product_line", ""))).strip()
        document_type = str(item.get("document_type", item.get("type", "vendor_pdf"))).strip() or "vendor_pdf"
        source_url = str(item.get("source_url", "")).strip()
        path_value = str(item.get("document_path", item.get("path", item.get("pdf_path", "")))).strip()
        document_label = str(item.get("document_label", "")).strip() or f"{manufacturer} {model} {document_type}".strip()
        record_path = resolve_knowledge_path(path_value) if path_value else None
        source_relative_path = path_value or source_url or document_label
        text_parts = [
            family,
            manufacturer,
            model,
            document_label,
            document_type,
            source_url,
            *(_path_terms(path_value)),
            str(item.get("pointer_text", "")).strip(),
            " ".join(str(piece).strip() for piece in item.get("document_keywords", []) if str(piece).strip()) if isinstance(item.get("document_keywords"), list) else "",
        ]
        text = " ".join(part for part in text_parts if part)
        if not text:
            continue
        key = f"vendor::{family}::{manufacturer}::{model}::{document_type}::{source_url}::{path_value}"
        if key in seen:
            continue
        seen.add(key)
        source_domain = _domain_from_url(source_url)
        evidence_tier = "official_vendor_document" if source_url and source_domain else "vendor_document_pointer" if document_type == "vendor_pdf_pointer" else "vendor_document"
        trust_level = "high" if source_url and source_domain else "medium"
        entries.append(
            {
                "corpus": "vendor_documents",
                "source_ref": document_label or source_url or path_value or "vendor_document",
                "path": record_path or (Path(path_value) if path_value else preferred_pdf_library_index()),
                "text": text,
                "lowered_text": text.lower(),
                "metadata": {
                    "knowledge_family": "vendor_documents",
                    "source_root": "vendor_documents",
                    "source_relative_path": source_relative_path,
                    "retrieval_priority": str(item.get("retrieval_priority", "medium")).strip().lower() or "medium",
                    "indexed_record": True,
                    "source_kind": "vendor_document",
                    "equipment_family": family,
                    "manufacturer": manufacturer,
                    "model": model,
                    "document_type": document_type,
                    "document_label": document_label,
                    "source_url": source_url,
                    "source_domain": source_domain,
                    "document_keywords": list(item.get("document_keywords", [])) if isinstance(item.get("document_keywords"), list) else [],
                    "evidence_tier": evidence_tier,
                    "trust_level": trust_level,
                    "document_path": path_value,
                },
            }
        )

    official_index = _safe_read_json(preferred_official_source_index()) or {}
    families = official_index.get("families", []) if isinstance(official_index, dict) else []
    if isinstance(families, list):
        for family_block in families:
            if not isinstance(family_block, dict):
                continue
            family = str(family_block.get("family", "")).strip()
            for record in family_block.get("records", []):
                if not isinstance(record, dict):
                    continue
                manufacturer = str(record.get("manufacturer", "")).strip()
                model = str(record.get("model_or_product_line", "")).strip()
                for url in record.get("source_urls", []):
                    if not isinstance(url, str) or not url.strip():
                        continue
                    label = f"{manufacturer} {model}".strip() or url.strip()
                    key = f"official::{label}::{url}"
                    if key in seen:
                        continue
                    seen.add(key)
                    text = " ".join(part for part in [family, manufacturer, model, label, url.strip(), _domain_from_url(url)] if part)
                    entries.append(
                        {
                            "corpus": "vendor_documents",
                            "source_ref": label,
                            "path": preferred_official_source_index(),
                            "text": text,
                            "lowered_text": text.lower(),
                            "metadata": {
                                "knowledge_family": "vendor_documents",
                                "source_root": "vendor_documents",
                                "source_relative_path": url.strip(),
                                "retrieval_priority": "high",
                                "indexed_record": True,
                                "source_kind": "vendor_document",
                                "equipment_family": family,
                                "manufacturer": manufacturer,
                                "model": model,
                                "document_type": "official_source_index",
                                "document_label": label,
                                "source_url": url.strip(),
                                "source_domain": _domain_from_url(url),
                                "evidence_tier": "official_vendor_document",
                                "trust_level": "high",
                            },
                        }
                    )
    return entries


def load_corpus_entries(corpus_name: str) -> list[dict[str, Any]]:
    if corpus_name == "equipment_catalog":
        entries = _equipment_catalog_entries()
        if entries:
            return entries
    if corpus_name == "vendor_documents":
        entries = _vendor_document_entries()
        if entries:
            return entries

    indexed_entries: list[dict[str, Any]] = []
    source_paths = runtime_corpus_source_paths(corpus_name)
    for source_path in source_paths:
        indexed_entries.extend(_indexed_entries_for_source(corpus_name, source_path))
    if indexed_entries:
        return indexed_entries

    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for source_path in source_paths:
        for path in _iter_scan_files(source_path):
            text = _normalize_text(_safe_read_text(path))
            if not text:
                continue
            try:
                source_relative_path = str(path.relative_to(source_path))
            except ValueError:
                source_relative_path = path.name
            dedupe_key = f"{corpus_name}:{source_relative_path}"
            if dedupe_key in seen_paths:
                continue
            seen_paths.add(dedupe_key)
            entries.append(
                {
                    "corpus": corpus_name,
                    "source_ref": source_relative_path,
                    "path": path,
                    "text": text,
                    "lowered_text": text.lower(),
                    "metadata": {
                        "knowledge_family": corpus_name,
                        "source_kind": corpus_name,
                        "source_root": str(source_path.relative_to(KNOWLEDGE_ROOT)) if source_path.exists() and source_path.is_relative_to(KNOWLEDGE_ROOT) else str(source_path),
                        "source_relative_path": source_relative_path,
                        "retrieval_priority": "medium",
                        "indexed_record": False,
                    },
                }
            )
    return entries
