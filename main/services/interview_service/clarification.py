from __future__ import annotations

from typing import Any

from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent
from shared.runtime_stage_contract import GAP_RESOLUTION_INTERVIEW_STAGE
from services.interview_service.question_catalog import get_question_by_field_path, get_question_by_id


def can_run_agent(context: Any | None) -> bool:
    if context is None:
        return False
    run_id = getattr(context, "run_id", None)
    return isinstance(run_id, str) and bool(run_id.strip())


def build_question_evidence_anchors(
    metadata: dict[str, Any] | None,
    suggested_sources: list[str] | None,
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    metadata = dict(metadata) if isinstance(metadata, dict) else {}

    normalized_field_path = str(metadata.get("normalized_field_path", "")).strip()
    if normalized_field_path:
        anchors.append({"anchor_type": "field_path", "field_path": normalized_field_path})

    related_artifact_ids = metadata.get("related_artifact_ids", [])
    if isinstance(related_artifact_ids, list):
        for artifact_id in related_artifact_ids:
            cleaned = str(artifact_id).strip()
            if cleaned:
                anchors.append({"anchor_type": "artifact_id", "artifact_id": cleaned})

    for source_name in suggested_sources or []:
        cleaned = str(source_name).strip()
        if cleaned:
            anchors.append({"anchor_type": "suggested_source", "source_name": cleaned})

    return anchors


def enrich_question_with_agent(*, context: Any | None, question_record: dict[str, Any]) -> dict[str, Any]:
    if not can_run_agent(context):
        return question_record

    field_path = str(question_record.get("field_path", "")).strip()
    question_text = str(question_record.get("question", "")).strip()
    reason = str(question_record.get("reason", "")).strip()
    metadata = question_record.get("metadata", {})
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    allowed_values = metadata.get("allowed_values", [])
    suggested_sources = question_record.get("suggested_sources", [])
    suggested_sources = suggested_sources if isinstance(suggested_sources, list) else []

    try:
        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="intake_clarification_agent",
                stage_name=GAP_RESOLUTION_INTERVIEW_STAGE,
                task_name="question_explanation",
                inputs={
                    "field_path": field_path,
                    "question_id": question_record.get("question_id"),
                    "question_text": question_text,
                    "reason": reason,
                    "category": question_record.get("category"),
                    "priority": question_record.get("priority"),
                    "allowed_values": allowed_values if isinstance(allowed_values, list) else [],
                    "metadata": metadata,
                    "suggested_sources": suggested_sources,
                },
                metadata={
                    "service": "interview_service",
                    "source": question_record.get("source"),
                },
                trigger_reason=reason or "interview_followup_generation",
                associated_field_paths=[field_path] if field_path else [],
                evidence_anchors=build_question_evidence_anchors(metadata, suggested_sources),
                suggested_output_fields=[
                    "clarified_question_text",
                    "explained_question",
                    "clarification_prompt",
                    "candidate_structured_answer",
                    "needs_human_reask",
                    "suggested_next_field_path",
                    "rationale",
                    "confidence",
                ],
            ),
        )
    except Exception as exc:
        metadata["agent_error"] = str(exc)
        question_record["metadata"] = metadata
        return question_record

    structured_output = result.get("structured_output", {})
    structured_output = structured_output if isinstance(structured_output, dict) else {}

    clarified_question_text = structured_output.get("clarified_question_text")
    explained_question = structured_output.get("explained_question")
    clarification_prompt = structured_output.get("clarification_prompt")
    rationale = structured_output.get("rationale")
    confidence = structured_output.get("confidence")
    candidate_structured_answer = structured_output.get("candidate_structured_answer")
    needs_human_reask = structured_output.get("needs_human_reask")
    suggested_next_field_path = structured_output.get("suggested_next_field_path")
    review_notes = structured_output.get("review_notes", [])

    if isinstance(clarified_question_text, str) and clarified_question_text.strip():
        metadata["help_text"] = clarified_question_text.strip()
    elif isinstance(explained_question, str) and explained_question.strip():
        metadata["help_text"] = explained_question.strip()
    if isinstance(clarification_prompt, str) and clarification_prompt.strip():
        metadata["clarification_prompt"] = clarification_prompt.strip()
    if isinstance(rationale, str) and rationale.strip():
        metadata["agent_rationale"] = rationale.strip()
    if isinstance(confidence, str) and confidence.strip():
        metadata["agent_confidence"] = confidence.strip()
    if candidate_structured_answer is not None:
        metadata["candidate_structured_answer"] = candidate_structured_answer
    if isinstance(needs_human_reask, bool):
        metadata["needs_human_reask"] = needs_human_reask
    if isinstance(suggested_next_field_path, str) and suggested_next_field_path.strip():
        metadata["suggested_next_field_path"] = suggested_next_field_path.strip()
    if isinstance(review_notes, list) and review_notes:
        metadata["agent_review_notes"] = [str(item).strip() for item in review_notes if isinstance(item, str) and item.strip()]

    metadata["agent_id"] = result.get("agent_id")
    metadata["agent_status"] = result.get("status")
    metadata["agent_audit_path"] = result.get("audit_path")
    metadata["agent_policy"] = result.get("policy", {})
    question_record["metadata"] = metadata
    return question_record


def enrich_clarification_with_agent(*, context: Any | None, clarification_record: dict[str, Any]) -> dict[str, Any]:
    if not can_run_agent(context):
        return clarification_record

    question_id = str(clarification_record.get("question_id", "")).strip()
    field_path = str(clarification_record.get("field_path", "")).strip()
    raw_answer = clarification_record.get("raw_answer")
    reason = str(clarification_record.get("reason", "")).strip()

    question = get_question_by_id(question_id)
    if question is None and field_path:
        question = get_question_by_field_path(field_path)

    allowed_values = list(question.allowed_values) if question is not None else []
    question_text = question.prompt if question is not None else f"Please provide the value for '{field_path}'."

    try:
        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="intake_clarification_agent",
                stage_name=GAP_RESOLUTION_INTERVIEW_STAGE,
                task_name="clarification_generation",
                inputs={
                    "field_path": field_path,
                    "question_id": question_id,
                    "question_text": question_text,
                    "raw_answer": raw_answer,
                    "reason": reason,
                    "allowed_values": allowed_values,
                },
                metadata={
                    "service": "interview_service",
                    "source": clarification_record.get("source_name", "interview_input"),
                },
                trigger_reason=reason or "raw_answer_failed_schema_parsing",
                associated_field_paths=[field_path] if field_path else [],
                evidence_anchors=[],
                suggested_output_fields=[
                    "clarification_prompt",
                    "candidate_structured_answer",
                    "needs_human_reask",
                    "rationale",
                    "confidence",
                ],
            ),
        )
    except Exception as exc:
        clarification_record["agent_error"] = str(exc)
        return clarification_record

    structured_output = result.get("structured_output", {})
    structured_output = structured_output if isinstance(structured_output, dict) else {}

    clarification_prompt = structured_output.get("clarification_prompt")
    candidate_structured_answer = structured_output.get("candidate_structured_answer")
    needs_human_reask = structured_output.get("needs_human_reask")
    rationale = structured_output.get("rationale")
    confidence = structured_output.get("confidence")
    review_notes = structured_output.get("review_notes", [])

    if isinstance(clarification_prompt, str) and clarification_prompt.strip():
        clarification_record["clarification_prompt"] = clarification_prompt.strip()
    if candidate_structured_answer is not None:
        clarification_record["candidate_structured_answer"] = candidate_structured_answer
    if isinstance(needs_human_reask, bool):
        clarification_record["needs_human_reask"] = needs_human_reask
    if isinstance(rationale, str) and rationale.strip():
        clarification_record["agent_rationale"] = rationale.strip()
    if isinstance(confidence, str) and confidence.strip():
        clarification_record["agent_confidence"] = confidence.strip()
    if isinstance(review_notes, list) and review_notes:
        clarification_record["agent_review_notes"] = [str(item).strip() for item in review_notes if isinstance(item, str) and item.strip()]

    clarification_record["agent_id"] = result.get("agent_id")
    clarification_record["agent_status"] = result.get("status")
    clarification_record["agent_audit_path"] = result.get("audit_path")
    clarification_record["agent_policy"] = result.get("policy", {})
    return clarification_record


def resolve_agent_task(reason: str | None) -> str:
    normalized_reason = str(reason or "").strip().lower()
    if normalized_reason in {"low_confidence", "review_required", "conflicting"}:
        return "confirmation_generation"
    return "question_explanation"


def build_agent_evidence_anchors(candidate_summary: list[dict[str, Any]], record_summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for item in candidate_summary:
        source_name = str(item.get("source_name", "")).strip()
        field_path = str(item.get("field_path", "")).strip()
        if source_name or field_path:
            anchors.append({
                "anchor_type": "candidate",
                "source_name": source_name,
                "field_path": field_path,
            })
    for item in record_summary:
        source_name = str(item.get("source_name", "")).strip()
        field_path = str(item.get("field_path", "")).strip()
        if source_name or field_path:
            anchors.append({
                "anchor_type": "canonical_record",
                "source_name": source_name,
                "field_path": field_path,
            })
    return anchors
