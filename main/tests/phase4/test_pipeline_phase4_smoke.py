from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from services.document_parser_service.service import parse_documents
from services.layout_analysis_service.service import run_layout_analysis
from services.ocr_service.service import run_ocr


def _build_context(run_id: str = "phase4_smoke_test"):
    config = SimpleNamespace(
        ocr_lang="en",
        ocr_render_scale=2.0,
    )
    return SimpleNamespace(
        run_id=run_id,
        config=config,
        run_dir=None,
    )


def _create_blank_pdf(pdf_path: Path) -> None:
    image = Image.new("RGB", (200, 200), "white")
    image.save(pdf_path, "PDF")


@pytest.mark.phase4
def test_pipeline_phase4_smoke(tmp_path: Path) -> None:
    context = _build_context()

    pdf_path = tmp_path / "blank_engineering_doc.pdf"
    _create_blank_pdf(pdf_path)

    ingestion_result = {
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "file_name": pdf_path.name,
                "file_path": str(pdf_path),
                "file_suffix": ".pdf",
            }
        ]
    }

    document_parser_result = parse_documents(
        context=context,
        ingestion_result=ingestion_result,
    )

    assert document_parser_result["status"] == "DOCUMENTS_PARSED"
    assert len(document_parser_result["parsed_documents"]) == 1

    parsed_document = document_parser_result["parsed_documents"][0]
    assert parsed_document["artifact_id"] == "artifact_001"
    assert parsed_document["page_count"] == 1
    assert parsed_document["route_hint"] in {
        "BORN_DIGITAL_PARSE",
        "HYBRID_PARSE_AND_OCR",
        "OCR_REQUIRED",
        "UNREADABLE",
    }

    layout_analysis_result = run_layout_analysis(
        context=context,
        document_parser_result=document_parser_result,
    )

    assert layout_analysis_result["status"] == "LAYOUT_ANALYZED"
    assert len(layout_analysis_result["documents"]) == 1

    layout_document = layout_analysis_result["documents"][0]
    assert layout_document["artifact_id"] == "artifact_001"
    assert len(layout_document["pages"]) == 1

    layout_page = layout_document["pages"][0]
    assert "page_classification" in layout_page
    assert "candidate_regions" in layout_page

    if parsed_document["route_hint"] in {"OCR_REQUIRED", "HYBRID_PARSE_AND_OCR"}:
        region_types = {
            region["region_type"]
            for region in layout_page["candidate_regions"]
        }
        assert "OCR_TARGET_REGION" in region_types

    ocr_result = run_ocr(
        context=context,
        document_parser_result=document_parser_result,
    )

    assert ocr_result["run_id"] == "phase4_smoke_test"
    assert "provider_name" in ocr_result
    assert "provider_available" in ocr_result
    assert "documents" in ocr_result
    assert "warnings" in ocr_result
    assert "status" in ocr_result

    if parsed_document["route_hint"] in {"OCR_REQUIRED", "HYBRID_PARSE_AND_OCR"}:
        if ocr_result["provider_available"]:
            assert len(ocr_result["documents"]) == 1
            ocr_document = ocr_result["documents"][0]
            assert ocr_document["artifact_id"] == "artifact_001"
            assert ocr_document["route_consumed"] == parsed_document["route_hint"]
            assert ocr_document["ocr_status"] in {
                "OCR_COMPLETED",
                "OCR_PARTIAL",
                "OCR_FAILED",
                "OCR_SKIPPED",
            }
        else:
            assert ocr_result["status"] == "OCR_DISABLED"
            assert ocr_result["warnings"]
    else:
        assert ocr_result["documents"] == []