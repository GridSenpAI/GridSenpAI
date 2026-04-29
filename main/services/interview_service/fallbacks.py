from __future__ import annotations

from typing import Any, Callable

from services.interview_service.models import InterviewFallbackResult, InterviewQuestion
from services.interview_service.missing_field_selection import (
    build_candidate_lookup,
    build_field_record_lookup,
    build_review_flag_lookup,
    collect_related_artifact_ids,
    coerce_dict_list,
    determine_resolution_reason,
    infer_triggering_status,
)


def generate_interview_fallback(
    *,
    requested_field_paths: list[str],
    candidates: list[Any],
    canonical_state: dict[str, Any],
    context: Any | None,
    normalize_field_path: Callable[[Any], str],
    build_question_metadata: Callable[[str], tuple[str, str]],
    classify_question_category: Callable[[dict[str, Any]], str],
    question_priority: Callable[[dict[str, Any]], int],
    question_enricher: Callable[[InterviewQuestion, Any | None, dict[str, list[Any]], dict[str, list[dict[str, Any]]]], InterviewQuestion],
) -> InterviewFallbackResult:
    field_records = coerce_dict_list(canonical_state.get("field_records"))
    review_flags = coerce_dict_list(canonical_state.get("review_flags"))

    record_lookup = build_field_record_lookup(field_records, normalize_field_path)
    review_flag_lookup = build_review_flag_lookup(review_flags, normalize_field_path)
    candidate_lookup = build_candidate_lookup(candidates, normalize_field_path)

    unresolved_fields: list[str] = []
    questions: list[InterviewQuestion] = []

    for requested_field_path in requested_field_paths:
        normalized_field_path = normalize_field_path(requested_field_path)
        resolution_reason = determine_resolution_reason(
            field_path=normalized_field_path,
            record_lookup=record_lookup,
            review_flag_lookup=review_flag_lookup,
            candidate_lookup=candidate_lookup,
        )
        if resolution_reason is None:
            continue

        unresolved_fields.append(requested_field_path)
        question_id, prompt = build_question_metadata(requested_field_path)
        related_artifact_ids = sorted({
            artifact_id
            for artifact_id in collect_related_artifact_ids(normalized_field_path, record_lookup, candidate_lookup)
            if artifact_id
        })
        triggering_status = infer_triggering_status(normalized_field_path, record_lookup)
        seed_question = {
            "field_path": requested_field_path,
            "reason": resolution_reason,
            "triggering_status": triggering_status,
            "required": True,
            "metadata": {
                "normalized_field_path": normalized_field_path,
                "review_flag_categories": review_flag_lookup.get(normalized_field_path, []),
            },
        }
        category = classify_question_category(seed_question)
        priority = question_priority(seed_question)
        question = InterviewQuestion(
            field_path=requested_field_path,
            question_id=question_id,
            prompt=prompt,
            reason=resolution_reason,
            triggering_status=triggering_status,
            question_category=category,
            priority=priority,
            requires_confirmation=category in {"confirmation", "low_confidence", "review_required", "conflicting"},
            related_artifact_ids=related_artifact_ids,
            metadata={
                "normalized_field_path": normalized_field_path,
                "review_flag_categories": review_flag_lookup.get(normalized_field_path, []),
                "question_category": category,
                "priority": priority,
            },
        )
        questions.append(
            question_enricher(
                question=question,
                context=context,
                candidate_lookup=candidate_lookup,
                record_lookup=record_lookup,
            )
        )

    return InterviewFallbackResult(unresolved_fields=unresolved_fields, questions=questions)
