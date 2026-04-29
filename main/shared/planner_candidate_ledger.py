from __future__ import annotations

"""Registry-first candidate ledger helpers.

The planner-required-fields registry is the target contract for extraction and
normalization.  This module builds deterministic worklists and candidate buckets
from that registry so upstream stages can reason in terms of master planner
fields before the final planner ledger is exported.
"""

from typing import Any

from shared.field_value_policies import (
    candidate_is_rejected_for_field,
    context_adjustment,
    normalization_authority_score,
    source_role_from_candidate,
)
from shared.master_field_policy import field_policy_export
from shared.planner_field_workflow import registry_field_work_items
from shared.planner_registry import (
    field_path_for_registry_field_id,
    registry_field_id_for_path,
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _numeric_confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        score = float(value)
        if score > 1.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))
    text = _lower(value)
    if text in {"high", "accepted", "direct_document_fact", "validated_applicant_answer"}:
        return 0.9
    if text in {"moderate", "medium", "candidate_only", "retrieved_candidate"}:
        return 0.65
    if text in {"low", "weak", "review_required", "conflicting"}:
        return 0.35
    if text in {"unresolved", "missing", "none"}:
        return 0.0
    return 0.5


def _confidence_label(score: float) -> str:
    if score >= 0.85:
        return "HIGH"
    if score >= 0.6:
        return "MODERATE"
    if score > 0:
        return "LOW"
    return "UNRESOLVED"


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def _candidate_text_blob(candidate: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "field_path",
        "field_id",
        "label",
        "method",
        "source_method",
        "source_role",
        "document_role",
        "source_document",
        "source_file_name",
        "file_name",
        "evidence_snippet",
        "snippet",
        "text",
        "section",
        "table",
        "row_label",
    ):
        value = candidate.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value[:5])
        elif value not in (None, "", [], {}):
            parts.append(str(value))
    evidence = candidate.get("evidence")
    if isinstance(evidence, list):
        for item in evidence[:3]:
            if isinstance(item, dict):
                parts.append(str(_first_present(item, ("snippet", "text", "excerpt", "line_text"))))
    return " ".join(part for part in parts if part).strip()


def _source_page(candidate: dict[str, Any]) -> str:
    value = _first_present(candidate, ("page_number", "page", "source_page"))
    if value not in (None, ""):
        return _clean(value)
    evidence = candidate.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                page = _first_present(item, ("page_number", "page", "source_page"))
                if page not in (None, ""):
                    return _clean(page)
    return ""


def _source_document(candidate: dict[str, Any]) -> str:
    value = _first_present(
        candidate,
        ("source_document", "source_file_name", "file_name", "artifact_name", "document_name", "artifact_id", "source_artifact_id"),
    )
    if value:
        return _clean(value)
    evidence = candidate.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                document = _first_present(item, ("source_document", "source_file_name", "file_name", "artifact_id"))
                if document:
                    return _clean(document)
    return ""


def _evidence_snippet(candidate: dict[str, Any], *, max_chars: int = 500) -> str:
    value = _first_present(candidate, ("evidence_snippet", "snippet", "text", "excerpt", "line_text"))
    if not value:
        evidence = candidate.get("evidence")
        if isinstance(evidence, list):
            for item in evidence:
                if isinstance(item, dict):
                    value = _first_present(item, ("snippet", "text", "excerpt", "line_text"))
                    if value:
                        break
    text = " ".join(str(value or "").split())
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _candidate_field_id(candidate: dict[str, Any]) -> str:
    raw = _clean(candidate.get("field_id")) or _clean(candidate.get("registry_field_id"))
    if raw:
        resolved = registry_field_id_for_path(raw) or raw
        return resolved
    raw_path = _clean(candidate.get("field_path")) or _clean(candidate.get("target_field"))
    return registry_field_id_for_path(raw_path)


def _candidate_field_path(candidate: dict[str, Any], field_id: str) -> str:
    raw_path = _clean(candidate.get("field_path")) or _clean(candidate.get("target_field"))
    if raw_path and "." in raw_path:
        return raw_path
    return field_path_for_registry_field_id(field_id) or field_id


def _candidate_authority(candidate: dict[str, Any], field_path: str) -> int:
    try:
        score_tuple = normalization_authority_score(field_path, candidate)
        if isinstance(score_tuple, tuple) and score_tuple:
            return int(score_tuple[0])
    except Exception:
        pass
    return 0


def _candidate_authority_details(candidate: dict[str, Any], field_path: str) -> tuple[int, list[str], bool]:
    try:
        adjustment, notes, rejected = context_adjustment(field_path, candidate)
        return int(adjustment), list(notes), bool(rejected)
    except Exception:
        return _candidate_authority(candidate, field_path), [], False


def build_registry_extraction_worklist(*, include_optional: bool = True) -> list[dict[str, Any]]:
    """Build one extraction/normalization target per registry field."""
    worklist: list[dict[str, Any]] = []
    for item in registry_field_work_items(include_optional=include_optional):
        if not isinstance(item, dict):
            continue
        field_id = _clean(item.get("field_id"))
        field_path = _clean(item.get("field_path")) or field_id
        if not field_id:
            continue
        policy = field_policy_export(field_path or field_id)
        aliases = []
        for key in ("search_keywords", "accepted_contexts"):
            value = item.get(key) or policy.get(key)
            if isinstance(value, list):
                aliases.extend(_clean(alias) for alias in value if _clean(alias))
        aliases.extend(_clean(value) for value in (field_id, field_path, item.get("field_label")) if _clean(value))
        deduped_aliases: list[str] = []
        seen: set[str] = set()
        for alias in aliases:
            lowered = alias.lower()
            if lowered not in seen:
                seen.add(lowered)
                deduped_aliases.append(alias)
        worklist.append(
            {
                "field_id": field_id,
                "field_path": field_path,
                "field_label": _clean(item.get("field_label")) or field_id,
                "expected_data_type": _clean(item.get("expected_data_type")) or _clean(policy.get("data_type")),
                "expected_unit": _clean(item.get("expected_unit")) or _clean(policy.get("expected_unit")),
                "policy_family": _clean(item.get("policy_family")) or _clean(policy.get("policy_family")) or "general",
                "requiredness": _clean(item.get("requiredness")) or "optional",
                "planner_critical": bool(item.get("planner_critical")),
                "packet_section": _clean(item.get("packet_section")),
                "group": _clean(item.get("group")),
                "aliases": deduped_aliases[:25],
                "accepted_contexts": list(policy.get("accepted_contexts", [])) if isinstance(policy.get("accepted_contexts"), list) else [],
                "rejected_contexts": list(policy.get("rejected_contexts", [])) if isinstance(policy.get("rejected_contexts"), list) else [],
                "preferred_source_roles": dict(policy.get("preferred_source_roles", {})) if isinstance(policy.get("preferred_source_roles"), dict) else {},
                "workflow_status": "TARGETED",
            }
        )
    return worklist


def build_registry_candidate_ledger(
    *,
    schema_field_candidates: list[dict[str, Any]] | None = None,
    normalized_input: dict[str, Any] | None = None,
    accepted_updates: list[dict[str, Any]] | None = None,
    rejected_updates: list[dict[str, Any]] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    include_optional: bool = True,
    max_candidates_per_field: int = 12,
) -> dict[str, Any]:
    """Bucket extraction/normalization candidates under every master registry field."""
    rows_by_id: dict[str, dict[str, Any]] = {}
    for target in build_registry_extraction_worklist(include_optional=include_optional):
        field_id = _clean(target.get("field_id"))
        if not field_id:
            continue
        rows_by_id[field_id] = {
            **target,
            "candidates": [],
            "candidate_count": 0,
            "rejected_candidate_count": 0,
            "conflict_count": 0,
            "accepted_value": None,
            "accepted_source": {},
            "status": "MISSING",
        }

    candidates = [item for item in (schema_field_candidates or []) if isinstance(item, dict)]
    for index, candidate in enumerate(candidates, start=1):
        field_id = _candidate_field_id(candidate)
        if not field_id or field_id not in rows_by_id:
            continue
        row = rows_by_id[field_id]
        field_path = _candidate_field_path(candidate, field_id)
        confidence_score = _numeric_confidence(candidate.get("confidence", candidate.get("confidence_score", "")))
        source_role = source_role_from_candidate(candidate) or _clean(candidate.get("source_role")) or "unknown"
        authority_score, authority_notes, authority_rejected = _candidate_authority_details(candidate, field_path)
        rejected = bool(authority_rejected or candidate_is_rejected_for_field(field_path, candidate))
        candidate_record = {
            "candidate_id": _clean(candidate.get("candidate_id")) or f"registry_candidate::{field_id}::{index:04d}",
            "field_id": field_id,
            "field_path": field_path,
            "value": candidate.get("value", candidate.get("candidate_value")),
            "normalized_value": candidate.get("normalized_value"),
            "confidence_score": confidence_score,
            "confidence_label": _confidence_label(confidence_score),
            "authority_score": authority_score,
            "authority_adjustment": authority_score,
            "authority_notes": authority_notes[:6],
            "policy_authority_note": "; ".join(authority_notes[:3]),
            "source_role": source_role,
            "source_document": _source_document(candidate),
            "source_page": _source_page(candidate),
            "source_section": _clean(_first_present(candidate, ("section", "source_section", "table", "row_label", "line_label"))),
            "source_anchor_id": _clean(_first_present(candidate, ("source_anchor_id", "anchor_id", "artifact_id", "source_artifact_id"))),
            "method": _clean(_first_present(candidate, ("method", "source_method"))),
            "evidence_snippet": _evidence_snippet(candidate),
            "rejected_by_field_policy": bool(rejected),
            "field_policy_reason": "Rejected by field accepted/rejected-context/source-authority policy." if rejected else "Candidate remains eligible for normalization/adjudication.",
        }
        row["candidates"].append(candidate_record)
        row["candidate_count"] += 1
        if rejected:
            row["rejected_candidate_count"] += 1

    for row in rows_by_id.values():
        row["candidates"].sort(
            key=lambda item: (
                int(item.get("rejected_by_field_policy", False)) * -1,
                float(item.get("authority_score", 0)),
                float(item.get("confidence_score", 0.0)),
            ),
            reverse=True,
        )
        if max_candidates_per_field > 0:
            row["candidates"] = row["candidates"][:max_candidates_per_field]

    normalized = normalized_input if isinstance(normalized_input, dict) else {}
    planner_values = normalized.get("planner_field_values", {})
    planner_sources = normalized.get("planner_field_sources", {})
    if not isinstance(planner_values, dict):
        planner_values = {}
    if not isinstance(planner_sources, dict):
        planner_sources = {}

    for field_id, value in planner_values.items():
        key = _clean(field_id)
        if key in rows_by_id and value not in (None, "", [], {}):
            rows_by_id[key]["accepted_value"] = value
            rows_by_id[key]["accepted_source"] = planner_sources.get(key, {}) if isinstance(planner_sources.get(key), dict) else {}
            rows_by_id[key]["status"] = "ACCEPTED_BY_NORMALIZATION"

    for update in accepted_updates or []:
        if not isinstance(update, dict):
            continue
        field_id = registry_field_id_for_path(update.get("field_path")) or _clean(update.get("field_id"))
        if field_id in rows_by_id and update.get("accepted_value") not in (None, "", [], {}):
            rows_by_id[field_id]["accepted_value"] = update.get("accepted_value")
            rows_by_id[field_id]["accepted_source"] = {
                "source_type": update.get("source_type"),
                "source_name": update.get("source_name"),
                "source_anchor_id": update.get("source_anchor_id"),
                "confidence": update.get("confidence"),
                "decision": update.get("decision"),
                "reason": update.get("reason"),
            }
            rows_by_id[field_id]["status"] = "ACCEPTED_BY_NORMALIZATION"

    for update in rejected_updates or []:
        if not isinstance(update, dict):
            continue
        field_id = registry_field_id_for_path(update.get("field_path")) or _clean(update.get("field_id"))
        if field_id in rows_by_id:
            rows_by_id[field_id]["rejected_candidate_count"] += 1

    for conflict in conflicts or []:
        if not isinstance(conflict, dict):
            continue
        field_id = registry_field_id_for_path(conflict.get("field_path")) or _clean(conflict.get("field_id"))
        if field_id in rows_by_id:
            rows_by_id[field_id]["conflict_count"] += 1
            if rows_by_id[field_id]["status"] == "ACCEPTED_BY_NORMALIZATION":
                rows_by_id[field_id]["status"] = "ACCEPTED_WITH_CONFLICT"
            else:
                rows_by_id[field_id]["status"] = "CONFLICTING_CANDIDATES"

    rows = list(rows_by_id.values())
    rows.sort(key=lambda row: (_clean(row.get("packet_section")), _clean(row.get("group")), _clean(row.get("field_id"))))
    summary = {
        "registry_field_count": len(rows),
        "field_count_with_candidates": len([row for row in rows if int(row.get("candidate_count", 0)) > 0]),
        "field_count_with_accepted_values": len([row for row in rows if row.get("accepted_value") not in (None, "", [], {})]),
        "missing_field_count": len([row for row in rows if row.get("status") == "MISSING"]),
        "conflicting_field_count": len([row for row in rows if int(row.get("conflict_count", 0)) > 0]),
        "rejected_candidate_count": sum(int(row.get("rejected_candidate_count", 0)) for row in rows),
        "registry_first_bridge": True,
    }
    return {"planner_candidate_ledger": rows, "planner_candidate_ledger_summary": summary}
