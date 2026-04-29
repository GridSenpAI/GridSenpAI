# services/translation_service/utils.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.planner_registry import translation_dependency_paths, translation_source_field_paths, translation_topics



def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_nested_value(payload: dict[str, Any], field_path: str) -> Any:
    current: Any = payload
    for token in field_path.split("."):
        if not isinstance(current, dict) or token not in current:
            return None
        current = current[token]
    return current


def set_nested_value(payload: dict[str, Any], field_path: str, value: Any) -> None:
    tokens = field_path.split(".")
    current = payload

    for token in tokens[:-1]:
        next_value = current.get(token)
        if not isinstance(next_value, dict):
            next_value = {}
            current[token] = next_value
        current = next_value

    current[tokens[-1]] = value


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_dependency_paths(parameter_path: str) -> list[str]:
    return sorted(translation_dependency_paths(parameter_path))


def get_source_field_paths(parameter_path: str) -> list[str]:
    return sorted(translation_source_field_paths(parameter_path))


def collect_conflict_field_paths(validation_report: dict[str, Any] | None) -> set[str]:
    if not isinstance(validation_report, dict):
        return set()

    conflicts = validation_report.get("conflicts", [])
    if not isinstance(conflicts, list):
        return set()

    result: set[str] = set()

    for item in conflicts:
        if not isinstance(item, dict):
            continue
        field_path = str(item.get("field_path", "")).strip()
        if field_path:
            result.add(field_path)

    return result


def collect_missing_fields(validation_report: dict[str, Any] | None) -> set[str]:
    if not isinstance(validation_report, dict):
        return set()

    missing_fields = validation_report.get("missing_fields", [])
    if not isinstance(missing_fields, list):
        return set()

    result: set[str] = set()

    for item in missing_fields:
        if isinstance(item, str):
            field_path = item.strip()
            if field_path:
                result.add(field_path)
        elif isinstance(item, dict):
            field_path = str(item.get("field_path", "")).strip()
            if field_path:
                result.add(field_path)

    return result


def collect_confirmed_field_paths(validation_report: dict[str, Any] | None) -> set[str]:
    if not isinstance(validation_report, dict):
        return set()

    interview_summary = validation_report.get("interview_summary", {})
    if not isinstance(interview_summary, dict):
        return set()

    confirmed = interview_summary.get("confirmed_field_paths", [])
    if not isinstance(confirmed, list):
        return set()

    return {
        str(field_path).strip()
        for field_path in confirmed
        if isinstance(field_path, str) and field_path.strip()
    }


def has_conflict_for_field(validation_report: dict[str, Any], field_path: str) -> bool:
    return field_path in collect_conflict_field_paths(validation_report)


def _topics_for_parameter(parameter_path: str) -> set[str]:
    return translation_topics(parameter_path)


def count_supporting_snippets(
    canonical_state: dict[str, Any],
    topics: set[str],
) -> tuple[int, list[str]]:
    snippets = canonical_state.get("evidence_snippets", [])
    if not isinstance(snippets, list):
        return 0, []

    lowered_topics = {
        topic.strip().lower()
        for topic in topics
        if isinstance(topic, str) and topic.strip()
    }

    matched_ids: list[str] = []

    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue

        snippet_id = str(snippet.get("snippet_id", "")).strip()
        text = str(snippet.get("text", "")).strip().lower()
        source_ref = str(snippet.get("source_ref", "")).strip().lower()
        metadata = snippet.get("metadata", {})
        metadata_topic = ""
        if isinstance(metadata, dict):
            metadata_topic = str(metadata.get("topic", "")).strip().lower()

        if any(
            topic in text or topic in source_ref or topic == metadata_topic
            for topic in lowered_topics
        ):
            if snippet_id:
                matched_ids.append(snippet_id)

    return len(matched_ids), matched_ids


def count_supporting_evidence(
    *,
    parameter_path: str,
    snippets: list[dict[str, Any]] | None,
) -> int:
    if not isinstance(snippets, list):
        return 0

    topics = _topics_for_parameter(parameter_path)
    if not topics:
        return 0

    count = 0

    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue

        metadata = snippet.get("metadata", {})
        if not isinstance(metadata, dict):
            continue

        topic = str(metadata.get("topic", "")).strip().lower()
        if topic and topic in topics:
            count += 1

    return count


def get_supporting_snippet_ids(
    *,
    parameter_path: str,
    snippets: list[dict[str, Any]] | None,
) -> list[str]:
    if not isinstance(snippets, list):
        return []

    topics = _topics_for_parameter(parameter_path)
    if not topics:
        return []

    matched_ids: list[str] = []

    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue

        metadata = snippet.get("metadata", {})
        if not isinstance(metadata, dict):
            continue

        topic = str(metadata.get("topic", "")).strip().lower()
        snippet_id = str(snippet.get("snippet_id", "")).strip()

        if topic and topic in topics and snippet_id:
            matched_ids.append(snippet_id)

    return matched_ids


def build_confidence_factors(
    *,
    parameter_path: str,
    provenance_type: str,
    provenance_ref: str | list[str],
    validation_report: dict[str, Any] | None,
    snippets: list[dict[str, Any]] | None,
    assumption_used: bool,
    derived_from_rule: bool,
) -> dict[str, Any]:
    dependency_paths = get_dependency_paths(parameter_path)
    confirmed_field_paths = collect_confirmed_field_paths(validation_report)
    conflict_field_paths = collect_conflict_field_paths(validation_report)
    missing_fields = collect_missing_fields(validation_report)

    engineer_confirmed = any(path in confirmed_field_paths for path in dependency_paths)
    conflict_present = any(path in conflict_field_paths for path in dependency_paths)
    missing_dependency = any(path in missing_fields for path in dependency_paths)

    provenance_ref_text = ""
    if isinstance(provenance_ref, str):
        provenance_ref_text = provenance_ref.lower()
    elif isinstance(provenance_ref, list):
        provenance_ref_text = " ".join(str(item).lower() for item in provenance_ref)

    uses_default_rule = (
        str(provenance_type).strip().lower() == "rule"
        and "default" in provenance_ref_text
    )

    direct_evidence_count = count_supporting_evidence(
        parameter_path=parameter_path,
        snippets=snippets if isinstance(snippets, list) else [],
    )

    return {
        "engineer_confirmed": engineer_confirmed,
        "direct_evidence_count": direct_evidence_count,
        "derived_from_rule": bool(derived_from_rule),
        "assumption_used": bool(assumption_used),
        "conflict_present": conflict_present,
        "missing_dependency": missing_dependency,
        "uses_default_rule": uses_default_rule,
    }


# services/translation_service/utils.py

def compute_confidence_score(
    *,
    provenance_type: str,
    factors: dict[str, Any],
) -> float:
    score = 0.50

    if bool(factors.get("engineer_confirmed", False)):
        score += 0.25

    evidence_count = int(factors.get("direct_evidence_count", 0))
    if evidence_count >= 2:
        score += 0.40
    elif evidence_count == 1:
        score += 0.15

    if bool(factors.get("derived_from_rule", False)):
        score += 0.10

    if bool(factors.get("conflict_present", False)):
        score -= 0.05

    if bool(factors.get("missing_dependency", False)):
        score -= 0.20

    if bool(factors.get("uses_default_rule", False)):
        score -= 0.05

    if bool(factors.get("assumption_used", False)):
        score -= 0.30

    if str(provenance_type).strip().lower() == "assumption":
        score -= 0.10

    return round(max(0.0, min(1.0, score)), 2)


def score_confidence(
    *,
    engineer_confirmed: bool,
    direct_evidence_count: int,
    derived_from_rule: bool,
    assumption_used: bool,
    conflict_present: bool,
    missing_dependency: bool,
    uses_default_rule: bool,
) -> float:
    return compute_confidence_score(
        provenance_type="rule",
        factors={
            "engineer_confirmed": engineer_confirmed,
            "direct_evidence_count": direct_evidence_count,
            "derived_from_rule": derived_from_rule,
            "assumption_used": assumption_used,
            "conflict_present": conflict_present,
            "missing_dependency": missing_dependency,
            "uses_default_rule": uses_default_rule,
        },
    )


def map_confidence_tag(score: float) -> str:
    if score >= 0.85:
        return "HIGH"
    if score >= 0.60:
        return "MODERATE"
    return "LOW"


def confidence_tag_from_score(score: float, *, needs_review: bool = False) -> str:
    if needs_review:
        return "LOW"
    return map_confidence_tag(score)