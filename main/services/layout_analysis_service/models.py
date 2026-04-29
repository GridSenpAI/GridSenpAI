from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BoundingBox:
    x0: float
    top: float
    x1: float
    bottom: float

    def to_dict(self) -> dict[str, float]:
        return {
            "x0": self.x0,
            "top": self.top,
            "x1": self.x1,
            "bottom": self.bottom,
        }


@dataclass(slots=True)
class CandidateRegion:
    region_id: str
    page_number: int
    region_type: str
    bbox: BoundingBox
    confidence: float
    source_method: str
    supporting_terms: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "page_number": self.page_number,
            "region_type": self.region_type,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "source_method": self.source_method,
            "supporting_terms": list(self.supporting_terms),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class PageLayoutResult:
    page_number: int
    page_classification: str
    confidence: float
    candidate_regions: list[CandidateRegion] = field(default_factory=list)
    extraction_profiles: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "page_classification": self.page_classification,
            "confidence": self.confidence,
            "candidate_regions": [region.to_dict() for region in self.candidate_regions],
            "extraction_profiles": list(self.extraction_profiles),
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class DocumentLayoutResult:
    artifact_id: str
    file_name: str
    repository_key: str
    route_hint: str
    document_classification: str
    confidence: float
    pages: list[PageLayoutResult] = field(default_factory=list)
    extraction_profiles: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "file_name": self.file_name,
            "repository_key": self.repository_key,
            "route_hint": self.route_hint,
            "document_classification": self.document_classification,
            "confidence": self.confidence,
            "pages": [page.to_dict() for page in self.pages],
            "extraction_profiles": list(self.extraction_profiles),
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class LayoutAnalysisResult:
    run_id: str
    documents: list[DocumentLayoutResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "LAYOUT_ANALYZED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "documents": [document.to_dict() for document in self.documents],
            "warnings": list(self.warnings),
            "status": self.status,
        }