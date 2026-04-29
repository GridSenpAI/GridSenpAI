from types import SimpleNamespace

import pytest

from services.document_parser_service.service import parse_documents


def _build_context(run_id: str = "parser_test_run"):
    return SimpleNamespace(run_id=run_id)


def test_parser_returns_valid_result_structure():
    context = _build_context()

    result = parse_documents(context=context, ingestion_result=None)

    assert result["run_id"] == "parser_test_run"
    assert "parsed_documents" in result
    assert "warnings" in result
    assert "status" in result


def test_parser_handles_no_artifacts():
    context = _build_context()

    ingestion_result = {
        "artifacts": []
    }

    result = parse_documents(context=context, ingestion_result=ingestion_result)

    assert result["parsed_documents"] == []
    assert result["warnings"]
    assert result["status"] == "DOCUMENTS_PARSED"


def test_parser_skips_non_pdf_artifacts():
    context = _build_context()

    ingestion_result = {
        "artifacts": [
            {
                "artifact_id": "doc1",
                "file_name": "file.txt",
                "file_path": "fake/file.txt",
                "file_suffix": ".txt",
            }
        ]
    }

    result = parse_documents(context=context, ingestion_result=ingestion_result)

    assert result["parsed_documents"] == []


def test_parser_requires_artifact_fields():
    context = _build_context()

    ingestion_result = {
        "artifacts": [
            {
                "artifact_id": "doc1",
                "file_name": "file.pdf",
            }
        ]
    }

    with pytest.raises(KeyError):
        parse_documents(context=context, ingestion_result=ingestion_result)


def test_parser_handles_missing_file():
    context = _build_context()

    ingestion_result = {
        "artifacts": [
            {
                "artifact_id": "doc2",
                "file_name": "missing.pdf",
                "file_path": "missing/file/path.pdf",
                "file_suffix": ".pdf",
            }
        ]
    }

    result = parse_documents(context=context, ingestion_result=ingestion_result)

    assert len(result["parsed_documents"]) == 1

    parsed_doc = result["parsed_documents"][0]

    assert parsed_doc["parse_status"] == "PARSE_FAILED"
    assert parsed_doc["route_hint"] == "UNREADABLE"
    assert parsed_doc["page_count"] == 0