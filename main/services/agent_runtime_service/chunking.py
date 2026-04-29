from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DOMAIN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("project_identity", ("project", "applicant", "customer", "identity", "name", "site")),
    ("load_and_demand", ("load", "demand", "mw", "mva", "power", "pf", "power_factor")),
    ("poi_and_voltage", ("poi", "point_of_interconnection", "voltage", "kv", "substation", "bus")),
    ("equipment", ("generator", "transformer", "ups", "battery", "ats", "switchgear", "motor", "equipment")),
    ("protection_controls", ("protection", "relay", "control", "fault", "settings")),
    ("telemetry_scada", ("telemetry", "scada", "meter", "metering", "rtu")),
    ("energization_schedule", ("energization", "in_service", "service_date", "commissioning", "cod", "schedule", "phase")),
    ("retrieval_evidence", ("retrieval", "snippet", "source", "evidence", "corpus", "query", "vendor", "official")),
    ("normalization_quality", ("normalization", "normalized", "schema", "validation", "missing", "contamination")),
    ("adjudication_conflicts", ("adjudication", "conflict", "candidate", "runner", "accepted", "confidence")),
    ("translation_parameters", ("translation", "steady_state", "zip", "reactive", "parameter", "scenario")),
    ("planner_packet_review", ("packet", "export", "readiness", "manifest", "coverage", "release")),
    ("unresolved_fields", ("unresolved", "blocked", "manual_review", "question", "interview")),
)

HEAVY_KEYS: set[str] = {
    "raw_text",
    "full_text",
    "page_text",
    "ocr_text",
    "document_text",
    "full_packet_text",
    "planner_packet_body",
    "canonical_state",
    "normalized_input",
    "extraction_result",
    "ocr_result",
    "artifacts",
    "pages",
}

@dataclass(slots=True)
class AdvisoryChunk:
    chunk_id: str
    agent_id: str
    agent_family_id: str
    stage_name: str
    task_name: str
    domain: str
    field_paths: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    estimated_chars: int = 0
    max_prompt_chars: int = 0
    source_section_names: list[str] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "agent_id": self.agent_id,
            "agent_family_id": self.agent_family_id,
            "stage_name": self.stage_name,
            "task_name": self.task_name,
            "domain": self.domain,
            "field_paths": list(self.field_paths),
            "payload": self.payload,
            "estimated_chars": self.estimated_chars,
            "max_prompt_chars": self.max_prompt_chars,
            "source_section_names": list(self.source_section_names),
            "lineage": dict(self.lineage),
        }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def estimate_prompt_chars(payload: Any) -> int:
    try:
        return len(json.dumps(json_safe(payload), sort_keys=True, ensure_ascii=False, default=str))
    except Exception:
        return len(str(payload))


def truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3] + "..."


def _looks_like_field_path(value: Any) -> bool:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > 220:
        return False
    if " " in cleaned or "\n" in cleaned or "\r" in cleaned or "\t" in cleaned:
        return False
    if "." not in cleaned:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_.:\-\[\]]+", cleaned))


def _field_path_from_item(item: Any) -> str:
    if isinstance(item, str):
        cleaned = item.strip()
        return cleaned if _looks_like_field_path(cleaned) else ""
    if not isinstance(item, dict):
        return ""
    for key in ("field_path", "field_id", "target_field", "registry_field_path", "path"):
        value = item.get(key)
        if isinstance(value, str) and _looks_like_field_path(value):
            return value.strip()
    return ""


def infer_domain(name: Any, payload: Any = None) -> str:
    haystack = str(name or "").lower()
    if isinstance(payload, dict):
        sample = " ".join(str(k) for k in list(payload.keys())[:20])
        haystack += " " + sample.lower()
        haystack += " " + _field_path_from_item(payload).lower()
    elif isinstance(payload, str):
        haystack += " " + payload[:300].lower()
    for domain, keywords in DOMAIN_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return domain
    return "miscellaneous"


def cap_evidence(value: Any, *, max_evidence_chars: int = 1200, max_list_items: int = 8, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated:max_depth]"
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, child in value.items():
            key_str = str(key)
            if key_str in HEAVY_KEYS:
                compact[key_str] = truncate_text(child, max_evidence_chars)
                continue
            compact[key_str] = cap_evidence(child, max_evidence_chars=max_evidence_chars, max_list_items=max_list_items, depth=depth + 1)
        return compact
    if isinstance(value, list):
        retained = [cap_evidence(item, max_evidence_chars=max_evidence_chars, max_list_items=max_list_items, depth=depth + 1) for item in value[:max_list_items]]
        if len(value) > max_list_items:
            retained.append({"_truncated": True, "original_count": len(value), "retained_count": max_list_items})
        return retained
    if isinstance(value, tuple):
        return cap_evidence(list(value), max_evidence_chars=max_evidence_chars, max_list_items=max_list_items, depth=depth)
    if isinstance(value, str):
        return truncate_text(value, max_evidence_chars if depth >= 2 else max_evidence_chars * 2)
    return value


def _append_to_domain(domain_map: dict[str, list[tuple[str, Any]]], domain: str, key: str, value: Any) -> None:
    domain_map.setdefault(domain, []).append((key, value))


def _iter_rows_from_inputs(inputs: dict[str, Any]) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    row_keys = {"ledger", "rows", "planner_field_ledger", "field_rows", "output_parameters", "snippets", "queries", "candidates", "manual_review_queue", "planner_action_queue"}
    for key, value in inputs.items():
        if isinstance(value, list) and key in row_keys:
            for idx, item in enumerate(value):
                rows.append((f"{key}[{idx}]", item))
    return rows


def build_advisory_chunks(
    *,
    agent_id: str,
    agent_family_id: str,
    stage_name: str,
    task_name: str,
    inputs: dict[str, Any],
    max_prompt_chars: int,
    max_evidence_chars: int = 1200,
    target_ratio: float = 0.65,
) -> list[AdvisoryChunk]:
    safe_inputs = inputs if isinstance(inputs, dict) else {"input": inputs}
    target_chars = max(2000, int(max_prompt_chars * target_ratio))
    domain_map: dict[str, list[tuple[str, Any]]] = {}
    row_keys = {"ledger", "rows", "planner_field_ledger", "field_rows", "output_parameters", "snippets", "queries", "candidates", "manual_review_queue", "planner_action_queue"}

    for key, value in _iter_rows_from_inputs(safe_inputs):
        _append_to_domain(domain_map, infer_domain(key, value), key, value)

    for key, value in safe_inputs.items():
        key_str = str(key)
        if key_str in row_keys and isinstance(value, list):
            continue
        _append_to_domain(domain_map, infer_domain(key_str, value), key_str, value)

    chunks: list[AdvisoryChunk] = []
    sequence = 1
    for domain in sorted(domain_map.keys()):
        current: dict[str, Any] = {}
        current_sections: list[str] = []
        current_fields: list[str] = []
        current_lineage: list[str] = []

        def flush() -> None:
            nonlocal sequence, current, current_sections, current_fields, current_lineage
            if not current:
                return
            payload = {"chunk_domain": domain, "sections": current, "lineage": current_lineage}
            chunks.append(
                AdvisoryChunk(
                    chunk_id=f"{agent_id}_{task_name}_{sequence:03d}",
                    agent_id=agent_id,
                    agent_family_id=agent_family_id,
                    stage_name=stage_name,
                    task_name=task_name,
                    domain=domain,
                    field_paths=sorted(set(path for path in current_fields if path)),
                    payload=payload,
                    estimated_chars=estimate_prompt_chars(payload),
                    max_prompt_chars=max_prompt_chars,
                    source_section_names=list(current_sections),
                    lineage={"source_keys": list(current_lineage)},
                )
            )
            sequence += 1
            current = {}
            current_sections = []
            current_fields = []
            current_lineage = []

        for key, value in domain_map[domain]:
            compact = cap_evidence(value, max_evidence_chars=max_evidence_chars)
            section_key = re.sub(r"[^A-Za-z0-9_\[\].-]+", "_", str(key))[:120] or f"section_{sequence}"
            candidate = dict(current)
            candidate[section_key] = compact
            if estimate_prompt_chars(candidate) > target_chars and current:
                flush()
            current[section_key] = compact
            current_sections.append(section_key)
            current_lineage.append(str(key))
            field_path = _field_path_from_item(value)
            if field_path:
                current_fields.append(field_path)
        flush()

    if not chunks:
        compact = cap_evidence(safe_inputs, max_evidence_chars=max_evidence_chars)
        payload = {"chunk_domain": "miscellaneous", "sections": {"inputs": compact}, "lineage": ["inputs"]}
        chunks.append(
            AdvisoryChunk(
                chunk_id=f"{agent_id}_{task_name}_001",
                agent_id=agent_id,
                agent_family_id=agent_family_id,
                stage_name=stage_name,
                task_name=task_name,
                domain="miscellaneous",
                payload=payload,
                estimated_chars=estimate_prompt_chars(payload),
                max_prompt_chars=max_prompt_chars,
                source_section_names=["inputs"],
                lineage={"source_keys": ["inputs"]},
            )
        )
    return chunks


def merge_chunk_outputs(chunk_outputs: list[dict[str, Any]], *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    merged: dict[str, Any] = dict(fallback or {})
    review_notes: list[Any] = []
    rationale_parts: list[str] = []
    for item in chunk_outputs:
        output = item.get("output") if isinstance(item, dict) else None
        if not isinstance(output, dict):
            continue
        for key, value in output.items():
            if key == "deterministic_override_allowed":
                continue
            if key == "review_notes" and isinstance(value, list):
                review_notes.extend(value)
                continue
            if key == "rationale" and value:
                rationale_parts.append(str(value))
                continue
            if isinstance(value, list):
                existing = merged.get(key)
                if not isinstance(existing, list):
                    existing = []
                existing.extend(value)
                merged[key] = existing[:80]
                continue
            if isinstance(value, dict):
                existing = merged.get(key)
                merged[key] = {**existing, **value} if isinstance(existing, dict) else value
                continue
            if value not in (None, "", []):
                merged[key] = value
    if review_notes:
        existing_notes = merged.get("review_notes") if isinstance(merged.get("review_notes"), list) else []
        merged["review_notes"] = (existing_notes + review_notes)[:80]
    if rationale_parts:
        merged["rationale"] = " ".join(rationale_parts)[:2000]
    merged["deterministic_override_allowed"] = False
    return merged
