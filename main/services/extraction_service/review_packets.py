from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from shared.master_field_policy import field_policy_export
from shared.planner_registry import resolve_registry_field

DEFAULT_MAX_INPUT_CHARS = 3200
DEFAULT_MAX_FIELDS_PER_PACKET = 5
DEFAULT_MAX_CANDIDATES_PER_FIELD = 4
DEFAULT_MAX_SNIPPET_CHARS = 220
DEFAULT_MAX_PACKETS = 6


@dataclass(slots=True)
class ExtractionReviewPacketPlan:
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


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))


def _metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    evidence_metadata = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
    merged: dict[str, Any] = {}
    merged.update(evidence_metadata)
    merged.update(metadata)
    return merged


def _first_value(candidate: dict[str, Any], metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = candidate.get(key)
        if value not in (None, "", [], {}):
            return value
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    for key in keys:
        value = evidence.get(key)
        if value not in (None, "", [], {}):
            return value
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def _artifact_lookup(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = _clean_text(artifact.get("artifact_id") or artifact.get("id"), max_chars=120)
        if artifact_id:
            lookup[artifact_id] = artifact
    return lookup


def _artifact_summary(candidate: dict[str, Any], artifacts_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metadata = _metadata(candidate)
    artifact_id = _clean_text(
        _first_value(candidate, metadata, "artifact_id", "source_artifact_id", "document_id"),
        max_chars=120,
    )
    artifact = artifacts_by_id.get(artifact_id, {})
    document = _first_value(
        candidate,
        metadata,
        "source_document",
        "document_name",
        "filename",
        "file_name",
        "artifact_name",
    )
    if not document and isinstance(artifact, dict):
        document = artifact.get("filename") or artifact.get("file_name") or artifact.get("name") or artifact_id
    return {
        "artifact_id": artifact_id,
        "document": _clean_text(document or artifact_id, max_chars=140),
        "page": _clean_text(_first_value(candidate, metadata, "page", "page_number", "source_page"), max_chars=40),
        "section_table_row_line": _clean_text(
            _first_value(candidate, metadata, "section", "source_section", "table", "row", "line", "region_id", "parser_block_id"),
            max_chars=160,
        ),
        "source_role": _clean_text(_first_value(candidate, metadata, "source_role", "document_role", "artifact_type", "classification"), max_chars=80),
    }


def _evidence_snippet(candidate: dict[str, Any], *, max_chars: int) -> str:
    metadata = _metadata(candidate)
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    for key in (
        "evidence_snippet",
        "snippet",
        "source_excerpt",
        "excerpt",
        "text_excerpt",
        "label_context",
        "context",
        "raw_text",
        "text",
    ):
        for container in (candidate, evidence, metadata):
            value = container.get(key) if isinstance(container, dict) else None
            text = _clean_text(value, max_chars=max_chars)
            if text:
                return text
    return ""


def _candidate_score(candidate: dict[str, Any]) -> float:
    for key in ("deterministic_confidence", "adjusted_confidence", "score", "confidence"):
        try:
            value = candidate.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _normal_value_key(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(round(float(value), 6))
    return _clean_text(value, max_chars=160).lower().replace(",", "")


def _field_definition(field_path: str, *, max_chars: int) -> tuple[str, str, str, list[str]]:
    registry = resolve_registry_field(field_path)
    if not isinstance(registry, dict):
        return "", "", "unknown", "", []
    label = _clean_text(registry.get("label") or registry.get("name") or field_path, max_chars=140)
    definition = ""
    for key in ("definition", "description", "field_definition", "notes", "guidance"):
        definition = _clean_text(registry.get(key), max_chars=max_chars)
        if definition:
            break
    expected_type = _clean_text(registry.get("data_type") or registry.get("type"), max_chars=60)
    expected_unit = _clean_text(registry.get("units") or registry.get("unit"), max_chars=40)
    aliases_raw = registry.get("aliases") or registry.get("alternate_labels") or []
    aliases: list[str] = []
    if isinstance(aliases_raw, list):
        aliases = [_clean_text(alias, max_chars=70) for alias in aliases_raw if _clean_text(alias, max_chars=70)][:5]
    return label, definition, expected_type or "unknown", expected_unit, aliases


def _compact_candidate(candidate: dict[str, Any], artifacts_by_id: dict[str, dict[str, Any]], *, max_snippet_chars: int) -> dict[str, Any]:
    metadata = _metadata(candidate)
    return {
        "candidate_id": _clean_text(_first_value(candidate, metadata, "candidate_id", "id"), max_chars=100),
        "field_path": _clean_text(candidate.get("field_path"), max_chars=140),
        "value": candidate.get("value"),
        "unit": _clean_text(_first_value(candidate, metadata, "unit", "units"), max_chars=40),
        "confidence": round(_candidate_score(candidate), 4),
        "method": _clean_text(candidate.get("method") or candidate.get("source_method"), max_chars=100),
        "source": _artifact_summary(candidate, artifacts_by_id),
        "evidence_snippet": _evidence_snippet(candidate, max_chars=max_snippet_chars),
        "policy_notes": [
            _clean_text(note, max_chars=140)
            for note in (
                candidate.get("policy_notes") if isinstance(candidate.get("policy_notes"), list) else []
            )
        ][:3],
    }


def _group_candidates(schema_field_candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in schema_field_candidates:
        if not isinstance(candidate, dict):
            continue
        field_path = _clean_text(candidate.get("field_path"), max_chars=180)
        if not field_path:
            continue
        grouped.setdefault(field_path, []).append(candidate)
    return grouped


def _field_needs_review(field_path: str, candidates: list[dict[str, Any]]) -> bool:
    if not candidates:
        return False
    ranked = sorted(candidates, key=_candidate_score, reverse=True)
    best = ranked[0]
    best_score = _candidate_score(best)
    if best_score < 0.60:
        return True
    values = {_normal_value_key(candidate.get("value")) for candidate in ranked if _candidate_score(candidate) >= 0.55}
    values.discard("")
    if len(values) > 1:
        return True
    if len(ranked) > 1 and (_candidate_score(ranked[0]) - _candidate_score(ranked[1])) < 0.08:
        return True
    return False


def _target_priority(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, float, str]:
    field_path, candidates = item
    policy = field_policy_export(field_path)
    critical = 0 if str(policy.get("requiredness", "")).lower() in {"required", "mandatory"} else 1
    best_score = max((_candidate_score(candidate) for candidate in candidates), default=0.0)
    return (critical, best_score, field_path)


def _compact_field(field_path: str, candidates: list[dict[str, Any]], artifacts_by_id: dict[str, dict[str, Any]], *, max_candidates: int, max_snippet_chars: int) -> dict[str, Any]:
    label, definition, expected_type, expected_unit, aliases = _field_definition(field_path, max_chars=260)
    policy = field_policy_export(field_path)
    compact_candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=_candidate_score, reverse=True):
        signature = json.dumps([candidate.get("value"), candidate.get("artifact_id"), candidate.get("method")], sort_keys=True, default=str)
        if signature in seen:
            continue
        seen.add(signature)
        compact_candidates.append(_compact_candidate(candidate, artifacts_by_id, max_snippet_chars=max_snippet_chars))
        if len(compact_candidates) >= max_candidates:
            break
    return {
        "field_path": field_path,
        "field_label": label or field_path,
        "field_definition": definition,
        "expected_type": expected_type,
        "expected_unit": expected_unit or _clean_text(policy.get("expected_unit"), max_chars=40),
        "aliases": aliases,
        "field_policy": {
            "policy_family": policy.get("policy_family", "general"),
            "accepted_contexts": list(policy.get("accepted_contexts", []))[:6] if isinstance(policy.get("accepted_contexts"), list) else [],
            "rejected_contexts": list(policy.get("rejected_contexts", []))[:6] if isinstance(policy.get("rejected_contexts"), list) else [],
            "preferred_source_roles": policy.get("preferred_source_roles", {}),
        },
        "candidate_count": len(candidates),
        "candidates": compact_candidates,
        "question_for_llm": (
            "Using only these compact extraction candidates, identify the best candidate for this master field, "
            "whether evidence is too weak/conflicting, and what follow-up is needed. Do not infer from full documents."
        ),
    }


def _packet_input(fields: list[dict[str, Any]], packet_index: int, warnings: list[str], coverage_gaps: list[str]) -> dict[str, Any]:
    return {
        "extraction_review_packet_version": "field_compact_v1",
        "packet_index": packet_index,
        "instruction": (
            "Review only these compact field-level extraction candidates. Return advisory candidate rankings, conflict notes, "
            "and follow-up recommendations. Do not request or rely on full artifacts or raw extraction blobs."
        ),
        "warnings": [_clean_text(warning, max_chars=160) for warning in warnings[:6]],
        "coverage_gaps_sample": [_clean_text(field, max_chars=140) for field in coverage_gaps[:12]],
        "review_targets": fields,
    }


def build_extraction_review_packet_plan(
    *,
    artifacts: list[dict[str, Any]],
    schema_field_candidates: list[dict[str, Any]],
    warnings: list[str],
    uncovered_planner_registry_fields: list[str],
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    max_fields_per_packet: int = DEFAULT_MAX_FIELDS_PER_PACKET,
    max_candidates_per_field: int = DEFAULT_MAX_CANDIDATES_PER_FIELD,
    max_snippet_chars: int = DEFAULT_MAX_SNIPPET_CHARS,
    max_packets: int = DEFAULT_MAX_PACKETS,
) -> ExtractionReviewPacketPlan:
    artifacts_by_id = _artifact_lookup(artifacts)
    grouped = _group_candidates(schema_field_candidates)
    targets = [item for item in grouped.items() if _field_needs_review(item[0], item[1])]
    targets.sort(key=_target_priority)
    shrink_events: list[str] = []
    packets: list[dict[str, Any]] = []
    cursor = 0
    packet_index = 1
    while cursor < len(targets) and len(packets) < max_packets:
        target_slice = targets[cursor: cursor + max_fields_per_packet]
        cursor += max_fields_per_packet
        if not target_slice:
            continue
        candidate_cap = max_candidates_per_field
        snippet_cap = max_snippet_chars
        field_cap = len(target_slice)
        while True:
            fields = [
                _compact_field(field_path, candidates, artifacts_by_id, max_candidates=candidate_cap, max_snippet_chars=snippet_cap)
                for field_path, candidates in target_slice[:field_cap]
            ]
            payload = _packet_input(fields, packet_index, warnings, uncovered_planner_registry_fields)
            if _json_size(payload) <= max_input_chars:
                packets.append(payload)
                packet_index += 1
                break
            if candidate_cap > 1:
                candidate_cap -= 1
                shrink_events.append(f"packet_{packet_index}: reduced candidates to {candidate_cap}")
                continue
            if snippet_cap > 60:
                snippet_cap = max(60, snippet_cap // 2)
                shrink_events.append(f"packet_{packet_index}: reduced snippets to {snippet_cap} chars")
                continue
            if field_cap > 1:
                cursor -= field_cap - 1
                field_cap = 1
                shrink_events.append(f"packet_{packet_index}: split to one field")
                continue
            # Last resort: preserve the field and value/source facts but remove optional prose.
            fields = [
                _compact_field(target_slice[0][0], target_slice[0][1], artifacts_by_id, max_candidates=1, max_snippet_chars=40)
            ]
            field = fields[0]
            field["field_definition"] = _clean_text(field.get("field_definition"), max_chars=80)
            field["aliases"] = []
            field["field_policy"] = {"policy_family": field.get("field_policy", {}).get("policy_family", "general")}
            payload = _packet_input(fields, packet_index, [], uncovered_planner_registry_fields[:3])
            packets.append(payload)
            shrink_events.append(f"packet_{packet_index}: last-resort compact packet size {_json_size(payload)} chars")
            packet_index += 1
            break
    status = "NO_REVIEW_TARGETS" if not targets else "READY" if packets else "NO_PACKETS_BUILT"
    return ExtractionReviewPacketPlan(
        status=status,
        packets=packets,
        target_count=len(targets),
        omitted_target_count=max(0, len(targets) - cursor),
        max_input_chars=max_input_chars,
        max_fields_per_packet=max_fields_per_packet,
        max_candidates_per_field=max_candidates_per_field,
        max_snippet_chars=max_snippet_chars,
        shrink_events=shrink_events,
    )
