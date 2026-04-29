from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class BoundingBox:
    x0: float
    top: float
    x1: float
    bottom: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(slots=True)
class ParsedTextBlock:
    block_id: str
    page_number: int
    block_index: int
    text: str
    bbox: BoundingBox
    char_count: int
    source_method: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "page_number": self.page_number,
            "block_index": self.block_index,
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "char_count": self.char_count,
            "source_method": self.source_method,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ParsedPage:
    page_number: int
    width: float
    height: float
    extracted_text: str
    char_count: int
    text_blocks: list[ParsedTextBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "extracted_text": self.extracted_text,
            "char_count": self.char_count,
            "text_blocks": [block.to_dict() for block in self.text_blocks],
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class ParsedDocument:
    artifact_id: str
    file_name: str
    file_path: str
    file_suffix: str
    repository_key: str
    parser_name: str
    parser_version: str
    parse_status: str
    route_hint: str
    page_count: int
    pages_with_text: int
    text_coverage_ratio: float
    evidence_ready: bool
    pages: list[ParsedPage] = field(default_factory=list)
    structure_hints: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_suffix": self.file_suffix,
            "repository_key": self.repository_key,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "parse_status": self.parse_status,
            "route_hint": self.route_hint,
            "page_count": self.page_count,
            "pages_with_text": self.pages_with_text,
            "text_coverage_ratio": self.text_coverage_ratio,
            "evidence_ready": self.evidence_ready,
            "pages": [page.to_dict() for page in self.pages],
            "structure_hints": dict(self.structure_hints),
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class DocumentParserResult:
    run_id: str
    parsed_documents: list[ParsedDocument] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "DOCUMENTS_PARSED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "parsed_documents": [document.to_dict() for document in self.parsed_documents],
            "warnings": list(self.warnings),
            "status": self.status,
        }