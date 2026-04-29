from __future__ import annotations

from typing import Any, Dict, List

from services.extraction_service.models import ScheduleExtraction, ScheduleExtractionResult, ScheduleRow
from services.extraction_service.workers.common import (
    coerce_table_llm_value,
    detect_equipment_name,
    detect_schedule_type,
    ensure_runtime,
    extract_numeric_values,
    extract_schedule_rows,
    llm_enabled,
    normalize_rows,
    normalize_schedule_row,
    normalize_whitespace,
    safe_float,
    summarize_schedule_value,
)



def _coerce_documents(document_parser_result: dict | None) -> list[dict]:
    if not document_parser_result:
        return []
    docs = document_parser_result.get("parsed_documents", [])
    return [document for document in docs if isinstance(document, dict)]



def _coerce_ocr_documents(ocr_result: dict | None) -> list[dict]:
    if not ocr_result:
        return []
    docs = ocr_result.get("documents", [])
    return [document for document in docs if isinstance(document, dict)]



def _collect_table_regions(layout_result: dict | None) -> list[dict]:
    if not layout_result:
        return []
    regions = layout_result.get("candidate_regions", [])
    return [
        region
        for region in regions
        if isinstance(region, dict) and region.get("region_type") == "TABLE_EVIDENCE_REGION"
    ]



def _collect_text_blocks(document: dict) -> List[dict]:
    blocks: List[dict] = []
    for page in document.get("pages", []):
        for block in page.get("text_blocks", []):
            blocks.append(block)
    return blocks



def _collect_ocr_regions(ocr_doc: dict | None) -> List[dict]:
    if not ocr_doc:
        return []
    regions: List[dict] = []
    for page in ocr_doc.get("pages", []):
        for region in page.get("text_regions", []):
            regions.append(region)
    return regions



def _extract_from_document(document: dict, ocr_doc: dict | None, table_regions: List[dict]) -> List[ScheduleExtraction]:
    artifact_id = str(document.get("artifact_id", ""))
    text_blocks = _collect_text_blocks(document)
    ocr_regions = _collect_ocr_regions(ocr_doc)
    extractions: List[ScheduleExtraction] = []

    for region in table_regions:
        if str(region.get("artifact_id", "")) != artifact_id:
            continue

        page_number_raw = region.get("page_number")
        if page_number_raw is None:
            continue
        try:
            page_number = int(page_number_raw)
        except (TypeError, ValueError):
            continue

        region_blocks = [block for block in text_blocks if int(block.get("page_number", 0)) == page_number]
        region_ocr = [region_item for region_item in ocr_regions if int(region_item.get("page_number", 0)) == page_number]
        rows = extract_schedule_rows(region_blocks, region_ocr)
        if not rows:
            continue

        normalized = normalize_rows(rows)
        schedule_type = detect_schedule_type(rows)
        schedule_rows = [
            ScheduleRow(
                equipment_id=row.get("equipment_id"),
                tokens=row.get("tokens", []),
                numeric_values=row.get("numeric_values", []),
            )
            for row in normalized
        ]
        extractions.append(
            ScheduleExtraction(
                artifact_id=artifact_id,
                page_number=page_number,
                schedule_type=schedule_type,
                rows=schedule_rows,
                confidence=region.get("confidence"),
                metadata={
                    "region_id": region.get("region_id"),
                    "bbox": region.get("bbox"),
                },
            )
        )
    return extractions



def run_table_schedule_service(
    context: Any,
    document_parser_result: Dict[str, Any] | None = None,
    layout_analysis_result: Dict[str, Any] | None = None,
    ocr_service_result: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    del context
    documents = _coerce_documents(document_parser_result)
    ocr_documents = {str(document.get("artifact_id", "")): document for document in _coerce_ocr_documents(ocr_service_result)}
    table_regions = _collect_table_regions(layout_analysis_result)

    schedule_candidates: List[ScheduleExtraction] = []
    warnings: List[str] = []
    for document in documents:
        artifact_id = str(document.get("artifact_id", ""))
        schedule_candidates.extend(
            _extract_from_document(
                document=document,
                ocr_doc=ocr_documents.get(artifact_id),
                table_regions=table_regions,
            )
        )

    if not documents:
        warnings.append("No parsed documents available for schedule extraction.")
    if documents and not table_regions:
        warnings.append("No table evidence regions were supplied by layout analysis.")

    run_id = "table_schedule_extraction"
    if document_parser_result:
        run_id = str(document_parser_result.get("run_id", run_id))
    result = ScheduleExtractionResult(
        run_id=run_id,
        schedule_candidates=schedule_candidates,
        warnings=warnings,
    )
    return result.to_dict()


class TableScheduleExtractionService:
    def _maybe_llm_extract(
        self,
        *,
        artifact: Dict[str, Any],
        field_path: str,
        text: str,
        deterministic_value: Any,
        deterministic_confidence: float,
    ) -> tuple[Any, float, str]:
        if not llm_enabled() or (deterministic_value is not None and deterministic_confidence >= 0.72) or not text.strip():
            return deterministic_value, deterministic_confidence, "table_schedule_extraction"

        try:
            from services.llm_runtime_service.models import LLMTaskRequest
            from services.llm_runtime_service.service import run_llm_task

            ensure_runtime()
            request = LLMTaskRequest(
                task_name="table_schedule_interpretation",
                prompt_template_id="phase4.table_schedule_extraction.v1",
                system_prompt=(
                    "You are a bounded engineering schedule extraction worker. "
                    "Return only valid JSON and do not invent unsupported schedule values."
                ),
                user_prompt=(
                    f"Field path: {field_path}\n"
                    f"Deterministic value: {deterministic_value!r}\n"
                    f"Schedule text:\n{text}\n\n"
                    "Return JSON with a single key named value."
                ),
                response_schema={
                    "type": "object",
                    "properties": {"value": {}},
                    "required": ["value"],
                },
                json_mode=True,
                metadata={
                    "service": "extraction_service",
                    "worker": "table_schedule_extraction",
                    "artifact_id": artifact.get("artifact_id"),
                    "field_path": field_path,
                },
            )
            runtime_result = run_llm_task(
                run_id=str(artifact.get("artifact_id", "table_schedule_extraction")),
                request=request,
            )
        except Exception:
            return deterministic_value, deterministic_confidence, "table_schedule_extraction"

        payload = runtime_result.parsed_json if isinstance(runtime_result.parsed_json, dict) else {}
        coerced_value = coerce_table_llm_value(field_path, payload.get("value"))
        if coerced_value is None:
            return deterministic_value, deterministic_confidence, "table_schedule_extraction"
        return coerced_value, max(deterministic_confidence, 0.74), "table_schedule_extraction_llm"

    def run(
        self,
        context: Any,
        document_parser_result: Dict[str, Any] | None = None,
        layout_analysis_result: Dict[str, Any] | None = None,
        ocr_service_result: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return run_table_schedule_service(
            context=context,
            document_parser_result=document_parser_result,
            layout_analysis_result=layout_analysis_result,
            ocr_service_result=ocr_service_result,
        )

    def extract(self, artifacts: List[Dict[str, Any]], field_paths: List[str], context: Any | None = None) -> List[Dict[str, Any]]:
        del context
        results: List[Dict[str, Any]] = []
        for artifact in artifacts:
            artifact_type = str(artifact.get("artifact_type", "") or "")
            text = str(artifact.get("parsed_text") or artifact.get("text") or artifact.get("content") or "")
            lowered = text.lower()

            if artifact_type not in {"relay_table", "relay_schedule", "equipment_schedule", "motor_schedule"}:
                continue

            rows = extract_schedule_rows([{"text": line} for line in text.splitlines() if str(line).strip()], [])
            normalized_rows = normalize_rows(rows)
            schedule_type = detect_schedule_type(rows)
            schedule_value = summarize_schedule_value(schedule_type, normalized_rows)

            for field_path in field_paths:
                value: Any = None
                confidence = 0.0
                method = "table_schedule_extraction"

                if field_path == "facility.relay_settings":
                    if artifact_type in {"relay_table", "relay_schedule"} and ("relay" in lowered or "50" in lowered or "51" in lowered):
                        value = True
                        confidence = 0.90
                elif field_path == "facility.motor_schedule":
                    if schedule_type == "MOTOR_SCHEDULE":
                        value = schedule_value
                        confidence = 0.82 if value is not None else 0.0
                elif field_path == "facility.equipment_schedule":
                    if schedule_type in {
                        "TRANSFORMER_SCHEDULE",
                        "GENERATOR_SCHEDULE",
                        "UPS_SCHEDULE",
                        "BREAKER_SCHEDULE",
                        "UNKNOWN_SCHEDULE",
                    } and normalized_rows:
                        value = schedule_value
                        confidence = 0.76 if value is not None else 0.0

                value, confidence, method = self._maybe_llm_extract(
                    artifact=artifact,
                    field_path=field_path,
                    text=text,
                    deterministic_value=value,
                    deterministic_confidence=confidence,
                )
                results.append(
                    {
                        "field_path": field_path,
                        "value": value,
                        "confidence": confidence,
                        "source_artifact_id": artifact.get("artifact_id"),
                        "method": method,
                        "evidence": {
                            "schedule_type": schedule_type,
                            "row_count": len(normalized_rows),
                        },
                    }
                )
        return results


__all__ = [
    "TableScheduleExtractionService",
    "coerce_table_llm_value",
    "detect_equipment_name",
    "detect_schedule_type",
    "extract_numeric_values",
    "extract_schedule_rows",
    "normalize_rows",
    "normalize_schedule_row",
    "normalize_whitespace",
    "run_table_schedule_service",
    "safe_float",
    "summarize_schedule_value",
]
