from __future__ import annotations

import importlib
import importlib.metadata
import os
import re
from pathlib import Path
from typing import Any

from app.config import CONFIG


DEFAULT_RENDER_SCALE = 2.0
DEFAULT_OCR_LANG = "en"
SPARSE_TEXT_CHAR_THRESHOLD = 80


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_region_id(*, artifact_id: str, page_number: int, region_index: int) -> str:
    return f"{artifact_id}_p{page_number:04d}_ocr_{region_index:05d}"


def file_exists(file_path: str | Path) -> bool:
    return Path(file_path).exists()


def get_distribution_version(distribution_name: str) -> str:
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def import_optional(module_name: str) -> tuple[Any | None, str | None]:
    try:
        return importlib.import_module(module_name), None
    except Exception as exc:
        return None, f"{module_name} import failed: {exc.__class__.__name__}: {exc}"


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return None
    return bool(value)


def is_ocr_runtime_enabled(context: Any) -> bool:
    env_value = _coerce_bool(os.environ.get("GRIDSENPAI_OCR_RUNTIME_ENABLED"))
    if env_value is not None:
        return env_value

    config = getattr(context, "config", None)
    value = _coerce_bool(getattr(config, "ocr_enabled", None))
    if value is None:
        value = _coerce_bool(getattr(config, "ocr_runtime_enabled", None))
    if value is None:
        ocr_config = getattr(CONFIG, "ocr", None)
        value = _coerce_bool(getattr(ocr_config, "enabled", None))
    if value is None:
        return True
    return value


def get_ocr_lang(context: Any) -> str:
    config = getattr(context, "config", None)
    value = getattr(config, "ocr_lang", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_OCR_LANG




def get_ocr_text_detection_model_name(context: Any) -> str:
    config = getattr(context, "config", None)
    value = getattr(config, "ocr_text_detection_model_name", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "PP-OCRv5_server_det"


def get_ocr_text_recognition_model_name(context: Any) -> str:
    config = getattr(context, "config", None)
    value = getattr(config, "ocr_text_recognition_model_name", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "PP-OCRv5_server_rec"


def get_render_scale(context: Any) -> float:
    config = getattr(context, "config", None)
    value = getattr(config, "ocr_render_scale", None)
    if value is None:
        return DEFAULT_RENDER_SCALE
    return safe_float(value, default=DEFAULT_RENDER_SCALE)


def _layout_requests_ocr(layout_document: dict[str, Any] | None) -> bool:
    if not isinstance(layout_document, dict):
        return False
    pages = layout_document.get("pages", [])
    if not isinstance(pages, list):
        return False
    for page in pages:
        if not isinstance(page, dict):
            continue
        if str(page.get("page_classification", "")).strip() in {"DIAGRAM_PAGE", "TABLE_PAGE", "MIXED_PAGE"}:
            return True
        warnings = page.get("warnings", [])
        if isinstance(warnings, list) and any("targeted ocr" in str(item).lower() for item in warnings):
            return True
    return False


def should_process_route(route_hint: str, parsed_document: dict[str, Any] | None = None, layout_document: dict[str, Any] | None = None) -> bool:
    if route_hint in {"OCR_REQUIRED", "HYBRID_PARSE_AND_OCR"}:
        return True
    if route_hint == "BORN_DIGITAL_PARSE":
        if _layout_requests_ocr(layout_document):
            return True
        if isinstance(parsed_document, dict):
            structure_hints = parsed_document.get("structure_hints", {})
            if isinstance(structure_hints, dict) and structure_hints.get("ocr_candidate_pages"):
                return True
    return False


def select_pages_for_ocr(parsed_document: dict[str, Any], layout_document: dict[str, Any] | None = None) -> list[int]:
    route_hint = str(parsed_document.get("route_hint", "")).strip()
    pages = parsed_document.get("pages", [])
    page_count = safe_int(parsed_document.get("page_count"))
    if not isinstance(pages, list):
        pages = []
    selected: list[int] = []

    if route_hint == "OCR_REQUIRED":
        if pages:
            for page in pages:
                if not isinstance(page, dict):
                    continue
                page_number = safe_int(page.get("page_number"))
                if page_number > 0:
                    selected.append(page_number)
        elif page_count > 0:
            selected.extend(range(1, page_count + 1))
    elif route_hint == "HYBRID_PARSE_AND_OCR":
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_number = safe_int(page.get("page_number"))
            extracted_text = normalize_whitespace(str(page.get("extracted_text", "")))
            char_count = safe_int(page.get("char_count"))
            warnings = page.get("warnings", [])
            if not isinstance(warnings, list):
                warnings = []
            if page_number > 0 and (not extracted_text or char_count <= SPARSE_TEXT_CHAR_THRESHOLD or any("no extractable" in str(item).lower() for item in warnings)):
                selected.append(page_number)

    if route_hint == "BORN_DIGITAL_PARSE":
        structure_hints = parsed_document.get("structure_hints", {})
        if isinstance(structure_hints, dict):
            for page_number in structure_hints.get("ocr_candidate_pages", []):
                page_number = safe_int(page_number)
                if page_number > 0:
                    selected.append(page_number)
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_number = safe_int(page.get("page_number"))
            char_count = safe_int(page.get("char_count"))
            warnings = page.get("warnings", [])
            if not isinstance(warnings, list):
                warnings = []
            if page_number > 0 and (char_count <= SPARSE_TEXT_CHAR_THRESHOLD or any("no extractable" in str(item).lower() for item in warnings)):
                selected.append(page_number)

    if isinstance(layout_document, dict):
        layout_pages = layout_document.get("pages", [])
        if isinstance(layout_pages, list):
            for page in layout_pages:
                if not isinstance(page, dict):
                    continue
                page_number = safe_int(page.get("page_number"))
                if page_number <= 0:
                    continue
                page_classification = str(page.get("page_classification", "")).strip()
                candidate_regions = page.get("candidate_regions", [])
                if not isinstance(candidate_regions, list):
                    candidate_regions = []
                if page_classification in {"DIAGRAM_PAGE", "TABLE_PAGE", "MIXED_PAGE"} or any(isinstance(region, dict) and str(region.get("region_type", "")).strip() in {"OCR_TARGET_REGION", "DIAGRAM_EVIDENCE_REGION", "TABLE_EVIDENCE_REGION"} for region in candidate_regions):
                    selected.append(page_number)

    return sorted(set(selected))
