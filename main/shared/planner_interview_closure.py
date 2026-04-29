from __future__ import annotations

"""Interview-to-planner-ledger closure helpers.

Applicant interview answers are the highest practical project-specific authority,
but they must be merged into the same planner field ledger contract instead of
remaining as loose interview artifacts.  This module applies confirmed interview
answers to ledger rows, records conflicts, and creates deterministic follow-up
confirmation prompts when a human answer conflicts with very high-confidence
document evidence.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from shared.planner_field_governance import build_planner_field_governance

UNKNOWN_ANSWER_TOKENS = {
    "",
    "unknown",
    "i don't know",
    "i do not know",
    "dont know",
    "don't know",
    "not sure",
    "n/a",
    "na",
    "tbd",
    "to be determined",
}
HIGH_CONFIDENCE_DOCUMENT_THRESHOLD = 0.90
INTERVIEW_SUPPLIED_CONFIDENCE = 0.92
INTERVIEW_CONFIRMED_CONFIDENCE = 0.96
INTERVIEW_CONFLICT_CONFIRMED_CONFIDENCE = 0.94


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _norm(value: Any) -> str:
    return _clean(value).casefold()


def _field_key(value: dict[str, Any]) -> str:
    return _clean(value.get("field_path")) or _clean(value.get("field_id"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _is_unknown_answer(value: Any) -> bool:
    return _norm(value) in UNKNOWN_ANSWER_TOKENS


def _answer_value(record: dict[str, Any]) -> Any:
    for key in ("confirmed_answer", "answer", "value", "raw_answer"):
        if key in record and record.get(key) not in (None, ""):
            return record.get(key)
    return ""


def _answer_status(record: dict[str, Any]) -> str:
    return _clean(record.get("answer_status") or record.get("status") or "CONFIRMED").upper()


def _source_label(record: dict[str, Any]) -> str:
    source = _clean(record.get("source_name")) or "Applicant interview"
    qid = _clean(record.get("question_id"))
    return f"{source} / {qid}" if qid else source


def _collect_confirmed_answers(
    interview_result: dict[str, Any] | None,
    gap_resolution_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if isinstance(interview_result, dict):
        sources.append(interview_result)
        session = interview_result.get("session")
        if isinstance(session, dict):
            sources.append(session)
    if isinstance(gap_resolution_result, dict):
        interview = gap_resolution_result.get("interview")
        if isinstance(interview, dict):
            sources.append(interview)
        substages = gap_resolution_result.get("substages")
        if isinstance(substages, dict) and isinstance(substages.get("interview"), dict):
            sources.append(substages["interview"])

    answers: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        for key in ("answers_confirmed", "confirmed_answers", "answers"):
            values = source.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                field_path = _clean(item.get("field_path")) or _clean(item.get("field_id"))
                if not field_path:
                    continue
                answer = _answer_value(item)
                identity = (field_path, _clean(item.get("question_id")), _clean(answer))
                if identity in seen:
                    continue
                seen.add(identity)
                answers.append(item)
    return answers


def _row_source_is_interview(row: dict[str, Any]) -> bool:
    return _norm(row.get("source_role")) == "interview" or _norm(row.get("source_document")).startswith("applicant interview")


def _values_match(left: Any, right: Any) -> bool:
    left_norm = _norm(left)
    right_norm = _norm(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    try:
        return abs(float(left_norm.replace(",", "")) - float(right_norm.replace(",", ""))) < 0.0001
    except Exception:
        return False


def _confirmation_prompt(row: dict[str, Any], record: dict[str, Any], answer: Any) -> str:
    source_document = _clean(row.get("source_document")) or "the source documents"
    page = _clean(row.get("source_page"))
    source = f"{source_document}, page {page}" if page else source_document
    return (
        f"Are you sure? Based on {source}, the answer for "
        f"{_clean(row.get('field_label')) or _field_key(row)} appears to be "
        f"{_clean(row.get('accepted_value'))}, but you said {_clean(answer)}. Which is correct?"
    )


def _append_reason(existing: Any, reason: str) -> str:
    current = _clean(existing)
    reason = _clean(reason)
    if not current:
        return reason
    if reason and reason not in current:
        return f"{current}; {reason}"
    return current


def _apply_answer_to_row(row: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    answer = _answer_value(record)
    answer_text = _clean(answer)
    status = _answer_status(record)
    question_id = _clean(record.get("question_id"))
    captured_at = _clean(record.get("captured_at")) or _utc_now_iso()
    current_value = row.get("accepted_value")
    current_confidence = _safe_float(row.get("confidence_score"), 0.0)
    current_status = _clean(row.get("status")).upper()
    current_has_value = bool(_clean(current_value)) and _clean(current_value).upper() != "UNRESOLVED"
    conflict_confirmed = _clean(record.get("confirmation_status")).upper() in {
        "CONFIRMED_CONFLICT",
        "APPLICANT_CONFIRMED",
        "CONFIRMED_OVERRIDE",
    }

    row["interview_status"] = status if status else "CONFIRMED"
    row["interview_question_id"] = question_id
    row["interview_answer"] = answer_text
    row["interview_captured_at"] = captured_at
    row["interview_source_reference"] = _source_label(record)

    if _is_unknown_answer(answer):
        row["interview_status"] = "UNKNOWN_OR_DECLINED"
        row["manual_review_reason"] = _append_reason(
            row.get("manual_review_reason"),
            "Applicant answered unknown/no-answer; retained best available document evidence.",
        )
        if not current_has_value:
            row["status"] = "UNRESOLVED"
            row["accepted_value"] = "UNRESOLVED"
            row["confidence_score"] = 0.0
            row["source_document"] = "No direct source found"
            row["unresolved_reason"] = "Applicant could not provide this value and no accepted source was available."
        return row

    if current_has_value and _values_match(current_value, answer):
        row["status"] = "INTERVIEW_CONFIRMED"
        row["confidence_score"] = max(current_confidence, INTERVIEW_CONFIRMED_CONFIDENCE)
        row["confidence_band"] = "HIGH"
        row["release_state"] = "READY"
        row["export_readiness_tier"] = "ready"
        row["planner_packet_use_policy"] = "show_as_interview_confirmed"
        row["manual_review_reason"] = _append_reason(
            row.get("manual_review_reason"),
            "Applicant confirmed the document-supported value.",
        )
        return row

    if current_has_value and not _row_source_is_interview(row):
        conflict_note = (
            f"Applicant interview answer '{answer_text}' conflicts with current document-supported value "
            f"'{_clean(current_value)}' from {_clean(row.get('source_document')) or 'document evidence'}."
        )
        if current_confidence >= HIGH_CONFIDENCE_DOCUMENT_THRESHOLD and not conflict_confirmed:
            row["status"] = "BLOCKED_BY_CONFLICT"
            row["release_state"] = "BLOCKED" if bool(row.get("planner_critical", False)) else "PROVISIONAL"
            row["export_readiness_tier"] = "blocked" if bool(row.get("planner_critical", False)) else "warning"
            row["planner_packet_use_policy"] = "show_as_conflict_requiring_interview_confirmation"
            row["conflict_summary"] = _append_reason(row.get("conflict_summary"), conflict_note)
            row["manual_review_reason"] = _append_reason(
                row.get("manual_review_reason"),
                "High-confidence document evidence conflicts with applicant response; confirmation required.",
            )
            row["needs_interview_confirmation"] = True
            row["interview_confirmation_prompt"] = _confirmation_prompt(row, record, answer)
            row["interview_conflicting_value"] = answer_text
            return row

        row["previous_document_value"] = current_value
        row["previous_document_confidence"] = current_confidence
        row["previous_document_source"] = _clean(row.get("source_document"))
        row["conflict_summary"] = _append_reason(row.get("conflict_summary"), conflict_note)
        row["status"] = "INTERVIEW_CONFLICT_CONFIRMED" if conflict_confirmed else "INTERVIEW_SUPPLIED"
        row["accepted_value"] = answer_text
        row["normalized_value"] = answer_text
        row["confidence_score"] = max(current_confidence, INTERVIEW_CONFLICT_CONFIRMED_CONFIDENCE if conflict_confirmed else INTERVIEW_SUPPLIED_CONFIDENCE)
        row["confidence_band"] = "HIGH"
        row["source_document"] = "Applicant interview"
        row["source_page"] = ""
        row["source_section"] = question_id
        row["source_line"] = ""
        row["source_anchor"] = _source_label(record)
        row["source_role"] = "interview"
        row["evidence_snippet"] = f"Applicant answer: {answer_text}"
        row["release_state"] = "READY"
        row["export_readiness_tier"] = "ready"
        row["planner_packet_use_policy"] = "show_as_interview_supplied_with_conflict_note"
        return row

    row["status"] = "INTERVIEW_SUPPLIED"
    row["accepted_value"] = answer_text
    row["normalized_value"] = answer_text
    row["confidence_score"] = max(current_confidence, INTERVIEW_SUPPLIED_CONFIDENCE)
    row["confidence_band"] = "HIGH"
    row["source_document"] = "Applicant interview"
    row["source_page"] = ""
    row["source_section"] = question_id
    row["source_line"] = ""
    row["source_anchor"] = _source_label(record)
    row["source_role"] = "interview"
    row["evidence_snippet"] = f"Applicant answer: {answer_text}"
    row["candidate_count"] = max(int(row.get("candidate_count", 0) or 0), 1)
    row["unresolved_reason"] = ""
    row["manual_review_reason"] = _append_reason(row.get("manual_review_reason"), "Applicant supplied this value directly.")
    row["release_state"] = "READY"
    row["export_readiness_tier"] = "ready"
    row["translation_use_policy"] = row.get("translation_use_policy") or "use"
    row["scenario_use_policy"] = row.get("scenario_use_policy") or "use"
    row["planner_packet_use_policy"] = "show_as_interview_supplied"
    row["registry_backfilled"] = False
    return row


def apply_interview_answers_to_planner_contract(
    planner_field_contract: dict[str, Any] | None,
    *,
    interview_result: dict[str, Any] | None = None,
    gap_resolution_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a planner-field contract with interview answers merged into rows."""
    contract = deepcopy(planner_field_contract) if isinstance(planner_field_contract, dict) else {}
    rows = contract.get("planner_field_ledger", []) if isinstance(contract.get("planner_field_ledger"), list) else []
    answers = _collect_confirmed_answers(interview_result, gap_resolution_result)
    answers_by_field: dict[str, dict[str, Any]] = {}
    for answer in answers:
        field_path = _clean(answer.get("field_path")) or _clean(answer.get("field_id"))
        if field_path:
            answers_by_field[field_path] = answer

    touched: list[str] = []
    confirmation_required: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _field_key(row)
        answer = answers_by_field.get(key)
        if not isinstance(answer, dict):
            continue
        _apply_answer_to_row(row, answer)
        touched.append(key)
        if row.get("needs_interview_confirmation"):
            confirmation_required.append(
                {
                    "field_path": key,
                    "field_label": _clean(row.get("field_label")) or key,
                    "question_id": _clean(row.get("interview_question_id")),
                    "confirmation_prompt": _clean(row.get("interview_confirmation_prompt")),
                    "document_value": row.get("accepted_value"),
                    "interview_value": row.get("interview_conflicting_value"),
                    "document_source": _clean(row.get("source_document")),
                    "document_confidence": _safe_float(row.get("confidence_score"), 0.0),
                    "planner_critical": bool(row.get("planner_critical", False)),
                }
            )

    existing_keys = {_field_key(row) for row in rows if isinstance(row, dict)}
    for field_path, answer in answers_by_field.items():
        if field_path in existing_keys:
            continue
        answer_value = _answer_value(answer)
        if _is_unknown_answer(answer_value):
            continue
        new_row = {
            "ledger_contract_version": "planner_field_ledger_v2",
            "field_path": field_path,
            "field_id": field_path,
            "field_label": field_path,
            "accepted_value": _clean(answer_value),
            "normalized_value": _clean(answer_value),
            "confidence_score": INTERVIEW_SUPPLIED_CONFIDENCE,
            "confidence_band": "HIGH",
            "status": "INTERVIEW_SUPPLIED",
            "release_state": "READY",
            "export_readiness_tier": "ready",
            "translation_use_policy": "use",
            "scenario_use_policy": "use",
            "planner_packet_use_policy": "show_as_interview_supplied",
            "source_document": "Applicant interview",
            "source_section": _clean(answer.get("question_id")),
            "source_anchor": _source_label(answer),
            "source_role": "interview",
            "evidence_snippet": f"Applicant answer: {_clean(answer_value)}",
            "interview_status": _answer_status(answer),
            "interview_question_id": _clean(answer.get("question_id")),
            "interview_answer": _clean(answer_value),
            "interview_captured_at": _clean(answer.get("captured_at")) or _utc_now_iso(),
            "planner_critical": False,
            "requiredness": "interview_supplied",
            "candidate_count": 1,
            "registry_backfilled": False,
        }
        rows.append(new_row)
        touched.append(field_path)
        existing_keys.add(field_path)

    status_counts = Counter(_clean(row.get("status")) for row in rows if isinstance(row, dict))
    summary = contract.get("planner_field_ledger_summary") if isinstance(contract.get("planner_field_ledger_summary"), dict) else {}
    summary.update(
        {
            "interview_closure_applied": True,
            "interview_answer_count": len(answers),
            "interview_rows_updated_count": len(touched),
            "interview_confirmation_required_count": len(confirmation_required),
            "status_counts_after_interview_closure": dict(sorted(status_counts.items())),
        }
    )
    contract["planner_field_ledger"] = rows
    contract["planner_field_ledger_summary"] = summary
    contract["planner_field_governance"] = build_planner_field_governance(rows)
    contract["planner_interview_closure"] = {
        "contract_version": "planner_interview_closure_v1",
        "created_at": _utc_now_iso(),
        "interview_answer_count": len(answers),
        "rows_updated_count": len(touched),
        "updated_field_paths": sorted(set(touched)),
        "confirmation_required_count": len(confirmation_required),
        "confirmation_required": confirmation_required[:100],
    }
    return contract
