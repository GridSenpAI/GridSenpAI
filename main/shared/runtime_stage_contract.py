from __future__ import annotations

from typing import Any

from app.config import CONFIG
from shared.planner_registry import planner_legacy_artifact_manifest, planner_schema_alignment_summary

GAP_RESOLUTION_RETRIEVAL_STAGE = "gap_resolution::retrieval"
GAP_RESOLUTION_INTERVIEW_STAGE = "gap_resolution::interview"

TOP_LEVEL_STAGE_ORDER: tuple[str, ...] = tuple(CONFIG.runtime_architecture.public_spine)
GAP_RESOLUTION_SUBSTAGE_ORDER: tuple[str, ...] = (
    GAP_RESOLUTION_RETRIEVAL_STAGE,
    GAP_RESOLUTION_INTERVIEW_STAGE,
)

CANONICAL_STAGE_STATUS_ORDER: tuple[str, ...] = (
    "ingestion",
    "extraction",
    "normalization",
    GAP_RESOLUTION_RETRIEVAL_STAGE,
    GAP_RESOLUTION_INTERVIEW_STAGE,
    "validation",
    "canonical_state_governance",
    "canonical_state",
    "translation",
    "scenarios",
    "export",
)

_LEGACY_STAGE_ALIASES: dict[str, tuple[str, ...]] = {
    GAP_RESOLUTION_RETRIEVAL_STAGE: ("retrieval",),
    GAP_RESOLUTION_INTERVIEW_STAGE: ("interview",),
    "retrieval": (GAP_RESOLUTION_RETRIEVAL_STAGE,),
    "interview": (GAP_RESOLUTION_INTERVIEW_STAGE,),
}

_STAGE_DISPLAY_LABELS: dict[str, str] = {
    "ingestion": "Ingestion",
    "extraction": "Extraction",
    "normalization": "Normalization",
    GAP_RESOLUTION_RETRIEVAL_STAGE: "Gap Resolution / Retrieval",
    GAP_RESOLUTION_INTERVIEW_STAGE: "Gap Resolution / Interview",
    "validation": "Validation",
    "canonical_state_governance": "Canonical Governance",
    "canonical_state": "Canonical State",
    "translation": "Translation",
    "scenarios": "Scenarios",
    "export": "Export",
    "governance": "Governance",
    "replay": "Replay",
}


def public_stage_order() -> list[str]:
    return list(TOP_LEVEL_STAGE_ORDER)


def gap_resolution_substage_order() -> list[str]:
    return list(CONFIG.runtime_architecture.gap_resolution_substages)


def canonical_stage_status_order() -> list[str]:
    return list(CANONICAL_STAGE_STATUS_ORDER)


def display_stage_name(stage_name: str) -> str:
    normalized = str(stage_name).strip()
    if not normalized:
        return "Unknown Stage"
    return _STAGE_DISPLAY_LABELS.get(normalized, normalized.replace("::", " / ").replace("_", " ").title())


def public_stage_labels() -> list[dict[str, str]]:
    return [
        {"stage_name": stage_name, "display_label": display_stage_name(stage_name)}
        for stage_name in public_stage_order()
    ]


def gap_resolution_substage_labels() -> list[dict[str, str]]:
    return [
        {"stage_name": stage_name, "display_label": display_stage_name(stage_name)}
        for stage_name in gap_resolution_substage_order()
    ]


def gap_resolution_stage_name(capability_name: str) -> str:
    normalized = str(capability_name).strip().lower()
    if normalized == "retrieval":
        return GAP_RESOLUTION_RETRIEVAL_STAGE
    if normalized in {"interview", "intake"}:
        return GAP_RESOLUTION_INTERVIEW_STAGE
    return str(capability_name).strip()


def stage_name_aliases(stage_name: str) -> tuple[str, ...]:
    normalized = str(stage_name).strip()
    if not normalized:
        return tuple()
    extras = _LEGACY_STAGE_ALIASES.get(normalized, tuple())
    ordered = [normalized, *extras]
    seen: set[str] = set()
    result: list[str] = []
    for item in ordered:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def ordered_stage_status_items(stage_status: Any) -> list[tuple[str, str]]:
    if not isinstance(stage_status, dict):
        return []

    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()

    for stage_name in CANONICAL_STAGE_STATUS_ORDER:
        status_value = stage_status.get(stage_name)
        if isinstance(status_value, str) and status_value.strip():
            ordered.append((stage_name, status_value.strip()))
            seen.add(stage_name)

    for stage_name, status_value in stage_status.items():
        if stage_name in seen:
            continue
        if isinstance(stage_name, str) and stage_name.strip() and isinstance(status_value, str) and status_value.strip():
            ordered.append((stage_name.strip(), status_value.strip()))

    return ordered


def ordered_stage_status(stage_status: Any) -> dict[str, str]:
    return {stage_name: status for stage_name, status in ordered_stage_status_items(stage_status)}


def labeled_stage_status_items(stage_status: Any) -> list[tuple[str, str, str]]:
    return [
        (stage_name, display_stage_name(stage_name), status)
        for stage_name, status in ordered_stage_status_items(stage_status)
    ]


def replay_contract_summary() -> dict[str, Any]:
    runtime_architecture = CONFIG.runtime_architecture
    schema_config = CONFIG.schemas
    path_config = CONFIG.paths
    return {
        "public_stage_order": public_stage_order(),
        "public_stage_labels": public_stage_labels(),
        "gap_resolution_substage_order": gap_resolution_substage_order(),
        "gap_resolution_substage_labels": gap_resolution_substage_labels(),
        "canonical_stage_status_order": canonical_stage_status_order(),
        "active_bounded_assist_backend": runtime_architecture.active_bounded_assist_backend,
        "inactive_compatibility_layers": list(runtime_architecture.inactive_compatibility_layers),
        "canonical_knowledge_families": list(runtime_architecture.canonical_knowledge_families),
        "legacy_knowledge_fallbacks": list(runtime_architecture.legacy_knowledge_fallbacks),
        "primary_planner_contract_path": str(schema_config.primary_planner_contract_path(path_config)),
        "planner_required_fields_path": str(schema_config.planner_required_fields_path(path_config)),
        "legacy_input_schema_path": str(schema_config.input_schema_path(path_config)),
        "legacy_output_schema_path": str(schema_config.output_schema_path(path_config)),
        "derived_schema_alignment": planner_schema_alignment_summary(),
        "legacy_artifact_manifest": planner_legacy_artifact_manifest(),
        "legacy_artifacts_safe_to_delete_now": planner_legacy_artifact_manifest().get("safe_to_delete_now", []),
        "deleted_legacy_artifacts": planner_legacy_artifact_manifest().get("deleted_legacy_artifacts", []),
    }
