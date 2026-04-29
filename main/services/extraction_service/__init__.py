from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "ExtractionCandidate",
    "ExtractionDomainCoordinator",
    "ExtractionPipelineInput",
    "ExtractionPipelineResult",
    "ExtractionRoute",
    "ExtractionRouter",
    "EntityObservationRecord",
    "ResolvedEntity",
    "ScheduleExtraction",
    "ScheduleExtractionResult",
    "ScheduleRow",
    "SpecExtractionResult",
    "SpecSheetExtractionService",
    "TableScheduleExtractionService",
    "coerce_spec_llm_value",
    "coerce_table_llm_value",
    "detect_equipment_name",
    "detect_schedule_type",
    "extract_numeric_values",
    "extract_schedule_rows",
    "get_artifact_text",
    "infer_generator_ratings",
    "infer_transformer_ratings",
    "infer_ups_topology",
    "is_spec_artifact",
    "normalize_rows",
    "normalize_schedule_row",
    "normalize_whitespace",
    "run_table_schedule_service",
    "safe_float",
    "summarize_schedule_value",
]

_ATTRIBUTE_MODULE_MAP = {
    "ExtractionDomainCoordinator": ("services.extraction_service.domain", "ExtractionDomainCoordinator"),
    "ExtractionRoute": ("services.extraction_service.domain", "ExtractionRoute"),
    "ExtractionRouter": ("services.extraction_service.domain", "ExtractionRouter"),
    "EntityObservationRecord": ("services.extraction_service.models", "EntityObservationRecord"),
    "ExtractionCandidate": ("services.extraction_service.models", "ExtractionCandidate"),
    "ExtractionPipelineInput": ("services.extraction_service.models", "ExtractionPipelineInput"),
    "ExtractionPipelineResult": ("services.extraction_service.models", "ExtractionPipelineResult"),
    "ResolvedEntity": ("services.extraction_service.models", "ResolvedEntity"),
    "ScheduleExtraction": ("services.extraction_service.models", "ScheduleExtraction"),
    "ScheduleExtractionResult": ("services.extraction_service.models", "ScheduleExtractionResult"),
    "ScheduleRow": ("services.extraction_service.models", "ScheduleRow"),
    "SpecExtractionResult": ("services.extraction_service.models", "SpecExtractionResult"),
    "SpecSheetExtractionService": ("services.extraction_service.workers", "SpecSheetExtractionService"),
    "TableScheduleExtractionService": ("services.extraction_service.workers", "TableScheduleExtractionService"),
    "coerce_spec_llm_value": ("services.extraction_service.workers", "coerce_spec_llm_value"),
    "coerce_table_llm_value": ("services.extraction_service.workers", "coerce_table_llm_value"),
    "detect_equipment_name": ("services.extraction_service.workers", "detect_equipment_name"),
    "detect_schedule_type": ("services.extraction_service.workers", "detect_schedule_type"),
    "extract_numeric_values": ("services.extraction_service.workers", "extract_numeric_values"),
    "extract_schedule_rows": ("services.extraction_service.workers", "extract_schedule_rows"),
    "get_artifact_text": ("services.extraction_service.workers", "get_artifact_text"),
    "infer_generator_ratings": ("services.extraction_service.workers", "infer_generator_ratings"),
    "infer_transformer_ratings": ("services.extraction_service.workers", "infer_transformer_ratings"),
    "infer_ups_topology": ("services.extraction_service.workers", "infer_ups_topology"),
    "is_spec_artifact": ("services.extraction_service.workers", "is_spec_artifact"),
    "normalize_rows": ("services.extraction_service.workers", "normalize_rows"),
    "normalize_schedule_row": ("services.extraction_service.workers", "normalize_schedule_row"),
    "normalize_whitespace": ("services.extraction_service.workers", "normalize_whitespace"),
    "run_table_schedule_service": ("services.extraction_service.workers", "run_table_schedule_service"),
    "safe_float": ("services.extraction_service.workers", "safe_float"),
    "summarize_schedule_value": ("services.extraction_service.workers", "summarize_schedule_value"),
}


def __getattr__(name: str) -> Any:
    target = _ATTRIBUTE_MODULE_MAP.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
