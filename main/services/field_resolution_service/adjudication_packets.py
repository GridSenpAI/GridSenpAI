from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from shared.planner_registry import resolve_registry_field
from shared.master_field_policy import field_policy_export

DEFAULT_MAX_INPUT_CHARS = 2600
DEFAULT_MAX_FIELDS_PER_PACKET = 3
DEFAULT_MAX_CANDIDATES_PER_FIELD = 3
DEFAULT_MAX_SNIPPET_CHARS = 180


@dataclass(slots=True)
class AdjudicationPacketPlan:
    status: str
    packets: list[dict[str, Any]]
    target_count: int
    omitted_target_count: int
    max_input_chars: int
    max_fields_per_packet: int
    max_candidates_per_field: int
    max_snippet_chars: int
    shrink_events: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "packets": list(self.packets),
            "packet_count": len(self.packets),
            "target_count": self.target_count,
            "omitted_target_count": self.omitted_target_count,
            "max_input_chars": self.max_input_chars,
            "max_fields_per_packet": self.max_fields_per_packet,
            "max_candidates_per_field": self.max_candidates_per_field,
            "max_snippet_chars": self.max_snippet_chars,
            "shrink_events": list(self.shrink_events),
        }


def _clean_text(value: Any, *, max_chars: int) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _field_definition(field: dict[str, Any] | None, fallback: str, *, max_chars: int) -> str:
    if isinstance(field, dict):
        for key in ("definition", "description", "field_definition", "notes", "guidance"):
            value = _clean_text(field.get(key), max_chars=max_chars)
            if value:
                return value
    return fallback


def _metadata_value(candidate: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = candidate.get(key)
        if value not in (None, "", [], {}):
            return value
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def _source_location(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    source_refs = candidate.get("source_ref") if isinstance(candidate.get("source_ref"), list) else []
    document = _metadata_value(
        candidate,
        "source_document",
        "document_name",
        "filename",
        "file_name",
        "artifact_name",
        "artifact_id",
    )
    page = _metadata_value(candidate, "source_page", "page", "page_number", "page_index")
    section = _metadata_value(candidate, "section", "source_section", "table", "row", "line", "region_id")
    if not document and source_refs:
        document = source_refs[0]
    if not page and len(source_refs) > 1:
        page = source_refs[1]
    return {
        "document": _clean_text(document, max_chars=120),
        "page": _clean_text(page, max_chars=40),
        "section_table_row_line": _clean_text(section, max_chars=140),
        "anchor": _clean_text(candidate.get("source_anchor") or metadata.get("source_anchor"), max_chars=100),
    }


def _evidence_snippet(candidate: dict[str, Any], *, max_chars: int) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for key in (
        "evidence_snippet",
        "snippet",
        "source_excerpt",
        "excerpt",
        "text_excerpt",
        "raw_text",
        "context",
        "label_context",
    ):
        value = candidate.get(key)
        if value in (None, "", [], {}):
            value = metadata.get(key)
        text = _clean_text(value, max_chars=max_chars)
        if text:
            return text
    return ""


def _candidate_score(candidate: dict[str, Any]) -> float:
    for key in ("score", "confidence", "deterministic_confidence", "accepted_confidence"):
        try:
            value = candidate.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _compact_candidate(candidate: dict[str, Any], *, max_snippet_chars: int) -> dict[str, Any]:
    return {
        "candidate_id": _clean_text(candidate.get("candidate_id"), max_chars=80),
        "value": candidate.get("value", candidate.get("accepted_value")),
        "unit": _clean_text(candidate.get("unit") or candidate.get("accepted_unit"), max_chars=40),
        "score": round(_candidate_score(candidate), 4),
        "confidence": candidate.get("confidence", candidate.get("accepted_confidence")),
        "confidence_band": _clean_text(candidate.get("confidence_band"), max_chars=40),
        "source_stage": _clean_text(candidate.get("source_stage"), max_chars=60),
        "source_stream": _clean_text(candidate.get("source_stream"), max_chars=60),
        "source_hierarchy": _clean_text(candidate.get("source_hierarchy"), max_chars=80),
        "source_type": _clean_text(candidate.get("source_type"), max_chars=80),
        "specificity": _clean_text(candidate.get("specificity"), max_chars=80),
        "source_location": _source_location(candidate),
        "evidence_snippet": _evidence_snippet(candidate, max_chars=max_snippet_chars),
        "notes": [
            _clean_text(note, max_chars=120)
            for note in candidate.get("consistency_notes", [])
            if _clean_text(note, max_chars=120)
        ][:2] if isinstance(candidate.get("consistency_notes"), list) else [],
    }


def _candidate_pool(entry: dict[str, Any], *, max_candidates: int, max_snippet_chars: int) -> list[dict[str, Any]]:
    raw_candidates: list[dict[str, Any]] = []
    if entry.get("accepted_candidate_id") or entry.get("accepted_value") is not None:
        accepted = {
            "candidate_id": entry.get("accepted_candidate_id") or "accepted_candidate",
            "value": entry.get("accepted_value"),
            "unit": entry.get("accepted_unit"),
            "score": entry.get("accepted_confidence") or 0.0,
            "confidence": entry.get("accepted_confidence"),
            "confidence_band": entry.get("confidence_band"),
            "source_hierarchy": entry.get("accepted_source_hierarchy"),
            "specificity": entry.get("accepted_specificity"),
            "source_ref": entry.get("source_ref") or entry.get("source_anchors") or [],
            "source_anchor": (entry.get("source_anchors") or [""])[0] if isinstance(entry.get("source_anchors"), list) and entry.get("source_anchors") else "",
            "metadata": {"source_anchor": (entry.get("source_anchors") or [""])[0] if isinstance(entry.get("source_anchors"), list) and entry.get("source_anchors") else ""},
        }
        raw_candidates.append(accepted)
    for key in ("candidates", "alternatives", "candidate_evidence_appendix", "supporting_sources"):
        values = entry.get(key)
        if isinstance(values, list):
            raw_candidates.extend(item for item in values if isinstance(item, dict))
    seen: set[str] = set()
    compact: list[dict[str, Any]] = []
    for candidate in sorted(raw_candidates, key=_candidate_score, reverse=True):
        signature = json.dumps(
            [candidate.get("candidate_id"), candidate.get("value", candidate.get("accepted_value")), candidate.get("source_anchor")],
            sort_keys=True,
            default=str,
        )
        if signature in seen:
            continue
        seen.add(signature)
        compact.append(_compact_candidate(candidate, max_snippet_chars=max_snippet_chars))
        if len(compact) >= max_candidates:
            break
    return compact


def _needs_adjudication(entry: dict[str, Any]) -> bool:
    status = str(entry.get("accepted_status", "")).strip().lower()
    if status in {"conflicting", "review_required"}:
        return True
    if bool(entry.get("needs_applicant_confirmation", False)):
        return True
    if str(entry.get("conflict_materiality", "")).strip().lower() in {"high", "material", "critical"}:
        return True
    if bool(entry.get("planner_review_flag", False)) and bool(entry.get("planner_critical", False)):
        return True
    alternatives = entry.get("alternatives")
    if bool(entry.get("planner_critical", False)) and isinstance(alternatives, list) and alternatives:
        return True
    return False


def _target_priority(entry: dict[str, Any]) -> tuple[int, int, int, float, str]:
    status = str(entry.get("accepted_status", "")).strip().lower()
    status_rank = {"conflicting": 0, "review_required": 1, "missing": 3, "unresolved": 4, "resolved": 6}.get(status, 5)
    planner_rank = 0 if bool(entry.get("planner_critical", False)) else 1
    materiality = str(entry.get("conflict_materiality", "")).strip().lower()
    materiality_rank = {"high": 0, "material": 0, "critical": 0, "moderate": 1, "low": 3, "none": 5}.get(materiality, 4)
    confidence = entry.get("accepted_confidence")
    try:
        confidence_rank = float(confidence)
    except (TypeError, ValueError):
        confidence_rank = -1.0
    return (planner_rank, status_rank, materiality_rank, -confidence_rank, str(entry.get("field_path") or entry.get("field_id") or ""))


def _compact_field(entry: dict[str, Any], *, max_candidates: int, max_snippet_chars: int) -> dict[str, Any]:
    field_key = str(entry.get("field_path") or entry.get("field_id") or "").strip()
    registry = resolve_registry_field(field_key) or resolve_registry_field(entry.get("field_id"))
    expected_type = ""
    expected_unit = ""
    aliases: list[str] = []
    if isinstance(registry, dict):
        expected_type = _clean_text(registry.get("data_type") or registry.get("type"), max_chars=60)
        expected_unit = _clean_text(registry.get("units") or registry.get("unit"), max_chars=40)
        raw_aliases = registry.get("aliases") or registry.get("alternate_labels") or []
        if isinstance(raw_aliases, list):
            aliases = [_clean_text(value, max_chars=60) for value in raw_aliases if _clean_text(value, max_chars=60)][:5]
    candidates = _candidate_pool(entry, max_candidates=max_candidates, max_snippet_chars=max_snippet_chars)
    policy = field_policy_export(field_key or entry.get("field_id"))
    return {
        "field_policy": {
            "policy_family": policy.get("policy_family", "general"),
            "accepted_contexts": policy.get("accepted_contexts", [])[:6],
            "rejected_contexts": policy.get("rejected_contexts", [])[:6],
            "preferred_source_roles": policy.get("preferred_source_roles", {}),
            "minimum_confidence_for_auto_accept": policy.get("minimum_confidence_for_auto_accept", ""),
        },
        "field_id": _clean_text(entry.get("field_id"), max_chars=100),
        "field_path": _clean_text(entry.get("field_path"), max_chars=140),
        "field_label": _clean_text(entry.get("label"), max_chars=140),
        "field_definition": _field_definition(registry, _clean_text(entry.get("decision_basis") or entry.get("label"), max_chars=220), max_chars=260),
        "expected_type": expected_type or _clean_text(policy.get("data_type"), max_chars=60),
        "expected_unit": expected_unit or _clean_text(policy.get("expected_unit"), max_chars=40) or _clean_text(entry.get("accepted_unit"), max_chars=40),
        "aliases": aliases,
        "current_status": _clean_text(entry.get("accepted_status"), max_chars=60),
        "current_accepted_value": entry.get("accepted_value"),
        "current_confidence": entry.get("accepted_confidence"),
        "confidence_band": _clean_text(entry.get("confidence_band"), max_chars=40),
        "planner_critical": bool(entry.get("planner_critical", False)),
        "requiredness": _clean_text(entry.get("requiredness"), max_chars=40),
        "conflict_reason": _clean_text(
            entry.get("contradiction_summary") or entry.get("unresolved_reason") or entry.get("decision_basis"),
            max_chars=240,
        ),
        "candidates": candidates,
        "question_for_llm": (
            "Review the compact candidates only. Identify whether the current accepted value should remain planner-visible, "
            "whether applicant confirmation is needed, and whether any hidden conflict/manual-review note should be preserved. "
            "Do not overwrite deterministic values."
        ),
    }


def _packet_input(summary: dict[str, Any], fields: list[dict[str, Any]], packet_index: int) -> dict[str, Any]:
    return {
        "adjudication_packet_version": "field_compact_v1",
        "packet_index": packet_index,
        "field_resolution_summary": summary,
        "adjudication_targets": fields,
        "instruction": (
            "Use only these compact field-level candidates. Return advisory per_field_adjudication notes; "
            "do not request deterministic overrides and do not infer from missing full documents."
        ),
    }


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))


def build_adjudication_packet_plan(
    *,
    ledger: list[dict[str, Any]],
    summary: dict[str, Any],
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    max_fields_per_packet: int = DEFAULT_MAX_FIELDS_PER_PACKET,
    max_candidates_per_field: int = DEFAULT_MAX_CANDIDATES_PER_FIELD,
    max_snippet_chars: int = DEFAULT_MAX_SNIPPET_CHARS,
    max_packets: int = 6,
) -> AdjudicationPacketPlan:
    targets = [dict(item) for item in ledger if isinstance(item, dict) and _needs_adjudication(item)]
    targets.sort(key=_target_priority)
    shrink_events: list[str] = []
    packets: list[dict[str, Any]] = []
    cursor = 0
    packet_index = 1
    while cursor < len(targets) and len(packets) < max_packets:
        fields: list[dict[str, Any]] = []
        for entry in targets[cursor: cursor + max_fields_per_packet]:
            fields.append(_compact_field(entry, max_candidates=max_candidates_per_field, max_snippet_chars=max_snippet_chars))
        cursor += max_fields_per_packet
        if not fields:
            continue
        candidate_cap = max_candidates_per_field
        snippet_cap = max_snippet_chars
        while True:
            payload = _packet_input(summary, fields, packet_index)
            if _json_size(payload) <= max_input_chars:
                packets.append(payload)
                packet_index += 1
                break
            if candidate_cap > 1:
                candidate_cap -= 1
                fields = [_compact_field(entry, max_candidates=candidate_cap, max_snippet_chars=snippet_cap) for entry in targets[cursor - max_fields_per_packet: cursor][: len(fields)]]
                shrink_events.append(f"packet_{packet_index}: reduced candidates to {candidate_cap}")
                continue
            if snippet_cap > 60:
                snippet_cap = max(60, snippet_cap // 2)
                fields = [_compact_field(entry, max_candidates=candidate_cap, max_snippet_chars=snippet_cap) for entry in targets[cursor - max_fields_per_packet: cursor][: len(fields)]]
                shrink_events.append(f"packet_{packet_index}: reduced snippets to {snippet_cap} chars")
                continue
            if len(fields) > 1:
                cursor -= len(fields) - 1
                fields = fields[:1]
                shrink_events.append(f"packet_{packet_index}: split to one field")
                continue
            # Last resort: preserve one candidate and no long snippets instead of sending an oversized request.
            field = fields[0]
            if isinstance(field.get("candidates"), list):
                field["candidates"] = field["candidates"][:1]
                for candidate in field["candidates"]:
                    if isinstance(candidate, dict):
                        candidate["evidence_snippet"] = _clean_text(candidate.get("evidence_snippet"), max_chars=60)
            field["field_definition"] = _clean_text(field.get("field_definition"), max_chars=120)
            field["conflict_reason"] = _clean_text(field.get("conflict_reason"), max_chars=120)
            payload = _packet_input(summary, [field], packet_index)
            if _json_size(payload) <= max_input_chars:
                packets.append(payload)
                packet_index += 1
            else:
                shrink_events.append(f"packet_{packet_index}: omitted field after compacting below minimum caps")
            break
    omitted = max(0, len(targets) - cursor)
    if not targets:
        status = "ADJUDICATION_SKIPPED_NO_CONFLICTS"
    elif packets and omitted:
        status = "ADJUDICATION_PARTIAL"
    elif packets:
        status = "ADJUDICATION_PACKETS_READY"
    else:
        status = "ADJUDICATION_BLOCKED_PROMPT_TOO_LARGE"
    return AdjudicationPacketPlan(
        status=status,
        packets=packets,
        target_count=len(targets),
        omitted_target_count=omitted,
        max_input_chars=max_input_chars,
        max_fields_per_packet=max_fields_per_packet,
        max_candidates_per_field=max_candidates_per_field,
        max_snippet_chars=max_snippet_chars,
        shrink_events=shrink_events,
    )
