from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config import CONFIG
from services.ocr_service.models import BoundingBox, OCRTextRegion
from services.ocr_service.service import _apply_ocr_ambiguity_agent, _should_review_region


@dataclass(slots=True)
class _TestConfig:
    project_name: str = "GridSenpAI Test"
    schema_version_output: str = "1.0.0"


@dataclass(slots=True)
class _TestContext:
    run_id: str
    run_dir: Path
    config: _TestConfig = field(default_factory=_TestConfig)


def test_should_review_region_for_low_confidence_text() -> None:
    region = OCRTextRegion(
        region_id="artifact_001_p001_r001",
        page_number=1,
        text="XFMR ?",
        bbox=BoundingBox(x0=0.0, top=0.0, x1=10.0, bottom=10.0),
        confidence=0.42,
        source_method="paddleocr.predict",
    )

    assert _should_review_region(region) is True


def test_should_not_review_region_for_high_confidence_text() -> None:
    region = OCRTextRegion(
        region_id="artifact_001_p001_r002",
        page_number=1,
        text="MAIN TRANSFORMER",
        bbox=BoundingBox(x0=0.0, top=0.0, x1=10.0, bottom=10.0),
        confidence=0.93,
        source_method="paddleocr.predict",
    )

    assert _should_review_region(region) is False


def test_apply_ocr_ambiguity_agent_enriches_region_when_context_available(
    tmp_path: Path,
) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = _TestContext(
            run_id="ocr_ambiguity_agent_test",
            run_dir=tmp_path / "ocr_ambiguity_agent_test",
        )

        region = OCRTextRegion(
            region_id="artifact_001_p001_r003",
            page_number=1,
            text="UPS ?",
            bbox=BoundingBox(x0=1.0, top=2.0, x1=20.0, bottom=22.0),
            confidence=0.51,
            source_method="paddleocr.predict",
        )

        enriched = _apply_ocr_ambiguity_agent(
            context=context,
            artifact_id="artifact_001",
            route_hint="OCR_REQUIRED",
            region=region,
        )

        assert enriched.agent_id == "ocr_ambiguity_agent"
        assert enriched.agent_status == "COMPLETED"
        assert enriched.agent_audit_path is not None
        assert enriched.clarified_text == "UPS ?"
        assert "agent_policy" in enriched.metadata
        assert enriched.metadata["agent_policy"]["allowed"] is True
    finally:
        CONFIG.model.allow_model_assistance = original_flag

from services.ocr_service.utils import select_pages_for_ocr, should_process_route


def test_should_process_born_digital_diagram_pages_when_layout_requests_ocr() -> None:
    parsed_document = {"route_hint": "BORN_DIGITAL_PARSE", "structure_hints": {"ocr_candidate_pages": [2]}, "pages": [{"page_number": 2, "char_count": 42, "warnings": []}]}
    layout_document = {"pages": [{"page_number": 2, "page_classification": "DIAGRAM_PAGE", "candidate_regions": [{"region_type": "DIAGRAM_EVIDENCE_REGION"}], "warnings": []}]}
    assert should_process_route("BORN_DIGITAL_PARSE", parsed_document=parsed_document, layout_document=layout_document) is True
    assert select_pages_for_ocr(parsed_document, layout_document=layout_document) == [2]
