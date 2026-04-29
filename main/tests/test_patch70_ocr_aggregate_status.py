from __future__ import annotations

from services.ocr_service.models import OCRDocumentResult
from services.ocr_service.service import _aggregate_ocr_status


def _doc(status: str, requested: bool = True, chars: int = 0) -> OCRDocumentResult:
    return OCRDocumentResult(
        artifact_id="a",
        file_name="a.pdf",
        file_path="a.pdf",
        repository_key="a",
        provider_name="PaddleOCR",
        provider_version="test",
        ocr_status=status,
        route_consumed="HYBRID_PARSE_AND_OCR",
        pages_requested=[1] if requested else [],
        pages_processed=[],
        pages=[],
        warnings=[],
    )


def test_ocr_aggregate_reports_all_targeted_failures() -> None:
    assert _aggregate_ocr_status(
        provider_available=True,
        provider_enabled=True,
        documents=[_doc("OCR_FAILED"), _doc("OCR_FAILED")],
    ) == "OCR_FAILED_ALL_DOCUMENTS"


def test_ocr_aggregate_reports_provider_unavailable_and_disabled() -> None:
    assert _aggregate_ocr_status(provider_available=False, provider_enabled=True, documents=[]) == "OCR_PROVIDER_UNAVAILABLE"
    assert _aggregate_ocr_status(provider_available=False, provider_enabled=False, documents=[]) == "OCR_DISABLED"


def test_ocr_aggregate_reports_skipped_when_no_targets() -> None:
    assert _aggregate_ocr_status(
        provider_available=True,
        provider_enabled=True,
        documents=[_doc("OCR_SKIPPED", requested=False)],
    ) == "OCR_SKIPPED_NOT_NEEDED"
