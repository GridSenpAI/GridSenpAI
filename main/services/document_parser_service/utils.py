from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path
from typing import Any


SUPPORTED_SUFFIXES: set[str] = {
    ".pdf",
}


def get_pdfplumber_version() -> str:
    try:
        return importlib.metadata.version("pdfplumber")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def build_repository_key(*, run_id: str, artifact_id: str) -> str:
    return f"{run_id}/artifacts/{artifact_id}"


def build_block_id(*, artifact_id: str, page_number: int, block_index: int) -> str:
    return f"{artifact_id}_p{page_number:04d}_b{block_index:05d}"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def file_exists(file_path: str | Path) -> bool:
    return Path(file_path).exists()


def is_pdf_artifact(artifact: dict[str, Any]) -> bool:
    file_suffix = str(artifact.get("file_suffix", "")).strip().lower()
    if file_suffix == ".pdf":
        return True

    file_name = str(artifact.get("file_name", "")).strip().lower()
    return file_name.endswith(".pdf")


def ensure_required_artifact_fields(artifact: dict[str, Any]) -> None:
    required_fields = {
        "artifact_id",
        "file_name",
        "file_path",
        "file_suffix",
    }

    missing_fields = [field_name for field_name in sorted(required_fields) if field_name not in artifact]
    if missing_fields:
        raise KeyError(
            "Artifact payload is missing required fields for document parsing: "
            + ", ".join(missing_fields)
        )


def classify_route_hint(*, page_count: int, pages_with_text: int, average_chars_per_text_page: float, structure_hints: dict[str, Any] | None = None) -> str:
    if page_count == 0:
        return "UNREADABLE"

    text_ratio = pages_with_text / page_count if page_count else 0.0
    structure_hints = structure_hints or {}
    ocr_candidate_pages = structure_hints.get("ocr_candidate_pages", [])
    if not isinstance(ocr_candidate_pages, list):
        ocr_candidate_pages = []

    if text_ratio >= 0.8 and average_chars_per_text_page >= 100:
        if ocr_candidate_pages and average_chars_per_text_page < 250:
            return "HYBRID_PARSE_AND_OCR"
        return "BORN_DIGITAL_PARSE"

    if 0.2 <= text_ratio < 0.8:
        return "HYBRID_PARSE_AND_OCR"

    return "OCR_REQUIRED"


def classify_parse_status(*, route_hint: str, page_count: int) -> str:
    if page_count == 0:
        return "PARSE_FAILED"
    if route_hint == "BORN_DIGITAL_PARSE":
        return "PARSED"
    if route_hint == "HYBRID_PARSE_AND_OCR":
        return "PARTIAL_PARSE"
    if route_hint == "OCR_REQUIRED":
        return "OCR_RECOMMENDED"
    return "PARSE_FAILED"


def detect_structure_hints(lines_by_page: list[list[str]]) -> dict[str, Any]:
    heading_candidates: list[dict[str, Any]] = []
    keyword_pages: dict[str, list[int]] = {
        "diagram": [],
        "schematic": [],
        "one_line": [],
        "single_line": [],
        "protection": [],
        "relay": [],
        "transformer": [],
        "generator": [],
        "ups": [],
        "switchyard": [],
    }

    for page_number, page_lines in enumerate(lines_by_page, start=1):
        for line in page_lines:
            cleaned = line.strip()
            if not cleaned:
                continue

            alpha_chars = [char for char in cleaned if char.isalpha()]
            uppercase_ratio = (
                sum(1 for char in alpha_chars if char.isupper()) / len(alpha_chars)
                if alpha_chars
                else 0.0
            )

            if len(cleaned) <= 120 and uppercase_ratio >= 0.8:
                heading_candidates.append(
                    {
                        "page_number": page_number,
                        "heading_text": cleaned,
                    }
                )

            lowered = cleaned.lower()
            if "diagram" in lowered:
                keyword_pages["diagram"].append(page_number)
            if "schematic" in lowered:
                keyword_pages["schematic"].append(page_number)
            if "one line" in lowered or "one-line" in lowered:
                keyword_pages["one_line"].append(page_number)
            if "single line" in lowered or "single-line" in lowered:
                keyword_pages["single_line"].append(page_number)
            if "protection" in lowered:
                keyword_pages["protection"].append(page_number)
            if "relay" in lowered:
                keyword_pages["relay"].append(page_number)
            if "transformer" in lowered:
                keyword_pages["transformer"].append(page_number)
            if "generator" in lowered:
                keyword_pages["generator"].append(page_number)
            if "ups" in lowered:
                keyword_pages["ups"].append(page_number)
            if "switchyard" in lowered:
                keyword_pages["switchyard"].append(page_number)

    keyword_pages = {
        key: sorted(set(value))
        for key, value in keyword_pages.items()
        if value
    }
    ocr_candidate_pages = sorted(
        {
            page_number
            for key, page_numbers in keyword_pages.items()
            if key in {"diagram", "schematic", "one_line", "single_line", "protection", "relay", "switchyard"}
            for page_number in page_numbers
        }
    )

    return {
        "heading_candidates": heading_candidates,
        "keyword_pages": keyword_pages,
        "ocr_candidate_pages": ocr_candidate_pages,
    }
