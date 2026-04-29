from __future__ import annotations

"""Bridge the registry-first planner candidate ledger into canonical/field resolution.

The candidate ledger is produced during normalization.  These helpers make that
ledger an active runtime input for canonical state and field resolution instead
of leaving it as a passive artifact.
"""

from typing import Any

from shared.confidence_utils import confidence_band_from_score, normalize_confidence_score
from shared.planner_registry import field_path_for_registry_field_id, registry_field_id_for_path


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if text:
            return float(text)
    except (TypeError, ValueError):
        return default
    return default


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        cleaned = _clean(item)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            output.append(cleaned)
    return output


def planner_candidate_rows_from_normalized_input(normalized_input: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = normalized_input if isinstance(normalized_input, dict) else {}
    rows = payload.get("planner_candidate_ledger")
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def planner_candidate_rows_from_normalization_result(normalization_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = normalization_result if isinstance(normalization_result, dict) else {}
    normalized_input = payload.get("normalized_input") if isinstance(payload.get("normalized_input"), dict) else {}
    return planner_candidate_rows_from_normalized_input(normalized_input)


def planner_candidate_summary_from_normalized_input(normalized_input: dict[str, Any] | None) -> dict[str, Any]:
    payload = normalized_input if isinstance(normalized_input, dict) else {}
    summary = payload.get("planner_candidate_ledger_summary")
    return dict(summary) if isinstance(summary, dict) else {}


def planner_candidate_summary_from_normalization_result(normalization_result: dict[str, Any] | None) -> dict[str, Any]:
    payload = normalization_result if isinstance(normalization_result, dict) else {}
    normalized_input = payload.get("normalized_input") if isinstance(payload.get("normalized_input"), dict) else {}
    return planner_candidate_summary_from_normalized_input(normalized_input)


def _field_id_for_row(row: dict[str, Any]) -> str:
    raw = _clean(row.get("field_id")) or _clean(row.get("registry_field_id"))
    if raw:
        return raw
    return registry_field_id_for_path(row.get("field_path"))


def _field_path_for_row(row: dict[str, Any], field_id: str = "") -> str:
    raw = _clean(row.get("field_path"))
    if raw:
        return raw
    resolved = field_path_for_registry_field_id(field_id)
    return _clean(resolved) or field_id


def _candidate_source_refs(candidate: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("source_anchor_id", "source_anchor", "source_document", "source_file_name", "source_ref"):
        value = candidate.get(key)
        if isinstance(value, list):
            refs.extend(_clean(item) for item in value)
        else:
            refs.append(_clean(value))
    return _dedupe(refs)


def _candidate_metadata(
    *,
    row: dict[str, Any],
    candidate: dict[str, Any],
    source_kind: str,
) -> dict[str, Any]:
    source_document = _clean(candidate.get("source_document"))
    source_page = _clean(candidate.get("source_page"))
    source_section = _clean(candidate.get("source_section"))
    source_anchor = _clean(candidate.get("source_anchor_id")) or _clean(candidate.get("source_anchor"))
    return {
        "record_origin": "planner_candidate_ledger",
        "planner_candidate_source_kind": source_kind,
        "planner_candidate_primary": True,
        "candidate_governance_source": "planner_candidate_ledger",
        "field_id": _field_id_for_row(row),
        "field_label": _clean(row.get("field_label")),
        "expected_data_type": _clean(row.get("expected_data_type")),
        "expected_unit": _clean(row.get("expected_unit")),
        "policy_family": _clean(row.get("policy_family")),
        "source_role": _clean(candidate.get("source_role")),
        "source_document": source_document,
        "source_file_name": source_document,
        "page_number": source_page,
        "source_page": source_page,
        "section": source_section,
        "source_section": source_section,
        "source_anchor_id": source_anchor,
        "source_method": _clean(candidate.get("method")) or "planner_candidate_ledger",
        "unit": _clean(row.get("expected_unit")),
        "authority_score": candidate.get("authority_score"),
        "authority_notes": list(candidate.get("authority_notes", [])) if isinstance(candidate.get("authority_notes"), list) else [],
        "policy_authority_note": _clean(candidate.get("policy_authority_note")),
        "evidence_snippet": _clean(candidate.get("evidence_snippet")),
        "rejected_by_field_policy": bool(candidate.get("rejected_by_field_policy", False)),
    }


def candidate_ledger_records_for_lookup_keys(
    rows: list[dict[str, Any]] | None,
    lookup_keys: list[str],
    *,
    include_rejected: bool = False,
) -> list[dict[str, Any]]:
    """Return field-resolution-compatible records for candidate-ledger rows."""
    normalized = {_clean(key) for key in lookup_keys if _clean(key)}
    if not normalized:
        return []
    records: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        field_id = _field_id_for_row(row)
        field_path = _field_path_for_row(row, field_id)
        row_keys = {field_id, field_path, registry_field_id_for_path(field_path)}
        row_keys |= set(lookup_keys) if field_id in normalized or field_path in normalized else set()
        if not (row_keys & normalized):
            continue
        candidates = row.get("candidates") if isinstance(row.get("candidates"), list) else []
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            if bool(candidate.get("rejected_by_field_policy", False)) and not include_rejected:
                continue
            value = candidate.get("normalized_value") if candidate.get("normalized_value") not in (None, "", [], {}) else candidate.get("value")
            source_refs = _candidate_source_refs(candidate)
            raw_confidence = candidate.get("confidence_score")
            confidence = normalize_confidence_score(raw_confidence, band=_clean(candidate.get("confidence_label")), default=0.5)
            record = {
                "field_record_id": _clean(candidate.get("candidate_id")) or f"planner_candidate_ledger::{field_id}::{index:04d}",
                "field_path": field_path,
                "value": value,
                "source_stage": "normalization",
                "source_type": "planner_candidate_ledger",
                "source_ref": source_refs,
                "confidence_score": confidence,
                "confidence_tag": confidence_band_from_score(confidence, fallback=_clean(candidate.get("confidence_label")) or "MODERATE"),
                "evidence_strength": "STRONG" if source_refs else "MODERATE",
                "is_missing": value in (None, "", [], {}),
                "metadata": _candidate_metadata(row=row, candidate=candidate, source_kind="candidate"),
            }
            records.append(record)
        accepted_value = row.get("accepted_value")
        if accepted_value not in (None, "", [], {}):
            accepted_source = row.get("accepted_source") if isinstance(row.get("accepted_source"), dict) else {}
            source_refs = _dedupe([
                _clean(accepted_source.get("source_anchor_id")),
                _clean(accepted_source.get("source_name")),
                _clean(accepted_source.get("source_type")),
            ])
            raw_confidence = accepted_source.get("confidence")
            confidence = normalize_confidence_score(raw_confidence, band="HIGH", default=0.8)
            record = {
                "field_record_id": f"planner_candidate_ledger::{field_id}::accepted",
                "field_path": field_path,
                "value": accepted_value,
                "source_stage": "normalization",
                "source_type": "planner_candidate_ledger_accepted_value",
                "source_ref": source_refs,
                "confidence_score": confidence,
                "confidence_tag": confidence_band_from_score(confidence, fallback="HIGH"),
                "evidence_strength": "STRONG" if source_refs else "MODERATE",
                "is_missing": False,
                "metadata": {
                    "record_origin": "planner_candidate_ledger",
                    "planner_candidate_source_kind": "accepted_value",
                    "planner_candidate_primary": True,
                    "candidate_governance_source": "planner_candidate_ledger",
                    "field_id": field_id,
                    "field_label": _clean(row.get("field_label")),
                    "source_method": "planner_candidate_ledger_accepted_value",
                    "source_role": _clean(accepted_source.get("source_type")) or "normalization",
                    "source_anchor_id": _clean(accepted_source.get("source_anchor_id")),
                    "confidence_reason": _clean(accepted_source.get("reason")),
                    "decision": _clean(accepted_source.get("decision")),
                    "unit": _clean(row.get("expected_unit")),
                },
            }
            records.append(record)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        key = (
            _clean(record.get("field_record_id")),
            _clean(record.get("field_path")),
            repr(record.get("value")),
            tuple(record.get("source_ref", [])) if isinstance(record.get("source_ref"), list) else (),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def attach_candidate_ledger_to_canonical_state(
    canonical_state: dict[str, Any],
    *,
    normalization_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach candidate-ledger rows and source inputs to a canonical payload."""
    state = canonical_state if isinstance(canonical_state, dict) else {}
    rows = planner_candidate_rows_from_normalization_result(normalization_result)
    summary = planner_candidate_summary_from_normalization_result(normalization_result)
    if not rows:
        normalized_input = state.get("normalized_input") if isinstance(state.get("normalized_input"), dict) else {}
        rows = planner_candidate_rows_from_normalized_input(normalized_input)
        summary = planner_candidate_summary_from_normalized_input(normalized_input)
    if not rows:
        return state
    state["planner_candidate_ledger"] = rows
    state["planner_candidate_ledger_summary"] = summary
    source_inputs = state.get("source_candidate_inputs") if isinstance(state.get("source_candidate_inputs"), dict) else {}
    source_inputs = dict(source_inputs)
    source_inputs["planner_candidate_rows"] = rows
    # Keep both historical and explicit keys so runtime contracts and downstream
    # services can prove that candidate-ledger rows, not legacy side channels,
    # are the governed primary source.
    source_inputs["planner_candidate_ledger"] = rows
    source_inputs["planner_candidate_ledger_summary"] = summary
    source_inputs["candidate_governance_source"] = "planner_candidate_ledger"
    state["candidate_governance_source"] = "planner_candidate_ledger"
    state["source_candidate_inputs"] = source_inputs
    return state
