from __future__ import annotations

from typing import Any

from services.layout_analysis_service.models import (
    BoundingBox,
    CandidateRegion,
    DocumentLayoutResult,
    LayoutAnalysisResult,
    PageLayoutResult,
)
from services.layout_analysis_service.utils import (
    OCR_HEAVY_TERMS,
    TITLE_BLOCK_TERMS,
    bbox_union,
    build_region_id,
    classify_page,
    document_classification_from_pages,
    extraction_profiles_for_classification,
    merge_extraction_profiles,
    normalize_whitespace,
    tokenize,
)


def _coerce_documents(document_parser_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not document_parser_result:
        return []

    documents = document_parser_result.get("parsed_documents", [])
    if not isinstance(documents, list):
        raise TypeError("document_parser_result.parsed_documents must be a list.")

    return [document for document in documents if isinstance(document, dict)]


def _build_full_page_region(
    *,
    artifact_id: str,
    page_number: int,
    page_width: float,
    page_height: float,
    region_index: int,
    region_type: str,
    confidence: float,
    source_method: str,
    supporting_terms: list[str],
    metadata: dict[str, Any] | None = None,
) -> CandidateRegion:
    return CandidateRegion(
        region_id=build_region_id(
            artifact_id=artifact_id,
            page_number=page_number,
            region_index=region_index,
        ),
        page_number=page_number,
        region_type=region_type,
        bbox=BoundingBox(
            x0=0.0,
            top=0.0,
            x1=page_width,
            bottom=page_height,
        ),
        confidence=round(confidence, 4),
        source_method=source_method,
        supporting_terms=supporting_terms,
        metadata=metadata or {},
    )


def _build_title_block_region(
    *,
    artifact_id: str,
    page_number: int,
    page_width: float,
    page_height: float,
    text_blocks: list[dict[str, Any]],
    region_index: int,
    supporting_terms: list[str],
) -> CandidateRegion | None:
    candidate_boxes: list[dict[str, Any]] = []

    for block in text_blocks:
        text = normalize_whitespace(str(block.get("text", ""))).lower()
        tokens = tokenize(text)
        if any(token in TITLE_BLOCK_TERMS for token in tokens):
            bbox = block.get("bbox")
            if isinstance(bbox, dict):
                candidate_boxes.append(bbox)

    if not candidate_boxes:
        return None

    union = bbox_union(candidate_boxes)
    expanded_bottom = min(max(union["bottom"], page_height * 0.92), page_height)
    expanded_top = max(min(union["top"], page_height * 0.75), page_height * 0.72)

    return CandidateRegion(
        region_id=build_region_id(
            artifact_id=artifact_id,
            page_number=page_number,
            region_index=region_index,
        ),
        page_number=page_number,
        region_type="TITLE_BLOCK_REGION",
        bbox=BoundingBox(
            x0=0.0,
            top=expanded_top,
            x1=page_width,
            bottom=expanded_bottom,
        ),
        confidence=0.72,
        source_method="layout.keyword_region",
        supporting_terms=supporting_terms,
        metadata={"target_use": "title_block_metadata"},
    )


def _build_sparse_text_ocr_regions(
    *,
    artifact_id: str,
    page_number: int,
    page_width: float,
    page_height: float,
    page_text: str,
    route_hint: str,
    region_index_start: int,
) -> list[CandidateRegion]:
    regions: list[CandidateRegion] = []

    tokens = tokenize(page_text)
    matched_terms = sorted({token for token in tokens if token in OCR_HEAVY_TERMS})

    if route_hint in {"OCR_REQUIRED", "HYBRID_PARSE_AND_OCR"}:
        regions.append(
            _build_full_page_region(
                artifact_id=artifact_id,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                region_index=region_index_start,
                region_type="OCR_TARGET_REGION",
                confidence=0.85 if route_hint == "OCR_REQUIRED" else 0.68,
                source_method="layout.route_hint",
                supporting_terms=matched_terms,
                metadata={"ocr_mode": "page_level"},
            )
        )

    return regions


def _build_diagram_candidate_region(
    *,
    artifact_id: str,
    page_number: int,
    page_width: float,
    page_height: float,
    text_blocks: list[dict[str, Any]],
    supporting_terms: list[str],
    region_index: int,
) -> CandidateRegion:
    block_boxes: list[dict[str, Any]] = []
    for block in text_blocks:
        bbox = block.get("bbox")
        if isinstance(bbox, dict):
            block_boxes.append(bbox)

    if block_boxes:
        union = bbox_union(block_boxes)
        x0 = max(union["x0"] - 24.0, 0.0)
        top = max(union["top"] - 24.0, 0.0)
        x1 = min(union["x1"] + 24.0, page_width)
        bottom = min(union["bottom"] + 24.0, page_height)
    else:
        x0 = 0.0
        top = 0.0
        x1 = page_width
        bottom = page_height

    return CandidateRegion(
        region_id=build_region_id(
            artifact_id=artifact_id,
            page_number=page_number,
            region_index=region_index,
        ),
        page_number=page_number,
        region_type="DIAGRAM_EVIDENCE_REGION",
        bbox=BoundingBox(
            x0=x0,
            top=top,
            x1=x1,
            bottom=bottom,
        ),
        confidence=0.7,
        source_method="layout.text_block_union",
        supporting_terms=supporting_terms,
        metadata={"target_use": "diagram_evidence"},
    )


def _build_table_candidate_region(
    *,
    artifact_id: str,
    page_number: int,
    page_width: float,
    page_height: float,
    text_blocks: list[dict[str, Any]],
    supporting_terms: list[str],
    region_index: int,
) -> CandidateRegion:
    if text_blocks:
        union = bbox_union([block["bbox"] for block in text_blocks if isinstance(block.get("bbox"), dict)])
        x0 = max(union["x0"] - 12.0, 0.0)
        top = max(union["top"] - 12.0, 0.0)
        x1 = min(union["x1"] + 12.0, page_width)
        bottom = min(union["bottom"] + 12.0, page_height)
    else:
        x0 = 0.0
        top = 0.0
        x1 = page_width
        bottom = page_height

    return CandidateRegion(
        region_id=build_region_id(
            artifact_id=artifact_id,
            page_number=page_number,
            region_index=region_index,
        ),
        page_number=page_number,
        region_type="TABLE_EVIDENCE_REGION",
        bbox=BoundingBox(
            x0=x0,
            top=top,
            x1=x1,
            bottom=bottom,
        ),
        confidence=0.7,
        source_method="layout.text_block_union",
        supporting_terms=supporting_terms,
        metadata={"target_use": "table_evidence"},
    )


def _analyze_page(
    *,
    artifact_id: str,
    route_hint: str,
    page: dict[str, Any],
) -> PageLayoutResult:
    page_number = int(page.get("page_number", 0))
    page_width = float(page.get("width", 0.0))
    page_height = float(page.get("height", 0.0))
    page_text = normalize_whitespace(str(page.get("extracted_text", "")))
    text_blocks = page.get("text_blocks", [])
    if not isinstance(text_blocks, list):
        text_blocks = []

    page_classification, confidence, term_matches = classify_page(
        page_text=page_text,
        route_hint=route_hint,
        block_count=len(text_blocks),
    )
    extraction_profiles = extraction_profiles_for_classification(
        classification=page_classification,
        route_hint=route_hint,
    )

    candidate_regions: list[CandidateRegion] = []
    region_index = 1

    if page_classification in {"NARRATIVE_PAGE", "MIXED_PAGE"}:
        candidate_regions.append(
            _build_full_page_region(
                artifact_id=artifact_id,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                region_index=region_index,
                region_type="TEXT_EVIDENCE_REGION",
                confidence=max(confidence, 0.55),
                source_method="layout.page_classification",
                supporting_terms=term_matches["narrative_terms"],
                metadata={"target_use": "narrative_evidence"},
            )
        )
        region_index += 1

    if page_classification in {"TABLE_PAGE", "MIXED_PAGE"}:
        candidate_regions.append(
            _build_table_candidate_region(
                artifact_id=artifact_id,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                text_blocks=text_blocks,
                supporting_terms=term_matches["table_terms"],
                region_index=region_index,
            )
        )
        region_index += 1

    if page_classification in {"DIAGRAM_PAGE", "MIXED_PAGE"}:
        candidate_regions.append(
            _build_diagram_candidate_region(
                artifact_id=artifact_id,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                text_blocks=text_blocks,
                supporting_terms=term_matches["diagram_terms"],
                region_index=region_index,
            )
        )
        region_index += 1

    title_block_region = _build_title_block_region(
        artifact_id=artifact_id,
        page_number=page_number,
        page_width=page_width,
        page_height=page_height,
        text_blocks=text_blocks,
        region_index=region_index,
        supporting_terms=term_matches["title_block_terms"],
    )
    if title_block_region is not None:
        candidate_regions.append(title_block_region)
        region_index += 1

    candidate_regions.extend(
        _build_sparse_text_ocr_regions(
            artifact_id=artifact_id,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            page_text=page_text,
            route_hint=route_hint,
            region_index_start=region_index,
        )
    )

    warnings: list[str] = []
    if not page_text and route_hint != "BORN_DIGITAL_PARSE":
        warnings.append("Page has no born-digital text and remains a candidate for targeted OCR.")

    return PageLayoutResult(
        page_number=page_number,
        page_classification=page_classification,
        confidence=confidence,
        candidate_regions=candidate_regions,
        extraction_profiles=extraction_profiles,
        warnings=warnings,
    )


def _analyze_document(parsed_document: dict[str, Any]) -> DocumentLayoutResult:
    artifact_id = str(parsed_document.get("artifact_id", ""))
    file_name = str(parsed_document.get("file_name", ""))
    repository_key = str(parsed_document.get("repository_key", ""))
    route_hint = str(parsed_document.get("route_hint", ""))
    pages = parsed_document.get("pages", [])
    if not isinstance(pages, list):
        pages = []

    page_results: list[PageLayoutResult] = []
    page_classifications: list[str] = []
    page_profiles: list[list[str]] = []

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_result = _analyze_page(
            artifact_id=artifact_id,
            route_hint=route_hint,
            page=page,
        )
        page_results.append(page_result)
        page_classifications.append(page_result.page_classification)
        page_profiles.append(page_result.extraction_profiles)

    document_classification, confidence = document_classification_from_pages(page_classifications)
    extraction_profiles = merge_extraction_profiles(page_profiles)

    warnings: list[str] = []
    if not page_results:
        warnings.append("No page payloads were available for layout analysis.")

    return DocumentLayoutResult(
        artifact_id=artifact_id,
        file_name=file_name,
        repository_key=repository_key,
        route_hint=route_hint,
        document_classification=document_classification,
        confidence=confidence,
        pages=page_results,
        extraction_profiles=extraction_profiles,
        warnings=warnings,
    )


def run_layout_analysis(
    context: Any,
    document_parser_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_documents = _coerce_documents(document_parser_result)
    documents: list[DocumentLayoutResult] = []
    warnings: list[str] = []

    for parsed_document in parsed_documents:
        documents.append(_analyze_document(parsed_document))

    if not documents:
        warnings.append("No parsed documents were provided to the layout analysis service.")

    result = LayoutAnalysisResult(
        run_id=str(getattr(context, "run_id", "")),
        documents=documents,
        warnings=warnings,
        status="LAYOUT_ANALYZED",
    )
    return result.to_dict()


def run_service(
    context: Any,
    document_parser_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_layout_analysis(
        context=context,
        document_parser_result=document_parser_result,
    )