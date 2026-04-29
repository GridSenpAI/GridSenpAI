from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.ingestion_service.utils import classify_artifact, iter_supported_artifacts


@dataclass(frozen=True, slots=True)
class DocumentFieldPack:
    document_classes: tuple[str, ...]
    artifact_classifications: tuple[str, ...]
    active_field_paths: tuple[str, ...]
    suppressed_field_paths: tuple[str, ...]
    interview_suppressed_field_paths: tuple[str, ...]
    external_retrieval_candidate_fields: tuple[str, ...]
    rationale: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_classes": list(self.document_classes),
            "artifact_classifications": list(self.artifact_classifications),
            "active_field_paths": list(self.active_field_paths),
            "suppressed_field_paths": list(self.suppressed_field_paths),
            "interview_suppressed_field_paths": list(self.interview_suppressed_field_paths),
            "external_retrieval_candidate_fields": list(self.external_retrieval_candidate_fields),
            "rationale": list(self.rationale),
            "field_pack_active": bool(self.document_classes),
        }


_CLASS_TO_ARTIFACT_CLASSIFICATIONS: dict[str, tuple[str, ...]] = {
    "interconnection_study": (
        "poi_interconnection_documentation",
    ),
    "one_line_drawing": (
        "one_line_diagram",
        "site_plan",
    ),
    "equipment_schedule": (
        "equipment_schedule",
        "load_study",
        "cooling_documentation",
    ),
    "vendor_datasheet": (
        "transformer_datasheet",
        "generator_specification",
        "ups_documentation",
        "reactive_harmonic_package",
    ),
    "protection_package": (
        "protection_summary",
    ),
    "commissioning_telemetry_package": (
        "commissioning_notes",
        "load_information_form",
    ),
}

# These are the Phase 5.7 runtime-targeted fields currently most prone to backlog flooding when
# the intake bundle is mostly an interconnection study packet instead of detailed equipment packages.
_INTERCONNECTION_STUDY_BASE_SUPPRESSIONS: tuple[str, ...] = (
    "facility.generators.count",
    "facility.generators.ratings",
    "facility.ups.count",
    "facility.ups.topology",
    "facility.motor_schedule",
    "facility.equipment_schedule",
)

_CLASS_ENABLES: dict[str, tuple[str, ...]] = {
    "one_line_drawing": (
        "facility.generators.count",
        "facility.ups.count",
        "facility.substation.configuration",
        "facility.transformers.count",
    ),
    "equipment_schedule": (
        "facility.motor_schedule",
        "facility.equipment_schedule",
        "facility.generators.count",
        "facility.ups.count",
    ),
    "vendor_datasheet": (
        "facility.generators.ratings",
        "facility.ups.topology",
        "facility.transformers.ratings_mva",
    ),
    "protection_package": (
        "facility.relay_settings",
    ),
    "commissioning_telemetry_package": (
        "facility.modeling.dynamic_model_available",
        "facility.modeling.pscad_model_package",
    ),
}

_EXTERNAL_RETRIEVAL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "interconnection_study": (
        "facility.modeling.dynamic_model_available",
        "facility.modeling.pscad_model_package",
        "facility.substation.configuration",
        "facility.relay_settings",
    ),
    "commissioning_telemetry_package": (
        "facility.modeling.dynamic_model_available",
        "facility.modeling.pscad_model_package",
    ),
}


def _unique_ordered(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in values:
        cleaned = str(item or "").strip()
        if cleaned and cleaned not in seen:
            ordered.append(cleaned)
            seen.add(cleaned)
    return tuple(ordered)


def detect_document_classes(input_dir: str | Path | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if input_dir is None:
        return (), ()
    directory = Path(input_dir)
    if not directory.exists():
        return (), ()

    artifact_classifications: list[str] = []
    for artifact_path in iter_supported_artifacts(directory):
        classification = classify_artifact(artifact_path)
        if classification and classification != "unknown":
            artifact_classifications.append(classification)

    artifact_tuple = _unique_ordered(artifact_classifications)
    artifact_set = set(artifact_tuple)
    document_classes: list[str] = []
    for document_class, classifications in _CLASS_TO_ARTIFACT_CLASSIFICATIONS.items():
        if any(classification in artifact_set for classification in classifications):
            document_classes.append(document_class)
    return _unique_ordered(document_classes), artifact_tuple


def build_document_field_pack(
    *,
    input_dir: str | Path | None,
    requested_field_paths: list[str] | tuple[str, ...] | None,
) -> DocumentFieldPack:
    requested = _unique_ordered(list(requested_field_paths or []))
    document_classes, artifact_classifications = detect_document_classes(input_dir)
    requested_set = set(requested)

    if not requested or not document_classes:
        return DocumentFieldPack(
            document_classes=document_classes,
            artifact_classifications=artifact_classifications,
            active_field_paths=requested,
            suppressed_field_paths=(),
            interview_suppressed_field_paths=(),
            external_retrieval_candidate_fields=(),
            rationale=(),
        )

    suppressed: set[str] = set()
    rationale: list[str] = []

    if "interconnection_study" in document_classes:
        suppressed.update(field for field in _INTERCONNECTION_STUDY_BASE_SUPPRESSIONS if field in requested_set)
        rationale.append(
            "Interconnection-study-heavy intake detected; suppressing equipment-internal backlog fields unless supporting drawings, schedules, or datasheets are present."
        )

    for document_class in document_classes:
        for enabled_field in _CLASS_ENABLES.get(document_class, ()): 
            suppressed.discard(enabled_field)

    # If no suppression survived, leave the active set untouched.
    active = tuple(field for field in requested if field not in suppressed)
    external_candidates = _unique_ordered(
        [
            field
            for document_class in document_classes
            for field in _EXTERNAL_RETRIEVAL_CANDIDATES.get(document_class, ())
            if field in requested_set
        ]
    )

    if suppressed:
        rationale.append(
            "Suppressed fields remain available for later intake runs if better supporting document classes are added."
        )

    return DocumentFieldPack(
        document_classes=document_classes,
        artifact_classifications=artifact_classifications,
        active_field_paths=active or requested,
        suppressed_field_paths=_unique_ordered(list(suppressed)),
        interview_suppressed_field_paths=_unique_ordered(list(suppressed)),
        external_retrieval_candidate_fields=external_candidates,
        rationale=_unique_ordered(rationale),
    )


def filter_question_records_by_field_pack(
    questions: list[dict[str, Any]],
    field_pack: DocumentFieldPack | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if field_pack is None or not field_pack.interview_suppressed_field_paths:
        return questions, []

    suppressed = set(field_pack.interview_suppressed_field_paths)
    kept: list[dict[str, Any]] = []
    removed_fields: list[str] = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        field_path = str(item.get("field_path", "")).strip()
        if field_path and field_path in suppressed:
            if field_path not in removed_fields:
                removed_fields.append(field_path)
            continue
        kept.append(item)
    return kept, removed_fields
