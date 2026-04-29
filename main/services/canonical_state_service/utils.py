from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from shared.types import CanonicalFacilityState


VALIDATION_MISSING_CODES = {
    "MISSING",
    "REQUIRED",
    "UNRESOLVED",
    "NEEDS_INPUT",
}

DEFAULT_CONFIDENCE_THRESHOLD = 0.60


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_dict(payload: Any, name: str) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TypeError(f"{name} must be a dict, got {type(payload).__name__}.")
    return payload


def require_list(payload: Any, name: str) -> list[Any]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise TypeError(f"{name} must be a list, got {type(payload).__name__}.")
    return payload


def require_run_id(run_id: Any) -> str:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string.")
    return run_id.strip()


def validate_stage_run_id(
    expected_run_id: str,
    payload: dict[str, Any] | None,
    stage_name: str,
) -> None:
    if payload is None:
        return

    if not isinstance(payload, dict):
        raise TypeError(
            f"{stage_name} payload must be a dict, got {type(payload).__name__}."
        )

    payload_run_id = payload.get("run_id")
    if payload_run_id is None:
        return

    if str(payload_run_id) != expected_run_id:
        raise ValueError(
            f"{stage_name} payload run_id mismatch: "
            f"expected {expected_run_id}, got {payload_run_id}."
        )


def make_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def normalize_path(path: str) -> str:
    return ".".join(part for part in path.split(".") if part.strip())


def normalize_field_path(path: Any) -> str:
    if not isinstance(path, str):
        return ""
    normalized = path.strip().replace("/", ".")
    normalized = normalized.replace("..", ".")
    return ".".join(part for part in normalized.split(".") if part.strip())


def deduplicate_strings(values: Iterable[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)

    return ordered


def flatten_scalar_paths(
    payload: dict[str, Any],
    prefix: str = "",
) -> list[tuple[str, Any]]:
    flattened: list[tuple[str, Any]] = []

    def _walk(node: Any, current_path: str) -> None:
        if isinstance(node, dict):
            for key in sorted(node.keys(), key=str):
                child_path = f"{current_path}.{key}" if current_path else str(key)
                _walk(node[key], child_path)
            return

        if isinstance(node, list):
            for index, item in enumerate(node):
                child_path = f"{current_path}[{index}]"
                _walk(item, child_path)
            return

        flattened.append((normalize_path(current_path), node))

    _walk(payload, prefix)
    return flattened


def canonicalize_value_for_compare(value: Any) -> str:
    try:
        return json.dumps(make_json_safe(value), sort_keys=True, ensure_ascii=False)
    except TypeError:
        return repr(value)


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def confidence_tag_from_score(score: float | None) -> str:
    if score is None:
        return "UNRESOLVED"
    if score >= 0.85:
        return "HIGH"
    if score >= 0.60:
        return "MODERATE"
    if score >= 0.00:
        return "LOW"
    return "UNRESOLVED"


def confidence_score_from_tag(tag: Any) -> float | None:
    if not isinstance(tag, str):
        return None

    normalized = tag.strip().upper()
    if normalized == "HIGH":
        return 0.90
    if normalized == "MODERATE":
        return 0.70
    if normalized == "LOW":
        return 0.35
    if normalized == "UNRESOLVED":
        return None
    return None


def passes_confidence_threshold(confidence: float) -> bool:
    return confidence >= DEFAULT_CONFIDENCE_THRESHOLD


def select_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda candidate: candidate.get("confidence", 0.0),
        reverse=True,
    )[0]


def evidence_strength_from_sources(
    source_type: str,
    source_ref: list[str],
    confidence_tag: str,
) -> str:
    if source_type == "translation_output" and confidence_tag == "HIGH":
        return "STRONG"
    if source_type == "translation_output" and confidence_tag == "MODERATE":
        return "MODERATE"
    if source_type == "normalized_input" and source_ref:
        return "MODERATE"
    if source_ref:
        return "WEAK"
    return "UNKNOWN"


def validation_status_from_context(
    schema_valid: bool,
    has_conflict: bool,
    is_missing: bool,
    confidence_tag: str,
) -> str:
    if is_missing:
        return "MISSING"
    if has_conflict:
        return "CONFLICTED"
    if not schema_valid:
        return "SCHEMA_WARNING"
    if confidence_tag == "UNRESOLVED":
        return "REVIEW_REQUIRED"
    return "VALID"


def review_status_from_context(
    has_conflict: bool,
    is_missing: bool,
    confidence_tag: str,
) -> str:
    if has_conflict or is_missing or confidence_tag in {"LOW", "UNRESOLVED"}:
        return "REVIEW_REQUIRED"
    return "CLEAR"


def extract_missing_field_paths(validation_report: dict[str, Any]) -> list[str]:
    missing_fields = require_list(validation_report.get("missing_fields", []), "missing_fields")
    paths: list[str] = []

    for item in missing_fields:
        if isinstance(item, str) and item.strip():
            paths.append(normalize_path(item))
            continue

        if not isinstance(item, dict):
            continue

        for key in ("field_path", "path", "parameter_path", "target_path"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(normalize_path(value))
                break

    return deduplicate_strings(paths)


def canonical_state_summary_from_payload(
    canonical_state_payload: dict[str, Any],
) -> dict[str, Any]:
    state = require_dict(canonical_state_payload, "canonical_state_payload")

    validation_report = state.get("validation_report", {})
    if not isinstance(validation_report, dict):
        validation_report = {}

    missing_fields = extract_missing_field_paths(validation_report)
    output_parameters = require_list(state.get("output_parameters", []), "output_parameters")
    assumptions = require_list(state.get("assumptions", []), "assumptions")
    artifacts = require_list(state.get("artifacts", []), "artifacts")
    entities = require_list(state.get("entities", []), "entities")
    topology_cues = require_list(state.get("topology_cues", []), "topology_cues")
    source_anchors = require_list(state.get("source_anchors", []), "source_anchors")
    evidence_snippets = require_list(state.get("evidence_snippets", []), "evidence_snippets")
    scenarios = require_list(state.get("scenarios", []), "scenarios")
    followup_questions = require_list(state.get("followup_questions", []), "followup_questions")
    field_records = require_list(state.get("field_records", []), "field_records")
    conflict_records = require_list(state.get("conflict_records", []), "conflict_records")
    review_flags = require_list(state.get("review_flags", []), "review_flags")

    return {
        "artifact_count": len(artifacts),
        "entity_count": len(entities),
        "topology_cue_count": len(topology_cues),
        "source_anchor_count": len(source_anchors),
        "evidence_snippet_count": len(evidence_snippets),
        "output_parameter_count": len(output_parameters),
        "assumption_count": len(assumptions),
        "scenario_count": len(scenarios),
        "followup_question_count": len(followup_questions),
        "field_record_count": len(field_records),
        "conflict_count": len(conflict_records),
        "review_flag_count": len(review_flags),
        "missing_field_count": len(missing_fields),
        "stage_status": require_dict(state.get("stage_status", {}), "stage_status"),
    }


def write_canonical_state_snapshot(
    *,
    canonical_state: CanonicalFacilityState,
    output_path: str | Path,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(canonical_state.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output
