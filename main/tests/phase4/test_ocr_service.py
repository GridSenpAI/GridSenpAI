from types import SimpleNamespace

from services.ocr_service.service import run_ocr


def _build_context(run_id: str = "ocr_test_run"):
    return SimpleNamespace(run_id=run_id)


def test_ocr_returns_valid_service_result() -> None:
    context = _build_context()

    result = run_ocr(context=context, document_parser_result=None)

    assert result["run_id"] == "ocr_test_run"
    assert "provider_name" in result
    assert "provider_available" in result
    assert "documents" in result
    assert "warnings" in result
    assert "status" in result


def test_ocr_handles_empty_document_input() -> None:
    context = _build_context()

    result = run_ocr(context=context, document_parser_result={})

    assert result["documents"] == []
    assert isinstance(result["warnings"], list)


def test_ocr_skips_routes_without_ocr_requirement() -> None:
    context = _build_context()

    document_parser_result = {
        "parsed_documents": [
            {
                "artifact_id": "doc1",
                "file_name": "test.pdf",
                "file_path": "fake/path/test.pdf",
                "repository_key": "repo/test/test.pdf",
                "route_hint": "BORN_DIGITAL_PARSE",
                "pages": [],
            }
        ]
    }

    result = run_ocr(context=context, document_parser_result=document_parser_result)

    assert result["documents"] == []


def test_ocr_requests_pages_for_required_route() -> None:
    context = _build_context()

    document_parser_result = {
        "parsed_documents": [
            {
                "artifact_id": "doc2",
                "file_name": "scan.pdf",
                "file_path": "fake/path/scan.pdf",
                "repository_key": "repo/test/scan.pdf",
                "route_hint": "OCR_REQUIRED",
                "pages": [
                    {"page_number": 1},
                    {"page_number": 2},
                ],
            }
        ]
    }

    result = run_ocr(context=context, document_parser_result=document_parser_result)

    if result["documents"]:
        doc = result["documents"][0]
        assert doc["pages_requested"] == [1, 2]


def test_ocr_handles_missing_file() -> None:
    context = _build_context()

    document_parser_result = {
        "parsed_documents": [
            {
                "artifact_id": "doc3",
                "file_name": "missing.pdf",
                "file_path": "missing/file/path.pdf",
                "repository_key": "repo/test/missing.pdf",
                "route_hint": "OCR_REQUIRED",
                "pages": [{"page_number": 1}],
            }
        ]
    }

    result = run_ocr(context=context, document_parser_result=document_parser_result)

    if result["documents"]:
        doc = result["documents"][0]
        assert doc["ocr_status"] in {"OCR_FAILED", "OCR_PARTIAL", "OCR_COMPLETED"}



def test_ocr_uses_layout_targets_to_limit_requested_pages() -> None:
    context = _build_context()

    document_parser_result = {
        "parsed_documents": [
            {
                "artifact_id": "doc4",
                "file_name": "scan.pdf",
                "file_path": "fake/path/scan.pdf",
                "repository_key": "repo/test/scan.pdf",
                "route_hint": "OCR_REQUIRED",
                "pages": [
                    {"page_number": 1},
                    {"page_number": 2},
                    {"page_number": 3},
                ],
            }
        ]
    }

    layout_analysis_result = {
        "documents": [
            {
                "artifact_id": "doc4",
                "pages": [
                    {
                        "page_number": 2,
                        "candidate_regions": [
                            {
                                "region_id": "doc4_p0002_ocr_target",
                                "region_type": "OCR_TARGET_REGION",
                            }
                        ],
                        "warnings": [],
                    }
                ],
            }
        ]
    }

    result = run_ocr(
        context=context,
        document_parser_result=document_parser_result,
        layout_analysis_result=layout_analysis_result,
    )

    if result["documents"]:
        doc = result["documents"][0]
        assert doc["pages_requested"] == [2]

def test_create_provider_passes_explicit_paddleocr_model_names(monkeypatch) -> None:
    from services.ocr_service import service as ocr_service_module

    captured: dict[str, object] = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class FakeModule:
        PaddleOCR = FakePaddleOCR

    def fake_import_optional(module_name: str):
        if module_name == "paddleocr":
            return FakeModule, None
        if module_name == "paddle":
            return object(), None
        if module_name == "pypdfium2":
            return object(), None
        return None, f"unexpected module: {module_name}"

    monkeypatch.setattr(ocr_service_module, "import_optional", fake_import_optional)

    context = SimpleNamespace(
        config=SimpleNamespace(
            ocr_lang="en",
            ocr_text_detection_model_name="PP-OCRv5_server_det",
            ocr_text_recognition_model_name="PP-OCRv5_server_rec",
        )
    )

    provider, warnings, provider_health = ocr_service_module._create_provider(context)

    assert provider is not None
    assert warnings == []
    assert captured["text_detection_model_name"] == "PP-OCRv5_server_det"
    assert captured["text_recognition_model_name"] == "PP-OCRv5_server_rec"
    assert provider_health["configured_models"]["text_detection_model_name"] == "PP-OCRv5_server_det"
    assert provider_health["configured_models"]["text_recognition_model_name"] == "PP-OCRv5_server_rec"


def test_ocr_disabled_skips_provider_initialization(monkeypatch) -> None:
    from services.ocr_service import service as ocr_service_module

    def fail_create_provider(context):
        raise AssertionError("OCR provider should not initialize when OCR is disabled.")

    monkeypatch.setattr(ocr_service_module, "_create_provider", fail_create_provider)

    context = SimpleNamespace(
        run_id="ocr_disabled_test",
        config=SimpleNamespace(ocr_enabled=False),
    )

    result = run_ocr(
        context=context,
        document_parser_result={
            "parsed_documents": [
                {
                    "artifact_id": "doc_disabled",
                    "file_name": "scan.pdf",
                    "file_path": "fake/path/scan.pdf",
                    "repository_key": "repo/test/scan.pdf",
                    "route_hint": "OCR_REQUIRED",
                    "pages": [{"page_number": 1}],
                }
            ]
        },
    )

    assert result["run_id"] == "ocr_disabled_test"
    assert result["status"] == "OCR_DISABLED"
    assert result["provider_available"] is False
    assert result["documents"] == []
    assert result["provider_health"]["ocr_runtime_enabled"] is False
    assert result["provider_health"]["provider_initialized"] is False
