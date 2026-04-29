from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.interview_service.clarification import enrich_clarification_with_agent
from services.interview_service.question_catalog import get_question_by_field_path, get_question_by_id
from services.interview_service.utils import process_raw_answer


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_answer_record(*, question_id: str, field_path: str, answer: Any, source_name: str) -> dict[str, Any]:
    status = "CONFIRMED"
    if answer is None or (isinstance(answer, str) and answer.strip() == ""):
        status = "CLARIFICATION_REQUIRED"
    return {
        "question_id": question_id,
        "field_path": field_path,
        "answer": answer,
        "source_name": source_name,
        "answer_status": status,
    }


def append_processed_answer(
    *,
    context: Any | None,
    question_id: str,
    field_path: str,
    raw_answer: Any,
    source_name: str,
    answers_candidate: list[dict[str, Any]],
    answers_confirmed: list[dict[str, Any]],
    clarifications: list[dict[str, Any]],
) -> None:
    raw_answer_text = "" if raw_answer is None else str(raw_answer)

    question = get_question_by_id(question_id)
    if question is None:
        question = get_question_by_field_path(field_path)

    if question is None:
        normalized = _normalize_answer_record(
            question_id=question_id,
            field_path=field_path,
            answer=raw_answer,
            source_name=source_name,
        )
        answers_candidate.append(normalized)
        if normalized["answer_status"] == "CONFIRMED":
            answers_confirmed.append(
                {
                    "question_id": question_id,
                    "field_path": field_path,
                    "confirmed_answer": raw_answer,
                    "raw_answer": raw_answer_text,
                    "source_name": source_name,
                    "answer_status": "CONFIRMED",
                    "provenance_type": "engineer_response",
                    "confidence_tag": "HIGH",
                    "captured_at": utc_now_iso(),
                }
            )
        else:
            clarification_record = {
                "question_id": question_id,
                "field_path": field_path,
                "raw_answer": raw_answer_text,
                "clarification_prompt": f"Please provide a structured answer for field '{field_path}'.",
                "reason": "The supplied answer was blank or missing.",
                "status": "OPEN",
                "created_at": utc_now_iso(),
                "source_name": source_name,
            }
            clarifications.append(
                enrich_clarification_with_agent(context=context, clarification_record=clarification_record)
            )
        return

    candidate, confirmed, clarification = process_raw_answer(
        question=question,
        raw_answer=raw_answer_text,
        source_name=source_name,
    )
    answers_candidate.append(candidate.to_dict())
    if confirmed is not None:
        answers_confirmed.append(confirmed.to_dict())
    if clarification is not None:
        clarification_record = clarification.to_dict()
        clarification_record["source_name"] = source_name
        clarifications.append(
            enrich_clarification_with_agent(context=context, clarification_record=clarification_record)
        )
