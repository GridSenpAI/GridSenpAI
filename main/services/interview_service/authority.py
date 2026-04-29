from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

UNKNOWN_ANSWER_PATTERNS = {
    "i don't know",
    "i dont know",
    "dont know",
    "don't know",
    "unknown",
    "not sure",
    "unsure",
    "n/a",
    "na",
    "not available",
    "tbd",
    "to be determined",
}

HIGH_CONFIDENCE_DOCUMENT_CONFLICT_THRESHOLD = 0.90
INTERVIEW_CONFIDENCE = 0.97
CONFIRMED_INTERVIEW_CONFIDENCE = 0.99


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_answer_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def answer_is_unknown(value: Any) -> bool:
    normalized = normalize_answer_text(value)
    if not normalized:
        return True
    if normalized in UNKNOWN_ANSWER_PATTERNS:
        return True
    return bool(re.fullmatch(r"(?:i\s+)?do\s+not\s+know", normalized))


def _parse_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        candidate = float(value)
        return candidate if math.isfinite(candidate) else None
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        candidate = float(match.group(0))
    except Exception:
        return None
    return candidate if math.isfinite(candidate) else None


def values_equivalent(left: Any, right: Any) -> bool:
    left_num = _parse_float(left)
    right_num = _parse_float(right)
    if left_num is not None and right_num is not None:
        tolerance = max(0.01, abs(left_num) * 0.005, abs(right_num) * 0.005)
        return abs(left_num - right_num) <= tolerance
    return normalize_answer_text(left) == normalize_answer_text(right)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        candidate = float(value)
    except Exception:
        return None
    return candidate if math.isfinite(candidate) else None


def _field_safe_key(field_path: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", field_path.strip()).strip("_") or "field"


def build_interview_candidate(answer: dict[str, Any], *, source_name: str | None = None, confirmed: bool = False) -> dict[str, Any]:
    field_path = str(answer.get("field_path", "")).strip()
    question_id = str(answer.get("question_id", "")).strip()
    raw_answer = answer.get("raw_answer", answer.get("answer", ""))
    value = answer.get("confirmed_answer", answer.get("answer", answer.get("value")))
    captured_at = str(answer.get("captured_at", "")).strip() or utc_now_iso()
    resolved_source_name = source_name or str(answer.get("source_name", "")).strip() or "applicant_interview"
    source_hierarchy = "applicant_confirmed_answer" if confirmed else "applicant_supplied_answer"
    confidence = CONFIRMED_INTERVIEW_CONFIDENCE if confirmed else INTERVIEW_CONFIDENCE

    return {
        "candidate_id": f"interview::{question_id or 'question'}::{_field_safe_key(field_path)}",
        "field_id": str(answer.get("field_id", "")).strip(),
        "field_path": field_path,
        "label": str(answer.get("label", field_path)).strip() or field_path,
        "value": value,
        "source_stage": "interview",
        "source_type": "human_input",
        "source_stream": "interview",
        "source_hierarchy": source_hierarchy,
        "source_ref": [resolved_source_name],
        "source_anchor": f"interview::{resolved_source_name}::{question_id or field_path}",
        "specificity": "direct_field_match",
        "confidence": confidence,
        "confidence_band": "HIGH",
        "evidence_strength": "HUMAN_SUPPLIED",
        "score": confidence,
        "metadata": {
            "question_id": question_id,
            "raw_answer": raw_answer,
            "captured_at": captured_at,
            "answer_status": str(answer.get("answer_status", "CONFIRMED")).strip() or "CONFIRMED",
            "provenance_type": str(answer.get("provenance_type", "engineer_response")).strip() or "engineer_response",
        },
    }


def interview_answer_confirms_existing(answer_value: Any, accepted_value: Any) -> bool:
    if answer_is_unknown(answer_value):
        return False
    return values_equivalent(answer_value, accepted_value)


def merge_interview_answer_into_ledger_entry(entry: dict[str, Any], answer: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge an applicant interview answer into one field-resolution ledger entry.

    The interview answer is always retained as a first-class candidate. It wins over
    absent/weak document evidence. A conflicting answer against very high-confidence
    document evidence is not finalized; the entry is marked for confirmation instead.
    """

    merged = dict(entry)
    field_path = str(answer.get("field_path", merged.get("field_path", ""))).strip()
    answer_value = answer.get("confirmed_answer", answer.get("answer", answer.get("value")))
    raw_answer = answer.get("raw_answer", answer_value)
    source_name = str(answer.get("source_name", "")).strip() or "applicant_interview"
    question_id = str(answer.get("question_id", "")).strip()
    candidate = build_interview_candidate(answer, source_name=source_name, confirmed=True)

    candidates = list(merged.get("candidates", [])) if isinstance(merged.get("candidates", []), list) else []
    if not any(isinstance(item, dict) and item.get("candidate_id") == candidate["candidate_id"] for item in candidates):
        candidates.append(candidate)
    merged["candidates"] = candidates[-10:]

    supporting_sources = list(merged.get("supporting_sources", [])) if isinstance(merged.get("supporting_sources", []), list) else []
    supporting_sources.append({
        "source_stage": "interview",
        "source_type": "human_input",
        "source_hierarchy": candidate["source_hierarchy"],
        "source_ref": [source_name],
        "source_anchor": candidate["source_anchor"],
        "value": answer_value,
        "question_id": question_id,
        "raw_answer": raw_answer,
    })
    merged["supporting_sources"] = supporting_sources[-8:]

    source_anchors = list(merged.get("source_anchors", [])) if isinstance(merged.get("source_anchors", []), list) else []
    source_anchors.append(candidate["source_anchor"])
    merged["source_anchors"] = list(dict.fromkeys(str(anchor).strip() for anchor in source_anchors if str(anchor).strip()))

    current_value = merged.get("accepted_value")
    current_confidence = _safe_float(merged.get("accepted_confidence")) or 0.0
    current_hierarchy = normalize_answer_text(merged.get("accepted_source_hierarchy"))
    document_backed = current_value not in (None, "") and "applicant" not in current_hierarchy and "interview" not in current_hierarchy
    has_conflict = document_backed and not values_equivalent(current_value, answer_value)
    answer_unknown = answer_is_unknown(answer_value)
    question_id_normalized = normalize_answer_text(answer.get("question_id", ""))
    answer_status_normalized = normalize_answer_text(answer.get("answer_status", ""))
    conflict_confirmation = (
        question_id_normalized.startswith("interview_confirm_conflict")
        or bool(answer.get("confirms_conflict", False))
        or answer_status_normalized in {"confirmed_conflict", "conflict_confirmed"}
    )

    decision: dict[str, Any] = {
        "field_path": field_path,
        "question_id": question_id,
        "source_name": source_name,
        "interview_value": answer_value,
        "previous_value": current_value,
        "previous_confidence": current_confidence,
        "interview_candidate_id": candidate["candidate_id"],
        "action": "",
        "requires_followup_confirmation": False,
    }

    why_accepted = list(merged.get("why_accepted", [])) if isinstance(merged.get("why_accepted", []), list) else []

    if answer_unknown:
        decision["action"] = "UNKNOWN_ANSWER_DOCUMENT_OR_UNRESOLVED_VALUE_RETAINED"
        merged["applicant_answer_state"] = "unknown"
        merged["planner_review_flag"] = bool(merged.get("planner_review_flag", False) or not document_backed)
        if not document_backed:
            merged["accepted_status"] = merged.get("accepted_status") or "unresolved"
            merged["unresolved_reason"] = "Applicant answered that the value is unknown and no governed document winner was available."
            merged["needs_applicant_confirmation"] = False
        notes = list(merged.get("consistency_notes", [])) if isinstance(merged.get("consistency_notes", []), list) else []
        notes.append("Applicant answered 'I don't know'; existing governed document evidence is retained where available.")
        merged["consistency_notes"] = notes[-5:]
        return merged, decision

    if has_conflict and current_confidence >= HIGH_CONFIDENCE_DOCUMENT_CONFLICT_THRESHOLD and not conflict_confirmation:
        decision["action"] = "HIGH_CONFIDENCE_DOCUMENT_CONFLICT_REQUIRES_CONFIRMATION"
        decision["requires_followup_confirmation"] = True
        merged["applicant_answer_state"] = "conflict_requires_confirmation"
        merged["needs_applicant_confirmation"] = True
        merged["planner_review_flag"] = True
        merged["conflict_materiality"] = "high"
        merged["accepted_status"] = "review_required"
        merged["status"] = "review_required"
        merged["contradiction_summary"] = (
            f"Applicant answer '{answer_value}' conflicts with high-confidence document value '{current_value}'. "
            "Follow-up confirmation is required before overriding the document-backed value."
        )
        merged["applicant_question_profile"] = {
            "question_type": "confirm_high_confidence_conflict",
            "question_id": f"INTERVIEW_CONFIRM_CONFLICT::{question_id or _field_safe_key(field_path)}",
            "field_path": field_path,
            "prompt": f"Are you sure? Based on the document evidence, the answer appears to be {current_value}, but you said {answer_value}. Which is correct?",
            "document_value": current_value,
            "interview_value": answer_value,
            "document_confidence": current_confidence,
            "source_anchors": list(merged.get("source_anchors", []))[:5],
        }
        return merged, decision

    if current_value not in (None, "") and values_equivalent(current_value, answer_value):
        decision["action"] = "INTERVIEW_CONFIRMED_DOCUMENT_VALUE"
        merged["accepted_status"] = "resolved"
        merged["status"] = "resolved"
        merged["accepted_value"] = current_value
        merged["accepted_confidence"] = max(current_confidence, CONFIRMED_INTERVIEW_CONFIDENCE)
        merged["confidence_band"] = "HIGH"
        merged["accepted_value_kind"] = "interview_confirmed_document_value"
        merged["accepted_source_hierarchy"] = "document_value_confirmed_by_applicant"
        merged["accepted_specificity"] = "direct_field_match"
        merged["accepted_candidate_id"] = str(merged.get("accepted_candidate_id") or candidate["candidate_id"])
        merged["needs_applicant_confirmation"] = False
        merged["planner_review_flag"] = False
        merged["conflict_materiality"] = "none"
        merged["applicant_answer_state"] = "confirmed_existing_value"
        merged["contradiction_summary"] = ""
        why_accepted.append("Applicant confirmed the governed document value during the interview.")
        merged["why_accepted"] = why_accepted[-4:]
        return merged, decision

    decision["action"] = "INTERVIEW_VALUE_ACCEPTED"
    if has_conflict:
        decision["action"] = "INTERVIEW_CONFLICT_CONFIRMED" if conflict_confirmation else "INTERVIEW_VALUE_ACCEPTED_WITH_CONFLICT_NOTE"
        # Non-high-confidence document conflicts are resolved by the applicant's confirmed answer.
        # Preserve the historical contradiction note, but clear the active review posture.
        merged["conflict_materiality"] = "high" if conflict_confirmation else "none"
        confidence_phrase = "high-confidence" if conflict_confirmation else "lower-confidence"
        confirmation_phrase = " after explicit applicant confirmation" if conflict_confirmation else ""
        merged["contradiction_summary"] = (
            f"Applicant answer '{answer_value}' conflicts with {confidence_phrase} document value '{current_value}'. "
            f"The applicant answer was accepted as the higher practical authority{confirmation_phrase}."
        )
    else:
        merged["conflict_materiality"] = "none"
        merged["contradiction_summary"] = ""

    merged["accepted_value"] = answer_value
    merged["accepted_status"] = "resolved"
    merged["status"] = "resolved"
    merged["accepted_confidence"] = INTERVIEW_CONFIDENCE if not has_conflict else 0.93
    merged["confidence_band"] = "HIGH"
    merged["accepted_candidate_id"] = candidate["candidate_id"]
    merged["accepted_value_kind"] = "applicant_supplied" if current_value in (None, "") else "applicant_override"
    merged["accepted_source_hierarchy"] = "applicant_confirmed_answer"
    merged["accepted_specificity"] = "direct_field_match"
    merged["needs_applicant_confirmation"] = False
    merged["planner_review_flag"] = False
    merged["applicant_answer_state"] = "conflict_confirmed" if conflict_confirmation and has_conflict else ("confirmed_override" if has_conflict else "confirmed_supplied")
    merged["unresolved_reason"] = ""
    merged["acceptance_margin"] = max(float(merged.get("acceptance_margin", 0.0) or 0.0), 0.25)
    why_accepted.append("Applicant confirmed value accepted as the highest practical authority for this field.")
    merged["why_accepted"] = why_accepted[-4:]
    return merged, decision
