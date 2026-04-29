from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pdfplumber.page import Page

import pdfplumber


from services.document_parser_service.models import (
    BoundingBox,
    DocumentParserResult,
    ParsedDocument,
    ParsedPage,
    ParsedTextBlock,
)
from services.document_parser_service.utils import (
    build_block_id,
    build_repository_key,
    classify_parse_status,
    classify_route_hint,
    detect_structure_hints,
    ensure_required_artifact_fields,
    file_exists,
    get_pdfplumber_version,
    is_pdf_artifact,
    normalize_whitespace,
    safe_float,
)


PARSER_NAME = "pdfplumber"
PARSER_VERSION = get_pdfplumber_version()


def _coerce_artifacts(ingestion_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not ingestion_result:
        return []

    artifacts = ingestion_result.get("artifacts")
    if artifacts is None:
        artifacts = ingestion_result.get("artifacts_discovered", [])

    if not isinstance(artifacts, list):
        raise TypeError("ingestion_result artifacts payload must be a list.")

    return [artifact for artifact in artifacts if isinstance(artifact, dict)]


def _extract_text_blocks(
    *,
    artifact_id: str,
    page_number: int,
    page: "Page",
) -> list[ParsedTextBlock]:
    words = page.extract_words(
        x_tolerance=2,
        y_tolerance=2,
        keep_blank_chars=False,
        use_text_flow=True,
    )

    if not words:
        return []

    blocks: list[ParsedTextBlock] = []
    current_words: list[dict[str, Any]] = []
    current_top: float | None = None
    block_index = 1

    for word in words:
        top = safe_float(word.get("top"))
        if current_top is None:
            current_top = top

        same_line = abs(top - current_top) <= 6.0
        if not same_line and current_words:
            block = _flush_line_block(
                artifact_id=artifact_id,
                page_number=page_number,
                block_index=block_index,
                words=current_words,
            )
            if block is not None:
                blocks.append(block)
                block_index += 1
            current_words = []
            current_top = top

        current_words.append(word)

    if current_words:
        block = _flush_line_block(
            artifact_id=artifact_id,
            page_number=page_number,
            block_index=block_index,
            words=current_words,
        )
        if block is not None:
            blocks.append(block)

    return blocks


def _flush_line_block(
    *,
    artifact_id: str,
    page_number: int,
    block_index: int,
    words: list[dict[str, Any]],
) -> ParsedTextBlock | None:
    sorted_words = sorted(words, key=lambda item: safe_float(item.get("x0")))
    text = normalize_whitespace(" ".join(str(item.get("text", "")) for item in sorted_words))
    if not text:
        return None

    x0 = min(safe_float(item.get("x0")) for item in sorted_words)
    top = min(safe_float(item.get("top")) for item in sorted_words)
    x1 = max(safe_float(item.get("x1")) for item in sorted_words)
    bottom = max(safe_float(item.get("bottom")) for item in sorted_words)

    return ParsedTextBlock(
        block_id=build_block_id(
            artifact_id=artifact_id,
            page_number=page_number,
            block_index=block_index,
        ),
        page_number=page_number,
        block_index=block_index,
        text=text,
        bbox=BoundingBox(
            x0=x0,
            top=top,
            x1=x1,
            bottom=bottom,
        ),
        char_count=len(text),
        source_method="pdfplumber.extract_words",
        metadata={},
    )


def _parse_pdf_artifact(context: Any, artifact: dict[str, Any]) -> ParsedDocument:
    ensure_required_artifact_fields(artifact)

    artifact_id = str(artifact["artifact_id"])
    file_name = str(artifact["file_name"])
    file_path = Path(str(artifact["file_path"]))
    file_suffix = str(artifact["file_suffix"]).lower()
    repository_key = build_repository_key(
        run_id=str(context.run_id),
        artifact_id=artifact_id,
    )

    if not file_exists(file_path):
        return ParsedDocument(
            artifact_id=artifact_id,
            file_name=file_name,
            file_path=str(file_path),
            file_suffix=file_suffix,
            repository_key=repository_key,
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            parse_status="PARSE_FAILED",
            route_hint="UNREADABLE",
            page_count=0,
            pages_with_text=0,
            text_coverage_ratio=0.0,
            evidence_ready=False,
            pages=[],
            structure_hints={},
            warnings=[f"Artifact file does not exist on disk: {file_path}"],
        )

    pages: list[ParsedPage] = []
    document_warnings: list[str] = []
    lines_by_page: list[list[str]] = []
    pages_with_text = 0
    total_chars = 0

    try:
        with pdfplumber.open(str(file_path)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                raw_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                normalized_text = normalize_whitespace(raw_text)
                text_blocks = _extract_text_blocks(
                    artifact_id=artifact_id,
                    page_number=page_number,
                    page=page,
                )

                if normalized_text:
                    pages_with_text += 1
                    total_chars += len(normalized_text)

                page_warnings: list[str] = []
                if not normalized_text:
                    page_warnings.append("No extractable born-digital text found on this page.")
                if normalized_text and not text_blocks:
                    page_warnings.append("Page text was extracted, but no text blocks were recovered.")

                lines_by_page.append([line.strip() for line in raw_text.splitlines() if line.strip()])

                pages.append(
                    ParsedPage(
                        page_number=page_number,
                        width=safe_float(page.width),
                        height=safe_float(page.height),
                        extracted_text=normalized_text,
                        char_count=len(normalized_text),
                        text_blocks=text_blocks,
                        warnings=page_warnings,
                    )
                )
    except Exception as exc:
        return ParsedDocument(
            artifact_id=artifact_id,
            file_name=file_name,
            file_path=str(file_path),
            file_suffix=file_suffix,
            repository_key=repository_key,
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            parse_status="PARSE_FAILED",
            route_hint="UNREADABLE",
            page_count=0,
            pages_with_text=0,
            text_coverage_ratio=0.0,
            evidence_ready=False,
            pages=[],
            structure_hints={},
            warnings=[f"PDF parsing failed: {exc.__class__.__name__}: {exc}"],
        )

    page_count = len(pages)
    average_chars_per_text_page = total_chars / pages_with_text if pages_with_text else 0.0
    text_coverage_ratio = pages_with_text / page_count if page_count else 0.0
    structure_hints = detect_structure_hints(lines_by_page)
    route_hint = classify_route_hint(
        page_count=page_count,
        pages_with_text=pages_with_text,
        average_chars_per_text_page=average_chars_per_text_page,
        structure_hints=structure_hints,
    )
    parse_status = classify_parse_status(
        route_hint=route_hint,
        page_count=page_count,
    )
    evidence_ready = any(page.text_blocks for page in pages)

    if route_hint != "BORN_DIGITAL_PARSE":
        document_warnings.append("Document should be routed to OCR or hybrid parsing in a later stage.")

    return ParsedDocument(
        artifact_id=artifact_id,
        file_name=file_name,
        file_path=str(file_path),
        file_suffix=file_suffix,
        repository_key=repository_key,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        parse_status=parse_status,
        route_hint=route_hint,
        page_count=page_count,
        pages_with_text=pages_with_text,
        text_coverage_ratio=round(text_coverage_ratio, 4),
        evidence_ready=evidence_ready,
        pages=pages,
        structure_hints=structure_hints,
        warnings=document_warnings,
    )


def parse_documents(
    context: Any,
    ingestion_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifacts = _coerce_artifacts(ingestion_result)
    parsed_documents: list[ParsedDocument] = []
    warnings: list[str] = []

    for artifact in artifacts:
        if not is_pdf_artifact(artifact):
            continue
        parsed_documents.append(_parse_pdf_artifact(context=context, artifact=artifact))

    if not parsed_documents:
        warnings.append("No PDF artifacts were available for document parsing.")

    result = DocumentParserResult(
        run_id=str(context.run_id),
        parsed_documents=parsed_documents,
        warnings=warnings,
        status="DOCUMENTS_PARSED",
    )
    return result.to_dict()


def run_service(
    context: Any,
    ingestion_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return parse_documents(context=context, ingestion_result=ingestion_result)