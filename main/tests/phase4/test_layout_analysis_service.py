from types import SimpleNamespace

from services.layout_analysis_service.service import run_layout_analysis


def _build_context(run_id: str = "layout_test_run"):
    return SimpleNamespace(run_id=run_id)


def test_layout_analysis_returns_layout_analyzed_status() -> None:
    context = _build_context()

    result = run_layout_analysis(context=context, document_parser_result=None)

    assert result["status"] == "LAYOUT_ANALYZED"


def test_layout_analysis_handles_empty_input() -> None:
    context = _build_context()

    result = run_layout_analysis(context=context, document_parser_result={})

    assert result["documents"] == []
    assert "warnings" in result


def test_layout_analysis_classifies_document() -> None:
    context = _build_context()

    document_parser_result = {
        "parsed_documents": [
            {
                "artifact_id": "doc1",
                "file_name": "sample.pdf",
                "repository_key": "repo/test/sample.pdf",
                "route_hint": "BORN_DIGITAL_PARSE",
                "pages": [
                    {
                        "page_number": 1,
                        "width": 1000,
                        "height": 1000,
                        "extracted_text": "facility interconnection study report summary",
                        "text_blocks": [],
                    }
                ],
            }
        ]
    }

    result = run_layout_analysis(context=context, document_parser_result=document_parser_result)

    assert len(result["documents"]) == 1

    document = result["documents"][0]

    assert document["artifact_id"] == "doc1"
    assert document["document_classification"] in {
        "NARRATIVE_DOCUMENT",
        "TABLE_DOCUMENT",
        "DIAGRAM_DOCUMENT",
        "MIXED_DOCUMENT",
        "UNCLASSIFIED_DOCUMENT",
    }


def test_layout_analysis_generates_page_results() -> None:
    context = _build_context()

    document_parser_result = {
        "parsed_documents": [
            {
                "artifact_id": "doc2",
                "file_name": "diagram.pdf",
                "repository_key": "repo/test/diagram.pdf",
                "route_hint": "HYBRID_PARSE_AND_OCR",
                "pages": [
                    {
                        "page_number": 1,
                        "width": 800,
                        "height": 600,
                        "extracted_text": "one-line substation diagram relay protection",
                        "text_blocks": [],
                    }
                ],
            }
        ]
    }

    result = run_layout_analysis(context=context, document_parser_result=document_parser_result)

    document = result["documents"][0]

    assert len(document["pages"]) == 1

    page = document["pages"][0]

    assert "page_number" in page
    assert "page_classification" in page
    assert "candidate_regions" in page


def test_layout_analysis_creates_candidate_regions() -> None:
    context = _build_context()

    document_parser_result = {
        "parsed_documents": [
            {
                "artifact_id": "doc3",
                "file_name": "table.pdf",
                "repository_key": "repo/test/table.pdf",
                "route_hint": "BORN_DIGITAL_PARSE",
                "pages": [
                    {
                        "page_number": 1,
                        "width": 800,
                        "height": 600,
                        "extracted_text": "equipment schedule transformer generator rating mva kv",
                        "text_blocks": [
                            {
                                "text": "equipment schedule transformer rating",
                                "bbox": {"x0": 10, "top": 10, "x1": 400, "bottom": 200},
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result = run_layout_analysis(context=context, document_parser_result=document_parser_result)

    page = result["documents"][0]["pages"][0]

    assert isinstance(page["candidate_regions"], list)