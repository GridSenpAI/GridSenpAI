from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from shared.planner_registry import (
    field_path_for_registry_field_id,
    load_planner_registry,
    planner_document_names_for_field,
    planner_document_specs as registry_planner_document_specs,
    planner_registry_fields,
    preferred_sources_for_field,
)

@dataclass(frozen=True, slots=True)
class ExtractionFieldSpec:
    field_id: str
    display_name: str
    data_type: str
    description: str
    search_documents: tuple[str, ...] = ()
    search_keywords: tuple[str, ...] = ()
    expected_format: str = ""
    lif_mapping: str = ""
    verification: dict[str, Any] = field(default_factory=dict)
    required_for: tuple[str, ...] = ()
    used_in: tuple[str, ...] = ()
    field_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "field_path": self.field_path,
            "display_name": self.display_name,
            "data_type": self.data_type,
            "description": self.description,
            "search_documents": list(self.search_documents),
            "search_keywords": list(self.search_keywords),
            "expected_format": self.expected_format,
            "lif_mapping": self.lif_mapping,
            "verification": dict(self.verification),
            "required_for": list(self.required_for),
            "used_in": list(self.used_in),
        }


@dataclass(frozen=True, slots=True)
class IntakeQuestionSpec:
    group: str
    purpose: str
    field_id: str
    question: str
    data_type: str
    required_for: tuple[str, ...] = ()
    used_in: tuple[str, ...] = ()
    field_path: str | None = None
    question_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "purpose": self.purpose,
            "field_id": self.field_id,
            "field_path": self.field_path,
            "question_id": self.question_id,
            "question": self.question,
            "data_type": self.data_type,
            "required_for": list(self.required_for),
            "used_in": list(self.used_in),
        }


@dataclass(frozen=True, slots=True)
class PlannerDocumentSpec:
    document_name: str
    description: str
    used_for: tuple[str, ...] = ()
    study_tools: tuple[str, ...] = ()
    data_fields_provided: tuple[str, ...] = ()
    required_stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_name": self.document_name,
            "description": self.description,
            "used_for": list(self.used_for),
            "study_tools": list(self.study_tools),
            "data_fields_provided": list(self.data_fields_provided),
            "required_stage": self.required_stage,
        }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object at {path}, got {type(payload).__name__}.")
    return payload


def _as_clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items: list[str] = []
    for item in value:
        cleaned = _as_clean_str(item)
        if cleaned:
            items.append(cleaned)
    return tuple(items)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _build_question_id(field_id: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in field_id.upper())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized or "UNKNOWN_FIELD"


_LEGACY_FIELD_ID_ALIASES: dict[str, str] = {
    "service_delivery_point_voltage_kv": "point_of_interconnection_voltage_kv",
    "requested_peak_demand_mw": "peak_demand_mw",
    "generator_count": "generator_unit_count",
}

_CANONICAL_FIELD_PATH_FALLBACKS: dict[str, str] = {
    "point_of_interconnection_voltage_kv": "facility.poi_voltage_kv",
    "peak_demand_mw": "facility.load_schedule.phase_1_mw",
    "generator_unit_count": "facility.generators.count",
}


def _canonical_field_id(field_id: str) -> str:
    normalized = _as_clean_str(field_id)
    return _LEGACY_FIELD_ID_ALIASES.get(normalized, normalized)


def _field_id_to_field_path(field_id: str) -> str | None:
    canonical = _canonical_field_id(field_id)
    return field_path_for_registry_field_id(canonical) or _CANONICAL_FIELD_PATH_FALLBACKS.get(canonical)


@lru_cache(maxsize=1)
def load_extraction_blueprint() -> tuple[ExtractionFieldSpec, ...]:
    field_specs: list[ExtractionFieldSpec] = []
    for item in planner_registry_fields():
        field_id = _as_clean_str(item.get("field_id"))
        if not field_id:
            continue
        touchpoints = _as_str_tuple(item.get("pipeline_touchpoints"))
        if not any(
            tp in touchpoints
            for tp in (
                "entity_extraction",
                "internal_knowledge_retrieval",
                "vendor_pdf_retrieval",
                "official_web_retrieval",
                "applicant_interview",
                "ocr_layout_parsing",
                "ontology_mapping",
                "document_classification",
                "artifact_ingestion",
                "normalization",
                "field_resolution",
            )
        ):
            continue
        preferred_sources = tuple(
            str(source).strip()
            for source in item.get("preferred_sources", [])
            if isinstance(source, str) and str(source).strip()
        )
        planner_documents = tuple(planner_document_names_for_field(field_id))
        search_documents = planner_documents or preferred_sources
        field_specs.append(
            ExtractionFieldSpec(
                field_id=field_id,
                field_path=_field_id_to_field_path(field_id),
                display_name=_as_clean_str(item.get("label")) or field_id,
                data_type=_as_clean_str(item.get("data_type")) or "string",
                description=_as_clean_str(item.get("notes")) or _as_clean_str(item.get("label")),
                search_documents=search_documents,
                search_keywords=tuple(
                    str(keyword).strip()
                    for keyword in item.get("search_keywords", [])
                    if isinstance(keyword, str) and str(keyword).strip()
                ),
                expected_format="",
                lif_mapping=field_id,
                verification={
                    "planner_critical": bool(item.get("planner_critical", False)),
                    "minimum_confidence_for_auto_accept": _as_clean_str(item.get("minimum_confidence_for_auto_accept")),
                    "allow_low_confidence_accept": bool(item.get("allow_low_confidence_accept", False)),
                },
                required_for=tuple(
                    str(value).strip()
                    for value in item.get("used_in_studies", [])
                    if isinstance(value, str) and str(value).strip()
                ),
                used_in=touchpoints,
            )
        )
    return tuple(field_specs)


@lru_cache(maxsize=1)
def load_intake_question_specs() -> tuple[IntakeQuestionSpec, ...]:
    question_specs: list[IntakeQuestionSpec] = []
    for item in planner_registry_fields():
        field_id = _as_clean_str(item.get("field_id"))
        if not field_id:
            continue
        touchpoints = _as_str_tuple(item.get("pipeline_touchpoints"))
        requiredness = _as_clean_str(item.get("requiredness")).lower() or "optional"
        planner_critical = bool(item.get("planner_critical", False))
        if "applicant_interview" not in touchpoints and not planner_critical and requiredness == "optional":
            continue
        label = _as_clean_str(item.get("label")) or field_id.replace("_", " ")
        sources = preferred_sources_for_field(field_id)
        source_hint = f" Review sources such as {', '.join(sources[:2])}." if sources else ""
        required_hint = (
            "This is required for the planner packet."
            if requiredness in {"required", "conditionally_required"}
            else "This helps strengthen packet completeness."
        )
        question_text = f"Please provide or confirm {label}. {required_hint}{source_hint}"
        question_specs.append(
            IntakeQuestionSpec(
                group=_as_clean_str(item.get("group")) or "planner_required_fields",
                purpose=f"Capture or confirm {label} for planner-ready packet generation.",
                field_id=field_id,
                field_path=_field_id_to_field_path(field_id),
                question_id=_build_question_id(field_id),
                question=question_text.strip(),
                data_type=_as_clean_str(item.get("data_type")) or "string",
                required_for=tuple(
                    str(value).strip()
                    for value in item.get("used_in_studies", [])
                    if isinstance(value, str) and str(value).strip()
                ),
                used_in=touchpoints,
            )
        )
    return tuple(question_specs)


@lru_cache(maxsize=1)
def load_planner_document_specs() -> tuple[PlannerDocumentSpec, ...]:
    documents: list[PlannerDocumentSpec] = []
    for item in registry_planner_document_specs():
        document_name = _as_clean_str(item.get("document_name"))
        if not document_name:
            continue
        documents.append(
            PlannerDocumentSpec(
                document_name=document_name,
                description=_as_clean_str(item.get("description")),
                used_for=_as_str_tuple(item.get("used_for")),
                study_tools=_as_str_tuple(item.get("study_tools")),
                data_fields_provided=_as_str_tuple(item.get("data_fields_provided")),
                required_stage=_as_clean_str(item.get("required_stage")),
            )
        )
    return tuple(documents)


@lru_cache(maxsize=1)
def extraction_field_index() -> dict[str, ExtractionFieldSpec]:
    mapping = {item.field_id: item for item in load_extraction_blueprint()}
    for legacy_field_id, canonical_field_id in _LEGACY_FIELD_ID_ALIASES.items():
        if canonical_field_id in mapping and legacy_field_id not in mapping:
            canonical_item = mapping[canonical_field_id]
            mapping[legacy_field_id] = ExtractionFieldSpec(
                field_id=legacy_field_id,
                display_name=canonical_item.display_name,
                data_type=canonical_item.data_type,
                description=canonical_item.description,
                search_documents=canonical_item.search_documents,
                search_keywords=canonical_item.search_keywords,
                expected_format=canonical_item.expected_format,
                lif_mapping=legacy_field_id,
                verification=canonical_item.verification,
                required_for=canonical_item.required_for,
                used_in=canonical_item.used_in,
                field_path=canonical_item.field_path,
            )
    return mapping


@lru_cache(maxsize=1)
def intake_question_index() -> dict[str, IntakeQuestionSpec]:
    mapping = {item.field_id: item for item in load_intake_question_specs()}
    for legacy_field_id, canonical_field_id in _LEGACY_FIELD_ID_ALIASES.items():
        if canonical_field_id in mapping and legacy_field_id not in mapping:
            canonical_item = mapping[canonical_field_id]
            mapping[legacy_field_id] = IntakeQuestionSpec(
                group=canonical_item.group,
                purpose=canonical_item.purpose,
                field_id=legacy_field_id,
                question=canonical_item.question,
                data_type=canonical_item.data_type,
                required_for=canonical_item.required_for,
                used_in=canonical_item.used_in,
                field_path=canonical_item.field_path,
                question_id=_build_question_id(legacy_field_id),
            )
    return mapping


@lru_cache(maxsize=1)
def planner_document_index() -> dict[str, PlannerDocumentSpec]:
    return {item.document_name: item for item in load_planner_document_specs()}


@lru_cache(maxsize=1)
def documents_by_field_id() -> dict[str, tuple[PlannerDocumentSpec, ...]]:
    mapping: dict[str, list[PlannerDocumentSpec]] = {}
    for document in load_planner_document_specs():
        for field_id in document.data_fields_provided:
            mapping.setdefault(field_id, []).append(document)
            for legacy_field_id, canonical_field_id in _LEGACY_FIELD_ID_ALIASES.items():
                if field_id == canonical_field_id:
                    mapping.setdefault(legacy_field_id, []).append(document)
    return {key: tuple(value) for key, value in mapping.items()}


@lru_cache(maxsize=1)
def extraction_fields_by_document_name() -> dict[str, tuple[ExtractionFieldSpec, ...]]:
    mapping: dict[str, list[ExtractionFieldSpec]] = {}
    field_index = extraction_field_index()
    for field_spec in load_extraction_blueprint():
        for document_name in field_spec.search_documents:
            mapping.setdefault(document_name, []).append(field_spec)
    for document in load_planner_document_specs():
        bucket = mapping.setdefault(document.document_name, [])
        for field_id in document.data_fields_provided:
            field_spec = field_index.get(field_id)
            if field_spec is not None and all(existing.field_id != field_spec.field_id for existing in bucket):
                bucket.append(field_spec)
    for legacy_field_id, canonical_field_id in _LEGACY_FIELD_ID_ALIASES.items():
        alias_spec = field_index.get(legacy_field_id)
        canonical_spec = field_index.get(canonical_field_id)
        if alias_spec is None or canonical_spec is None:
            continue
        for document_name in canonical_spec.search_documents:
            bucket = mapping.setdefault(document_name, [])
            if all(existing.field_id != legacy_field_id for existing in bucket):
                bucket.append(alias_spec)
        for document in load_planner_document_specs():
            if canonical_field_id in document.data_fields_provided or legacy_field_id in document.data_fields_provided:
                bucket = mapping.setdefault(document.document_name, [])
                if all(existing.field_id != legacy_field_id for existing in bucket):
                    bucket.append(alias_spec)
    return {key: tuple(value) for key, value in mapping.items()}


def get_extraction_field(field_id: str) -> ExtractionFieldSpec | None:
    return extraction_field_index().get(field_id.strip())


def get_intake_question(field_id: str) -> IntakeQuestionSpec | None:
    return intake_question_index().get(field_id.strip())


def get_planner_document(document_name: str) -> PlannerDocumentSpec | None:
    return planner_document_index().get(document_name.strip())


def get_documents_for_field(field_id: str) -> tuple[PlannerDocumentSpec, ...]:
    return documents_by_field_id().get(field_id.strip(), ())


def get_extraction_fields_for_document(document_name: str) -> tuple[ExtractionFieldSpec, ...]:
    return extraction_fields_by_document_name().get(document_name.strip(), ())


def build_registry_summary() -> dict[str, Any]:
    extraction_fields = load_extraction_blueprint()
    intake_questions = load_intake_question_specs()
    planner_documents = load_planner_document_specs()
    mapped_field_paths = sum(1 for item in extraction_fields if item.field_path)
    unmapped_field_paths = len(extraction_fields) - mapped_field_paths
    return {
        "extraction_field_count": len(extraction_fields),
        "intake_question_count": len(intake_questions),
        "planner_document_count": len(planner_documents),
        "mapped_field_path_count": mapped_field_paths,
        "unmapped_field_path_count": unmapped_field_paths,
    }
