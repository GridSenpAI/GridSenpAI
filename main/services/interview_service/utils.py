from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from shared.field_paths import normalize_field_path as canonical_normalize_field_path
from services.interview_service.models import (
    ConfirmedInterviewAnswer,
    InterviewAnswerCandidate,
    InterviewClarification,
    InterviewQuestion,
)
from shared.schemas.domain_registry import load_intake_question_specs




def normalize_field_path(field_path: Any) -> str:
    return canonical_normalize_field_path(field_path)


ALLOWED_ANSWER_TYPES: set[str] = {
    "string",
    "integer",
    "number",
    "boolean",
    "enum",
}


def _normalize_string(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_boolean(raw_answer: str) -> bool | None:
    lowered = _normalize_string(raw_answer).lower()

    if lowered in {"yes", "y", "true", "present", "installed", "1"}:
        return True
    if lowered in {"no", "n", "false", "absent", "not installed", "0"}:
        return False
    return None


def _parse_integer(raw_answer: str) -> int | None:
    match = re.search(r"-?\d+", raw_answer)
    if not match:
        return None

    try:
        return int(match.group(0))
    except ValueError:
        return None


def _parse_number(raw_answer: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", raw_answer)
    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_enum(raw_answer: str, allowed_values: list[Any]) -> Any | None:
    normalized = _normalize_string(raw_answer)
    normalized_lower = normalized.lower()

    for allowed in allowed_values:
        if isinstance(allowed, str) and allowed.lower() == normalized_lower:
            return allowed
        if isinstance(allowed, bool):
            if normalized_lower in {"yes", "y", "true", "1"} and allowed is True:
                return True
            if normalized_lower in {"no", "n", "false", "0"} and allowed is False:
                return False
        if isinstance(allowed, int) and normalized_lower == str(allowed):
            return allowed

    alias_map: dict[str, Any] = {
        "n+1": "N+1",
        "n plus 1": "N+1",
        "2n": "2N",
        "double conversion": "DOUBLE_CONVERSION",
        "eco mode": "ECO_MODE",
        "unknown": "UNKNOWN",
        "grid parallel": "GRID_PARALLEL",
        "grid-parallel": "GRID_PARALLEL",
        "parallel": "GRID_PARALLEL",
        "islanded": "ISLANDED_ONLY",
        "island mode": "ISLANDED_ONLY",
        "islanded only": "ISLANDED_ONLY",
        "island only": "ISLANDED_ONLY",
        "both": "GRID_PARALLEL_AND_ISLAND",
        "parallel and island": "GRID_PARALLEL_AND_ISLAND",
        "grid parallel and island": "GRID_PARALLEL_AND_ISLAND",
        "grid-parallel and island": "GRID_PARALLEL_AND_ISLAND",
        "50": 50,
        "60": 60,
        "yes": True,
        "no": False,
        "true": True,
        "false": False,
    }

    if normalized_lower in alias_map and alias_map[normalized_lower] in allowed_values:
        return alias_map[normalized_lower]

    integer_candidate = _parse_integer(raw_answer)
    if integer_candidate in allowed_values:
        return integer_candidate

    return None


def parse_answer_value(
    question: InterviewQuestion,
    raw_answer: str,
) -> Any | None:
    if question.answer_type not in ALLOWED_ANSWER_TYPES:
        raise ValueError(
            f"Unsupported answer_type '{question.answer_type}' for question '{question.question_id}'."
        )

    normalized_answer = _normalize_string(raw_answer)

    if not normalized_answer:
        return None

    if question.answer_type == "string":
        return normalized_answer

    if question.answer_type == "boolean":
        return _parse_boolean(normalized_answer)

    if question.answer_type == "integer":
        return _parse_integer(normalized_answer)

    if question.answer_type == "number":
        return _parse_number(normalized_answer)

    if question.answer_type == "enum":
        return _parse_enum(normalized_answer, question.allowed_values)

    return None


def answer_needs_clarification(
    question: InterviewQuestion,
    raw_answer: str,
    interpreted_candidate: Any,
) -> tuple[bool, str]:
    normalized_answer = _normalize_string(raw_answer)

    if not normalized_answer:
        return True, "No answer content was provided."

    if interpreted_candidate is None:
        return True, "The answer could not be parsed into the expected type."

    if question.answer_type == "integer":
        if isinstance(interpreted_candidate, int) and interpreted_candidate < 0:
            return True, "Negative counts are not valid for this field."

    if question.answer_type == "number":
        if isinstance(interpreted_candidate, (int, float)) and interpreted_candidate < 0:
            return True, "Negative numeric values are not valid for this field."

    if question.answer_type == "enum":
        if question.allowed_values and interpreted_candidate not in question.allowed_values:
            return True, "The answer is not one of the allowed values."

    return False, ""


def build_candidate_answer(
    question: InterviewQuestion,
    raw_answer: str,
    source_name: str,
) -> InterviewAnswerCandidate:
    interpreted_candidate = parse_answer_value(question, raw_answer)

    return InterviewAnswerCandidate(
        question_id=question.question_id,
        field_path=question.field_path,
        raw_answer=raw_answer,
        interpreted_candidate=interpreted_candidate,
        source_name=source_name,
    )


def build_confirmed_answer(
    question: InterviewQuestion,
    raw_answer: str,
    confirmed_answer: Any,
    source_name: str,
) -> ConfirmedInterviewAnswer:
    return ConfirmedInterviewAnswer(
        question_id=question.question_id,
        field_path=question.field_path,
        confirmed_answer=confirmed_answer,
        raw_answer=raw_answer,
        source_name=source_name,
    )


def build_clarification(
    question: InterviewQuestion,
    raw_answer: str,
    reason: str,
) -> InterviewClarification:
    clarification_prompt = (
        f"I could not safely record an answer for '{question.prompt}' from: "
        f"'{raw_answer}'. Please restate the answer in a structured form."
    )

    return InterviewClarification(
        question_id=question.question_id,
        field_path=question.field_path,
        raw_answer=raw_answer,
        clarification_prompt=clarification_prompt,
        reason=reason,
    )


def process_raw_answer(
    question: InterviewQuestion,
    raw_answer: str,
    source_name: str,
) -> tuple[
    InterviewAnswerCandidate,
    ConfirmedInterviewAnswer | None,
    InterviewClarification | None,
]:
    candidate = build_candidate_answer(
        question=question,
        raw_answer=raw_answer,
        source_name=source_name,
    )

    needs_clarification, reason = answer_needs_clarification(
        question=question,
        raw_answer=raw_answer,
        interpreted_candidate=candidate.interpreted_candidate,
    )

    if needs_clarification:
        clarification = build_clarification(
            question=question,
            raw_answer=raw_answer,
            reason=reason,
        )
        return candidate, None, clarification

    confirmed = build_confirmed_answer(
        question=question,
        raw_answer=raw_answer,
        confirmed_answer=candidate.interpreted_candidate,
        source_name=source_name,
    )
    return candidate, confirmed, None

FIELD_QUESTION_MAP: dict[str, tuple[str, str]] = {
    "facility.transformer_count": (
        "FACILITY_TRANSFORMER_COUNT",
        "Please provide the number of transformers installed at the facility.",
    ),
    "facility.transformer_ratings": (
        "FACILITY_TRANSFORMER_RATINGS",
        "Please provide the transformer ratings for the facility.",
    ),
    "facility.generator_count": (
        "FACILITY_GENERATOR_COUNT",
        "Please provide the number of generators installed at the facility.",
    ),
    "facility.generator_ratings": (
        "FACILITY_GENERATOR_RATINGS",
        "Please provide the generator ratings for the facility.",
    ),
    "facility.ups_count": (
        "FACILITY_UPS_COUNT",
        "Please provide the number of UPS systems installed at the facility.",
    ),
    "facility.ups_topology": (
        "FACILITY_UPS_TOPOLOGY",
        "Please describe the UPS topology installed at the facility.",
    ),
    "facility.substation_configuration": (
        "FACILITY_SUBSTATION_CONFIGURATION",
        "Please provide the facility substation configuration.",
    ),
    "facility.motor_schedule": (
        "FACILITY_MOTOR_SCHEDULE",
        "Please provide the facility motor schedule.",
    ),
    "facility.relay_settings": (
        "FACILITY_RELAY_SETTINGS",
        "Please provide the relay settings for the facility.",
    ),
    "facility.equipment_schedule": (
        "FACILITY_EQUIPMENT_SCHEDULE",
        "Please provide the equipment schedule for the facility.",
    ),
    "facility.dynamic_model_available": (
        "FACILITY_DYNAMIC_MODEL_AVAILABLE",
        "Is a dynamic model package available for the facility?",
    ),
    "facility.pscad_model_package": (
        "FACILITY_PSCAD_MODEL_PACKAGE",
        "Is a PSCAD or EMT model package available for the facility?",
    ),
}


