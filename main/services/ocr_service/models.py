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
class OCRTextRegion:
    region_id: str
    page_number: int
    text: str
    bbox: BoundingBox
    confidence: float | None
    source_method: str
    metadata: dict[str, Any] = field(default_factory=dict)
    clarified_text: str | None = None
    clarified_label: str | None = None
    clarified_value: str | None = None
    agent_id: str | None = None
    agent_status: str | None = None
    agent_audit_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "page_number": self.page_number,
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "source_method": self.source_method,
            "metadata": dict(self.metadata),
            "clarified_text": self.clarified_text,
            "clarified_label": self.clarified_label,
            "clarified_value": self.clarified_value,
            "agent_id": self.agent_id,
            "agent_status": self.agent_status,
            "agent_audit_path": self.agent_audit_path,
        }


@dataclass(slots=True)
class OCRPageResult:
    page_number: int
    image_width: int
    image_height: int
    extracted_text: str
    char_count: int
    text_regions: list[OCRTextRegion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "extracted_text": self.extracted_text,
            "char_count": self.char_count,
            "text_regions": [region.to_dict() for region in self.text_regions],
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class OCRDocumentResult:
    artifact_id: str
    file_name: str
    file_path: str
    repository_key: str
    provider_name: str
    provider_version: str
    ocr_status: str
    route_consumed: str
    pages_requested: list[int] = field(default_factory=list)
    pages_processed: list[int] = field(default_factory=list)
    pages: list[OCRPageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "repository_key": self.repository_key,
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "ocr_status": self.ocr_status,
            "route_consumed": self.route_consumed,
            "pages_requested": list(self.pages_requested),
            "pages_processed": list(self.pages_processed),
            "pages": [page.to_dict() for page in self.pages],
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class OCRServiceResult:
    run_id: str
    provider_name: str
    provider_version: str
    provider_available: bool
    documents: list[OCRDocumentResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provider_health: dict[str, Any] = field(default_factory=dict)
    status: str = "OCR_COMPLETED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "provider_available": self.provider_available,
            "documents": [document.to_dict() for document in self.documents],
            "warnings": list(self.warnings),
            "provider_health": dict(self.provider_health),
            "status": self.status,
        }