from __future__ import annotations

"""Ledger-driven adjudication governance helpers.

This module makes adjudication explicit at the planner-ledger layer.  The
field-resolution service can still run compact LLM advisory packets, but the
planner ledger needs its own deterministic contract showing which master fields
required adjudication, whether advisory adjudication succeeded, and which fields
must remain blocked/provisional when adjudication did not complete.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from shared.confidence_utils import confidence_band_from_score, normalize_confidence_score

FAILED_ADJUDICATION_STATUSES = {
    "ADJUDICATION_PARTIAL",
    "ADJUDICATION_REQUIRED_BUT_FAILED",
    "ADJUDICATION_BLOCKED_PROMPT_TOO_LARGE",
    "ADJUDICATION_PACKETS_READY",
}
COMPLETED_ADJUDICATION_STATUSES = {"ADJUDICATION_COMPLETED"}
SKIPPED_ADJUDICATION_STATUSES = {"ADJUDICATION_SKIPPED_NO_CONFLICTS"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _field_key(row: dict[str, Any]) -> str:
    return _clean(row.get("field_path")) or _clean(row.get("field_id"))


def _status(value: Any) -> str:
    return _clean(value).upper()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _optional_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


def _per_field_value_decisions(adjudication: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = adjudication.get("per_field_decisions")
    if not isinstance(values, list):
        values = []
    result: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        key = _field_key(item)
        if not key:
            continue
        result[key] = item
    return result


def _merge_value_decision(decision: dict[str, Any], value_decision: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value_decision, dict) or not value_decision:
        return decision
    candidate_id = _clean(
        _first_present(
            value_decision,
            ("accepted_candidate_id", "selected_candidate_id", "winning_candidate_id", "candidate_id"),
        )
    )
    value = _first_present(value_decision, ("accepted_value", "selected_value", "winning_value", "value", "normalized_value"))
    confidence = _optional_float(
        _first_present(value_decision, ("confidence_score", "confidence", "adjudicated_confidence"))
    )
    if candidate_id:
        decision["adjudicated_candidate_id"] = candidate_id
    if value is not None:
        decision["adjudicated_value"] = value
        decision["adjudicated_normalized_value"] = value_decision.get("normalized_value", value)
    if _clean(value_decision.get("unit")):
        decision["adjudicated_unit"] = _clean(value_decision.get("unit"))
    if confidence is not None:
        decision["adjudicated_confidence_score"] = confidence
    for source_key in ("source_document", "source_page", "source_section", "source_line", "source_anchor", "evidence_snippet"):
        cleaned = _clean(value_decision.get(source_key))
        if cleaned:
            decision[f"adjudicated_{source_key}"] = cleaned
    if _clean(value_decision.get("rationale")):
        decision["adjudicated_rationale"] = _clean(value_decision.get("rationale"))
    if _clean(value_decision.get("conflict_note")):
        decision["adjudicated_conflict_note"] = _clean(value_decision.get("conflict_note"))
    if _clean(value_decision.get("status")):
        decision["adjudicated_value_status"] = _clean(value_decision.get("status"))
    return decision



def _candidate_identifier(candidate: dict[str, Any], index: int = 0) -> str:
    for key in ("candidate_id", "id", "source_candidate_id", "row_id"):
        value = _clean(candidate.get(key))
        if value:
            return value
    return f"candidate_{index + 1}"


def _candidate_value(candidate: dict[str, Any]) -> Any:
    return _first_present(
        candidate,
        (
            "value",
            "accepted_value",
            "normalized_value",
            "raw_value",
            "candidate_value",
            "field_value",
        ),
    )


def _canonical_value_key(value: Any) -> str:
    """Normalize values for corroboration grouping without project-specific rules."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"number::{round(float(value), 6):g}"
    text = _clean(value).lower()
    if not text:
        return ""
    try:
        numeric = float(text.replace(",", ""))
        return f"number::{round(numeric, 6):g}"
    except Exception:
        return "text::" + " ".join(text.replace("_", " ").split())


def _clean_source_value(value: Any) -> str:
    cleaned = _clean(value)
    return "" if cleaned.lower() in {"none", "null", "n/a", "na", "unknown", "no direct source found"} else cleaned


def _source_document_for_candidate(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    source_ref = candidate.get("source_ref") if isinstance(candidate.get("source_ref"), list) else []
    for mapping in (candidate, metadata, evidence):
        for key in ("source_document", "source_file_name", "source_name", "document_name", "filename", "file_name", "artifact_name", "source_anchor", "source_anchor_id"):
            cleaned = _clean_source_value(mapping.get(key))
            if cleaned:
                return cleaned
    for item in source_ref:
        cleaned = _clean_source_value(item)
        if cleaned:
            return cleaned
    return ""


def _candidate_source_role(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    for mapping in (candidate, metadata, evidence):
        value = _clean(mapping.get("source_role") or mapping.get("document_role") or mapping.get("artifact_role"))
        if value:
            return value.lower()
    return ""


def _candidate_stream(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for mapping in (candidate, metadata):
        value = _clean(
            mapping.get("source_stream")
            or mapping.get("source_method")
            or mapping.get("method")
            or mapping.get("stage")
            or mapping.get("candidate_source")
        )
        if value:
            return value.lower()
    return ""


def _is_nonresponsive_interview_candidate(candidate: dict[str, Any]) -> bool:
    value = _clean(_candidate_value(candidate)).lower()
    if not value:
        return True
    return value in {
        "i don't know",
        "i do not know",
        "unknown",
        "unsure",
        "not sure",
        "n/a",
        "na",
        "none",
        "no answer",
    }


_SOURCE_ROLE_AUTHORITY_WEIGHTS: dict[str, float] = {
    "interview": 0.20,
    "applicant_interview": 0.20,
    "applicant_confirmed_answer": 0.22,
    "engineer_interview": 0.20,
    "human_input": 0.20,
    "application_request_form": 0.16,
    "request_form": 0.16,
    "load_request_form": 0.16,
    "interconnection_request": 0.16,
    "project_summary": 0.12,
    "load_schedule": 0.12,
    "equipment_schedule": 0.12,
    "technical_particulars": 0.12,
    "facilities_study": 0.10,
    "interconnection_memo": 0.10,
    "one_line_diagram": 0.06,
    "single_line_diagram": 0.06,
    "metering_scada": 0.06,
    "protection_controls": 0.06,
    "site_plan": 0.03,
    "drawing": 0.02,
    "vendor_datasheet": 0.05,
    "oem_datasheet": 0.05,
}


def _source_role_authority_bonus(source_role: str) -> float:
    role = source_role.lower()
    if not role:
        return 0.0
    for key, weight in _SOURCE_ROLE_AUTHORITY_WEIGHTS.items():
        if key in role:
            return weight
    return 0.0


def _candidate_policy_adjustment(candidate: dict[str, Any]) -> float:
    adjustment = 0.0
    for key in (
        "policy_authority_adjustment",
        "authority_adjustment",
        "source_authority_adjustment",
        "context_adjustment",
        "field_policy_adjustment",
    ):
        value = _optional_float(candidate.get(key))
        if value is not None:
            adjustment += value
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for key in (
        "policy_authority_adjustment",
        "authority_adjustment",
        "source_authority_adjustment",
        "context_adjustment",
        "field_policy_adjustment",
    ):
        value = _optional_float(metadata.get(key))
        if value is not None:
            adjustment += value

    status_blob = " ".join(
        _clean(candidate.get(key)).lower()
        for key in ("status", "candidate_status", "policy_status", "context_status", "rejection_reason")
    )
    if "reject" in status_blob or "wrong_context" in status_blob or "excluded" in status_blob:
        adjustment -= 0.35
    if "overcapture" in status_blob:
        adjustment -= 0.15
    if "drawing_repeat" in status_blob or "repeated_symbol" in status_blob:
        adjustment -= 0.12
    if "confirmed" in status_blob:
        adjustment += 0.12
    return adjustment


def _score_deterministic_candidate(candidate: dict[str, Any], *, index: int) -> dict[str, Any]:
    value = _candidate_value(candidate)
    confidence = _optional_float(
        _first_present(
            candidate,
            (
                "confidence_score",
                "confidence",
                "score",
                "base_confidence",
                "candidate_confidence",
            ),
        )
    )
    if confidence is None:
        confidence = 0.0
    source_role = _candidate_source_role(candidate)
    stream = _candidate_stream(candidate)
    interview_candidate = any(token in f"{source_role} {stream}" for token in ("interview", "human_input", "applicant_confirmed"))
    nonresponsive = interview_candidate and _is_nonresponsive_interview_candidate(candidate)

    score = confidence
    score += _source_role_authority_bonus(source_role)
    score += _candidate_policy_adjustment(candidate)
    if interview_candidate and not nonresponsive:
        score += 0.15
    if nonresponsive:
        score -= 0.55
    if value in (None, ""):
        score -= 1.0

    return {
        "candidate": candidate,
        "candidate_id": _candidate_identifier(candidate, index),
        "value": value,
        "normalized_value": candidate.get("normalized_value", value),
        "unit": _clean(candidate.get("unit")),
        "confidence": normalize_confidence_score(confidence),
        "score": max(-1.0, min(1.5, score)),
        "source_role": source_role,
        "source_stream": stream,
        "interview_candidate": interview_candidate,
        "nonresponsive": nonresponsive,
    }


def _synthetic_candidate_from_plan_item(item: dict[str, Any]) -> dict[str, Any]:
    """Build a safe candidate from a compact plan row when option lists are absent.

    Real runs can still produce older compact adjudication rows that carry a
    current accepted/provisional value but omit candidate_options.  Treating
    those rows as having no evidence forces BLOCKED_BY_ADJUDICATION_FAILURE.
    This fallback keeps the decision deterministic and source-aware without
    inventing new facts.
    """
    value = item.get("accepted_value")
    if value in (None, "", "UNRESOLVED"):
        return {}
    source_reference = _clean(item.get("source_reference"))
    source_document = source_reference
    source_page = ""
    if ", page " in source_reference.lower():
        before, after = source_reference.split(", page ", 1) if ", page " in source_reference else source_reference.split(", Page ", 1)
        source_document = before.strip()
        source_page = after.split(",", 1)[0].strip()
    return {
        "candidate_id": _clean(item.get("accepted_candidate_id")) or f"synthetic::{_field_key(item)}",
        "value": value,
        "normalized_value": value,
        "unit": _clean(item.get("expected_unit")),
        "confidence_score": normalize_confidence_score(item.get("confidence_score"), band=_clean(item.get("confidence_band")), default=0.0),
        "confidence_band": _clean(item.get("confidence_band")),
        "source_role": _clean(item.get("source_role")) or _clean(item.get("policy_family")) or "planner_ledger",
        "source_stage": "planner_field_ledger",
        "source_stream": "planner_field_ledger",
        "source_document": source_document if source_document != "No direct source found" else "",
        "source_page": source_page,
        "source_section": _clean(item.get("source_section")),
        "source_anchor": _clean(item.get("source_anchor")) or source_reference,
        "evidence_snippet": _clean(item.get("evidence_snippet")),
    }


def _candidate_options_from_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    values = item.get("candidate_options")
    if isinstance(values, list):
        candidates = [candidate for candidate in values if isinstance(candidate, dict)]
        if candidates:
            return candidates
    values = item.get("candidates")
    if isinstance(values, list):
        candidates = [candidate for candidate in values if isinstance(candidate, dict)]
        if candidates:
            return candidates
    synthetic = _synthetic_candidate_from_plan_item(item)
    return [synthetic] if synthetic else []


def _corroborated_value_decision(scored: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Accept repeated agreement as support, not conflict.

    Real intake packages often repeat the same value in the request form,
    summary, one-line, and equipment schedule.  If the normalized value agrees
    across independent source documents/roles, deterministic adjudication should
    promote the value instead of requiring an LLM decision.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in scored:
        if entry.get("nonresponsive"):
            continue
        key = _canonical_value_key(entry.get("normalized_value", entry.get("value")))
        if not key:
            continue
        grouped.setdefault(key, []).append(entry)
    best_group: list[dict[str, Any]] = []
    for group in grouped.values():
        docs = {_source_document_for_candidate(item.get("candidate", {})) for item in group if isinstance(item.get("candidate"), dict)}
        docs.discard("")
        roles = {_clean(item.get("source_role")) for item in group if _clean(item.get("source_role"))}
        max_score = max((float(item.get("score", 0.0) or 0.0) for item in group), default=0.0)
        if len(group) >= 2 and (len(docs) >= 2 or len(roles) >= 2 or max_score >= 0.82):
            if not best_group or (len(docs), len(group), max_score) > (
                len({_source_document_for_candidate(item.get("candidate", {})) for item in best_group if isinstance(item.get("candidate"), dict)}),
                len(best_group),
                max(float(item.get("score", 0.0) or 0.0) for item in best_group),
            ):
                best_group = group
    if not best_group:
        return None
    best_group.sort(key=lambda entry: (float(entry.get("score", 0.0) or 0.0), float(entry.get("confidence", 0.0) or 0.0)), reverse=True)
    winner = best_group[0]
    winner_candidate = winner.get("candidate") if isinstance(winner.get("candidate"), dict) else {}
    docs = {_source_document_for_candidate(item.get("candidate", {})) for item in best_group if isinstance(item.get("candidate"), dict)}
    docs.discard("")
    confidence = max(float(winner.get("confidence", 0.0) or 0.0), min(0.98, float(winner.get("score", 0.0) or 0.0) + min(0.10, 0.03 * (len(best_group) - 1))))
    return {
        "deterministic_decision_status": "DETERMINISTIC_ADJUDICATION_COMPLETED",
        "adjudication_method": "deterministic",
        "accepted_candidate_id": winner["candidate_id"],
        "accepted_value": winner["value"],
        "normalized_value": winner["normalized_value"],
        "unit": winner["unit"],
        "confidence_score": normalize_confidence_score(confidence),
        "status": "ACCEPTED" if confidence >= 0.85 else "PROVISIONAL",
        "source_document": winner_candidate.get("source_document") or _source_document_for_candidate(winner_candidate),
        "source_page": winner_candidate.get("source_page"),
        "source_section": winner_candidate.get("source_section"),
        "source_line": winner_candidate.get("source_line"),
        "source_anchor": winner_candidate.get("source_anchor"),
        "evidence_snippet": winner_candidate.get("evidence_snippet") or winner_candidate.get("snippet"),
        "rationale": f"Deterministic adjudication accepted corroborated value repeated across {len(best_group)} candidate(s) and {len(docs)} source document(s).",
        "conflict_note": "Repeated source-appropriate candidates normalized to the same value; treated as corroboration instead of material conflict.",
        "scored_candidate_count": len(scored),
        "corroborating_candidate_count": len(best_group),
        "corroborating_source_document_count": len(docs),
    }


def _deterministic_value_decision_for_item(item: dict[str, Any]) -> dict[str, Any]:
    candidates = _candidate_options_from_item(item)
    scored = [
        _score_deterministic_candidate(candidate, index=index)
        for index, candidate in enumerate(candidates)
    ]
    corroborated = _corroborated_value_decision(scored)
    if corroborated is not None:
        return corroborated
    viable = [
        entry for entry in scored
        if entry["value"] not in (None, "")
        and not entry["nonresponsive"]
        and entry["score"] >= 0.35
    ]
    if not viable:
        return {
            "deterministic_decision_status": "DETERMINISTIC_ADJUDICATION_BLOCKED",
            "adjudication_method": "deterministic",
            "status": "BLOCKED_BY_MISSING_SOURCE",
            "rationale": "Deterministic adjudication found no viable responsive candidate above the minimum evidence threshold.",
            "conflict_note": "No candidate could be safely accepted without manual review.",
            "scored_candidate_count": len(scored),
        }

    viable.sort(key=lambda entry: (entry["score"], entry["confidence"]), reverse=True)
    winner = viable[0]
    runner_up = viable[1] if len(viable) > 1 else None
    score_gap = winner["score"] - (runner_up["score"] if runner_up else -1.0)
    high_confidence = winner["confidence"] >= 0.85 or winner["score"] >= 0.90
    interview_winner = bool(winner.get("interview_candidate"))

    if runner_up and _canonical_value_key(runner_up.get("normalized_value", runner_up.get("value"))) == _canonical_value_key(winner.get("normalized_value", winner.get("value"))):
        runner_up = None
        score_gap = 1.0

    if runner_up and score_gap < 0.05 and not high_confidence and not interview_winner:
        return {
            "deterministic_decision_status": "DETERMINISTIC_ADJUDICATION_BLOCKED",
            "adjudication_method": "deterministic",
            "status": "BLOCKED_BY_CONFLICT",
            "rationale": "Deterministic adjudication found competing candidates with insufficient score separation.",
            "conflict_note": f"Top candidate {_clean(winner['candidate_id'])} was too close to {_clean(runner_up['candidate_id'])}; manual review required.",
            "scored_candidate_count": len(scored),
            "top_candidate_id": winner["candidate_id"],
            "runner_up_candidate_id": runner_up["candidate_id"],
        }

    confidence = max(winner["confidence"], min(0.98, winner["score"]))
    value_status = "ACCEPTED"
    if confidence < 0.85 and not interview_winner:
        value_status = "PROVISIONAL"
    if runner_up and _clean(runner_up.get("value")) and _clean(runner_up.get("value")) != _clean(winner.get("value")):
        conflict_note = (
            f"Deterministic adjudication selected {winner['candidate_id']} over "
            f"{runner_up['candidate_id']} based on confidence/source authority."
        )
    else:
        conflict_note = "Deterministic adjudication selected the strongest available candidate."

    winner_candidate = winner["candidate"] if isinstance(winner.get("candidate"), dict) else {}
    return {
        "deterministic_decision_status": "DETERMINISTIC_ADJUDICATION_COMPLETED",
        "adjudication_method": "deterministic",
        "accepted_candidate_id": winner["candidate_id"],
        "accepted_value": winner["value"],
        "normalized_value": winner["normalized_value"],
        "unit": winner["unit"],
        "confidence_score": normalize_confidence_score(confidence),
        "status": value_status,
        "source_document": winner_candidate.get("source_document"),
        "source_page": winner_candidate.get("source_page"),
        "source_section": winner_candidate.get("source_section"),
        "source_line": winner_candidate.get("source_line"),
        "source_anchor": winner_candidate.get("source_anchor"),
        "evidence_snippet": winner_candidate.get("evidence_snippet") or winner_candidate.get("snippet"),
        "rationale": (
            "Deterministic adjudication selected the highest scoring candidate using "
            "confidence, interview authority, source-role authority, and field-policy adjustments."
        ),
        "conflict_note": conflict_note,
        "scored_candidate_count": len(scored),
        "top_score": round(float(winner["score"]), 4),
        "runner_up_score": round(float(runner_up["score"]), 4) if runner_up else None,
    }


def _should_attempt_deterministic_decision(
    *,
    adjudication_status: str,
    value_decision: dict[str, Any] | None,
    item: dict[str, Any],
) -> bool:
    if isinstance(value_decision, dict) and value_decision:
        return False
    explicit_candidates = bool(item.get("candidate_options") if isinstance(item.get("candidate_options"), list) else item.get("candidates") if isinstance(item.get("candidates"), list) else [])
    status = _status(adjudication_status)
    if not _candidate_options_from_item(item):
        return False
    if status in FAILED_ADJUDICATION_STATUSES and not explicit_candidates:
        return False
    return (
        status in COMPLETED_ADJUDICATION_STATUSES
        or status in FAILED_ADJUDICATION_STATUSES
        or status == "ADJUDICATION_STATUS_UNKNOWN"
        or not status
    )



def _decision_for_plan_item(item: dict[str, Any], *, adjudication_status: str, support_summary: dict[str, Any], value_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    field_path = _field_key(item)
    planner_critical = bool(item.get("planner_critical", False))
    current_status = _status(item.get("status")) or "UNKNOWN"
    confidence = _safe_float(item.get("confidence_score"), 0.0)
    completed = adjudication_status in COMPLETED_ADJUDICATION_STATUSES
    skipped = adjudication_status in SKIPPED_ADJUDICATION_STATUSES
    failed = adjudication_status in FAILED_ADJUDICATION_STATUSES

    deterministic_value_decision: dict[str, Any] | None = None
    if _should_attempt_deterministic_decision(
        adjudication_status=adjudication_status,
        value_decision=value_decision,
        item=item,
    ):
        deterministic_value_decision = _deterministic_value_decision_for_item(item)
        if _clean(deterministic_value_decision.get("deterministic_decision_status")) == "DETERMINISTIC_ADJUDICATION_COMPLETED":
            value_decision = deterministic_value_decision
            completed = True
            failed = False
            skipped = False
            adjudication_status = "ADJUDICATION_COMPLETED"
        elif _clean(deterministic_value_decision.get("deterministic_decision_status")) == "DETERMINISTIC_ADJUDICATION_BLOCKED":
            # If a compact row already has a current value but no adjudicable
            # alternatives, do not convert that value into an adjudication
            # failure.  Preserve it as provisional so final export can surface
            # the value with review posture instead of hiding it behind a hard
            # block.
            if (
                item.get("accepted_value") not in (None, "", "UNRESOLVED")
                and _clean(deterministic_value_decision.get("status")) == "BLOCKED_BY_MISSING_SOURCE"
            ):
                value_decision = {
                    "accepted_value": item.get("accepted_value"),
                    "normalized_value": item.get("accepted_value"),
                    "confidence_score": normalize_confidence_score(item.get("confidence_score"), band=_clean(item.get("confidence_band")), default=0.59),
                    "status": "PROVISIONAL",
                    "rationale": "No viable alternate candidate was available; preserved current ledger value as provisional instead of hard-blocking adjudication. Planner-critical rows remain draft/blocked at export if other release gates fail.",
                    "conflict_note": _clean(item.get("manual_review_reason")) or _clean(item.get("unresolved_reason")),
                }
                completed = True
                failed = False
                skipped = False
                adjudication_status = "ADJUDICATION_COMPLETED"
            else:
                failed = True
                completed = False
                skipped = False
                adjudication_status = "ADJUDICATION_REQUIRED_BUT_FAILED"

    if completed:
        decision_status = "ADJUDICATION_COMPLETED"
        row_action = "USE_ADJUDICATED_LEDGER_POSTURE"
        release_effect = "no_additional_block"
    elif skipped:
        decision_status = "ADJUDICATION_SKIPPED_NO_CONFLICTS"
        row_action = "NO_ADJUDICATION_REQUIRED"
        release_effect = "no_additional_block"
    elif failed:
        decision_status = "ADJUDICATION_REQUIRED_BUT_NOT_COMPLETED"
        row_action = "BLOCK_OR_MANUAL_REVIEW_FIELD"
        release_effect = "manual_review_required" if planner_critical else "warning"
    else:
        decision_status = "ADJUDICATION_STATUS_UNKNOWN"
        row_action = "MANUAL_REVIEW_FIELD"
        release_effect = "manual_review_required" if planner_critical else "warning"

    reason_parts = []
    for key in ("conflict_summary", "manual_review_reason", "unresolved_reason", "adjudication_question"):
        text = _clean(item.get(key))
        if text and text not in reason_parts:
            reason_parts.append(text)
    if isinstance(deterministic_value_decision, dict) and _clean(deterministic_value_decision.get("rationale")):
        reason_parts.insert(0, _clean(deterministic_value_decision.get("rationale")))
    if not reason_parts:
        reason_parts.append("Ledger governance marked this field for compact adjudication.")

    decision = {
        "field_path": field_path,
        "field_id": _clean(item.get("field_id")),
        "field_label": _clean(item.get("field_label")) or field_path,
        "planner_critical": planner_critical,
        "requiredness": _clean(item.get("requiredness")),
        "policy_family": _clean(item.get("policy_family")) or "general",
        "pre_adjudication_status": current_status,
        "pre_adjudication_value": item.get("accepted_value", "UNRESOLVED"),
        "pre_adjudication_confidence": confidence,
        "source_reference": _clean(item.get("source_reference")),
        "candidate_count": int(item.get("candidate_count", 0) or len(_candidate_options_from_item(item)) or 0),
        "adjudication_decision_status": decision_status,
        "recommended_row_action": row_action,
        "release_effect": release_effect,
        "reason": "; ".join(reason_parts[:4]),
        "support_summary_available": bool(support_summary),
        "adjudication_method": "llm" if isinstance(value_decision, dict) and value_decision and not deterministic_value_decision else (
            "deterministic" if deterministic_value_decision else "not_required" if skipped else "none"
        ),
    }
    if isinstance(deterministic_value_decision, dict):
        decision["deterministic_adjudication"] = deterministic_value_decision
        decision["deterministic_decision_status"] = _clean(deterministic_value_decision.get("deterministic_decision_status"))
        if _clean(deterministic_value_decision.get("status")):
            decision["deterministic_value_status"] = _clean(deterministic_value_decision.get("status"))
    return _merge_value_decision(decision, value_decision)

def build_ledger_adjudication_artifact(
    *,
    run_id: str,
    planner_field_contract: dict[str, Any] | None,
    adjudication_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the planner-ledger adjudication artifact from ledger governance.

    This does not perform LLM inference.  It deterministically records which
    ledger fields required compact adjudication and whether the upstream compact
    advisory pass completed, failed, or was skipped.
    """
    contract = planner_field_contract if isinstance(planner_field_contract, dict) else {}
    governance = contract.get("planner_field_governance", {}) if isinstance(contract.get("planner_field_governance"), dict) else {}
    plan = governance.get("adjudication_plan", []) if isinstance(governance.get("adjudication_plan"), list) else []
    adjudication = adjudication_result if isinstance(adjudication_result, dict) else {}
    adjudication_status = _status(adjudication.get("status")) or "ADJUDICATION_SKIPPED_NO_CONFLICTS"
    support_summary = adjudication.get("support_summary", {}) if isinstance(adjudication.get("support_summary"), dict) else {}
    value_decisions = _per_field_value_decisions(adjudication)

    decisions = [
        _decision_for_plan_item(
            item,
            adjudication_status=adjudication_status,
            support_summary=support_summary,
            value_decision=value_decisions.get(_field_key(item)),
        )
        for item in plan
        if isinstance(item, dict)
    ]
    planned_keys = {_field_key(item) for item in plan if isinstance(item, dict) and _field_key(item)}
    for field_key, value_decision in value_decisions.items():
        if field_key in planned_keys:
            continue
        synthetic_item = {
            "field_path": field_key,
            "field_id": _clean(value_decision.get("field_id")) or field_key,
            "field_label": _clean(value_decision.get("field_label")) or field_key,
            "status": "PROVISIONAL",
            "accepted_value": value_decision.get("accepted_value", value_decision.get("value", "UNRESOLVED")),
            "confidence_score": normalize_confidence_score(value_decision.get("confidence_score", value_decision.get("confidence", 0.0))),
            "conflict_summary": _clean(value_decision.get("conflict_note")),
            "adjudication_question": "Apply compact adjudication decision to planner ledger row.",
        }
        decisions.append(_decision_for_plan_item(
            synthetic_item,
            adjudication_status=adjudication_status,
            support_summary=support_summary,
            value_decision=value_decision,
        ))
    status_counts = Counter(_clean(item.get("adjudication_decision_status")) for item in decisions)
    critical_failed = [
        item for item in decisions
        if bool(item.get("planner_critical")) and _clean(item.get("adjudication_decision_status")) in {
            "ADJUDICATION_REQUIRED_BUT_NOT_COMPLETED", "ADJUDICATION_STATUS_UNKNOWN"
        }
    ]

    if not decisions:
        ledger_status = "LEDGER_ADJUDICATION_SKIPPED_NO_FIELDS"
        release_effect = "no_global_export_block"
    elif critical_failed:
        ledger_status = "LEDGER_ADJUDICATION_REQUIRED_BUT_FAILED_CRITICAL"
        release_effect = "manual_review_required"
    elif any(_clean(item.get("adjudication_decision_status")) == "ADJUDICATION_REQUIRED_BUT_NOT_COMPLETED" for item in decisions):
        ledger_status = "LEDGER_ADJUDICATION_PARTIAL_OR_FAILED_NONCRITICAL"
        release_effect = "warnings_only"
    elif adjudication_status in COMPLETED_ADJUDICATION_STATUSES:
        ledger_status = "LEDGER_ADJUDICATION_COMPLETED"
        release_effect = "no_global_export_block"
    else:
        ledger_status = "LEDGER_ADJUDICATION_READY_OR_SKIPPED"
        release_effect = "no_global_export_block"

    return {
        "contract_version": "planner_ledger_adjudication_v1",
        "run_id": run_id,
        "created_at": _utc_now_iso(),
        "status": ledger_status,
        "field_resolution_adjudication_status": adjudication_status,
        "release_effect": release_effect,
        "required": bool(decisions),
        "decision_count": len(decisions),
        "planner_critical_failed_count": len(critical_failed),
        "decision_status_counts": dict(sorted(status_counts.items())),
        "decisions": decisions[:150],
    }



def _candidate_options(row: dict[str, Any]) -> list[dict[str, Any]]:
    values = row.get("candidate_options")
    if isinstance(values, list):
        return [item for item in values if isinstance(item, dict)]
    return []


def _candidate_by_id(row: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    cleaned_id = _clean(candidate_id)
    if not cleaned_id:
        return {}
    for index, candidate in enumerate(_candidate_options(row)):
        if _clean(candidate.get("candidate_id")) == cleaned_id:
            return candidate
        if _candidate_identifier(candidate, index) == cleaned_id:
            return candidate
    return {}


def _apply_adjudicated_value(row: dict[str, Any], decision: dict[str, Any]) -> bool:
    """Apply a completed compact adjudication value decision to one ledger row."""
    if _clean(decision.get("adjudication_decision_status")) != "ADJUDICATION_COMPLETED":
        return False
    candidate = _candidate_by_id(row, _clean(decision.get("adjudicated_candidate_id")))
    source = candidate if candidate else decision
    value = candidate.get("value") if candidate else decision.get("adjudicated_value")
    if value in (None, ""):
        return False

    row["accepted_value"] = value
    row["normalized_value"] = candidate.get("normalized_value", value) if candidate else decision.get("adjudicated_normalized_value", value)
    unit = _clean(candidate.get("unit")) if candidate else _clean(decision.get("adjudicated_unit"))
    if unit:
        row["unit"] = unit
    confidence = _optional_float(candidate.get("confidence_score") if candidate else decision.get("adjudicated_confidence_score"))
    if confidence is not None:
        normalized_confidence = normalize_confidence_score(confidence, band=_clean(candidate.get("confidence_band")), default=0.0)
        row["confidence_score"] = normalized_confidence
        if not _clean(row.get("confidence_band")) or _clean(row.get("confidence_band")) == "UNRESOLVED":
            row["confidence_band"] = confidence_band_from_score(normalized_confidence)
    if _clean(candidate.get("confidence_band")):
        row["confidence_band"] = _clean(candidate.get("confidence_band"))
    candidate_id = _clean(candidate.get("candidate_id")) or _clean(decision.get("adjudicated_candidate_id"))
    if candidate_id:
        row["accepted_candidate_id"] = candidate_id

    source_map = {
        "source_document": "adjudicated_source_document",
        "source_page": "adjudicated_source_page",
        "source_section": "adjudicated_source_section",
        "source_line": "adjudicated_source_line",
        "source_anchor": "adjudicated_source_anchor",
        "evidence_snippet": "adjudicated_evidence_snippet",
    }
    for row_key, decision_key in source_map.items():
        candidate_value = _clean(source.get(row_key))
        decision_value = _clean(decision.get(decision_key))
        final_value = candidate_value or decision_value
        if final_value:
            row[row_key] = final_value
    if _clean(candidate.get("source_role")):
        row["source_role"] = _clean(candidate.get("source_role"))

    rationale = _clean(decision.get("adjudicated_rationale")) or _clean(decision.get("reason"))
    conflict_note = _clean(decision.get("adjudicated_conflict_note"))
    existing_conflict = _clean(row.get("conflict_summary"))
    if conflict_note:
        row["conflict_summary"] = (f"{existing_conflict}; {conflict_note}" if existing_conflict and conflict_note not in existing_conflict else conflict_note)
    if rationale:
        existing_reason = _clean(row.get("manual_review_reason"))
        if existing_reason and rationale not in existing_reason:
            row["manual_review_reason"] = f"{existing_reason}; Adjudication rationale: {rationale}"
        elif not existing_reason:
            row["manual_review_reason"] = f"Adjudication rationale: {rationale}"

    value_status = _clean(decision.get("adjudicated_value_status")) or _clean(decision.get("deterministic_value_status"))
    method = _clean(decision.get("adjudication_method")) or "llm"
    row["adjudication_method"] = method
    if value_status == "PROVISIONAL":
        row["status"] = "PROVISIONAL"
        row["release_state"] = "PROVISIONAL"
        row["export_readiness_tier"] = "warning"
        row["translation_use_policy"] = "use_with_warning"
        row["scenario_use_policy"] = "manual_review_before_use"
        row["planner_packet_use_policy"] = "show_provisional_adjudicated_value"
    else:
        row["status"] = "ACCEPTED_WITH_CONFLICT_NOTE" if _clean(row.get("conflict_summary")) else "ACCEPTED"
        row["release_state"] = "READY"
        row["export_readiness_tier"] = "ready"
        row["translation_use_policy"] = "use_accepted_value"
        row["scenario_use_policy"] = "use_accepted_value"
        row["planner_packet_use_policy"] = "show_accepted_adjudicated_value"
    row["unresolved_reason"] = ""
    row["adjudication_applied"] = True
    return True


def _refresh_summary_after_adjudication(contract: dict[str, Any], artifact: dict[str, Any], applied_count: int) -> None:
    rows = contract.get("planner_field_ledger") if isinstance(contract.get("planner_field_ledger"), list) else []
    counts = Counter(_clean(row.get("status")) or "UNKNOWN" for row in rows if isinstance(row, dict))
    summary = contract.get("planner_field_ledger_summary") if isinstance(contract.get("planner_field_ledger_summary"), dict) else {}
    summary["status_counts"] = dict(sorted(counts.items()))
    summary["accepted_count"] = sum(counts.get(key, 0) for key in ("ACCEPTED", "ACCEPTED_WITH_CONFLICT_NOTE", "INTERVIEW_CONFIRMED", "INTERVIEW_SUPPLIED", "INTERVIEW_CONFLICT_CONFIRMED"))
    summary["unresolved_or_blocked_count"] = sum(count for status, count in counts.items() if status.startswith("BLOCKED") or status == "UNRESOLVED")
    summary["ledger_adjudication_status"] = _clean(artifact.get("status"))
    summary["ledger_adjudication_required_count"] = int(artifact.get("decision_count", 0) or 0)
    summary["ledger_adjudication_applied_value_count"] = applied_count
    summary["ledger_adjudication_planner_critical_failed_count"] = int(artifact.get("planner_critical_failed_count", 0) or 0)
    contract["planner_field_ledger_summary"] = summary

def apply_ledger_adjudication_to_contract(
    planner_field_contract: dict[str, Any] | None,
    ledger_adjudication: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a contract copy with field-level adjudication posture applied."""
    contract = deepcopy(planner_field_contract) if isinstance(planner_field_contract, dict) else {}
    artifact = ledger_adjudication if isinstance(ledger_adjudication, dict) else {}
    decisions = artifact.get("decisions", []) if isinstance(artifact.get("decisions"), list) else []
    decision_by_key = {
        _field_key(decision): decision
        for decision in decisions
        if isinstance(decision, dict) and _field_key(decision)
    }
    rows = contract.get("planner_field_ledger", []) if isinstance(contract.get("planner_field_ledger"), list) else []
    failed_statuses = {"ADJUDICATION_REQUIRED_BUT_NOT_COMPLETED", "ADJUDICATION_STATUS_UNKNOWN"}
    applied_value_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        decision = decision_by_key.get(_field_key(row))
        if not isinstance(decision, dict):
            row.setdefault("adjudication_required", False)
            continue
        decision_status = _clean(decision.get("adjudication_decision_status"))
        row["adjudication_required"] = True
        row["adjudication_status"] = decision_status
        row["adjudication_decision"] = decision
        row["adjudication_release_effect"] = _clean(decision.get("release_effect"))
        if _apply_adjudicated_value(row, decision):
            applied_value_count += 1
        if decision_status in failed_statuses:
            reason = _clean(decision.get("reason")) or "Compact adjudication was required but did not complete."
            deterministic_status = _clean(decision.get("deterministic_value_status"))
            deterministic_decision_status = _clean(decision.get("deterministic_decision_status"))
            if deterministic_decision_status == "DETERMINISTIC_ADJUDICATION_BLOCKED" and deterministic_status:
                row["status"] = deterministic_status
                row["release_state"] = "BLOCKED" if bool(row.get("planner_critical", False)) else "PROVISIONAL"
                row["export_readiness_tier"] = "blocked" if bool(row.get("planner_critical", False)) else "warning"
                row["planner_packet_use_policy"] = "show_as_blocked_by_deterministic_adjudication"
                row["adjudication_method"] = "deterministic"
            elif bool(row.get("planner_critical", False)) or _status(row.get("status")) in {"PROVISIONAL", "BLOCKED_BY_CONFLICT", "BLOCKED_BY_ADJUDICATION_FAILURE"}:
                row["status"] = "BLOCKED_BY_ADJUDICATION_FAILURE"
                row["release_state"] = "BLOCKED" if bool(row.get("planner_critical", False)) else "PROVISIONAL"
                row["export_readiness_tier"] = "blocked" if bool(row.get("planner_critical", False)) else "warning"
                row["planner_packet_use_policy"] = "show_as_blocked_by_adjudication_failure"
            row["manual_review_reason"] = (f"{_clean(row.get('manual_review_reason'))}; {reason}" if _clean(row.get("manual_review_reason")) else reason)
    contract["planner_field_ledger"] = rows
    _refresh_summary_after_adjudication(contract, artifact, applied_value_count)
    contract["planner_ledger_adjudication"] = artifact
    return contract
