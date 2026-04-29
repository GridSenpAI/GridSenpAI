from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent
from services.ocr_service.models import (
    BoundingBox,
    OCRDocumentResult,
    OCRPageResult,
    OCRServiceResult,
    OCRTextRegion,
)
from services.ocr_service.utils import (
    build_region_id,
    file_exists,
    get_distribution_version,
    get_ocr_lang,
    get_ocr_text_detection_model_name,
    get_ocr_text_recognition_model_name,
    get_render_scale,
    import_optional,
    is_ocr_runtime_enabled,
    normalize_whitespace,
    safe_float,
    safe_int,
    select_pages_for_ocr,
    should_process_route,
)


PROVIDER_NAME = "PaddleOCR"
OCR_AGENT_CONFIDENCE_THRESHOLD = 0.70
OCR_AGENT_MIN_TEXT_LENGTH = 2


def _coerce_documents(document_parser_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not document_parser_result:
        return []

    documents = document_parser_result.get("parsed_documents", [])
    if not isinstance(documents, list):
        raise TypeError("document_parser_result.parsed_documents must be a list.")

    return [document for document in documents if isinstance(document, dict)]


def _coerce_layout_documents(
    layout_analysis_result: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not layout_analysis_result:
        return {}

    documents = layout_analysis_result.get("documents", [])
    if not isinstance(documents, list):
        raise TypeError("layout_analysis_result.documents must be a list.")

    return {
        str(document.get("artifact_id", "")).strip(): document
        for document in documents
        if isinstance(document, dict) and str(document.get("artifact_id", "")).strip()
    }


def _select_pages_for_document_ocr(
    *,
    parsed_document: dict[str, Any],
    layout_document: dict[str, Any] | None,
) -> list[int]:
    base_selected = select_pages_for_ocr(parsed_document, layout_document=layout_document)

    if not isinstance(layout_document, dict):
        return base_selected

    layout_selected: list[int] = []
    pages = layout_document.get("pages", [])
    if not isinstance(pages, list):
        pages = []

    for page in pages:
        if not isinstance(page, dict):
            continue

        page_number = safe_int(page.get("page_number"))
        if page_number <= 0:
            continue

        candidate_regions = page.get("candidate_regions", [])
        if not isinstance(candidate_regions, list):
            candidate_regions = []

        page_warnings = page.get("warnings", [])
        if not isinstance(page_warnings, list):
            page_warnings = []

        has_explicit_ocr_target = any(
            isinstance(region, dict) and str(region.get("region_type", "")).strip() == "OCR_TARGET_REGION"
            for region in candidate_regions
        )

        warning_requests_ocr = any(
            "targeted ocr" in str(warning).lower()
            for warning in page_warnings
        )

        if has_explicit_ocr_target or warning_requests_ocr:
            layout_selected.append(page_number)

    deduped_layout_selected = sorted(set(layout_selected))

    if base_selected and deduped_layout_selected:
        intersected = sorted(set(base_selected).intersection(deduped_layout_selected))
        return intersected or deduped_layout_selected

    if deduped_layout_selected:
        return deduped_layout_selected

    return base_selected


def _optional_run_dir(context: Any) -> Path | None:
    run_dir = getattr(context, "run_dir", None)
    if run_dir is None:
        return None

    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _create_provider(context: Any) -> tuple[Any | None, list[str], dict[str, Any]]:
    warnings: list[str] = []
    provider_health: dict[str, Any] = {
        "paddleocr_module": {"available": False, "version": get_distribution_version("paddleocr")},
        "paddle_module": {"available": False, "version": get_distribution_version("paddlepaddle")},
        "pypdfium2_module": {"available": False, "version": get_distribution_version("pypdfium2")},
    }

    paddleocr_module, paddleocr_error = import_optional("paddleocr")
    if paddleocr_module is None:
        warnings.append(paddleocr_error or "paddleocr is not installed. OCR execution is unavailable.")
        provider_health["paddleocr_module"]["error"] = paddleocr_error
        return None, warnings, provider_health
    provider_health["paddleocr_module"]["available"] = True

    _, paddlepaddle_error = import_optional("paddle")
    if paddlepaddle_error is not None:
        warnings.append("paddle module is not importable. Install PaddlePaddle before running OCR.")
        provider_health["paddle_module"]["error"] = paddlepaddle_error
        return None, warnings, provider_health
    provider_health["paddle_module"]["available"] = True

    _, pdfium_error = import_optional("pypdfium2")
    if pdfium_error is None:
        provider_health["pypdfium2_module"]["available"] = True
    else:
        provider_health["pypdfium2_module"]["error"] = pdfium_error

    text_detection_model_name = get_ocr_text_detection_model_name(context)
    text_recognition_model_name = get_ocr_text_recognition_model_name(context)

    provider_health["configured_models"] = {
        "lang": get_ocr_lang(context),
        "text_detection_model_name": text_detection_model_name,
        "text_recognition_model_name": text_recognition_model_name,
    }

    try:
        provider = paddleocr_module.PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang=get_ocr_lang(context),
            text_detection_model_name=text_detection_model_name,
            text_recognition_model_name=text_recognition_model_name,
        )
    except Exception as exc:
        message = f"Failed to initialize PaddleOCR provider: {exc.__class__.__name__}: {exc}"
        warnings.append(message)
        provider_health["provider_initialization_error"] = message
        return None, warnings, provider_health

    provider_health["provider_initialized"] = True
    return provider, warnings, provider_health

def _render_page_image(
    *,
    pdf_path: Path,
    page_number: int,
    render_scale: float,
) -> tuple[Any | None, list[str]]:
    warnings: list[str] = []

    pdfium_module, pdfium_error = import_optional("pypdfium2")
    if pdfium_module is None:
        warnings.append(
            pdfium_error
            or "pypdfium2 is not installed. PDF page rasterization is unavailable."
        )
        return None, warnings

    try:
        document = pdfium_module.PdfDocument(str(pdf_path))
        if page_number < 1 or page_number > len(document):
            warnings.append(
                f"Requested page {page_number} is outside the PDF page range."
            )
            return None, warnings

        page = document[page_number - 1]
        bitmap = page.render(scale=render_scale)
        image = bitmap.to_pil()
        page.close()
        document.close()
        return image, warnings
    except Exception as exc:
        warnings.append(
            f"PDF rasterization failed for page {page_number}: "
            f"{exc.__class__.__name__}: {exc}"
        )
        return None, warnings


def _persist_temp_image(
    *,
    context: Any,
    artifact_id: str,
    page_number: int,
    image: Any,
) -> Path:
    run_dir = _optional_run_dir(context)
    if run_dir is None:
        temp_dir = Path.cwd() / ".gridsenpai_ocr_tmp"
    else:
        temp_dir = run_dir / "ocr" / "temp_images"

    temp_dir.mkdir(parents=True, exist_ok=True)
    image_path = temp_dir / f"{artifact_id}_page_{page_number:04d}.png"
    image.save(image_path)
    return image_path


def _prediction_shape_summary(value: Any) -> dict[str, Any]:
    """Return low-cardinality diagnostics for PaddleOCR result shapes."""
    summary: dict[str, Any] = {"type": type(value).__name__}
    if isinstance(value, dict):
        summary["keys"] = sorted(str(key) for key in value.keys())[:30]
        return summary
    attrs: list[str] = []
    for attr in ("res", "json", "to_json", "to_dict", "boxes", "texts", "scores", "rec_texts", "rec_scores", "rec_boxes", "dt_polys"):
        if hasattr(value, attr):
            attrs.append(attr)
    if attrs:
        summary["attributes"] = attrs
    return summary


def _call_payload_adapter(adapter: Any) -> Any:
    if callable(adapter):
        try:
            return adapter()
        except TypeError:
            return adapter
    return adapter


def _coerce_prediction_payload(prediction: Any) -> dict[str, Any]:
    """Coerce PaddleOCR 2.x/3.x prediction objects into a plain payload dict."""
    if isinstance(prediction, dict):
        payload: Any = prediction
    else:
        payload = None
        for attr in ("res", "json", "to_json", "to_dict"):
            if hasattr(prediction, attr):
                payload = _call_payload_adapter(getattr(prediction, attr))
                break

        if isinstance(payload, str):
            try:
                import json
                payload = json.loads(payload)
            except Exception:
                payload = None

        if isinstance(payload, dict) and "res" in payload and isinstance(payload["res"], dict):
            payload = payload["res"]

        if not isinstance(payload, dict):
            payload = {}
            for attr in ("rec_texts", "rec_scores", "rec_boxes", "dt_polys", "boxes", "texts", "scores"):
                attr_value = getattr(prediction, attr, None)
                if attr_value is not None:
                    payload[attr] = attr_value

    if not isinstance(payload, dict):
        return {}

    if "rec_texts" not in payload and "texts" in payload:
        payload["rec_texts"] = payload.get("texts")
    if "rec_scores" not in payload and "scores" in payload:
        payload["rec_scores"] = payload.get("scores")
    if "rec_boxes" not in payload:
        for key in ("boxes", "det_boxes", "dt_boxes"):
            if key in payload:
                payload["rec_boxes"] = payload.get(key)
                break
        if "rec_boxes" not in payload and "dt_polys" in payload:
            payload["rec_boxes"] = payload.get("dt_polys")

    return payload


def _coerce_prediction_payloads(predictions: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    diagnostics: dict[str, Any] = {"prediction_shape": _prediction_shape_summary(predictions)}
    raw_predictions: list[Any] = []

    if predictions is None:
        diagnostics["prediction_count"] = 0
        return [], diagnostics

    if isinstance(predictions, dict):
        raw_predictions = [predictions]
    elif isinstance(predictions, (str, bytes)):
        raw_predictions = [predictions]
    elif isinstance(predictions, Iterable):
        try:
            raw_predictions = list(predictions)
        except TypeError:
            raw_predictions = [predictions]
    else:
        raw_predictions = [predictions]

    diagnostics["prediction_count"] = len(raw_predictions)
    diagnostics["first_prediction_shape"] = _prediction_shape_summary(raw_predictions[0]) if raw_predictions else {}

    payloads = [_coerce_prediction_payload(prediction) for prediction in raw_predictions]
    payloads = [payload for payload in payloads if payload]
    diagnostics["payload_count"] = len(payloads)
    diagnostics["first_payload_keys"] = sorted(str(key) for key in payloads[0].keys())[:30] if payloads else []
    return payloads, diagnostics


def _coerce_sequence(value: Any) -> list[Any]:
    """Return a plain list for PaddleOCR/PaddleX list-like and numpy-like values."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, bytes)):
        return [value]

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            converted = tolist()
        except Exception:
            converted = None
        if converted is not None:
            return _coerce_sequence(converted)

    if isinstance(value, Iterable):
        try:
            return list(value)
        except TypeError:
            return []

    return [value]


def _flatten_numeric_values(value: Any) -> list[float]:
    values: list[float] = []
    for item in _coerce_sequence(value):
        if isinstance(item, (list, tuple)) or (hasattr(item, "tolist") and not isinstance(item, (str, bytes))):
            values.extend(_flatten_numeric_values(item))
            continue
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            continue
    return values


def _bbox_from_coordinate_payload(coordinates: Any) -> BoundingBox | None:
    """Convert PaddleOCR box/polygon payloads into the internal bbox shape."""
    numbers = _flatten_numeric_values(coordinates)
    if len(numbers) < 4:
        return None

    # PaddleOCR rec_boxes commonly returns [x_min, y_min, x_max, y_max].
    if len(numbers) == 4:
        x0, top, x1, bottom = numbers
        return BoundingBox(x0=x0, top=top, x1=x1, bottom=bottom)

    # PaddleOCR rec_polys/dt_polys commonly returns polygon points.
    paired = list(zip(numbers[0::2], numbers[1::2]))
    if not paired:
        return None
    xs = [point[0] for point in paired]
    ys = [point[1] for point in paired]
    return BoundingBox(x0=min(xs), top=min(ys), x1=max(xs), bottom=max(ys))


def _extract_regions_from_prediction(
    *,
    artifact_id: str,
    page_number: int,
    prediction_payload: dict[str, Any],
) -> list[OCRTextRegion]:
    texts = [normalize_whitespace(str(text)) for text in _coerce_sequence(prediction_payload.get("rec_texts", []))]
    texts = [text for text in texts if text]
    scores = _coerce_sequence(prediction_payload.get("rec_scores", []))

    coordinate_candidates = [
        prediction_payload.get("rec_boxes"),
        prediction_payload.get("rec_polys"),
        prediction_payload.get("dt_polys"),
    ]
    coordinate_rows: list[Any] = []
    for candidate in coordinate_candidates:
        rows = _coerce_sequence(candidate)
        if rows:
            coordinate_rows = rows
            break

    regions: list[OCRTextRegion] = []

    for index, text in enumerate(texts):
        bbox = None
        bbox_source = None
        if index < len(coordinate_rows):
            bbox = _bbox_from_coordinate_payload(coordinate_rows[index])
            bbox_source = "rec_boxes_or_polygon" if bbox is not None else None
        if bbox is None:
            bbox = BoundingBox(x0=0.0, top=0.0, x1=0.0, bottom=0.0)

        confidence: float | None = None
        if index < len(scores):
            confidence = safe_float(scores[index])

        metadata: dict[str, Any] = {
            "ocr_payload_keys": sorted(str(key) for key in prediction_payload.keys()),
            "ocr_text_index": index,
        }
        if bbox_source is None:
            metadata["coordinate_warning"] = "OCR text recognized but no usable coordinate payload was available."
        else:
            metadata["coordinate_source"] = bbox_source

        regions.append(
            OCRTextRegion(
                region_id=build_region_id(
                    artifact_id=artifact_id,
                    page_number=page_number,
                    region_index=index + 1,
                ),
                page_number=page_number,
                text=text,
                bbox=bbox,
                confidence=confidence,
                source_method="paddleocr.predict",
                metadata=metadata,
            )
        )

    return regions

def _can_run_agent(context: Any) -> bool:
    run_id = getattr(context, "run_id", None)
    return isinstance(run_id, str) and bool(run_id.strip())


def _should_review_region(region: OCRTextRegion) -> bool:
    text = normalize_whitespace(region.text)
    if len(text) < OCR_AGENT_MIN_TEXT_LENGTH:
        return False

    if region.confidence is None:
        return True

    return region.confidence < OCR_AGENT_CONFIDENCE_THRESHOLD


def _apply_ocr_ambiguity_agent(
    *,
    context: Any,
    artifact_id: str,
    route_hint: str,
    region: OCRTextRegion,
) -> OCRTextRegion:
    if not _can_run_agent(context):
        return region

    if not _should_review_region(region):
        return region

    agent_result = run_agent(
        context=context,
        request=AgentRequest(
            agent_id="ocr_ambiguity_agent",
            stage_name="ocr",
            task_name="ocr_clarification",
            inputs={
                "artifact_id": artifact_id,
                "route_hint": route_hint,
                "region_id": region.region_id,
                "page_number": region.page_number,
                "raw_text": region.text,
                "confidence": region.confidence,
                "source_method": region.source_method,
                "source_anchor": {
                    "page_number": region.page_number,
                    "region_id": region.region_id,
                    "bbox": region.bbox.to_dict(),
                },
            },
            metadata={
                "service": "ocr_service",
            },
        ),
    )

    structured_output = agent_result.get("structured_output", {})
    if not isinstance(structured_output, dict):
        structured_output = {}

    candidate_text = structured_output.get("candidate_text")
    candidate_label = structured_output.get("candidate_label")
    candidate_value = structured_output.get("candidate_value")
    review_notes = structured_output.get("review_notes", [])

    if isinstance(candidate_text, str) and candidate_text.strip():
        region.clarified_text = candidate_text.strip()

    if isinstance(candidate_label, str) and candidate_label.strip():
        region.clarified_label = candidate_label.strip()

    if isinstance(candidate_value, str) and candidate_value.strip():
        region.clarified_value = candidate_value.strip()

    region.agent_id = str(agent_result.get("agent_id", "")).strip() or "ocr_ambiguity_agent"
    region.agent_status = str(agent_result.get("status", "")).strip() or None
    region.agent_audit_path = str(agent_result.get("audit_path", "")).strip() or None

    if isinstance(review_notes, list) and review_notes:
        region.metadata["agent_review_notes"] = [
            str(item).strip()
            for item in review_notes
            if isinstance(item, str) and item.strip()
        ]

    region.metadata["agent_policy"] = agent_result.get("policy", {})
    return region


def _run_ocr_on_page(
    *,
    context: Any,
    provider: Any,
    artifact_id: str,
    route_hint: str,
    pdf_path: Path,
    page_number: int,
    render_scale: float,
) -> OCRPageResult:
    page_warnings: list[str] = []

    image, render_warnings = _render_page_image(
        pdf_path=pdf_path,
        page_number=page_number,
        render_scale=render_scale,
    )
    page_warnings.extend(render_warnings)

    if image is None:
        return OCRPageResult(
            page_number=page_number,
            image_width=0,
            image_height=0,
            extracted_text="",
            char_count=0,
            text_regions=[],
            warnings=page_warnings,
        )

    image_path = _persist_temp_image(
        context=context,
        artifact_id=artifact_id,
        page_number=page_number,
        image=image,
    )

    try:
        predictions = provider.predict(str(image_path))
    except Exception as exc:
        page_warnings.append(
            f"OCR provider prediction failed: {exc.__class__.__name__}: {exc}"
        )
        return OCRPageResult(
            page_number=page_number,
            image_width=safe_int(getattr(image, "width", 0)),
            image_height=safe_int(getattr(image, "height", 0)),
            extracted_text="",
            char_count=0,
            text_regions=[],
            warnings=page_warnings,
        )

    prediction_payloads, prediction_diagnostics = _coerce_prediction_payloads(predictions)
    page_warnings.append(
        "OCR prediction diagnostics: "
        f"prediction_count={prediction_diagnostics.get('prediction_count', 0)}, "
        f"payload_count={prediction_diagnostics.get('payload_count', 0)}, "
        f"first_payload_keys={prediction_diagnostics.get('first_payload_keys', [])}"
    )

    text_regions: list[OCRTextRegion] = []
    payload_region_counts: list[dict[str, int]] = []
    for prediction_payload in prediction_payloads:
        payload_regions = _extract_regions_from_prediction(
            artifact_id=artifact_id,
            page_number=page_number,
            prediction_payload=prediction_payload,
        )
        payload_region_counts.append({
            "rec_text_count": len(_coerce_sequence(prediction_payload.get("rec_texts", []))),
            "rec_score_count": len(_coerce_sequence(prediction_payload.get("rec_scores", []))),
            "rec_box_count": len(_coerce_sequence(prediction_payload.get("rec_boxes", []))),
            "rec_poly_count": len(_coerce_sequence(prediction_payload.get("rec_polys", []))),
            "dt_poly_count": len(_coerce_sequence(prediction_payload.get("dt_polys", []))),
            "regions_extracted_count": len(payload_regions),
        })
        text_regions.extend(payload_regions)

    if payload_region_counts:
        page_warnings.append(f"OCR region extraction diagnostics: {payload_region_counts}")

    enriched_regions: list[OCRTextRegion] = []
    for region in text_regions:
        enriched_regions.append(
            _apply_ocr_ambiguity_agent(
                context=context,
                artifact_id=artifact_id,
                route_hint=route_hint,
                region=region,
            )
        )

    extracted_text = normalize_whitespace(" ".join(region.text for region in enriched_regions))

    if not enriched_regions:
        if not prediction_payloads:
            page_warnings.append(
                "OCR completed but no usable prediction payload was parsed; "
                f"shape={prediction_diagnostics.get('prediction_shape', {})}, "
                f"first_prediction_shape={prediction_diagnostics.get('first_prediction_shape', {})}"
            )
        else:
            page_warnings.append(
                "OCR completed but no text regions were returned from parsed payload keys "
                f"{prediction_diagnostics.get('first_payload_keys', [])}."
            )

    return OCRPageResult(
        page_number=page_number,
        image_width=safe_int(getattr(image, "width", 0)),
        image_height=safe_int(getattr(image, "height", 0)),
        extracted_text=extracted_text,
        char_count=len(extracted_text),
        text_regions=enriched_regions,
        warnings=page_warnings,
    )


def _run_ocr_for_document(
    *,
    context: Any,
    provider: Any,
    parsed_document: dict[str, Any],
    layout_document: dict[str, Any] | None = None,
) -> OCRDocumentResult:
    artifact_id = str(parsed_document.get("artifact_id", ""))
    file_name = str(parsed_document.get("file_name", ""))
    file_path = Path(str(parsed_document.get("file_path", "")))
    repository_key = str(parsed_document.get("repository_key", ""))
    route_hint = str(parsed_document.get("route_hint", ""))

    requested_pages = _select_pages_for_document_ocr(
        parsed_document=parsed_document,
        layout_document=layout_document,
    )
    document_warnings: list[str] = []

    if not file_exists(file_path):
        document_warnings.append(f"Artifact file does not exist on disk: {file_path}")
        return OCRDocumentResult(
            artifact_id=artifact_id,
            file_name=file_name,
            file_path=str(file_path),
            repository_key=repository_key,
            provider_name=PROVIDER_NAME,
            provider_version=get_distribution_version("paddleocr"),
            ocr_status="OCR_FAILED",
            route_consumed=route_hint,
            pages_requested=requested_pages,
            pages_processed=[],
            pages=[],
            warnings=document_warnings,
        )

    if not requested_pages:
        document_warnings.append("No pages were selected for OCR.")
        return OCRDocumentResult(
            artifact_id=artifact_id,
            file_name=file_name,
            file_path=str(file_path),
            repository_key=repository_key,
            provider_name=PROVIDER_NAME,
            provider_version=get_distribution_version("paddleocr"),
            ocr_status="OCR_SKIPPED",
            route_consumed=route_hint,
            pages_requested=[],
            pages_processed=[],
            pages=[],
            warnings=document_warnings,
        )

    render_scale = get_render_scale(context)
    page_results: list[OCRPageResult] = []

    for page_number in requested_pages:
        page_result = _run_ocr_on_page(
            context=context,
            provider=provider,
            artifact_id=artifact_id,
            route_hint=route_hint,
            pdf_path=file_path,
            page_number=page_number,
            render_scale=render_scale,
        )
        page_results.append(page_result)

    processed_pages = [
        page.page_number
        for page in page_results
        if page.text_regions or not page.warnings
    ]

    ocr_status = "OCR_COMPLETED"
    if not processed_pages and requested_pages:
        ocr_status = "OCR_FAILED"
    elif len(processed_pages) < len(requested_pages):
        ocr_status = "OCR_PARTIAL"

    return OCRDocumentResult(
        artifact_id=artifact_id,
        file_name=file_name,
        file_path=str(file_path),
        repository_key=repository_key,
        provider_name=PROVIDER_NAME,
        provider_version=get_distribution_version("paddleocr"),
        ocr_status=ocr_status,
        route_consumed=route_hint,
        pages_requested=requested_pages,
        pages_processed=processed_pages,
        pages=page_results,
        warnings=document_warnings,
    )


def _aggregate_ocr_status(
    *,
    provider_available: bool,
    provider_enabled: bool,
    documents: list[OCRDocumentResult],
) -> str:
    if not provider_enabled:
        return "OCR_DISABLED"
    if not provider_available:
        return "OCR_PROVIDER_UNAVAILABLE"
    if not documents:
        return "OCR_SKIPPED_NOT_NEEDED"

    targeted = [
        document
        for document in documents
        if document.pages_requested or document.ocr_status not in {"OCR_SKIPPED", "OCR_SKIPPED_NOT_NEEDED"}
    ]
    if not targeted:
        return "OCR_SKIPPED_NOT_NEEDED"

    completed = [document for document in targeted if document.ocr_status == "OCR_COMPLETED"]
    partial = [document for document in targeted if document.ocr_status == "OCR_PARTIAL"]
    failed = [document for document in targeted if document.ocr_status == "OCR_FAILED"]

    extracted_chars = 0
    for document in targeted:
        for page in document.pages:
            extracted_chars += int(page.char_count or 0)

    if failed and not completed and not partial:
        return "OCR_FAILED_ALL_DOCUMENTS"
    if extracted_chars <= 0 and targeted:
        return "OCR_FAILED_NO_TEXT_EXTRACTED"
    if failed or partial:
        return "OCR_COMPLETED_WITH_ERRORS"
    return "OCR_COMPLETED"


def run_ocr(
    context: Any,
    document_parser_result: dict[str, Any] | None = None,
    layout_analysis_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_documents = _coerce_documents(document_parser_result)
    layout_documents_by_artifact = _coerce_layout_documents(layout_analysis_result)

    provider_health: dict[str, Any] = {}
    provider_warnings: list[str] = []
    provider: Any | None = None

    provider_enabled = is_ocr_runtime_enabled(context)

    if provider_enabled:
        provider, provider_warnings, provider_health = _create_provider(context)
    else:
        provider_health = {
            "ocr_runtime_enabled": False,
            "provider_initialized": False,
            "disabled_reason": "OCR runtime disabled by configuration.",
        }
        provider_warnings.append("OCR runtime is disabled by configuration; provider initialization was skipped.")

    provider_available = provider is not None

    documents: list[OCRDocumentResult] = []
    warnings: list[str] = list(provider_warnings)

    if not parsed_documents:
        warnings.append("No parsed documents were provided to the OCR service.")

    if provider is not None:
        for parsed_document in parsed_documents:
            route_hint = str(parsed_document.get("route_hint", "")).strip()
            if not should_process_route(route_hint, parsed_document=parsed_document, layout_document=layout_documents_by_artifact.get(str(parsed_document.get("artifact_id", "")).strip())):
                continue

            artifact_id = str(parsed_document.get("artifact_id", "")).strip()
            layout_document = layout_documents_by_artifact.get(artifact_id)

            documents.append(
                _run_ocr_for_document(
                    context=context,
                    provider=provider,
                    parsed_document=parsed_document,
                    layout_document=layout_document,
                )
            )
    else:
        if parsed_documents:
            warnings.append("OCR provider is unavailable, so OCR execution was skipped.")

    aggregate_status = _aggregate_ocr_status(
        provider_available=provider_available,
        provider_enabled=provider_enabled,
        documents=documents,
    )
    if aggregate_status in {"OCR_FAILED_ALL_DOCUMENTS", "OCR_FAILED_NO_TEXT_EXTRACTED"}:
        warnings.append(
            "OCR provider initialized, but OCR produced no usable text for targeted documents; "
            "downstream extraction should treat OCR evidence as unavailable."
        )
    elif aggregate_status == "OCR_COMPLETED_WITH_ERRORS":
        warnings.append("OCR completed with at least one failed or partial targeted document.")

    result = OCRServiceResult(
        run_id=str(getattr(context, "run_id", "")),
        provider_name=PROVIDER_NAME,
        provider_version=get_distribution_version("paddleocr"),
        provider_available=provider_available,
        documents=documents,
        warnings=warnings,
        provider_health={
            **provider_health,
            "aggregate_status": aggregate_status,
            "document_status_counts": {
                status: sum(1 for document in documents if document.ocr_status == status)
                for status in sorted({document.ocr_status for document in documents})
            },
        },
        status=aggregate_status,
    )
    return result.to_dict()


def run_service(
    context: Any,
    document_parser_result: dict[str, Any] | None = None,
    layout_analysis_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_ocr(
        context=context,
        document_parser_result=document_parser_result,
        layout_analysis_result=layout_analysis_result,
    )