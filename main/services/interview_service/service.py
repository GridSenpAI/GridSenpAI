from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime_service.models import AgentRequest
from shared.governed_summary import build_governed_summary
from shared.project_identity import resolve_project_identity
from shared.review_priority import build_field_governance_core, build_interview_priority_plan
from services.agent_runtime_service.service import run_agent
from shared.runtime_stage_contract import GAP_RESOLUTION_INTERVIEW_STAGE
from services.interview_service.question_catalog import (
    get_question_by_field_path,
    get_question_by_id,
)
from services.interview_service.utils import process_raw_answer
from services.interview_service.authority import merge_interview_answer_into_ledger_entry
from services.validation_service.utils import coerce_list
from shared.master_field_policy import field_policy_export
from shared.planner_field_workflow import build_interview_question_records_from_ledger
from shared.pre_interview_planner_ledger import build_pre_interview_planner_field_contract
from shared.planner_registry import (
    build_followup_profile,
    field_label,
    field_requiredness,
    interview_priority_rank_map,
    field_is_planner_critical,
    planner_registry_resolution_backlog,
    summarize_field_resolution_governance,
)
from shared.document_field_pack_registry import (
    build_document_field_pack,
    filter_question_records_by_field_pack,
)


SUPPORTED_SUFFIXES: set[str] = {".json", ".txt"}

# Transitional module-level fallback used by helper functions that canonicalize field names
# before run_service-level retrieval context is available. The active runtime path still
# passes concrete retrieval payloads into the helpers that need them.
retrieval_result: dict[str, Any] | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or "gridsenpai_project"


def _project_identity_from_context(
    context: Any,
    *,
    extraction_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    canonical_state_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = getattr(context, "config", None)
    project_name = getattr(config, "project_name", None)
    previous_identity = {
        "project_id": getattr(config, "project_id", None),
        "project_name": getattr(config, "project_name", None),
        "project_number": getattr(config, "project_number", None),
        "applicant": getattr(config, "applicant", None),
    }
    return resolve_project_identity(
        run_id=str(getattr(context, "run_id", "") or ""),
        replay_source_run_id=getattr(context, "replay_source_run_id", None),
        parent_run_id=getattr(context, "parent_run_id", None),
        existing_project_name=project_name if isinstance(project_name, str) else None,
        extraction_result=extraction_result,
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
        previous_identity=previous_identity,
    )


def _project_id_from_context(
    context: Any,
    *,
    extraction_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    canonical_state_result: dict[str, Any] | None = None,
) -> str:
    identity = _project_identity_from_context(
        context,
        extraction_result=extraction_result,
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
    )
    project_id = str(identity.get("project_id") or "").strip()
    return project_id or "UNRESOLVED_PROJECT"


def _session_root_from_context(context: Any) -> Path:
    project_root = Path(getattr(context, "project_root", Path(__file__).resolve().parents[2]))
    return project_root / "runs" / "interview_sessions"


def _session_path_from_context(context: Any, project_id: str) -> Path:
    return _session_root_from_context(context) / f"{_slugify(project_id)}_interview_session.json"


def _candidate_session_paths_from_context(
    context: Any,
    *,
    project_id: str,
    project_identity: dict[str, Any],
) -> list[Path]:
    session_root = _session_root_from_context(context)
    candidates: list[Path] = [_session_path_from_context(context, project_id)]

    for value in (
        project_identity.get("project_number"),
        project_identity.get("project_name"),
        getattr(getattr(context, "config", None), "project_name", None),
    ):
        cleaned = str(value or "").strip()
        if cleaned:
            candidates.append(session_root / f"{_slugify(f'PROJECT::{cleaned}')}_interview_session.json")
            candidates.append(session_root / f"{_slugify(cleaned)}_interview_session.json")

    if session_root.exists():
        run_ids = {
            str(getattr(context, "run_id", "") or "").strip(),
            str(getattr(context, "replay_source_run_id", "") or "").strip(),
            str(getattr(context, "parent_run_id", "") or "").strip(),
        }
        run_ids = {item for item in run_ids if item}
        for path in sorted(session_root.glob("*_interview_session.json")):
            payload = _safe_read_json(path)
            if not isinstance(payload, dict):
                continue
            ui_state = payload.get("ui_state", {})
            ui_state = ui_state if isinstance(ui_state, dict) else {}
            if str(payload.get("project_id", "")).strip() == project_id:
                candidates.append(path)
                continue
            if any(run_id and run_id in str(path) for run_id in run_ids):
                candidates.append(path)
                continue
            if str(ui_state.get("run_id", "")).strip() in run_ids:
                candidates.append(path)

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _normalize_interview_ui_status(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    aliases = {
        "SKIPPED": "SKIPPED_BY_USER",
        "SKIP": "SKIPPED_BY_USER",
        "INTERVIEW_SKIPPED_BY_USER": "SKIPPED_BY_USER",
        "DEFERRED": "DEFERRED_BY_USER",
        "INTERVIEW_DEFERRED_BY_USER": "DEFERRED_BY_USER",
        "PARTIAL_CONTINUE": "PARTIAL_SUBMITTED_CONTINUE",
    }
    return aliases.get(normalized, normalized)


def _select_session_path_for_workflow(
    *,
    primary_path: Path,
    candidate_paths: list[Path],
) -> Path:
    existing_paths = [path for path in candidate_paths if path.exists()]

    for path in existing_paths:
        payload = _safe_read_json(path)
        if not isinstance(payload, dict):
            continue
        ui_state = payload.get("ui_state", {})
        ui_state = ui_state if isinstance(ui_state, dict) else {}
        status = _normalize_interview_ui_status(ui_state.get("status"))
        if status in {"SKIPPED_BY_USER", "DEFERRED_BY_USER", "SUBMITTED_CONTINUE", "PARTIAL_SUBMITTED_CONTINUE"}:
            return path

    if primary_path.exists():
        return primary_path

    return existing_paths[0] if existing_paths else primary_path


def _discover_interview_files(input_dir: Path) -> list[Path]:
    candidates: list[Path] = []

    if not input_dir.exists():
        return candidates

    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue

        lowered = path.name.lower()
        if "interview" in lowered or "questionnaire" in lowered or "facility_intake" in lowered:
            candidates.append(path)

    return candidates


def _build_interview_source_record(path: Path) -> dict[str, Any]:
    return {
        "source_name": path.name,
        "source_path": str(path),
        "source_suffix": path.suffix.lower(),
        "loaded_at": utc_now_iso(),
    }


def _normalize_answer_record(
    question_id: str,
    field_path: str,
    answer: Any,
    source_name: str,
) -> dict[str, Any]:
    status = "CONFIRMED"

    if answer is None:
        status = "CLARIFICATION_REQUIRED"

    if isinstance(answer, str) and answer.strip() == "":
        status = "CLARIFICATION_REQUIRED"

    return {
        "question_id": question_id,
        "field_path": field_path,
        "answer": answer,
        "source_name": source_name,
        "answer_status": status,
    }


def _can_run_agent(context: Any | None) -> bool:
    if context is None:
        return False

    run_id = getattr(context, "run_id", None)
    return isinstance(run_id, str) and bool(run_id.strip())


def _build_question_evidence_anchors(
    metadata: dict[str, Any] | None,
    suggested_sources: list[str] | None,
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    metadata = metadata if isinstance(metadata, dict) else {}

    source_method = str(metadata.get("source_method", "")).strip()
    candidate_id = str(metadata.get("candidate_id", "")).strip()
    if source_method or candidate_id:
        anchors.append(
            {
                "anchor_type": "extraction_candidate",
                "candidate_id": candidate_id,
                "source_method": source_method,
            }
        )

    review_flag_id = str(metadata.get("review_flag_id", "")).strip()
    if review_flag_id:
        anchors.append(
            {
                "anchor_type": "review_flag",
                "review_flag_id": review_flag_id,
            }
        )

    for source_name in suggested_sources or []:
        cleaned = str(source_name).strip()
        if not cleaned:
            continue
        anchors.append(
            {
                "anchor_type": "suggested_source",
                "source_name": cleaned,
            }
        )

    return anchors


def _enrich_question_with_agent(
    *,
    context: Any | None,
    question_record: dict[str, Any],
) -> dict[str, Any]:
    if not _can_run_agent(context):
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
                agent_id="applicant_interview_agent",
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
                evidence_anchors=_build_question_evidence_anchors(metadata, suggested_sources),
                suggested_output_fields=[
                    "clarified_question_text",
                    "explained_question",
                    "clarification_prompt",
                    "candidate_structured_answer",
                    "needs_human_reask",
                    "suggested_next_field_path",
                    "rationale",
                    "confidence",
                    "review_priority_counts",
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
        metadata["agent_review_notes"] = [
            str(item).strip()
            for item in review_notes
            if isinstance(item, str) and item.strip()
        ]

    metadata["agent_id"] = result.get("agent_id")
    metadata["agent_status"] = result.get("status")
    metadata["agent_audit_path"] = result.get("audit_path")
    metadata["agent_policy"] = result.get("policy", {})
    question_record["metadata"] = metadata
    return question_record




MAX_AGENT_ENRICHED_INTERVIEW_QUESTIONS = 25
MAX_INTERVIEW_OVERSIGHT_AGENT_QUESTIONS = 30


def _compact_question_for_agent(question_record: dict[str, Any]) -> dict[str, Any]:
    metadata = question_record.get("metadata") if isinstance(question_record.get("metadata"), dict) else {}
    compact_metadata_keys = (
        "field_id",
        "planner_critical",
        "requiredness",
        "queue_status",
        "accepted_value",
        "accepted_confidence",
        "confidence_band",
        "conflict_materiality",
        "needs_applicant_confirmation",
        "planner_review_flag",
        "triage_bucket",
        "triage_rank",
        "triage_reason",
        "presentation_phase",
        "interview_priority_score",
    )
    compact_metadata: dict[str, Any] = {}
    for key in compact_metadata_keys:
        if key not in metadata:
            continue
        value = metadata.get(key)
        if value is None or value == "" or value == []:
            continue
        compact_metadata[key] = value
    reason = str(question_record.get("reason", "")).strip()
    question = str(question_record.get("question", "")).strip()
    return {
        "question_id": str(question_record.get("question_id", "")).strip(),
        "field_path": str(question_record.get("field_path", "")).strip(),
        "question": question[:500],
        "reason": reason[:600],
        "question_category": str(question_record.get("question_category", question_record.get("category", ""))).strip(),
        "priority": question_record.get("priority"),
        "triage_bucket": str(question_record.get("triage_bucket", compact_metadata.get("triage_bucket", ""))).strip(),
        "triage_rank": question_record.get("triage_rank", compact_metadata.get("triage_rank")),
        "source": str(question_record.get("source", "")).strip(),
        "metadata": compact_metadata,
    }


def _compact_questions_for_agent(questions: list[dict[str, Any]], *, max_count: int = MAX_INTERVIEW_OVERSIGHT_AGENT_QUESTIONS) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in questions if isinstance(questions, list) else []:
        if not isinstance(item, dict):
            continue
        compact.append(_compact_question_for_agent(item))
        if len(compact) >= max_count:
            break
    return compact


def _enrich_question_records_capped(
    *,
    context: Any | None,
    questions: list[dict[str, Any]],
    max_count: int = MAX_AGENT_ENRICHED_INTERVIEW_QUESTIONS,
) -> list[dict[str, Any]]:
    if not questions or not _can_run_agent(context):
        return questions

    enriched: list[dict[str, Any]] = []
    enriched_count = 0
    for item in questions:
        if not isinstance(item, dict):
            enriched.append(item)
            continue
        metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {}
        triage_rank = int(item.get("triage_rank", metadata.get("triage_rank", 99)) if item.get("triage_rank", metadata.get("triage_rank", 99)) not in (None, "") else 99)
        should_enrich = enriched_count < max_count and triage_rank <= 1
        if should_enrich:
            enriched.append(_enrich_question_with_agent(context=context, question_record=dict(item)))
            enriched_count += 1
            continue
        metadata["agent_enrichment_status"] = "SKIPPED_AFTER_TRIAGE_CAP"
        metadata["agent_enrichment_reason"] = "Question kept in interview queue, but agent explanation was skipped to prevent prompt/call explosion after triage."
        skipped = dict(item)
        skipped["metadata"] = metadata
        enriched.append(skipped)
    return enriched


def _enrich_clarification_with_agent(
    *,
    context: Any | None,
    clarification_record: dict[str, Any],
) -> dict[str, Any]:
    if not _can_run_agent(context):
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
        clarification_record["agent_review_notes"] = [
            str(item).strip()
            for item in review_notes
            if isinstance(item, str) and item.strip()
        ]

    clarification_record["agent_id"] = result.get("agent_id")
    clarification_record["agent_status"] = result.get("status")
    clarification_record["agent_audit_path"] = result.get("audit_path")
    clarification_record["agent_policy"] = result.get("policy", {})
    return clarification_record


def _append_processed_answer(
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
                _enrich_clarification_with_agent(
                    context=context,
                    clarification_record=clarification_record,
                )
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
            _enrich_clarification_with_agent(
                context=context,
                clarification_record=clarification_record,
            )
        )


def _extract_json_interview_payload(
    *,
    context: Any | None,
    payload: dict[str, Any],
    source_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    answers_candidate: list[dict[str, Any]] = []
    answers_confirmed: list[dict[str, Any]] = []
    clarifications: list[dict[str, Any]] = []
    warnings: list[str] = []

    raw_answers = payload.get("answers", [])

    if not isinstance(raw_answers, list):
        warnings.append(
            f"Interview source '{source_name}' has invalid 'answers' structure; expected list."
        )
        return answers_candidate, answers_confirmed, clarifications, warnings

    for index, item in enumerate(raw_answers, start=1):
        if not isinstance(item, dict):
            warnings.append(
                f"Interview source '{source_name}' answer #{index} is not an object."
            )
            continue

        question_id_value = item.get("question_id")
        field_path_value = item.get("field_path")
        answer = item.get("answer")

        question_id = ""
        field_path = ""

        if isinstance(question_id_value, str) and question_id_value.strip():
            question_id = question_id_value.strip()

        if isinstance(field_path_value, str) and field_path_value.strip():
            field_path = field_path_value.strip()

        if not question_id and field_path:
            question = get_question_by_field_path(field_path)
            if question is not None:
                question_id = question.question_id

        if not field_path and question_id:
            question = get_question_by_id(question_id)
            if question is not None:
                field_path = question.field_path

        if not question_id:
            warnings.append(
                f"Interview source '{source_name}' answer #{index} is missing question_id."
            )
            continue

        if not field_path:
            warnings.append(
                f"Interview source '{source_name}' answer #{index} is missing field_path."
            )
            continue

        _append_processed_answer(
            context=context,
            question_id=question_id,
            field_path=field_path,
            raw_answer=answer,
            source_name=source_name,
            answers_candidate=answers_candidate,
            answers_confirmed=answers_confirmed,
            clarifications=clarifications,
        )

    return answers_candidate, answers_confirmed, clarifications, warnings


def _extract_text_interview_payload(
    *,
    context: Any | None,
    text: str,
    source_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    answers_candidate: list[dict[str, Any]] = []
    answers_confirmed: list[dict[str, Any]] = []
    clarifications: list[dict[str, Any]] = []
    warnings: list[str] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if "question_id=" not in line or "field_path=" not in line or "answer=" not in line:
            warnings.append(
                f"Interview source '{source_name}' line {line_number} skipped due to invalid format."
            )
            continue

        parts = [part.strip() for part in line.split(";") if part.strip()]
        values: dict[str, str] = {}

        for part in parts:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            values[key.strip()] = value.strip()

        question_id = values.get("question_id", "")
        field_path = values.get("field_path", "")
        answer = values.get("answer", "")

        if not question_id or not field_path:
            warnings.append(
                f"Interview source '{source_name}' line {line_number} skipped due to missing required fields."
            )
            continue

        _append_processed_answer(
            context=context,
            question_id=question_id,
            field_path=field_path,
            raw_answer=answer,
            source_name=source_name,
            answers_candidate=answers_candidate,
            answers_confirmed=answers_confirmed,
            clarifications=clarifications,
        )

    return answers_candidate, answers_confirmed, clarifications, warnings


def _priority_from_severity(severity: Any) -> str:
    value = str(severity or "").strip().upper()
    if value in {"HIGH", "CRITICAL"}:
        return "HIGH"
    if value == "MODERATE":
        return "MODERATE"
    return "LOW"


def _question_record(
    *,
    question_id: str,
    field_path: str,
    question: str,
    category: str,
    priority: str,
    source: str,
    reason: str | None = None,
    suggested_sources: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question_id": question_id,
        "field_path": field_path,
        "question": question,
        "category": category,
        "priority": priority,
        "source": source,
    }
    if reason:
        payload["reason"] = reason
    if suggested_sources:
        payload["suggested_sources"] = suggested_sources
    if metadata:
        payload["metadata"] = metadata
    return payload


def _build_question_from_catalog_or_generic(
    *,
    field_path: str,
    default_question_id: str,
    default_question: str,
    category: str,
    priority: str,
    source: str,
    reason: str | None = None,
    suggested_sources: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog_question = get_question_by_field_path(field_path)

    if catalog_question is not None:
        catalog_metadata: dict[str, Any] = dict(metadata or {})
        if catalog_question.help_text:
            catalog_metadata["help_text"] = catalog_question.help_text
        if catalog_question.examples:
            catalog_metadata["examples"] = list(catalog_question.examples)
        if catalog_question.allowed_values:
            catalog_metadata["allowed_values"] = list(catalog_question.allowed_values)
        catalog_metadata["answer_type"] = catalog_question.answer_type
        catalog_metadata["required"] = catalog_question.required

        return _question_record(
            question_id=catalog_question.question_id,
            field_path=catalog_question.field_path,
            question=catalog_question.prompt,
            category=category,
            priority=priority,
            source=source,
            reason=reason,
            suggested_sources=suggested_sources,
            metadata=catalog_metadata,
        )

    profile = build_followup_profile(field_path)
    profile_metadata: dict[str, Any] = dict(metadata or {})
    if profile.get("field_id"):
        profile_metadata.setdefault("field_id", profile.get("field_id"))
    if profile.get("label"):
        profile_metadata.setdefault("label", profile.get("label"))
    profile_metadata.setdefault("required", field_requiredness(field_path) != "optional")
    profile_metadata.setdefault("planner_critical", field_is_planner_critical(field_path))
    profile_metadata.setdefault("field_policy", field_policy_export(field_path))

    fallback_question = default_question
    if default_question.startswith("Please provide the required value for '"):
        label = field_label(field_path)
        if label:
            fallback_question = f"Please provide or confirm {label.lower()}."

    return _question_record(
        question_id=default_question_id,
        field_path=field_path,
        question=fallback_question,
        category=category,
        priority=priority,
        source=source,
        reason=reason,
        suggested_sources=suggested_sources,
        metadata=profile_metadata,
    )


def _build_questions_from_extraction(
    extraction_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not extraction_result:
        return []

    questions: list[dict[str, Any]] = []
    schema_field_candidates = extraction_result.get("schema_field_candidates", [])
    if not isinstance(schema_field_candidates, list):
        return questions

    for candidate in schema_field_candidates:
        if not isinstance(candidate, dict):
            continue

        field_path = candidate.get("field_path")
        if not isinstance(field_path, str) or not field_path.strip():
            continue

        confidence_label = str(candidate.get("confidence_label", "")).strip().upper()
        if confidence_label not in {"LOW", "UNRESOLVED"}:
            continue

        questions.append(
            _build_question_from_catalog_or_generic(
                field_path=field_path.strip(),
                default_question_id=f"EXTRACTION_REVIEW::{field_path.strip()}",
                default_question=f"Please confirm the correct value for '{field_path.strip()}'.",
                category="extraction_review",
                priority="MODERATE",
                source="extraction_result",
                reason=f"Extraction produced {confidence_label or 'low'} confidence evidence for this field.",
                metadata={
                    "candidate_id": candidate.get("candidate_id"),
                    "source_method": candidate.get("source_method"),
                    "confidence_label": confidence_label,
                    "confidence": candidate.get("confidence"),
                },
            )
        )

    return questions


def _build_questions_from_normalization(
    normalization_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not normalization_result:
        return []

    raw_followups = normalization_result.get("followup_questions", [])
    if not isinstance(raw_followups, list):
        raw_followups = []

    questions: list[dict[str, Any]] = []
    seen_field_paths: set[str] = set()

    for index, item in enumerate(raw_followups, start=1):
        if not isinstance(item, dict):
            continue

        field_path = item.get("field_path")
        if not isinstance(field_path, str) or not field_path.strip():
            continue

        normalized_field_path = field_path.strip()
        reason = str(item.get("reason", "")).strip() or "Additional engineer input is required."
        severity = item.get("severity")
        suggested_sources_raw = item.get("suggested_sources", [])
        suggested_sources = [
            str(value).strip()
            for value in suggested_sources_raw
            if isinstance(value, str) and value.strip()
        ] if isinstance(suggested_sources_raw, list) else []

        questions.append(
            _build_question_from_catalog_or_generic(
                field_path=normalized_field_path,
                default_question_id=str(item.get("question_id") or f"NORMALIZATION_FOLLOWUP_{index:03d}"),
                default_question=f"Please provide the required value for '{normalized_field_path}'.",
                category="normalization_followup",
                priority=_priority_from_severity(severity),
                source="normalization_result",
                reason=reason,
                suggested_sources=suggested_sources,
                metadata={
                    "severity": severity,
                    **{key: value for key, value in item.items() if key not in {"question_id", "field_path", "reason", "suggested_sources", "severity"}},
                },
            )
        )
        seen_field_paths.add(normalized_field_path)

    validation_report = normalization_result.get("validation_report", {})
    if isinstance(validation_report, dict):
        raw_missing_fields = validation_report.get("missing_fields", [])
        if isinstance(raw_missing_fields, list):
            fallback_index = len(questions)
            for field_path in raw_missing_fields:
                normalized_field_path = str(field_path).strip()
                if not normalized_field_path or normalized_field_path in seen_field_paths:
                    continue
                fallback_index += 1
                questions.append(
                    _build_question_from_catalog_or_generic(
                        field_path=normalized_field_path,
                        default_question_id=f"NORMALIZATION_MISSING_{fallback_index:03d}",
                        default_question=f"Please provide the required value for '{normalized_field_path}'.",
                        category="normalization_missing_field",
                        priority="HIGH",
                        source="normalization_result",
                        reason="This planner-required field is still unresolved after extraction and normalization.",
                        metadata={
                            "derived_from": "validation_report.missing_fields",
                        },
                    )
                )
                seen_field_paths.add(normalized_field_path)

    return questions



def _build_governed_release_summary(canonical_state_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(canonical_state_result, dict):
        return {}
    canonical_state = canonical_state_result.get("canonical_state", {})
    if not isinstance(canonical_state, dict):
        return {}
    governance = build_field_governance_core(canonical_state=canonical_state)
    release = governance.get("governed_release_decision", {}) if isinstance(governance.get("governed_release_decision", {}), dict) else {}
    summary = release.get("summary", {}) if isinstance(release.get("summary", {}), dict) else {}
    return dict(summary)



def _filter_normalization_questions_for_interview(
    normalization_questions: list[dict[str, Any]],
    *,
    canonical_state_result: dict[str, Any] | None,
    authoritative_questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not normalization_questions:
        return []
    if not isinstance(canonical_state_result, dict):
        return list(normalization_questions)

    lookup = _build_field_resolution_lookup(canonical_state_result)
    authoritative_field_keys: set[str] = set()
    for item in authoritative_questions:
        if not isinstance(item, dict):
            continue
        field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
        if field_path:
            authoritative_field_keys.add(field_path)
        metadata = item.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        field_id = str(metadata.get("field_id", "")).strip()
        if field_id:
            authoritative_field_keys.add(field_id)

    release_summary = _build_governed_release_summary(canonical_state_result)
    release_state = str(release_summary.get("release_state", "")).strip().upper()
    blocking_field_count = int(release_summary.get("blocking_field_count", 0) or 0)
    strict_filter = bool(authoritative_field_keys) or (release_state == "READY" and blocking_field_count == 0)
    if not strict_filter:
        return list(normalization_questions)

    filtered: list[dict[str, Any]] = []
    for item in normalization_questions:
        if not isinstance(item, dict):
            continue
        field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
        metadata = item.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        field_id = str(metadata.get("field_id", "")).strip()
        identity_keys = {field_path, field_id} - {""}
        resolution_entry = lookup.get(field_path) or lookup.get(field_id) or {}
        accepted_status = str(resolution_entry.get("accepted_status", resolution_entry.get("status", ""))).strip().lower()
        needs_confirmation = bool(resolution_entry.get("needs_applicant_confirmation", False))
        conflict_materiality = str(resolution_entry.get("conflict_materiality", "")).strip().lower()
        planner_critical = bool(metadata.get("planner_critical", field_is_planner_critical(field_path)))
        question_category = _classify_question_category(item)

        keep = False
        if authoritative_field_keys.intersection(identity_keys):
            keep = True
        elif question_category in {"conflicting", "review_required", "confirmation"} and planner_critical:
            keep = True
        elif needs_confirmation and planner_critical:
            keep = True
        elif conflict_materiality in {"high", "medium"} and planner_critical:
            keep = True
        elif accepted_status in {"review_required", "conflict", "conflicting"} and planner_critical:
            keep = True
        elif not authoritative_field_keys and release_state != "READY":
            keep = True

        if keep:
            filtered.append(item)

    return filtered



def _normalized_field_key(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    return cleaned




def _retrieval_field_path_lookup(retrieval_result: dict[str, Any] | None) -> dict[str, str]:
    lookup: dict[str, str] = {}
    if not isinstance(retrieval_result, dict):
        return lookup

    equipment_resolution = retrieval_result.get("equipment_reference_resolution", {})
    if not isinstance(equipment_resolution, dict):
        return lookup

    planner_guidance = equipment_resolution.get("planner_guidance", {})
    if isinstance(planner_guidance, dict):
        family_targets = planner_guidance.get("family_targets", {})
        if isinstance(family_targets, dict):
            for raw_fields in family_targets.values():
                if not isinstance(raw_fields, list):
                    continue
                for field_path in raw_fields:
                    cleaned = str(field_path or "").strip()
                    if not cleaned:
                        continue
                    lookup.setdefault(_normalized_field_key(cleaned), cleaned)
                    lookup.setdefault(cleaned.split(".")[-1].strip().lower(), cleaned)

    for item in equipment_resolution.get("candidate_fields", []):
        if not isinstance(item, dict):
            continue
        for key_name in ("canonical_field_key", "matched_field_key"):
            cleaned = str(item.get(key_name, "")).strip()
            if not cleaned:
                continue
            lookup.setdefault(_normalized_field_key(cleaned), cleaned)
            lookup.setdefault(cleaned.split(".")[-1].strip().lower(), cleaned)

    return lookup


def _canonicalize_retrieval_field_path(field_path: Any, retrieval_result: dict[str, Any] | None) -> str:
    cleaned = str(field_path or "").strip()
    if not cleaned:
        return ""
    if "." in cleaned:
        return cleaned
    lookup = _retrieval_field_path_lookup(retrieval_result)
    normalized = _normalized_field_key(cleaned)
    mapped = lookup.get(normalized, "")
    if mapped:
        return mapped

    equipment_resolution = retrieval_result.get("equipment_reference_resolution", {}) if isinstance(retrieval_result, dict) else {}
    planner_guidance = equipment_resolution.get("planner_guidance", {}) if isinstance(equipment_resolution, dict) else {}
    families = planner_guidance.get("families", []) if isinstance(planner_guidance, dict) else []
    if isinstance(families, list) and families:
        primary_family = str(families[0]).strip()
        if primary_family:
            return f"facility.{primary_family}.{cleaned}"
    return cleaned

def _equipment_candidate_fields_by_path(retrieval_result: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(retrieval_result, dict):
        return {}

    equipment_resolution = retrieval_result.get("equipment_reference_resolution", {})
    if not isinstance(equipment_resolution, dict):
        return {}

    raw_candidates = equipment_resolution.get("candidate_fields", [])
    if not isinstance(raw_candidates, list):
        return {}

    lookup: dict[str, list[dict[str, Any]]] = {}
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        for key_name in ("canonical_field_key", "matched_field_key", "spec_field"):
            field_key = _normalized_field_key(candidate.get(key_name))
            if not field_key:
                continue
            lookup.setdefault(field_key, []).append(candidate)
    return lookup


def _equipment_identity_summaries(retrieval_result: dict[str, Any] | None) -> list[str]:
    if not isinstance(retrieval_result, dict):
        return []

    equipment_resolution = retrieval_result.get("equipment_reference_resolution", {})
    if not isinstance(equipment_resolution, dict):
        return []

    matched_records = equipment_resolution.get("matched_records", [])
    if not isinstance(matched_records, list):
        return []

    summaries: list[str] = []
    for item in matched_records:
        if not isinstance(item, dict):
            continue
        manufacturer = str(item.get("manufacturer", "")).strip()
        model = str(item.get("model", "")).strip()
        equipment_family = str(item.get("equipment_family", "")).strip()
        parts = [part for part in (manufacturer, model) if part]
        summary = " ".join(parts)
        if equipment_family:
            summary = f"{equipment_family}: {summary}" if summary else equipment_family
        if summary and summary not in summaries:
            summaries.append(summary)
    return summaries


def _candidate_summary_for_field(
    field_path: str,
    candidate_lookup: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    candidates = list(candidate_lookup.get(_normalized_field_key(field_path), []))
    compact_values: list[dict[str, Any]] = []
    suggested_sources: list[str] = []
    summary_parts: list[str] = []

    for item in candidates[:3]:
        value = item.get("value")
        manufacturer = str(item.get("manufacturer", "")).strip()
        model = str(item.get("model", "")).strip()
        source_type = str(item.get("source_type", "")).strip()
        source_url = str(item.get("source_url", "")).strip()
        confidence = item.get("confidence")

        compact_values.append(
            {
                "value": value,
                "manufacturer": manufacturer,
                "model": model,
                "source_type": source_type,
                "confidence": confidence,
                "source_url": source_url or None,
            }
        )

        descriptor_parts = [part for part in (manufacturer, model) if part]
        descriptor = " ".join(descriptor_parts)
        rendered = repr(value)
        if descriptor:
            rendered = f"{descriptor} → {rendered}"
        if source_type:
            rendered = f"{rendered} ({source_type})"
        summary_parts.append(rendered)

        if source_url and source_url not in suggested_sources:
            suggested_sources.append(source_url)

    return compact_values, suggested_sources, summary_parts


def _build_questions_from_retrieval(
    retrieval_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not retrieval_result:
        return []

    questions: list[dict[str, Any]] = []
    evidence_gap = retrieval_result.get("evidence_gap", {})
    if not isinstance(evidence_gap, dict):
        evidence_gap = {}

    gap_status = str(evidence_gap.get("status", "")).strip().upper()
    gap_reason = str(evidence_gap.get("reason", "")).strip()
    gap_fill_strategy = str(retrieval_result.get("gap_fill_strategy", "")).strip()
    candidate_lookup = _equipment_candidate_fields_by_path(retrieval_result)
    matched_identities = _equipment_identity_summaries(retrieval_result)
    official_web_lookup_required = bool(retrieval_result.get("official_web_lookup_required", False))

    backlog_items = retrieval_result.get("resolution_backlog", [])
    if isinstance(backlog_items, list) and backlog_items:
        for index, item in enumerate(backlog_items, start=1):
            if not isinstance(item, dict):
                continue
            field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
            if not field_path:
                continue
            category = str(item.get("category", "retrieval_gap")).strip().lower() or "retrieval_gap"
            priority = str(item.get("priority", "MODERATE")).strip().upper() or "MODERATE"
            reason = str(item.get("reason", "")).strip() or gap_reason or "Grounded retrieval could not fully resolve this field."
            attempted_steps = item.get("attempted_resolution_steps", [])
            if not isinstance(attempted_steps, list):
                attempted_steps = []
            candidate_values = item.get("candidate_values", [])
            if not isinstance(candidate_values, list) or not candidate_values:
                compact_values, suggested_sources, summary_parts = _candidate_summary_for_field(field_path, candidate_lookup)
            else:
                compact_values = [candidate for candidate in candidate_values if isinstance(candidate, dict)]
                suggested_sources = [
                    str(candidate.get("source_url", "")).strip()
                    for candidate in compact_values
                    if str(candidate.get("source_url", "")).strip()
                ]
                summary_parts = []
                for candidate in compact_values:
                    manufacturer = str(candidate.get("manufacturer", "")).strip()
                    model = str(candidate.get("model", "")).strip()
                    descriptor = " ".join(part for part in (manufacturer, model) if part).strip()
                    rendered = repr(candidate.get("value"))
                    if descriptor:
                        rendered = f"{descriptor} → {rendered}"
                    source_type = str(candidate.get("source_type", "")).strip()
                    if source_type:
                        rendered = f"{rendered} ({source_type})"
                    summary_parts.append(rendered)
            matched_for_item = item.get("matched_equipment_identities", [])
            if not isinstance(matched_for_item, list) or not matched_for_item:
                matched_for_item = matched_identities[:3]

            if category == "retrieval_confirmation":
                default_question = (
                    f"Grounded vendor evidence found a possible value for '{field_path}', but it needs applicant confirmation. Please confirm or correct it."
                )
                if summary_parts:
                    default_question = (
                        f"Please confirm the proposed value for '{field_path}'. Grounded retrieval found: {'; '.join(summary_parts)}."
                    )
                question_category = "retrieval_confirmation"
                source_reason = reason
            elif category == "retrieval_deferred":
                default_question = (
                    f"We could not resolve '{field_path}' from vendor specifications or grounded reference sources because it is not a vendor-fixed field. Please provide or confirm the project-specific engineering value."
                )
                question_category = "retrieval_deferred"
                source_reason = reason
            else:
                default_question = f"Grounded references did not fully resolve '{field_path}'. Please provide or confirm the engineering value."
                if matched_for_item:
                    default_question = (
                        f"After checking your documents and grounded references for {', '.join(matched_for_item[:2])}, we still need '{field_path}'. Please provide or confirm the correct engineering value."
                    )
                if summary_parts:
                    source_reason = f"{reason} Partial candidate evidence was found: {'; '.join(summary_parts)}."
                else:
                    source_reason = reason
                question_category = "retrieval_gap"

            questions.append(
                _build_question_from_catalog_or_generic(
                    field_path=field_path,
                    default_question_id=f"RETRIEVAL_{category.upper()}_{index:03d}",
                    default_question=default_question,
                    category=question_category,
                    priority=priority,
                    source="retrieval_result",
                    reason=source_reason,
                    suggested_sources=suggested_sources,
                    metadata={
                        "evidence_gap_status": gap_status or ("REVIEW_REQUIRED" if category == "retrieval_confirmation" else "UNRESOLVED"),
                        "attempted_resolution_steps": attempted_steps or (["equipment_catalog", "vendor_documents"] + (["official_web"] if official_web_lookup_required else [])),
                        "gap_fill_strategy": str(item.get("gap_fill_strategy", "")).strip() or gap_fill_strategy or None,
                        "matched_equipment_identities": matched_for_item[:3],
                        "candidate_values": compact_values,
                        "resolution_scope": str(item.get("resolution_scope", "")).strip() or None,
                    },
                )
            )
        return questions

    requested_fields = retrieval_result.get("requested_field_paths", [])
    if not isinstance(requested_fields, list):
        requested_fields = []
    review_required_fields = retrieval_result.get("review_required_field_paths", [])
    if not isinstance(review_required_fields, list):
        review_required_fields = []
    out_of_scope_fields = retrieval_result.get("out_of_scope_missing_field_paths", [])
    if not isinstance(out_of_scope_fields, list):
        out_of_scope_fields = []

    if gap_status and gap_status != "RESOLVED":
        for index, field_path_value in enumerate(requested_fields, start=1):
            field_path = _canonicalize_retrieval_field_path(field_path_value, retrieval_result)
            if not field_path:
                continue

            compact_values, suggested_sources, summary_parts = _candidate_summary_for_field(field_path, candidate_lookup)
            attempted_steps = ["equipment_catalog", "vendor_documents"]
            if official_web_lookup_required:
                attempted_steps.append("official_web")

            default_question = f"Grounded references did not fully resolve '{field_path}'. Please provide or confirm the engineering value."
            if matched_identities:
                default_question = (
                    f"After checking your documents and grounded references for {', '.join(matched_identities[:2])}, "
                    f"we still need '{field_path}'. Please provide or confirm the correct engineering value."
                )

            reason = gap_reason or "Library, vendor PDF, and guarded web retrieval did not fully resolve this field."
            if summary_parts:
                reason = f"{reason} Partial candidate evidence was found: {'; '.join(summary_parts)}."

            questions.append(
                _build_question_from_catalog_or_generic(
                    field_path=field_path,
                    default_question_id=f"RETRIEVAL_GAP_{index:03d}",
                    default_question=default_question,
                    category="retrieval_gap",
                    priority="HIGH",
                    source="retrieval_result",
                    reason=reason,
                    suggested_sources=suggested_sources,
                    metadata={
                        "evidence_gap_status": gap_status,
                        "attempted_resolution_steps": attempted_steps,
                        "gap_fill_strategy": gap_fill_strategy or None,
                        "matched_equipment_identities": matched_identities[:3],
                        "candidate_values": compact_values,
                    },
                )
            )

    for index, field_path_value in enumerate(out_of_scope_fields, start=1):
        field_path = _canonicalize_retrieval_field_path(field_path_value, retrieval_result)
        if not field_path:
            continue

        questions.append(
            _build_question_from_catalog_or_generic(
                field_path=field_path,
                default_question_id=f"RETRIEVAL_DEFERRED_{index:03d}",
                default_question=(
                    f"We could not resolve '{field_path}' from vendor specifications or grounded reference sources because it is not a vendor-fixed field. "
                    "Please provide or confirm the project-specific engineering value."
                ),
                category="retrieval_deferred",
                priority="MODERATE",
                source="retrieval_result",
                reason=(
                    "This field is outside the scope of vendor-spec resolution and should be confirmed from applicant documents, canonical engineering inputs, or direct applicant follow-up."
                ),
                suggested_sources=[],
                metadata={
                    "gap_fill_strategy": gap_fill_strategy or None,
                    "matched_equipment_identities": matched_identities[:3],
                    "resolution_scope": "non_vendor_project_specific",
                },
            )
        )

    for index, field_path_value in enumerate(review_required_fields, start=1):
        field_path = _canonicalize_retrieval_field_path(field_path_value, retrieval_result)
        if not field_path:
            continue

        compact_values, suggested_sources, summary_parts = _candidate_summary_for_field(field_path, candidate_lookup)
        default_question = (
            f"Grounded vendor evidence found a possible value for '{field_path}', but it needs applicant confirmation. "
            f"Please confirm or correct it."
        )
        if summary_parts:
            default_question = (
                f"Please confirm the proposed value for '{field_path}'. "
                f"Grounded retrieval found: {'; '.join(summary_parts)}."
            )

        reason = "Vendor PDF or official-source evidence produced a low-confidence candidate that still requires applicant confirmation."
        if matched_identities:
            reason = f"{reason} Matched equipment context: {', '.join(matched_identities[:3])}."

        questions.append(
            _build_question_from_catalog_or_generic(
                field_path=field_path,
                default_question_id=f"RETRIEVAL_CONFIRM_{index:03d}",
                default_question=default_question,
                category="retrieval_confirmation",
                priority="MODERATE",
                source="retrieval_result",
                reason=reason,
                suggested_sources=suggested_sources,
                metadata={
                    "evidence_gap_status": gap_status or "REVIEW_REQUIRED",
                    "gap_fill_strategy": gap_fill_strategy or None,
                    "matched_equipment_identities": matched_identities[:3],
                    "candidate_values": compact_values,
                },
            )
        )

    return questions


def _build_questions_from_canonical_state(
    canonical_state_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not canonical_state_result:
        return []

    canonical_state = canonical_state_result.get("canonical_state", {})
    if not isinstance(canonical_state, dict):
        return []

    review_flags = canonical_state.get("review_flags", [])
    if not isinstance(review_flags, list):
        return []

    questions: list[dict[str, Any]] = []

    for index, item in enumerate(review_flags, start=1):
        if not isinstance(item, dict):
            continue

        field_path_value = item.get("field_path")
        field_path = _canonicalize_retrieval_field_path(field_path_value, retrieval_result) if field_path_value is not None else ""
        if not field_path:
            continue

        category = str(item.get("category", "review_required")).strip().lower()
        severity = item.get("severity")
        message = str(item.get("message", "")).strip() or f"Review required for '{field_path}'."

        if category == "conflict":
            default_question = (
                f"Conflicting values exist for '{field_path}'. Please provide the correct engineering value."
            )
        elif category == "missing_field":
            default_question = (
                f"Required field '{field_path}' is missing. Please provide the value."
            )
        elif category == "low_confidence":
            default_question = (
                f"Current value for '{field_path}' is low confidence. Please confirm the correct value."
            )
        else:
            default_question = (
                f"Please review and provide guidance for '{field_path}'."
            )

        questions.append(
            _build_question_from_catalog_or_generic(
                field_path=field_path,
                default_question_id=str(item.get("review_flag_id") or f"CANONICAL_REVIEW_{index:03d}"),
                default_question=default_question,
                category=category,
                priority=_priority_from_severity(severity),
                source="canonical_state_result",
                reason=message,
                metadata={
                    "review_flag_id": item.get("review_flag_id"),
                    "status": item.get("status"),
                },
            )
        )

    return questions


def _question_source_rank(source: Any) -> int:
    normalized = str(source or "").strip().lower()
    return {
        "planner_registry_resolution_backlog": 500,
        "retrieval_result": 400,
        "canonical_state_result": 350,
        "extraction_result": 300,
        "normalization_result": 100,
    }.get(normalized, 0)


def _question_intent_rank(item: dict[str, Any]) -> int:
    category = _classify_question_category(item)
    question_text = str(item.get("question", "")).strip().lower()
    reason = str(item.get("reason", "")).strip().lower()
    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    has_candidate = bool(metadata.get("candidate_value") or metadata.get("accepted_value") or metadata.get("suggested_value"))
    blob = f"{category} {question_text} {reason}"
    if any(token in blob for token in ("conflict", "contradict", "which is correct", "resolve")):
        return 500
    if has_candidate or any(token in blob for token in ("confirm", "found", "appears to be")):
        return 400
    if any(token in blob for token in ("clarify", "which role", "voltage role", "phase")):
        return 350
    if any(token in blob for token in ("provide", "missing", "required")):
        return 250
    return 100



def _question_identity(item: dict[str, Any], retrieval_result: dict[str, Any] | None = None) -> str:
    metadata = item.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}

    # Dedupe must be planner-field deterministic. Prefer canonical field path
    # over source-specific question ids so generic normalization prompts and
    # planner-ledger confirm/correct prompts collapse into one best question.
    field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result).strip().lower()
    if field_path:
        return f"field_path::{field_path}"

    for key in ("canonical_field_path", "field_path", "matched_field_key"):
        metadata_field_path = _canonicalize_retrieval_field_path(metadata.get(key, ""), retrieval_result).strip().lower()
        if metadata_field_path:
            return f"field_path::{metadata_field_path}"

    field_id = str(metadata.get("field_id", "")).strip().lower()
    if field_id:
        return f"field_id::{field_id}"

    question_id = str(item.get("question_id", "")).strip().lower()
    return f"question_id::{question_id}"



def _priority_as_int(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    normalized = str(value or "").strip().upper()
    return {"HIGH": 300, "MODERATE": 200, "LOW": 100}.get(normalized, 0)



def _question_preference_key(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
    metadata = item.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    planner_critical = 1 if bool(metadata.get("planner_critical", False)) else 0
    reason = str(item.get("reason", "")).strip()
    question_text = str(item.get("question", "")).strip()
    return (
        _question_intent_rank(item),
        planner_critical,
        _question_source_rank(item.get("source")),
        _priority_as_int(item.get("priority", 0)),
        len(reason) + len(question_text),
    )



def _deduplicate_question_records(questions: list[dict[str, Any]], retrieval_result: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    best_by_identity: dict[str, dict[str, Any]] = {}
    ordered_identities: list[str] = []
    suppressed_by_identity: dict[str, list[dict[str, Any]]] = {}

    for item in questions:
        if not isinstance(item, dict):
            continue

        question_id = str(item.get("question_id", "")).strip()
        field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
        question_text = str(item.get("question", "")).strip()
        if not question_id or not field_path or not question_text:
            continue

        item = dict(item)
        item["field_path"] = field_path
        identity = _question_identity(item, retrieval_result)
        existing = best_by_identity.get(identity)
        if existing is None:
            best_by_identity[identity] = item
            suppressed_by_identity.setdefault(identity, [])
            ordered_identities.append(identity)
            continue

        if _question_preference_key(item) > _question_preference_key(existing):
            suppressed_by_identity.setdefault(identity, []).append(existing)
            best_by_identity[identity] = item
        else:
            suppressed_by_identity.setdefault(identity, []).append(item)

    deduped: list[dict[str, Any]] = []
    for identity in ordered_identities:
        if identity not in best_by_identity:
            continue
        winner = dict(best_by_identity[identity])
        suppressed = suppressed_by_identity.get(identity, [])
        if suppressed:
            metadata = winner.get("metadata", {})
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            metadata["deduped_question_count"] = len(suppressed)
            metadata["deduped_from_question_ids"] = [
                str(item.get("question_id", "")).strip()
                for item in suppressed
                if isinstance(item, dict) and str(item.get("question_id", "")).strip()
            ]
            metadata["dedupe_identity"] = identity
            winner["metadata"] = metadata
        deduped.append(winner)
    return deduped


def _deduplicate_answer_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for item in records:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id", "")).strip()
        field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
        if not question_id or not field_path:
            continue
        key = (question_id, field_path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _deduplicate_clarifications(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for item in records:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id", "")).strip()
        field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
        reason = str(item.get("reason", "")).strip()
        if not question_id or not field_path:
            continue
        key = (question_id, field_path, reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _empty_session_payload(path: Path, project_id: str) -> dict[str, Any]:
    now_iso = utc_now_iso()
    return {
        "session_id": f"interview_{_slugify(project_id)}",
        "project_id": project_id,
        "session_path": str(path),
        "created_at": now_iso,
        "updated_at": now_iso,
        "status": "IN_PROGRESS",
        "workflow_state": {},
        "ui_state": {},
        "project_identity": {},
        "sources": [],
        "questions": [],
        "answers_confirmed": [],
        "clarifications": [],
        "field_tracking": {
            "answered": [],
            "inferred": [],
            "conflicting": [],
            "missing": [],
        },
        "summary": {},
    }


def _load_existing_session(path: Path, project_id: str) -> dict[str, Any]:
    payload = _safe_read_json(path)
    now_iso = utc_now_iso()

    if payload is None:
        return _empty_session_payload(path, project_id)

    return {
        "session_id": str(payload.get("session_id", f"interview_{_slugify(project_id)}")).strip(),
        "project_id": str(payload.get("project_id", project_id)).strip() or project_id,
        "session_path": str(path),
        "created_at": str(payload.get("created_at", now_iso)).strip() or now_iso,
        "updated_at": str(payload.get("updated_at", now_iso)).strip() or now_iso,
        "status": str(payload.get("status", "IN_PROGRESS")).strip() or "IN_PROGRESS",
        "workflow_state": payload.get("workflow_state", {}) if isinstance(payload.get("workflow_state", {}), dict) else {},
        "ui_state": payload.get("ui_state", {}) if isinstance(payload.get("ui_state", {}), dict) else {},
        "project_identity": payload.get("project_identity", {}) if isinstance(payload.get("project_identity", {}), dict) else {},
        "sources": payload.get("sources", []) if isinstance(payload.get("sources", []), list) else [],
        "questions": payload.get("questions", []) if isinstance(payload.get("questions", []), list) else [],
        "answers_confirmed": (
            payload.get("answers_confirmed", [])
            if isinstance(payload.get("answers_confirmed", []), list)
            else []
        ),
        "clarifications": (
            payload.get("clarifications", [])
            if isinstance(payload.get("clarifications", []), list)
            else []
        ),
        "field_tracking": (
            payload.get("field_tracking", {})
            if isinstance(payload.get("field_tracking", {}), dict)
            else {"answered": [], "inferred": [], "conflicting": [], "missing": []}
        ),
        "summary": payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {},
    }


def _sorted_unique(values: list[str]) -> list[str]:
    return sorted({value for value in values if isinstance(value, str) and value.strip()})


def _build_inferred_field_paths(
    extraction_result: dict[str, Any] | None,
    answered_field_paths: set[str],
) -> list[str]:
    if not isinstance(extraction_result, dict):
        return []

    schema_field_candidates = extraction_result.get("schema_field_candidates", [])
    if not isinstance(schema_field_candidates, list):
        return []

    inferred: list[str] = []
    for item in schema_field_candidates:
        if not isinstance(item, dict):
            continue
        field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
        confidence_label = str(item.get("confidence_label", "")).strip().upper()
        if not field_path or field_path in answered_field_paths:
            continue
        if confidence_label in {"HIGH", "MODERATE"}:
            inferred.append(field_path)

    return _sorted_unique(inferred)


def _build_conflicting_field_paths(
    canonical_state_result: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(canonical_state_result, dict):
        return []

    canonical_state = canonical_state_result.get("canonical_state", {})
    if not isinstance(canonical_state, dict):
        return []

    review_flags = canonical_state.get("review_flags", [])
    if not isinstance(review_flags, list):
        return []

    conflicts: list[str] = []
    for item in review_flags:
        if not isinstance(item, dict):
            continue
        if str(item.get("category", "")).strip().lower() != "conflict":
            continue
        field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
        if field_path:
            conflicts.append(field_path)

    return _sorted_unique(conflicts)




def _classify_question_category(question_record: dict[str, Any]) -> str:
    reason = str(question_record.get("reason", "")).strip().lower()
    triggering_status = str(question_record.get("triggering_status", "")).strip().lower()
    metadata = question_record.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    review_categories = metadata.get("review_flag_categories", [])
    if not isinstance(review_categories, list):
        review_categories = []
    normalized_categories = {str(item).strip().lower() for item in review_categories if str(item).strip()}

    if "conflict" in normalized_categories or "conflict" in triggering_status or "conflict" in reason:
        return "conflicting"
    if "low_confidence" in normalized_categories or "low_confidence" in triggering_status or "low_confidence" in reason:
        return "low_confidence"
    if "review_required" in normalized_categories or "review_required" in triggering_status or "review_required" in reason:
        return "review_required"
    if "confirmation" in reason or "confirm" in reason:
        return "confirmation"
    return "missing"


def _question_priority(question_record: dict[str, Any]) -> int:
    category = _classify_question_category(question_record)
    base = {
        "conflicting": 400,
        "review_required": 300,
        "low_confidence": 250,
        "missing": 200,
        "confirmation": 150,
    }.get(category, 100)

    metadata = question_record.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    required = question_record.get("required")
    if required is None:
        required = metadata.get("required", True)
    if bool(required):
        base += 25

    planner_critical = metadata.get("planner_critical")
    if planner_critical is None:
        planner_critical = field_is_planner_critical(question_record.get("field_path"))
    if bool(planner_critical):
        base += 40

    field_path = str(question_record.get("field_path", "")).strip().lower()
    if any(token in field_path for token in ("rated_power", "voltage", "current", "frequency", "impedance", "fuel_type")):
        base += 15

    field_id = str(metadata.get("field_id") or "").strip()
    if not field_id:
        profile = build_followup_profile(question_record.get("field_path"))
        field_id = str(profile.get("field_id", "")).strip()
    rank_map = interview_priority_rank_map()
    if field_id in rank_map:
        base += max(0, 60 - rank_map[field_id])

    return base


def _sort_question_records(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _key(item: dict[str, Any]) -> tuple[int, int, str, str]:
        return (
            int(item.get("triage_rank", 99) or 99),
            -int(item.get("priority", 0) or 0),
            str(item.get("question_category", "")).strip().lower(),
            str(item.get("field_path", "")).strip().lower(),
        )

    return sorted(questions, key=_key)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _build_field_resolution_lookup(canonical_state_result: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(canonical_state_result, dict):
        return {}
    canonical_state = canonical_state_result.get("canonical_state", {})
    if not isinstance(canonical_state, dict):
        return {}
    field_resolution = canonical_state.get("field_resolution", {})
    lookup: dict[str, dict[str, Any]] = {}
    ledger = field_resolution.get("ledger", []) if isinstance(field_resolution, dict) else []
    if isinstance(ledger, list):
        for item in ledger:
            if not isinstance(item, dict):
                continue
            field_path = str(item.get("field_path", "")).strip()
            field_id = str(item.get("field_id", "")).strip()
            if field_path and field_path not in lookup:
                lookup[field_path] = item
            if field_id and field_id not in lookup:
                lookup[field_id] = item
    backlog = canonical_state.get("planner_registry_resolution_backlog")
    queue: list[dict[str, Any]] = []
    if isinstance(backlog, dict):
        raw_queue = backlog.get("queue", [])
        if isinstance(raw_queue, list):
            queue = [item for item in raw_queue if isinstance(item, dict)]
    elif isinstance(backlog, list):
        queue = [item for item in backlog if isinstance(item, dict)]
    for item in queue:
        field_path = str(item.get("field_path", "")).strip()
        field_id = str(item.get("field_id", "")).strip()
        if field_path and field_path not in lookup:
            lookup[field_path] = item
        if field_id and field_id not in lookup:
            lookup[field_id] = item
    return lookup


def _triage_question_records(
    questions: list[dict[str, Any]],
    *,
    canonical_state_result: dict[str, Any] | None,
    document_field_pack: Any | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    lookup = _build_field_resolution_lookup(canonical_state_result)
    external_candidates = set(getattr(document_field_pack, "external_retrieval_candidate_fields", ()) or ())
    triaged: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    counts = {
        "planner_critical_blocking": 0,
        "high_value_clarification": 0,
        "informational": 0,
        "suppressed_low_yield": 0,
    }

    for item in questions:
        if not isinstance(item, dict):
            continue
        enriched = dict(item)
        field_path = str(enriched.get("field_path", "")).strip()
        metadata = dict(enriched.get("metadata", {})) if isinstance(enriched.get("metadata"), dict) else {}
        question_category = str(enriched.get("question_category", "missing")).strip().lower() or "missing"
        planner_critical = bool(metadata.get("planner_critical", field_is_planner_critical(field_path)))
        resolution_entry = lookup.get(field_path) or lookup.get(str(metadata.get("field_id", "")).strip()) or {}
        accepted_status = str(resolution_entry.get("accepted_status", resolution_entry.get("status", ""))).strip().lower()
        confidence_band = str(resolution_entry.get("confidence_band", "")).strip().upper()
        accepted_confidence = _safe_float(resolution_entry.get("accepted_confidence"))
        needs_confirmation = bool(resolution_entry.get("needs_applicant_confirmation", False))
        conflict_materiality = str(resolution_entry.get("conflict_materiality", "")).strip().lower()
        is_external_candidate = field_path in external_candidates

        suppress_reason = ""
        if not planner_critical and question_category in {"confirmation", "low_confidence", "review_required"}:
            if accepted_status in {"resolved", "accepted"} and (confidence_band == "HIGH" or (accepted_confidence is not None and accepted_confidence >= 0.85)) and not needs_confirmation:
                suppress_reason = "Resolved with strong governed evidence; suppressing low-yield follow-up question."

        if suppress_reason:
            metadata["triage_bucket"] = "suppressed_low_yield"
            metadata["triage_reason"] = suppress_reason
            enriched["metadata"] = metadata
            suppressed.append(enriched)
            counts["suppressed_low_yield"] += 1
            continue

        if planner_critical or question_category in {"conflicting", "review_required"} or conflict_materiality in {"high", "medium"}:
            triage_bucket = "planner_critical_blocking"
            triage_rank = 0
            triage_reason = "Planner-critical or conflict-driven question that blocks governed release."
        elif question_category in {"low_confidence", "confirmation"} or is_external_candidate or bool(enriched.get("requires_confirmation", False)):
            triage_bucket = "high_value_clarification"
            triage_rank = 1
            triage_reason = "High-value clarification that can strengthen or confirm an otherwise usable field."
        else:
            triage_bucket = "informational"
            triage_rank = 2
            triage_reason = "Informational follow-up kept behind blocking and high-value clarification questions."

        presentation_phase = "immediate" if triage_bucket in {"planner_critical_blocking", "high_value_clarification"} else "deferred"
        metadata["triage_bucket"] = triage_bucket
        metadata["triage_reason"] = triage_reason
        metadata["triage_rank"] = triage_rank
        metadata["presentation_phase"] = presentation_phase
        metadata["interview_priority_score"] = int(metadata.get("interview_priority_score", enriched.get("priority", 0)) or enriched.get("priority", 0) or 0)
        metadata["resolution_confidence_band"] = confidence_band
        metadata["resolution_accepted_status"] = accepted_status
        metadata["document_external_retrieval_candidate"] = is_external_candidate
        enriched["metadata"] = metadata
        enriched["triage_bucket"] = triage_bucket
        enriched["triage_rank"] = triage_rank
        counts[triage_bucket] += 1
        triaged.append(enriched)

    return _sort_question_records(triaged), suppressed, counts


def _build_interview_readiness_summary(
    *,
    questions: list[dict[str, Any]],
    open_clarifications: list[dict[str, Any]],
    answered_field_paths: set[str],
    inferred_field_paths: list[str],
    conflicting_field_paths: list[str],
) -> dict[str, Any]:
    question_categories: dict[str, int] = {
        "missing": 0,
        "confirmation": 0,
        "low_confidence": 0,
        "review_required": 0,
        "conflicting": 0,
    }
    planner_critical_question_count = 0
    planner_critical_clarification_count = 0
    for item in questions:
        if not isinstance(item, dict):
            continue
        category = str(item.get("question_category", "missing")).strip().lower() or "missing"
        question_categories[category] = question_categories.get(category, 0) + 1
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        field_path = str(item.get("field_path", "")).strip()
        planner_critical = bool(metadata.get("planner_critical", False)) or field_is_planner_critical(field_path)
        if planner_critical:
            planner_critical_question_count += 1
    for item in open_clarifications:
        if not isinstance(item, dict):
            continue
        field_path = str(item.get("field_path", "")).strip()
        if field_is_planner_critical(field_path):
            planner_critical_clarification_count += 1
    unresolved_count = len([item for item in questions if isinstance(item, dict)])
    clarification_count = len([item for item in open_clarifications if isinstance(item, dict)])
    planner_critical_conflict_count = len([field_path for field_path in conflicting_field_paths if field_is_planner_critical(field_path)])
    blocking_categories = [name for name in ("missing", "conflicting", "review_required", "low_confidence") if question_categories.get(name, 0) > 0]
    ready_for_validation = unresolved_count == 0 and clarification_count == 0
    ready_for_final_output = (ready_for_validation and not conflicting_field_paths and planner_critical_question_count == 0 and planner_critical_clarification_count == 0 and planner_critical_conflict_count == 0)
    if ready_for_final_output:
        completion_state = "READY_FOR_FINAL_OUTPUT"
    elif planner_critical_clarification_count > 0:
        completion_state = "NEEDS_CRITICAL_CLARIFICATION"
    elif planner_critical_question_count > 0 or planner_critical_conflict_count > 0:
        completion_state = "NEEDS_CRITICAL_APPLICANT_INPUT"
    elif clarification_count > 0:
        completion_state = "NEEDS_CLARIFICATION"
    elif unresolved_count > 0:
        completion_state = "NEEDS_APPLICANT_INPUT"
    else:
        completion_state = "REVIEW_REQUIRED"
    return {
        "completion_state": completion_state,
        "ready_for_validation": ready_for_validation,
        "ready_for_final_output": ready_for_final_output,
        "blocking_categories": blocking_categories,
        "remaining_question_count": unresolved_count,
        "open_clarification_count": clarification_count,
        "question_categories": question_categories,
        "answered_field_count": len(answered_field_paths),
        "inferred_field_count": len(inferred_field_paths),
        "conflicting_field_count": len(conflicting_field_paths),
        "planner_critical_remaining_question_count": planner_critical_question_count,
        "planner_critical_open_clarification_count": planner_critical_clarification_count,
        "planner_critical_conflicting_field_count": planner_critical_conflict_count,
    }

def _build_questions_from_planner_field_ledger(
    canonical_state_result: dict[str, Any] | None,
    answered_field_paths: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(canonical_state_result, dict):
        return []
    canonical_state = canonical_state_result.get("canonical_state")
    if not isinstance(canonical_state, dict):
        canonical_state = canonical_state_result
    rows = canonical_state.get("planner_field_ledger") if isinstance(canonical_state, dict) else None
    if not isinstance(rows, list):
        contract = canonical_state.get("planner_field_contract") if isinstance(canonical_state, dict) else None
        if isinstance(contract, dict):
            rows = contract.get("planner_field_ledger")
    if not isinstance(rows, list):
        return []
    return build_interview_question_records_from_ledger(
        rows,
        answered_field_paths=answered_field_paths,
        max_questions=75,
    )


def _build_pre_interview_planner_field_contract(
    normalization_result: dict[str, Any] | None,
) -> dict[str, Any]:
    return build_pre_interview_planner_field_contract(
        normalization_result,
        include_optional=False,
    )


def _build_questions_from_pre_interview_planner_ledger(
    pre_interview_contract: dict[str, Any] | None,
    answered_field_paths: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(pre_interview_contract, dict):
        return []
    rows = pre_interview_contract.get("planner_field_ledger")
    if not isinstance(rows, list):
        return []

    focused_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate_count = int(row.get("candidate_count", 0) or 0)
        rejected_count = int(row.get("rejected_candidate_count", 0) or 0)
        conflict_summary = str(row.get("conflict_summary", "")).strip()
        status = str(row.get("status", "")).strip().upper()
        manual_review_reason = str(row.get("manual_review_reason", "")).strip()
        if candidate_count > 0 or rejected_count > 0 or conflict_summary or status in {"PROVISIONAL", "BLOCKED_BY_CONFLICT"}:
            focused_rows.append(row)
            continue
        if bool(row.get("needs_applicant_confirmation", False)) or "conflict" in manual_review_reason.lower():
            focused_rows.append(row)

    questions = build_interview_question_records_from_ledger(
        focused_rows,
        answered_field_paths=answered_field_paths,
        max_questions=75,
    )
    for question in questions:
        if not isinstance(question, dict):
            continue
        question["source"] = "pre_interview_planner_field_ledger"
        question["category"] = "pre_interview_planner_field_followup"
        question["question_category"] = question.get("question_category") or "pre_interview_planner_field_followup"
        metadata = question.get("metadata") if isinstance(question.get("metadata"), dict) else {}
        metadata = dict(metadata)
        metadata["pre_interview_working_ledger"] = True
        metadata["planner_registry_backed"] = True
        metadata["pre_interview_registry_backfilled_suppressed"] = len(rows) - len(focused_rows)
        question["metadata"] = metadata
    return questions
def _build_questions_from_registry_resolution_backlog(
    canonical_state_result: dict[str, Any] | None,
    answered_field_paths: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(canonical_state_result, dict):
        return []
    canonical_state = canonical_state_result.get("canonical_state")
    if not isinstance(canonical_state, dict):
        return []

    validation_report = canonical_state.get("validation_report") if isinstance(canonical_state.get("validation_report"), dict) else None
    field_resolution = canonical_state.get("field_resolution") if isinstance(canonical_state.get("field_resolution"), dict) else None
    overview = canonical_state.get("field_resolution_overview") if isinstance(canonical_state.get("field_resolution_overview"), dict) else {}

    if isinstance(field_resolution, dict):
        queue = field_resolution.get("backlog", [])
        backlog = {
            "planner_registry_backed": True,
            "queue": queue,
        }
    else:
        backlog = planner_registry_resolution_backlog(
            canonical_state,
            validation_report,
        )
        queue = backlog.get("queue", [])
    if not isinstance(queue, list):
        return []

    governance_summary = summarize_field_resolution_governance(
        canonical_state,
        validation_report,
        include_optional=False,
    )
    high_materiality_by_path = {
        str(item.get("field_path", "")).strip(): dict(item)
        for item in (overview.get("high_materiality_conflicts", []) if isinstance(overview, dict) else [])
        if isinstance(item, dict) and str(item.get("field_path", "")).strip()
    }
    planner_review_by_path = {
        str(item.get("field_path", "")).strip(): dict(item)
        for item in (overview.get("planner_review_queue", []) if isinstance(overview, dict) else [])
        if isinstance(item, dict) and str(item.get("field_path", "")).strip()
    }

    def _question_priority_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
        field_path = str(item.get("field_path", "")).strip()
        materiality_rank = {
            "high": 0,
            "medium": 1,
            "low": 2,
            "none": 3,
        }.get(str(item.get("conflict_materiality", "none")).strip().lower(), 3)
        review_rank = 0 if field_path in planner_review_by_path else 1
        applicant_question_profile = item.get("applicant_question_profile") if isinstance(item.get("applicant_question_profile"), dict) else {}
        priority = max(
            int(item.get("resolution_priority", 0) or 0),
            int(applicant_question_profile.get("interview_priority_score", 0) or 0),
        )
        return (materiality_rank, review_rank, priority if priority > 0 else 9999, field_path)

    ordered_queue = sorted([dict(item) for item in queue if isinstance(item, dict)], key=_question_priority_key)

    questions: list[dict[str, Any]] = []
    for item in ordered_queue:
        field_path = str(item.get("field_path", "")).strip() or str(item.get("field_id", "")).strip()
        if not field_path or field_path in answered_field_paths:
            continue

        status = str(item.get("status", item.get("accepted_status", "unresolved"))).strip().lower() or "unresolved"
        high_materiality_record = high_materiality_by_path.get(field_path)
        review_record = planner_review_by_path.get(field_path)
        conflict_materiality = str((high_materiality_record or item).get("conflict_materiality", "none")).strip().lower() or "none"
        question = get_question_by_field_path(field_path)
        prompt = question.prompt if question is not None else f"Please provide or confirm the value for {field_label(field_path)}."
        accepted_value = item.get("accepted_value")
        alternatives = item.get("alternatives", []) if isinstance(item.get("alternatives"), list) else []
        runner_up_value = None
        for alt in alternatives:
            if isinstance(alt, dict) and alt.get("value") is not None:
                runner_up_value = alt.get("value")
                break
        accepted_confidence = item.get("accepted_confidence")
        confidence_band = str(item.get("confidence_band", "")).strip() or "UNRESOLVED"
        candidate_summary = item.get("candidate_summary") if isinstance(item.get("candidate_summary"), dict) else {}
        dominance_profile = item.get("dominance_profile") if isinstance(item.get("dominance_profile"), dict) else {}
        runner_up_profile = item.get("runner_up_profile") if isinstance(item.get("runner_up_profile"), dict) else {}
        conflict_profile = item.get("conflict_profile") if isinstance(item.get("conflict_profile"), dict) else {}
        applicant_question_profile = item.get("applicant_question_profile") if isinstance(item.get("applicant_question_profile"), dict) else {}
        adjudication_trace = item.get("adjudication_trace") if isinstance(item.get("adjudication_trace"), dict) else {}
        contradiction_summary = str(item.get("contradiction_summary", "")).strip()
        unresolved_reason = str(item.get("unresolved_reason", "")).strip()
        if accepted_value is not None and status in {"conflicting", "review_required", "unresolved"}:
            prompt = f"{prompt} Current best-supported value is {accepted_value!r}"
            if accepted_confidence is not None:
                prompt += f" ({confidence_band.lower()} confidence)"
            prompt += "."
            if runner_up_value is not None:
                prompt += f" Runner-up value found: {runner_up_value!r}."
            runner_up_anchor = str(runner_up_profile.get("source_anchor", "")).strip()
            runner_up_hierarchy = str(runner_up_profile.get("source_hierarchy", "")).strip()
            runner_up_sources = int(runner_up_profile.get("group_independent_source_count", 0) or 0)
            if runner_up_anchor or runner_up_hierarchy or runner_up_sources:
                details = []
                if runner_up_hierarchy:
                    details.append(runner_up_hierarchy.replace("_", " "))
                if runner_up_sources:
                    details.append(f"{runner_up_sources} independent source trace(s)")
                if runner_up_anchor:
                    details.append(runner_up_anchor)
                prompt += f" Runner-up support: {', '.join(details)}."
            if conflict_materiality in {"high", "medium"}:
                prompt += f" Conflict materiality is {conflict_materiality}."
        question_category = str(applicant_question_profile.get("question_category", "")).strip().lower() or ("conflicting" if conflict_materiality == "high" else ("confirmation" if status in {"conflicting", "review_required"} else "missing"))
        question_strategy = str(applicant_question_profile.get("question_strategy", "")).strip().lower()
        if question_strategy == "resolve_material_conflict":
            prompt = f"Please decide the correct engineering value for {field_label(field_path)}. {prompt}"
        elif question_strategy in {"confirm_provisional_value", "verify_best_supported_value"}:
            prompt = f"Please confirm whether the current best-supported value for {field_label(field_path)} is correct. {prompt}"
        question_id = question.question_id if question is not None else f"AUTO_BACKLOG_{str(item.get('field_id','')).strip().upper() or field_path.replace('.', '_').upper()}"
        help_text = question.help_text if question is not None else None
        required = question.required if question is not None else str(item.get("requiredness", "optional")).strip().lower() != "optional"
        allowed_values = list(question.allowed_values) if question is not None else []
        examples = list(question.examples) if question is not None else []
        reason = {
            "conflicting": "This field has conflicting evidence and needs applicant confirmation.",
            "review_required": "This field remains low-confidence and needs applicant confirmation.",
            "missing": "This required planner field is still missing.",
        }.get(status, "This planner field remains unresolved.")
        why_accepted = item.get("why_accepted", []) if isinstance(item.get("why_accepted"), list) else []
        if contradiction_summary:
            reason += f" {contradiction_summary}"
        if unresolved_reason:
            reason += f" Unresolved reason: {unresolved_reason}."
        if why_accepted:
            reason = f"{reason} Current best-evidence rationale: {' '.join(str(part) for part in why_accepted[:2])}"
        adjudication_narrative = str(adjudication_trace.get("planner_narrative", "")).strip()
        if adjudication_narrative:
            reason += f" Adjudication trace: {adjudication_narrative}"
        dominance_level = str(dominance_profile.get("dominance_level", "")).strip().lower()
        if dominance_level in {"narrow", "contested", "single_source"}:
            reason += (
                f" Current dominance posture is {dominance_level.replace('_', ' ')}"
                f" with {int(dominance_profile.get('winner_group_independent_source_count', 0) or 0)} independent source trace(s)"
                f" supporting the current best value."
            )
        conflict_summary = str(conflict_profile.get("summary_text", "")).strip()
        if conflict_summary:
            reason += f" Runner-up conflict profile: {conflict_summary}."
        priority = max(
            int(item.get("resolution_priority", 0) or 0),
            int(applicant_question_profile.get("interview_priority_score", 0) or 0),
        )
        source_anchors = [str(anchor).strip() for anchor in item.get("source_anchors", []) if str(anchor).strip()] if isinstance(item.get("source_anchors"), list) else []
        related_artifact_ids = sorted({
            str(ref).strip()
            for ref in item.get("source_ref", [])
            if str(ref).strip()
        }) if isinstance(item.get("source_ref", []), list) else []
        if isinstance(item.get("supporting_sources"), list):
            for source in item.get("supporting_sources", []):
                if not isinstance(source, dict):
                    continue
                for ref in source.get("source_ref", []) if isinstance(source.get("source_ref"), list) else []:
                    ref_text = str(ref).strip()
                    if ref_text:
                        related_artifact_ids.append(ref_text)
        related_artifact_ids = sorted({artifact_id for artifact_id in related_artifact_ids if artifact_id})
        selection_rationale = applicant_question_profile.get("selection_rationale", []) if isinstance(applicant_question_profile.get("selection_rationale"), list) else []
        if selection_rationale:
            reason += " Interview targeting: " + " ".join(str(part) for part in selection_rationale[:3])
        metadata = {
            "field_id": str(item.get("field_id", "")).strip(),
            "planner_critical": bool(item.get("planner_critical", False)),
            "requiredness": str(item.get("requiredness", "optional")).strip() or "optional",
            "packet_section": str(item.get("packet_section", "")).strip(),
            "packet_section_label": str(item.get("packet_section_label", "")).strip(),
            "resolution_priority": priority,
            "planner_registry_backed": True,
            "queue_status": status,
            "accepted_value": accepted_value,
            "accepted_confidence": accepted_confidence,
            "confidence_band": confidence_band,
            "conflict_materiality": conflict_materiality,
            "acceptance_margin": float(item.get("acceptance_margin", 0.0) or 0.0),
            "planner_attention_tier": str(item.get("planner_attention_tier", "information")).strip() or "information",
            "needs_applicant_confirmation": bool(item.get("needs_applicant_confirmation", False)),
            "planner_review_flag": bool(item.get("planner_review_flag", False)),
            "candidate_summary": dict(candidate_summary),
            "dominance_profile": dict(dominance_profile),
            "runner_up_profile": dict(runner_up_profile),
            "conflict_profile": dict(conflict_profile),
            "applicant_question_profile": dict(applicant_question_profile),
            "adjudication_trace": dict(adjudication_trace),
            "source_anchors": source_anchors,
            "governance_summary": {
                "planner_review_count": max(
                    int(governance_summary.get("planner_review_count", 0) or 0),
                    len(planner_review_by_path),
                ),
                "high_materiality_conflict_count": max(
                    int(governance_summary.get("high_materiality_conflict_count", 0) or 0),
                    len(high_materiality_by_path),
                ),
            },
        }
        questions.append(
            {
                "question_id": question_id,
                "field_path": field_path,
                "question": prompt,
                "help_text": help_text,
                "required": required,
                "allowed_values": allowed_values,
                "examples": examples,
                "question_category": question_category,
                "priority": priority,
                "reason": reason.strip(),
                "suggested_sources": list(item.get("preferred_sources", [])) if isinstance(item.get("preferred_sources"), list) else [],
                "related_artifact_ids": related_artifact_ids,
                "metadata": metadata,
                "source": "planner_registry_resolution_backlog",
            }
        )
    return questions


def _build_missing_question_records(
    questions: list[dict[str, Any]],
    answered_field_paths: set[str],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []

    for item in questions:
        if not isinstance(item, dict):
            continue
        field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
        if not field_path:
            continue
        if field_path in answered_field_paths:
            continue
        enriched = dict(item)
        enriched["question_category"] = _classify_question_category(enriched)
        enriched["priority"] = _question_priority(enriched)
        enriched["requires_confirmation"] = enriched["question_category"] in {"confirmation", "low_confidence", "review_required", "conflicting"}
        filtered.append(enriched)

    return _sort_question_records(filtered)


def _persist_session(session_path: Path, payload: dict[str, Any]) -> None:
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _ledger_entry_identity_keys(entry: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for key_name in ("field_path", "field_id"):
        value = str(entry.get(key_name, "")).strip()
        if value:
            keys.append(value)
    return list(dict.fromkeys(keys))


def _ledger_entry_for_answer(
    *,
    field_path: str,
    answer: dict[str, Any],
) -> dict[str, Any]:
    return {
        "field_id": str(answer.get("field_id", "")).strip() or field_path,
        "field_path": field_path,
        "label": field_label(field_path) or field_path,
        "packet_section": "interview_supplied",
        "packet_section_label": "Applicant supplied values",
        "requiredness": field_requiredness(field_path),
        "planner_critical": field_is_planner_critical(field_path),
        "field_family": "general",
        "accepted_value": None,
        "accepted_unit": "",
        "accepted_status": "unresolved",
        "accepted_confidence": None,
        "confidence_band": "UNRESOLVED",
        "accepted_candidate_id": "",
        "why_accepted": [],
        "candidates": [],
        "alternatives": [],
        "source_anchors": [],
        "accepted_source_hierarchy": "",
        "accepted_specificity": "",
        "candidate_evidence_appendix": [],
        "supporting_sources": [],
        "source_stream_counts": {},
        "applicant_answer_state": "",
        "contradiction_summary": "",
        "decision_basis": "",
        "accepted_value_kind": "unresolved",
        "planner_attention_tier": "planner_critical" if field_is_planner_critical(field_path) else "information",
        "field_policy_class": "planner_critical" if field_is_planner_critical(field_path) else "supporting",
        "field_materiality_class": "critical" if field_is_planner_critical(field_path) else "descriptive",
        "conflict_materiality": "none",
        "acceptance_margin": 0.0,
        "runner_up_candidate_id": "",
        "unresolved_reason": "",
        "candidate_summary": {},
        "needs_applicant_confirmation": False,
        "planner_review_flag": False,
        "dominance_profile": {},
        "runner_up_profile": {},
        "conflict_profile": {},
        "applicant_question_profile": {},
        "planner_trust_row": {},
        "acceptance_policy_result": {},
        "field_release_profile": {},
        "adjudication_trace": {},
    }


def _replace_ledger_entry(ledger: list[dict[str, Any]], updated_entry: dict[str, Any]) -> list[dict[str, Any]]:
    field_path = str(updated_entry.get("field_path", "")).strip()
    field_id = str(updated_entry.get("field_id", "")).strip()
    replaced = False
    updated: list[dict[str, Any]] = []
    for entry in ledger:
        if not isinstance(entry, dict):
            updated.append(entry)
            continue
        entry_field_path = str(entry.get("field_path", "")).strip()
        entry_field_id = str(entry.get("field_id", "")).strip()
        if (field_path and entry_field_path == field_path) or (field_id and entry_field_id == field_id):
            if not replaced:
                updated.append(dict(updated_entry))
                replaced = True
            continue
        updated.append(entry)
    if not replaced:
        updated.append(dict(updated_entry))
    return updated


def _sync_field_record_from_ledger_entry(
    *,
    field_records: list[dict[str, Any]],
    field_path: str,
    entry: dict[str, Any],
    answer: dict[str, Any],
) -> list[dict[str, Any]]:
    value = entry.get("accepted_value")
    source_name = str(answer.get("source_name", "")).strip() or "applicant_interview"
    status = str(entry.get("accepted_status", "")).strip().lower()
    if status not in {"resolved", "review_required"}:
        return field_records

    record_found = False
    for record in field_records:
        if not isinstance(record, dict):
            continue
        if str(record.get("field_path", "")).strip() != field_path:
            continue
        record["value"] = value
        record["status"] = "interview_review_required" if status == "review_required" else "interview_confirmed"
        record["validation_status"] = record["status"]
        record["review_status"] = "review_required" if status == "review_required" else "resolved"
        record["conflict_status"] = "conflict" if entry.get("conflict_materiality") in {"high", "medium"} else "none"
        if status == "resolved":
            record["source_stage"] = "interview"
            record["source_type"] = "human_input"
        refs = record.get("source_ref", []) if isinstance(record.get("source_ref", []), list) else []
        refs.append(source_name)
        record["source_ref"] = list(dict.fromkeys(str(item).strip() for item in refs if str(item).strip()))
        record["updated_at"] = utc_now_iso()
        record_found = True

    if not record_found and status == "resolved":
        field_records.append(
            {
                "field_record_id": f"interview::{field_path}",
                "field_path": field_path,
                "value": value,
                "status": "interview_confirmed",
                "validation_status": "interview_confirmed",
                "review_status": "resolved",
                "conflict_status": "none" if not entry.get("contradiction_summary") else "conflict_note",
                "source_stage": "interview",
                "source_type": "human_input",
                "source_ref": [source_name],
                "metadata": {
                    "question_id": answer.get("question_id"),
                    "raw_answer": answer.get("raw_answer"),
                    "applicant_answer_state": entry.get("applicant_answer_state"),
                },
                "updated_at": utc_now_iso(),
            }
        )
    return field_records


def _build_interview_conflict_review_flag(entry: dict[str, Any]) -> dict[str, Any] | None:
    profile = entry.get("applicant_question_profile", {})
    if not isinstance(profile, dict) or not profile.get("question_id"):
        return None
    field_path = str(entry.get("field_path", "")).strip()
    return {
        "review_flag_id": str(profile.get("question_id")),
        "field_path": field_path,
        "category": "conflict",
        "severity": "HIGH",
        "status": "OPEN",
        "message": str(entry.get("contradiction_summary", "")).strip() or "Applicant answer conflicts with high-confidence document evidence.",
        "source": "interview_authority",
        "metadata": {
            "question_profile": dict(profile),
            "applicant_answer_state": entry.get("applicant_answer_state"),
        },
    }


def _apply_confirmed_answers_to_canonical_state(
    canonical_state_result: dict[str, Any] | None,
    answers_confirmed: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not canonical_state_result:
        return canonical_state_result

    canonical_state = canonical_state_result.get("canonical_state")
    if not isinstance(canonical_state, dict):
        return canonical_state_result

    field_records = coerce_list(
        canonical_state.get("field_records"),
        "canonical_state.field_records",
    )
    field_resolution = canonical_state.get("field_resolution") if isinstance(canonical_state.get("field_resolution"), dict) else {}
    accepted_field_index = field_resolution.get("accepted_field_index") if isinstance(field_resolution.get("accepted_field_index"), dict) else {}
    ledger = field_resolution.get("ledger") if isinstance(field_resolution.get("ledger"), list) else []
    ledger = [dict(item) for item in ledger if isinstance(item, dict)]
    interview_decisions: list[dict[str, Any]] = []
    generated_review_flags: list[dict[str, Any]] = []

    for answer in answers_confirmed:
        if not isinstance(answer, dict):
            continue

        field_path = str(answer.get("field_path", "")).strip()
        if not field_path:
            continue

        matching_entry: dict[str, Any] | None = None
        existing_entry = accepted_field_index.get(field_path)
        if isinstance(existing_entry, dict):
            matching_entry = dict(existing_entry)
        else:
            for entry in ledger:
                if isinstance(entry, dict) and str(entry.get("field_path", "")).strip() == field_path:
                    matching_entry = dict(entry)
                    break
        if matching_entry is None:
            matching_entry = _ledger_entry_for_answer(field_path=field_path, answer=answer)

        merged_entry, decision = merge_interview_answer_into_ledger_entry(matching_entry, answer)
        interview_decisions.append(decision)
        ledger = _replace_ledger_entry(ledger, merged_entry)

        for key in _ledger_entry_identity_keys(merged_entry):
            accepted_field_index[key] = dict(merged_entry)

        field_records = _sync_field_record_from_ledger_entry(
            field_records=field_records,
            field_path=field_path,
            entry=merged_entry,
            answer=answer,
        )

        action = str(decision.get("action", "")).strip()
        if action in {"INTERVIEW_VALUE_ACCEPTED", "INTERVIEW_VALUE_ACCEPTED_WITH_CONFLICT_NOTE", "INTERVIEW_CONFIRMED_DOCUMENT_VALUE", "INTERVIEW_CONFLICT_CONFIRMED"}:
            canonical_state[field_path] = {
                "value": merged_entry.get("accepted_value"),
                "confidence": merged_entry.get("accepted_confidence", 0.97),
                "status": "interview_conflict_confirmed" if action in {"INTERVIEW_VALUE_ACCEPTED_WITH_CONFLICT_NOTE", "INTERVIEW_CONFLICT_CONFIRMED"} else "interview_confirmed",
                "method": "interview",
                "source_artifact_id": str(answer.get("source_name", "")).strip() or "applicant_interview",
                "evidence": {
                    "question_id": answer.get("question_id"),
                    "raw_answer": answer.get("raw_answer"),
                    "interview_decision": action,
                    "contradiction_summary": merged_entry.get("contradiction_summary", ""),
                },
                "last_update_stage": "interview",
            }
        elif action == "HIGH_CONFIDENCE_DOCUMENT_CONFLICT_REQUIRES_CONFIRMATION":
            review_flag = _build_interview_conflict_review_flag(merged_entry)
            if review_flag is not None:
                generated_review_flags.append(review_flag)
        elif action == "UNKNOWN_ANSWER_DOCUMENT_OR_UNRESOLVED_VALUE_RETAINED":
            unknown_answers = canonical_state.get("interview_unknown_answers", [])
            if not isinstance(unknown_answers, list):
                unknown_answers = []
            unknown_answers.append(
                {
                    "field_path": field_path,
                    "question_id": answer.get("question_id"),
                    "raw_answer": answer.get("raw_answer", answer.get("confirmed_answer")),
                    "source_name": answer.get("source_name"),
                    "retained_value": merged_entry.get("accepted_value"),
                }
            )
            canonical_state["interview_unknown_answers"] = unknown_answers

    field_resolution["accepted_field_index"] = accepted_field_index
    field_resolution["ledger"] = ledger
    field_resolution["interview_authority_decisions"] = interview_decisions
    field_resolution["backlog"] = [
        dict(item)
        for item in ledger
        if isinstance(item, dict) and str(item.get("accepted_status", "unresolved")).strip().lower() != "resolved"
    ][:25]
    field_resolution["backlog_count"] = len(field_resolution["backlog"])
    field_resolution["backlog_field_ids"] = [str(item.get("field_id", "")).strip() for item in field_resolution["backlog"] if str(item.get("field_id", "")).strip()]
    field_resolution["planner_review_queue"] = [
        dict(item)
        for item in ledger
        if isinstance(item, dict) and bool(item.get("planner_review_flag", False))
    ][:25]
    field_resolution["planner_review_queue_count"] = len(field_resolution["planner_review_queue"])
    field_resolution["high_materiality_conflicts"] = [
        dict(item)
        for item in ledger
        if isinstance(item, dict) and str(item.get("conflict_materiality", "")).strip().lower() == "high"
    ][:25]
    field_resolution["high_materiality_conflict_count"] = len(field_resolution["high_materiality_conflicts"])
    summary = field_resolution.get("summary") if isinstance(field_resolution.get("summary"), dict) else {}
    summary.update({
        "accepted_field_index_count": len([key for key in accepted_field_index.keys() if "." in key]),
        "planner_review_count": len(field_resolution["planner_review_queue"]),
        "high_materiality_conflict_count": len(field_resolution["high_materiality_conflicts"]),
        "applicant_confirmation_needed_count": len([
            item for item in ledger if isinstance(item, dict) and bool(item.get("needs_applicant_confirmation", False))
        ]),
        "interview_authority_decision_count": len(interview_decisions),
    })
    field_resolution["summary"] = summary
    canonical_state["field_resolution"] = field_resolution
    canonical_state["accepted_planner_field_index"] = dict(accepted_field_index)

    if generated_review_flags:
        existing_flags = canonical_state.get("review_flags", []) if isinstance(canonical_state.get("review_flags", []), list) else []
        by_id: dict[str, dict[str, Any]] = {}
        for flag in [*existing_flags, *generated_review_flags]:
            if not isinstance(flag, dict):
                continue
            flag_id = str(flag.get("review_flag_id", "")).strip() or f"interview_conflict::{flag.get('field_path', '')}"
            by_id[flag_id] = dict(flag)
        canonical_state["review_flags"] = list(by_id.values())

    validation_report = canonical_state.get("validation_report") if isinstance(canonical_state.get("validation_report"), dict) else None
    refreshed_backlog = planner_registry_resolution_backlog(canonical_state, validation_report)
    canonical_state["planner_registry_resolution_backlog"] = refreshed_backlog
    canonical_state["field_resolution_overview"] = {
        "planner_review_queue": [dict(item) for item in field_resolution.get("planner_review_queue", [])],
        "high_materiality_conflicts": [dict(item) for item in field_resolution.get("high_materiality_conflicts", [])],
        "backlog_top": [dict(item) for item in field_resolution.get("backlog", [])[:10]],
        "summary": dict(summary),
        "interview_authority_decisions": [dict(item) for item in interview_decisions[-10:]],
    }
    canonical_state["governed_truth_summary"] = build_governed_summary(
        canonical_state,
        {"validation_report": validation_report} if isinstance(validation_report, dict) else None,
    )

    canonical_state["field_records"] = field_records
    canonical_state_result["canonical_state"] = canonical_state
    return canonical_state_result


def _build_interview_oversight_summary(
    *,
    context: Any,
    questions: list[dict[str, Any]],
    answered_field_paths: set[str],
    conflicting_field_paths: list[str],
    missing_field_paths: list[str],
    canonical_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recommended_missing_fields = [
        str(item.get("field_path", "")).strip()
        for item in questions
        if isinstance(item, dict) and str(item.get("field_path", "")).strip()
    ]
    recommended_confirmations = [
        field_path
        for field_path in conflicting_field_paths
        if field_path and field_path not in answered_field_paths
    ]
    ordered_question_ids = [
        str(item.get("question_id", "")).strip()
        for item in questions
        if isinstance(item, dict) and str(item.get("question_id", "")).strip()
    ]

    field_governance_core = build_field_governance_core(canonical_state=canonical_state if isinstance(canonical_state, dict) else {})
    manual_review_queue = field_governance_core.get("manual_review_queue", {}) if isinstance(field_governance_core.get("manual_review_queue", {}), dict) else {}
    review_priority_plan = build_interview_priority_plan(
        manual_review_queue=manual_review_queue,
        questions=questions,
        answered_field_paths=answered_field_paths,
    )
    field_governance_core = build_field_governance_core(
        canonical_state=canonical_state if isinstance(canonical_state, dict) else {},
        interview_priority_plan=review_priority_plan,
    )
    manual_review_queue = field_governance_core.get("manual_review_queue", {}) if isinstance(field_governance_core.get("manual_review_queue", {}), dict) else {}
    planner_action_queue = field_governance_core.get("planner_action_queue", {}) if isinstance(field_governance_core.get("planner_action_queue", {}), dict) else {}
    escalation_registry = field_governance_core.get("escalation_registry", {}) if isinstance(field_governance_core.get("escalation_registry", {}), dict) else {}
    stage_transition_decisions = field_governance_core.get("stage_transition_decisions", {}) if isinstance(field_governance_core.get("stage_transition_decisions", {}), dict) else {}
    field_governance_registry = field_governance_core.get("field_governance_registry", {}) if isinstance(field_governance_core.get("field_governance_registry", {}), dict) else {}
    governed_release_decision = field_governance_core.get("governed_release_decision", {}) if isinstance(field_governance_core.get("governed_release_decision", {}), dict) else {}

    backlog_preview = []
    for item in questions[:10]:
        if not isinstance(item, dict):
            continue
        backlog_preview.append({
            "question_id": str(item.get("question_id", "")).strip(),
            "field_path": str(item.get("field_path", "")).strip(),
            "field_id": str((item.get("metadata") or {}).get("field_id", "")).strip() if isinstance(item.get("metadata"), dict) else "",
            "priority": int(item.get("priority", 0) or 0),
            "question_category": str(item.get("question_category", "")).strip(),
            "planner_registry_backed": bool(((item.get("metadata") or {}).get("planner_registry_backed", False))) if isinstance(item.get("metadata"), dict) else False,
        })

    default_summary = {
        "recommended_missing_fields": recommended_missing_fields,
        "recommended_confirmations": recommended_confirmations,
        "question_sequence": review_priority_plan.get("question_sequence") or ordered_question_ids,
        "targeted_question_notes": review_priority_plan.get("targeted_question_notes") or backlog_preview,
        "initial_focus_question_count": int(review_priority_plan.get("initial_focus_question_count", 0) or 0),
        "deferred_question_count": int(review_priority_plan.get("deferred_question_count", 0) or 0),
        "blocker_field_paths": review_priority_plan.get("blocker_field_paths") or list(dict.fromkeys([*recommended_confirmations, *recommended_missing_fields[:5]])),
        "interview_focus_summary": str(review_priority_plan.get("interview_focus_summary") or "Target the interview on unresolved or conflicting planner-critical fields first."),
        "resolution_backlog_preview": backlog_preview,
        "sufficiency_assessment": "SUFFICIENT" if not recommended_missing_fields else "NEEDS_INTERVIEW",
        "interview_readiness": "READY" if questions else "NO_OPEN_QUESTIONS",
        "should_finalize_interview": not questions,
        "rationale": "The final applicant interview should target remaining missing or conflicted fields before final planner output.",
        "confidence": "MODERATE" if questions else "HIGH",
        "agent_id": "applicant_interview_agent",
        "agent_status": "SKIPPED",
        "agent_audit_path": "",
        "agent_policy": {},
        "manual_review_queue_summary": manual_review_queue.get("summary", {}) if isinstance(manual_review_queue, dict) else {},
        "review_priority_counts": review_priority_plan.get("review_priority_counts", {}),
        "planner_action_queue_summary": planner_action_queue.get("summary", {}) if isinstance(planner_action_queue, dict) else {},
        "escalation_registry_summary": escalation_registry.get("summary", {}) if isinstance(escalation_registry, dict) else {},
        "stage_transition_summary": stage_transition_decisions.get("summary", {}) if isinstance(stage_transition_decisions, dict) else {},
        "field_governance_summary": field_governance_registry.get("summary", {}) if isinstance(field_governance_registry, dict) else {},
        "governed_release_summary": governed_release_decision.get("summary", {}) if isinstance(governed_release_decision, dict) else {},
    }

    compact_agent_questions = _compact_questions_for_agent(questions)
    compact_associated_fields = list(dict.fromkeys([*recommended_missing_fields, *recommended_confirmations]))[:50]

    if not _can_run_agent(context):
        return default_summary

    try:
        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="applicant_interview_agent",
                stage_name=GAP_RESOLUTION_INTERVIEW_STAGE,
                task_name="interview_oversight",
                inputs={
                    "open_question_count": len(questions),
                    "answered_field_count": len(answered_field_paths),
                    "conflicting_field_count": len(conflicting_field_paths),
                    "missing_field_count": len(missing_field_paths),
                    "question_records": compact_agent_questions,
                    "question_record_count_sent": len(compact_agent_questions),
                    "question_record_count_total": len(questions),
                    "recommended_missing_fields": recommended_missing_fields,
                    "recommended_confirmations": recommended_confirmations,
                    "manual_review_queue_summary": manual_review_queue.get("summary", {}) if isinstance(manual_review_queue, dict) else {},
                    "review_priority_counts": review_priority_plan.get("review_priority_counts", {}),
                    "initial_focus_question_count": int(review_priority_plan.get("initial_focus_question_count", 0) or 0),
                    "deferred_question_count": int(review_priority_plan.get("deferred_question_count", 0) or 0),
                    "planner_action_queue_summary": planner_action_queue.get("summary", {}) if isinstance(planner_action_queue, dict) else {},
                    "escalation_registry_summary": escalation_registry.get("summary", {}) if isinstance(escalation_registry, dict) else {},
                    "stage_transition_summary": stage_transition_decisions.get("summary", {}) if isinstance(stage_transition_decisions, dict) else {},
                    "field_governance_summary": field_governance_registry.get("summary", {}) if isinstance(field_governance_registry, dict) else {},
                    "governed_release_summary": governed_release_decision.get("summary", {}) if isinstance(governed_release_decision, dict) else {},
                },
                metadata={
                    "service": "interview_service",
                    "owner": "run_service",
                },
                trigger_reason="final_interview_oversight",
                associated_field_paths=compact_associated_fields,
                suggested_output_fields=[
                    "recommended_missing_fields",
                    "recommended_confirmations",
                    "question_sequence",
                    "targeted_question_notes",
                    "blocker_field_paths",
                    "interview_focus_summary",
                    "initial_focus_question_count",
                    "deferred_question_count",
                    "resolution_backlog_preview",
                    "sufficiency_assessment",
                    "interview_readiness",
                    "should_finalize_interview",
                    "rationale",
                    "confidence",
                ],
                requested_capabilities=[
                    "structured_candidate_fields",
                    "followup_questions",
                    "confidence",
                    "rationale",
                ],
            ),
        )
    except Exception as exc:
        summary = dict(default_summary)
        summary["agent_error"] = str(exc)
        return summary

    structured_output = result.get("structured_output", {})
    if not isinstance(structured_output, dict):
        return default_summary

    summary = dict(default_summary)
    for key in [
        "recommended_missing_fields",
        "recommended_confirmations",
        "question_sequence",
        "targeted_question_notes",
        "blocker_field_paths",
        "interview_focus_summary",
        "sufficiency_assessment",
        "interview_readiness",
        "should_finalize_interview",
        "rationale",
        "confidence",
        "review_priority_counts",
        "initial_focus_question_count",
        "deferred_question_count",
    ]:
        if key in structured_output and structured_output.get(key) not in {None, ""}:
            summary[key] = structured_output.get(key)

    summary["agent_id"] = str(result.get("agent_id", "")).strip() or "applicant_interview_agent"
    summary["agent_status"] = str(result.get("status", "")).strip()
    summary["agent_audit_path"] = str(result.get("audit_path", "")).strip()
    summary["agent_policy"] = result.get("policy", {})
    return summary


def _apply_agent_question_sequence(
    questions: list[dict[str, Any]],
    question_sequence: list[str] | None,
) -> list[dict[str, Any]]:
    if not isinstance(question_sequence, list) or not question_sequence:
        return questions
    rank = {
        str(question_id).strip(): index
        for index, question_id in enumerate(question_sequence)
        if isinstance(question_id, str) and str(question_id).strip()
    }
    if not rank:
        return questions
    return sorted(
        questions,
        key=lambda item: (
            rank.get(str(item.get("question_id", "")).strip(), len(rank) + 1000),
            int((item.get("metadata") or {}).get("triage_rank", item.get("triage_rank", 99)) or 99) if isinstance(item.get("metadata"), dict) else int(item.get("triage_rank", 99) or 99),
            -int((item.get("metadata") or {}).get("interview_priority_score", item.get("priority", 0)) or item.get("priority", 0) or 0) if isinstance(item.get("metadata"), dict) else -int(item.get("priority", 0) or 0),
            str(item.get("question_id", "")).strip(),
        ),
    )


def _apply_targeted_question_notes(
    questions: list[dict[str, Any]],
    targeted_question_notes: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not isinstance(targeted_question_notes, list) or not targeted_question_notes:
        return questions
    note_lookup: dict[str, dict[str, Any]] = {}
    for item in targeted_question_notes:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id", "")).strip()
        field_path = str(item.get("field_path", "")).strip()
        key = question_id or field_path
        if key:
            note_lookup[key] = item
    if not note_lookup:
        return questions
    updated: list[dict[str, Any]] = []
    for question in questions:
        metadata = question.get("metadata") if isinstance(question.get("metadata"), dict) else {}
        metadata = dict(metadata)
        key = str(question.get("question_id", "")).strip() or str(question.get("field_path", "")).strip()
        note = note_lookup.get(key)
        if isinstance(note, dict):
            metadata["interview_focus_reason"] = str(note.get("focus_reason", "")).strip()
            metadata["interview_focus_category"] = str(note.get("question_category", "")).strip()
            metadata["interview_blocker"] = bool(str(question.get("field_path", "")).strip() in {
                str(v.get("field_path", "")).strip() for v in targeted_question_notes if isinstance(v, dict)
            } and metadata.get("planner_registry_backed", False))
            question["metadata"] = metadata
        updated.append(question)
    return updated


def run_service(
    context: Any,
    input_dir: str | Path | None = None,
    extraction_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    canonical_state_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_input_dir = Path(input_dir).resolve() if input_dir else context.input_dir
    interview_files = _discover_interview_files(resolved_input_dir)

    sources: list[dict[str, Any]] = []
    answers_candidate: list[dict[str, Any]] = []
    answers_confirmed: list[dict[str, Any]] = []
    clarifications: list[dict[str, Any]] = []
    warnings: list[str] = []

    for path in interview_files:
        source_record = _build_interview_source_record(path)
        sources.append(source_record)

        if path.suffix.lower() == ".json":
            payload = _safe_read_json(path)
            if payload is None:
                warnings.append(
                    f"Interview source '{path.name}' could not be parsed as JSON."
                )
                continue

            (
                extracted_candidates,
                extracted_confirmed,
                extracted_clarifications,
                extraction_warnings,
            ) = _extract_json_interview_payload(
                context=context,
                payload=payload,
                source_name=path.name,
            )

            answers_candidate.extend(extracted_candidates)
            answers_confirmed.extend(extracted_confirmed)
            clarifications.extend(extracted_clarifications)
            warnings.extend(extraction_warnings)
            continue

        text = _safe_read_text(path)
        if not text:
            warnings.append(
                f"Interview source '{path.name}' could not be read or was empty."
            )
            continue

        (
            extracted_candidates,
            extracted_confirmed,
            extracted_clarifications,
            extraction_warnings,
        ) = _extract_text_interview_payload(
            context=context,
            text=text,
            source_name=path.name,
        )

        answers_candidate.extend(extracted_candidates)
        answers_confirmed.extend(extracted_confirmed)
        clarifications.extend(extracted_clarifications)
        warnings.extend(extraction_warnings)

    extraction_questions = _build_questions_from_extraction(extraction_result)
    retrieval_questions = _build_questions_from_retrieval(retrieval_result)
    canonical_questions = _build_questions_from_canonical_state(canonical_state_result)

    generated_questions: list[dict[str, Any]] = []
    generated_questions.extend(extraction_questions)
    generated_questions.extend(retrieval_questions)
    generated_questions.extend(canonical_questions)

    project_identity = _project_identity_from_context(
        context,
        extraction_result=extraction_result,
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
    )
    project_id = str(project_identity.get("project_id") or "").strip() or "UNRESOLVED_PROJECT"
    primary_session_path = _session_path_from_context(context, project_id)
    session_path = _select_session_path_for_workflow(
        primary_path=primary_session_path,
        candidate_paths=_candidate_session_paths_from_context(
            context,
            project_id=project_id,
            project_identity=project_identity,
        ),
    )
    existing_session = _load_existing_session(session_path, project_id)

    existing_ui_state = existing_session.get("ui_state", {})
    if not isinstance(existing_ui_state, dict):
        existing_ui_state = {}
    ui_status = _normalize_interview_ui_status(existing_ui_state.get("status", ""))
    skip_requested_by_user = ui_status in {"SKIPPED_BY_USER", "DEFERRED_BY_USER"}
    continue_requested_by_user = ui_status in {"SUBMITTED_CONTINUE", "PARTIAL_SUBMITTED_CONTINUE", "SKIPPED_BY_USER", "DEFERRED_BY_USER"}
    skip_reason = str(existing_ui_state.get("decision_reason", "")).strip()

    persisted_answers = existing_session.get("answers_confirmed", [])
    if not isinstance(persisted_answers, list):
        persisted_answers = []

    persisted_clarifications = existing_session.get("clarifications", [])
    if not isinstance(persisted_clarifications, list):
        persisted_clarifications = []

    merged_answers_confirmed = _deduplicate_answer_records(
        persisted_answers + answers_confirmed
    )
    merged_clarifications = _deduplicate_clarifications(
        persisted_clarifications + clarifications
    )

    answered_field_paths = {
        str(item.get("field_path", "")).strip()
        for item in merged_answers_confirmed
        if isinstance(item, dict) and str(item.get("field_path", "")).strip()
    }

    pre_interview_planner_field_contract = _build_pre_interview_planner_field_contract(
        normalization_result
    )
    pre_interview_planner_ledger_questions = _build_questions_from_pre_interview_planner_ledger(
        pre_interview_planner_field_contract,
        answered_field_paths,
    )

    planner_ledger_questions = _build_questions_from_planner_field_ledger(
        canonical_state_result,
        answered_field_paths,
    )
    backlog_questions = _build_questions_from_registry_resolution_backlog(
        canonical_state_result,
        answered_field_paths,
    )
    normalization_questions = _build_questions_from_normalization(normalization_result)
    normalization_questions = _filter_normalization_questions_for_interview(
        normalization_questions,
        canonical_state_result=canonical_state_result,
        authoritative_questions=[
            *pre_interview_planner_ledger_questions,
            *planner_ledger_questions,
            *backlog_questions,
            *retrieval_questions,
            *canonical_questions,
            *extraction_questions,
        ],
    )

    generated_questions.extend(pre_interview_planner_ledger_questions)
    generated_questions.extend(normalization_questions)
    generated_questions.extend(planner_ledger_questions)
    generated_questions.extend(backlog_questions)
    generated_questions = _deduplicate_question_records(generated_questions, retrieval_result=retrieval_result)

    filtered_questions = _build_missing_question_records(
        generated_questions,
        answered_field_paths,
    )

    continuation_question_snapshot = [
        dict(item) for item in filtered_questions if isinstance(item, dict)
    ] if continue_requested_by_user else []
    skipped_question_snapshot = continuation_question_snapshot if skip_requested_by_user else []
    if skip_requested_by_user:
        warnings.append(
            "Applicant declined the interactive interview step. GridSenpAI continued the governed pipeline without applicant confirmations; output quality and confidence may be reduced."
        )
        filtered_questions = []
        merged_clarifications = []
    elif continue_requested_by_user:
        unanswered_fields = [
            str(item.get("field_path", "")).strip()
            for item in continuation_question_snapshot
            if isinstance(item, dict) and str(item.get("field_path", "")).strip() not in answered_field_paths
        ]
        if unanswered_fields:
            warnings.append(
                "Applicant submitted available interview responses and chose to continue; unanswered interview fields remain unresolved or planner-reviewable: "
                + ", ".join(dict.fromkeys(unanswered_fields))
            )
        filtered_questions = []

    document_field_pack = build_document_field_pack(
        input_dir=getattr(context, "input_dir", None),
        requested_field_paths=[
            str(item.get("field_path", "")).strip()
            for item in filtered_questions
            if isinstance(item, dict) and str(item.get("field_path", "")).strip()
        ],
    )
    filtered_questions, suppressed_question_fields = filter_question_records_by_field_pack(
        filtered_questions,
        document_field_pack,
    )
    if suppressed_question_fields:
        warnings.append(
            "Document-aware field-pack routing suppressed low-yield interview questions for this intake bundle: "
            + ", ".join(suppressed_question_fields)
        )

    filtered_questions, triage_suppressed_questions, interview_triage_counts = _triage_question_records(
        filtered_questions,
        canonical_state_result=canonical_state_result,
        document_field_pack=document_field_pack,
    )
    if triage_suppressed_questions:
        suppressed_fields = [
            str(item.get("field_path", "")).strip()
            for item in triage_suppressed_questions
            if isinstance(item, dict) and str(item.get("field_path", "")).strip()
        ]
        if suppressed_fields:
            warnings.append(
                "Interview triage suppressed low-yield follow-up questions already backed by strong governed evidence: "
                + ", ".join(dict.fromkeys(suppressed_fields))
            )

    pre_enrichment_question_count = len(filtered_questions)
    filtered_questions = _enrich_question_records_capped(
        context=context,
        questions=filtered_questions,
    )
    filtered_questions = _deduplicate_question_records(filtered_questions, retrieval_result=retrieval_result)
    if pre_enrichment_question_count > MAX_AGENT_ENRICHED_INTERVIEW_QUESTIONS and _can_run_agent(context):
        warnings.append(
            f"Interview agent enrichment was capped at {MAX_AGENT_ENRICHED_INTERVIEW_QUESTIONS} prioritized questions "
            f"out of {pre_enrichment_question_count} triaged questions to prevent prompt/call explosion."
        )

    inferred_field_paths = _build_inferred_field_paths(
        extraction_result,
        answered_field_paths,
    )
    conflicting_field_paths = _build_conflicting_field_paths(canonical_state_result)
    missing_field_paths = _sorted_unique(
        [
            str(item.get("field_path", "")).strip()
            for item in filtered_questions
            if isinstance(item, dict)
        ]
    )

    open_clarifications = [
        item
        for item in merged_clarifications
        if isinstance(item, dict)
        and str(item.get("status", "OPEN")).strip().upper() == "OPEN"
        and str(item.get("field_path", "")).strip() not in answered_field_paths
    ]

    interview_oversight = _build_interview_oversight_summary(
        context=context,
        questions=filtered_questions,
        answered_field_paths=answered_field_paths,
        conflicting_field_paths=conflicting_field_paths,
        missing_field_paths=missing_field_paths,
        canonical_state=(canonical_state_result.get("canonical_state") if isinstance(canonical_state_result, dict) and isinstance(canonical_state_result.get("canonical_state"), dict) else {}),
    )
    if isinstance(interview_oversight, dict):
        interview_oversight["interview_triage_counts"] = dict(interview_triage_counts)
        if continue_requested_by_user:
            interview_oversight["user_continued_after_interview"] = True
            interview_oversight["continued_question_count"] = len(continuation_question_snapshot)
            interview_oversight["continued_question_field_paths"] = [
                str(item.get("field_path", "")).strip()
                for item in continuation_question_snapshot
                if isinstance(item, dict) and str(item.get("field_path", "")).strip()
            ]
        if skip_requested_by_user:
            interview_oversight["user_declined_interview"] = True
            interview_oversight["user_declined_interview_reason"] = skip_reason
            interview_oversight["declined_question_count"] = len(skipped_question_snapshot)
            interview_oversight["declined_question_field_paths"] = [
                str(item.get("field_path", "")).strip()
                for item in skipped_question_snapshot
                if isinstance(item, dict) and str(item.get("field_path", "")).strip()
            ]
        interview_oversight["suppressed_low_yield_questions"] = [
            {
                "field_path": str(item.get("field_path", "")).strip(),
                "question_id": str(item.get("question_id", "")).strip(),
                "triage_reason": str(((item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}).get("triage_reason", "")).strip(),
            }
            for item in triage_suppressed_questions[:25]
            if isinstance(item, dict)
        ]

    filtered_questions = _apply_agent_question_sequence(
        filtered_questions,
        interview_oversight.get("question_sequence") if isinstance(interview_oversight, dict) else None,
    )
    filtered_questions = _apply_targeted_question_notes(
        filtered_questions,
        interview_oversight.get("targeted_question_notes") if isinstance(interview_oversight, dict) else None,
    )
    filtered_questions = _deduplicate_question_records(filtered_questions, retrieval_result=retrieval_result)

    readiness_summary = _build_interview_readiness_summary(
        questions=filtered_questions,
        open_clarifications=open_clarifications,
        answered_field_paths=answered_field_paths,
        inferred_field_paths=inferred_field_paths,
        conflicting_field_paths=conflicting_field_paths,
    )

    remaining_question_count = len(filtered_questions)
    open_clarification_count = len(open_clarifications)
    answered_count = len(merged_answers_confirmed)

    if skip_requested_by_user:
        session_status = "SKIPPED_BY_USER"
        stage_status = "INTERVIEW_SKIPPED_BY_USER"
        workflow_state = "INTERVIEW_SKIPPED_BY_USER"
        ready_for_downstream = True
        requires_user_action = False
        state_reason = "Applicant explicitly skipped or deferred the interactive interview step."
    elif continue_requested_by_user:
        session_status = "COMPLETE"
        stage_status = "INTERVIEW_ANSWERS_SUBMITTED" if answered_count else "INTERVIEW_DEFERRED_BY_USER"
        workflow_state = stage_status
        ready_for_downstream = True
        requires_user_action = False
        state_reason = "Applicant chose to continue after submitting available interview responses."
    elif remaining_question_count > 0 or open_clarification_count > 0:
        session_status = "WAITING_FOR_INTERVIEW"
        stage_status = "WAITING_FOR_INTERVIEW"
        workflow_state = "WAITING_FOR_INTERVIEW"
        ready_for_downstream = False
        requires_user_action = True
        state_reason = "Interview questions or open clarifications require applicant action before downstream planner outputs may run."
    elif answered_count > 0:
        session_status = "COMPLETE"
        stage_status = "INTERVIEW_ANSWERS_SUBMITTED"
        workflow_state = "INTERVIEW_ANSWERS_SUBMITTED"
        ready_for_downstream = True
        requires_user_action = False
        state_reason = "Structured interview answers were ingested and are ready for downstream ledger closure."
    else:
        session_status = "COMPLETE"
        stage_status = "INTERVIEW_NOT_REQUIRED"
        workflow_state = "INTERVIEW_NOT_REQUIRED"
        ready_for_downstream = True
        requires_user_action = False
        state_reason = "No applicant interview questions were required after governed triage."

    interview_workflow_state = {
        "state": workflow_state,
        "stage_status": stage_status,
        "session_status": session_status,
        "ready_for_downstream": ready_for_downstream,
        "requires_user_action": requires_user_action,
        "question_count": remaining_question_count,
        "answered_count": answered_count,
        "clarification_count": open_clarification_count,
        "skipped_count": len(skipped_question_snapshot),
        "remaining_question_count": remaining_question_count,
        "state_reason": state_reason,
    }

    session_payload = {
        "session_id": existing_session["session_id"],
        "project_id": project_id,
        "project_identity": project_identity,
        "ui_state": {
            **existing_ui_state,
            "status": "SKIPPED_BY_USER" if skip_requested_by_user else existing_ui_state.get("status", ""),
            "decision_reason": skip_reason,
            "draft_outputs_allowed": bool(skip_requested_by_user or continue_requested_by_user),
            "final_outputs_allowed": bool(not skip_requested_by_user),
            "updated_at": utc_now_iso(),
        } if existing_ui_state or skip_requested_by_user or continue_requested_by_user else {},
        "session_path": str(session_path),
        "created_at": existing_session["created_at"],
        "updated_at": utc_now_iso(),
        "status": session_status,
        "workflow_state": interview_workflow_state,
        "sources": sources,
        "questions": filtered_questions,
        "answers_confirmed": merged_answers_confirmed,
        "clarifications": open_clarifications,
        "field_tracking": {
            "answered": _sorted_unique(list(answered_field_paths)),
            "inferred": inferred_field_paths,
            "conflicting": conflicting_field_paths,
            "missing": missing_field_paths,
            "document_field_pack": document_field_pack.to_dict(),
            "pre_interview_planner_field_contract_summary": (
                pre_interview_planner_field_contract.get("planner_field_ledger_summary", {})
                if isinstance(pre_interview_planner_field_contract, dict)
                else {}
            ),
            "pre_interview_planner_field_ledger_question_count": len(pre_interview_planner_ledger_questions),
            "planner_registry_resolution_backlog": [
                {
                    "question_id": str(item.get("question_id", "")).strip(),
                    "field_path": str(item.get("field_path", "")).strip(),
                    "field_id": str((item.get("metadata") or {}).get("field_id", "")).strip() if isinstance(item.get("metadata"), dict) else "",
                    "priority": int(item.get("priority", 0) or 0),
                    "question_category": str(item.get("question_category", "")).strip(),
                    "planner_registry_backed": bool(((item.get("metadata") or {}).get("planner_registry_backed", False))) if isinstance(item.get("metadata"), dict) else False,
                }
                for item in filtered_questions[:25]
                if isinstance(item, dict)
            ],
        },
        "summary": {
            "question_count": remaining_question_count,
            "remaining_question_count": remaining_question_count,
            "requires_user_action": requires_user_action,
            "ready_for_downstream": ready_for_downstream,
            "workflow_state": workflow_state,
            "pre_interview_planner_field_ledger_question_count": len(pre_interview_planner_ledger_questions),
            "pre_interview_planner_field_ledger_field_count": int((pre_interview_planner_field_contract.get("planner_field_ledger_summary", {}) if isinstance(pre_interview_planner_field_contract, dict) else {}).get("field_count", 0) or 0),
            "pre_interview_planner_field_ledger_registry_complete": bool(((pre_interview_planner_field_contract.get("planner_field_ledger_summary", {}) if isinstance(pre_interview_planner_field_contract, dict) else {}).get("registry_completion_audit", {}) if isinstance((pre_interview_planner_field_contract.get("planner_field_ledger_summary", {}) if isinstance(pre_interview_planner_field_contract, dict) else {}).get("registry_completion_audit", {}), dict) else {}).get("registry_complete", False)),
            "answers_confirmed_count": len(merged_answers_confirmed),
            "clarification_count": len(open_clarifications),
            "answered_field_count": len(answered_field_paths),
            "inferred_field_count": len(inferred_field_paths),
            "conflicting_field_count": len(conflicting_field_paths),
            "missing_field_count": len(missing_field_paths),
            "blocker_field_count": len(interview_oversight.get("blocker_field_paths", [])) if isinstance(interview_oversight, dict) and isinstance(interview_oversight.get("blocker_field_paths"), list) else 0,
            "interview_focus_summary": str(interview_oversight.get("interview_focus_summary", "")).strip() if isinstance(interview_oversight, dict) else "",
            "manual_review_interview_dependency_count": int(((interview_oversight.get("manual_review_queue_summary") if isinstance(interview_oversight, dict) and isinstance(interview_oversight.get("manual_review_queue_summary"), dict) else {}).get("interview_dependency_count", 0))),
            "governed_release_state": str(((interview_oversight.get("governed_release_summary") if isinstance(interview_oversight, dict) and isinstance(interview_oversight.get("governed_release_summary"), dict) else {}).get("release_state", ""))).strip(),
            "governed_release_blocking_field_count": int(((interview_oversight.get("governed_release_summary") if isinstance(interview_oversight, dict) and isinstance(interview_oversight.get("governed_release_summary"), dict) else {}).get("blocking_field_count", 0))),
            "planner_critical_blocking_question_count": int(((interview_oversight.get("interview_triage_counts") if isinstance(interview_oversight, dict) and isinstance(interview_oversight.get("interview_triage_counts"), dict) else {}).get("planner_critical_blocking", 0))),
            "high_value_clarification_question_count": int(((interview_oversight.get("interview_triage_counts") if isinstance(interview_oversight, dict) and isinstance(interview_oversight.get("interview_triage_counts"), dict) else {}).get("high_value_clarification", 0))),
            "informational_question_count": int(((interview_oversight.get("interview_triage_counts") if isinstance(interview_oversight, dict) and isinstance(interview_oversight.get("interview_triage_counts"), dict) else {}).get("informational", 0))),
            "suppressed_low_yield_question_count": int(((interview_oversight.get("interview_triage_counts") if isinstance(interview_oversight, dict) and isinstance(interview_oversight.get("interview_triage_counts"), dict) else {}).get("suppressed_low_yield", 0))),
        },
        "interview_oversight": interview_oversight,
        "pre_interview_planner_field_contract": pre_interview_planner_field_contract,
    }

    _persist_session(session_path, session_payload)
    canonical_state_result = _apply_confirmed_answers_to_canonical_state(
        canonical_state_result,
        merged_answers_confirmed,
    )

    return {
        "run_id": context.run_id,
        "sources": sources,
        "questions": filtered_questions,
        "answers": merged_answers_confirmed,
        "answers_candidate": answers_candidate,
        "answers_confirmed": merged_answers_confirmed,
        "clarifications": open_clarifications,
        "warnings": warnings,
        "status": stage_status,
        "workflow_state": interview_workflow_state,
        "ready_for_downstream": ready_for_downstream,
        "requires_user_action": requires_user_action,
        "interview_processed_at": utc_now_iso(),
        "ingested_at": utc_now_iso(),
        "interview_session": session_payload,
        "field_tracking": session_payload["field_tracking"],
        "session_summary": session_payload["summary"],
        "interview_oversight": interview_oversight,
        "pre_interview_planner_field_contract": pre_interview_planner_field_contract,
        "pre_interview_planner_field_ledger_summary": (
            pre_interview_planner_field_contract.get("planner_field_ledger_summary", {})
            if isinstance(pre_interview_planner_field_contract, dict)
            else {}
        ),
    }


def ingest_interviews(
    context: Any,
    input_dir: str | Path | None = None,
    extraction_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    canonical_state_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_service(
        context=context,
        input_dir=input_dir,
        extraction_result=extraction_result,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
        canonical_state_result=canonical_state_result,
    )

class InterviewResolutionCoordinator:
    """Central owner for structured intake resolution during the revamp transition."""

    def generate_questions(
        self,
        requested_field_paths: list[str],
        candidates: list[Any],
        canonical_state: dict[str, Any],
        context: Any | None = None,
    ) -> Any:
        from services.interview_service.models import InterviewFallbackResult, InterviewQuestion
        from shared.field_paths import normalize_field_path
        from services.interview_service.utils import build_question_metadata

        field_records = self._coerce_dict_list(canonical_state.get("field_records"))
        review_flags = self._coerce_dict_list(canonical_state.get("review_flags"))

        record_lookup = self._build_field_record_lookup(field_records, normalize_field_path)
        review_flag_lookup = self._build_review_flag_lookup(review_flags, normalize_field_path)
        candidate_lookup = self._build_candidate_lookup(candidates, normalize_field_path)

        unresolved_fields: list[str] = []
        questions: list[InterviewQuestion] = []

        for requested_field_path in requested_field_paths:
            normalized_field_path = normalize_field_path(requested_field_path)
            resolution_reason = self._determine_resolution_reason(
                field_path=normalized_field_path,
                record_lookup=record_lookup,
                review_flag_lookup=review_flag_lookup,
                candidate_lookup=candidate_lookup,
            )

            if resolution_reason is None:
                continue

            unresolved_fields.append(requested_field_path)
            question_id, prompt = build_question_metadata(requested_field_path)

            related_artifact_ids = sorted(
                {
                    artifact_id
                    for artifact_id in self._collect_related_artifact_ids(
                        normalized_field_path,
                        record_lookup,
                        candidate_lookup,
                    )
                    if artifact_id
                }
            )

            triggering_status = self._infer_triggering_status(
                normalized_field_path,
                record_lookup,
            )
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
            question = InterviewQuestion(
                field_path=requested_field_path,
                question_id=question_id,
                prompt=prompt,
                reason=resolution_reason,
                triggering_status=triggering_status,
                question_category=_classify_question_category(seed_question),
                priority=_question_priority(seed_question),
                requires_confirmation=_classify_question_category(seed_question) in {"confirmation", "low_confidence", "review_required", "conflicting"},
                related_artifact_ids=related_artifact_ids,
                metadata={
                    "normalized_field_path": normalized_field_path,
                    "review_flag_categories": review_flag_lookup.get(normalized_field_path, []),
                    "question_category": _classify_question_category(seed_question),
                    "priority": _question_priority(seed_question),
                },
            )

            questions.append(
                self._apply_intake_clarification_agent(
                    question=question,
                    context=context,
                    candidate_lookup=candidate_lookup,
                    record_lookup=record_lookup,
                )
            )

        return InterviewFallbackResult(
            unresolved_fields=unresolved_fields,
            questions=questions,
        )

    def resolve_intake(self, intake_input: Any) -> Any:
        from services.extraction_service.models import ExtractionPipelineInput, ExtractionPipelineResult
        from services.extraction_service.domain import ExtractionDomainCoordinator
        from services.interview_service.models import IntakeResolutionResult

        pipeline_result: ExtractionPipelineResult = ExtractionDomainCoordinator().run_pipeline(
            ExtractionPipelineInput(
                artifacts=intake_input.artifacts,
                field_paths=intake_input.field_paths,
                canonical_state=intake_input.canonical_state,
                context=intake_input.context,
            )
        )

        interview_questions = self._decorate_interview_questions(
            questions=pipeline_result.interview_questions,
            intake_input=intake_input,
            canonical_state=pipeline_result.canonical_state,
        )
        interview_questions = self._apply_agent_question_enrichment(
            questions=interview_questions,
            intake_input=intake_input,
            canonical_state=pipeline_result.canonical_state,
        )

        return IntakeResolutionResult(
            canonical_state=pipeline_result.canonical_state,
            unresolved_fields=pipeline_result.unresolved_fields,
            interview_questions=interview_questions,
            ready_for_interview=self._is_ready_for_interview(interview_questions),
        )

    def orchestrate_phase3(self, orchestration_input: Any) -> Any:
        from types import SimpleNamespace
        from services.agent_policy_service.service import evaluate_agent_policy
        from services.extraction_service.domain import ExtractionDomainCoordinator
        from services.interview_service.models import (
            IntakeResolutionInput,
            Phase3IntakeOrchestrationResult,
        )
        from services.interview_service.utils import normalize_artifacts

        normalized_artifacts = normalize_artifacts(orchestration_input.artifacts)

        resolution_result = self.resolve_intake(
            IntakeResolutionInput(
                artifacts=normalized_artifacts,
                field_paths=orchestration_input.field_paths,
                canonical_state=orchestration_input.canonical_state,
                context=orchestration_input.context,
            )
        )

        extraction_domain = ExtractionDomainCoordinator()
        observations = extraction_domain.collect_entity_observations(normalized_artifacts)
        resolved_entities = extraction_domain.resolve_entities(observations)

        policy_context = orchestration_input.context or SimpleNamespace(run_id="phase3_orchestration")

        intake_agent_policy = evaluate_agent_policy(
            agent_id="intake_clarification_agent",
            stage_name=GAP_RESOLUTION_INTERVIEW_STAGE,
            task_name="question_explanation",
            context=policy_context,
        )
        blocked_override_policy = evaluate_agent_policy(
            agent_id="intake_clarification_agent",
            stage_name=GAP_RESOLUTION_INTERVIEW_STAGE,
            task_name="canonical_state_write",
            context=policy_context,
        )

        llm_task_policy = {
            "intake_clarification_agent": (
                f"{intake_agent_policy.status}: {intake_agent_policy.reason}"
            ),
            "canonical_state_write": (
                f"{blocked_override_policy.status}: {blocked_override_policy.reason}"
            ),
        }

        return Phase3IntakeOrchestrationResult(
            canonical_state=resolution_result.canonical_state,
            unresolved_fields=resolution_result.unresolved_fields,
            interview_questions=resolution_result.interview_questions,
            ready_for_interview=resolution_result.ready_for_interview,
            llm_task_policy=llm_task_policy,
            resolved_entities=resolved_entities,
        )

    def execute_phase3_bridge(self, bridge_input: Any) -> Any:
        from services.interview_service.models import (
            Phase3ExecutionBridgeResult,
            Phase3IntakeOrchestrationInput,
        )
        from services.interview_service.serialization import serialize_interview_questions, serialize_resolved_entities

        orchestration_result = self.orchestrate_phase3(
            Phase3IntakeOrchestrationInput(
                artifacts=bridge_input.artifacts,
                field_paths=bridge_input.requested_field_paths,
                canonical_state=bridge_input.canonical_state,
                context=getattr(bridge_input, "context", None),
            )
        )

        return Phase3ExecutionBridgeResult(
            canonical_state=orchestration_result.canonical_state,
            unresolved_fields=orchestration_result.unresolved_fields,
            interview_questions=serialize_interview_questions(
                orchestration_result.interview_questions
            ),
            ready_for_interview=orchestration_result.ready_for_interview,
            llm_task_policy=orchestration_result.llm_task_policy,
            resolved_entities=serialize_resolved_entities(
                orchestration_result.resolved_entities
            ),
        )

    def _apply_intake_clarification_agent(self, *, question: Any, context: Any | None, candidate_lookup: dict[str, list[Any]], record_lookup: dict[str, list[dict[str, Any]]]) -> Any:
        if not self._can_run_agent(context):
            return question

        from shared.field_paths import normalize_field_path

        normalized_field_path = normalize_field_path(question.field_path)
        candidate_summary = self._summarize_candidates(candidate_lookup.get(normalized_field_path, []))
        record_summary = self._summarize_records(record_lookup.get(normalized_field_path, []))
        review_flag_categories = question.metadata.get("review_flag_categories", [])
        if not isinstance(review_flag_categories, list):
            review_flag_categories = []

        task_name = self._resolve_agent_task(question.reason)
        agent_result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="intake_clarification_agent",
                stage_name=GAP_RESOLUTION_INTERVIEW_STAGE,
                task_name=task_name,
                inputs={
                    "field_path": question.field_path,
                    "question_id": question.question_id,
                    "question_text": question.prompt,
                    "reason": question.reason,
                    "triggering_status": question.triggering_status,
                    "related_artifact_ids": list(question.related_artifact_ids),
                    "review_flag_categories": [
                        str(item).strip() for item in review_flag_categories if isinstance(item, str) and str(item).strip()
                    ],
                    "candidate_summary": candidate_summary,
                    "record_summary": record_summary,
                },
                metadata={
                    "service": "interview_service",
                    "owner": "InterviewResolutionCoordinator",
                },
                trigger_reason=question.reason,
                associated_field_paths=[question.field_path],
                evidence_anchors=self._build_evidence_anchors(candidate_summary, record_summary),
                suggested_output_fields=[
                    "clarified_question_text",
                    "explained_question",
                    "clarification_prompt",
                    "candidate_structured_answer",
                    "needs_human_reask",
                    "rationale",
                    "confidence",
                ],
            ),
        )

        structured_output = agent_result.get("structured_output", {})
        if not isinstance(structured_output, dict):
            structured_output = {}

        explained_question = structured_output.get("explained_question")
        clarified_question_text = structured_output.get("clarified_question_text")
        clarification_prompt = structured_output.get("clarification_prompt")
        review_notes = structured_output.get("review_notes", [])
        candidate_structured_answer = structured_output.get("candidate_structured_answer")
        needs_human_reask = structured_output.get("needs_human_reask")
        rationale = structured_output.get("rationale")
        confidence = structured_output.get("confidence")

        if isinstance(clarified_question_text, str) and clarified_question_text.strip():
            question.help_text = clarified_question_text.strip()
        elif isinstance(explained_question, str) and explained_question.strip():
            question.help_text = explained_question.strip()

        if isinstance(clarification_prompt, str) and clarification_prompt.strip():
            question.clarification_prompt = clarification_prompt.strip()

        question.agent_id = str(agent_result.get("agent_id", "")).strip() or "intake_clarification_agent"
        question.agent_status = str(agent_result.get("status", "")).strip() or None
        question.agent_audit_path = str(agent_result.get("audit_path", "")).strip() or None

        if candidate_structured_answer is not None:
            question.metadata["candidate_structured_answer"] = candidate_structured_answer
        if isinstance(needs_human_reask, bool):
            question.metadata["needs_human_reask"] = needs_human_reask
        if isinstance(rationale, str) and rationale.strip():
            question.metadata["agent_rationale"] = rationale.strip()
        if isinstance(confidence, str) and confidence.strip():
            question.metadata["agent_confidence"] = confidence.strip()
        if isinstance(review_notes, list) and review_notes:
            existing_notes = question.metadata.get("agent_review_notes", [])
            if not isinstance(existing_notes, list):
                existing_notes = []
            question.metadata["agent_review_notes"] = [
                str(item).strip()
                for item in [*existing_notes, *review_notes]
                if isinstance(item, str) and item.strip()
            ]

        question.metadata["agent_policy"] = agent_result.get("policy", {})
        question.metadata["agent_task_name"] = task_name
        return question

    def _resolve_agent_task(self, resolution_reason: str) -> str:
        normalized = str(resolution_reason or "").strip().lower()
        if normalized in {"conflicting_extracted_values_require_human_resolution", "review_required_after_extraction"}:
            return "clarification_generation"
        return "question_explanation"

    def _build_evidence_anchors(self, candidate_summary: list[dict[str, Any]], record_summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
        anchors: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()

        for candidate in candidate_summary:
            artifact_id = str(candidate.get("source_artifact_id", "")).strip()
            if not artifact_id:
                continue
            key = ("candidate", artifact_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            anchors.append({"anchor_type": "candidate_artifact", "source_artifact_id": artifact_id, "field_path": str(candidate.get("field_path", "")).strip()})

        for record in record_summary:
            artifact_id = str(record.get("source_artifact_id", "")).strip()
            if not artifact_id:
                continue
            key = ("record", artifact_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            anchors.append({"anchor_type": "field_record_artifact", "source_artifact_id": artifact_id, "field_path": str(record.get("field_path", "")).strip()})

        return anchors

    def _can_run_agent(self, context: Any | None) -> bool:
        if context is None:
            return False
        run_id = getattr(context, "run_id", None)
        return isinstance(run_id, str) and bool(run_id.strip())

    def _summarize_candidates(self, candidates: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "field_path": getattr(candidate, "field_path", None),
                "value": getattr(candidate, "value", None),
                "confidence": getattr(candidate, "confidence", None),
                "source_artifact_id": getattr(candidate, "source_artifact_id", None),
                "method": getattr(candidate, "method", None),
            }
            for candidate in candidates
        ]

    def _summarize_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for record in records:
            summaries.append({
                "field_path": record.get("field_path"),
                "status": record.get("status"),
                "confidence": record.get("confidence"),
                "source_artifact_id": record.get("source_artifact_id"),
                "method": record.get("method"),
            })
        return summaries

    def _determine_resolution_reason(self, field_path: str, record_lookup: dict[str, list[dict[str, Any]]], review_flag_lookup: dict[str, list[str]], candidate_lookup: dict[str, list[Any]]) -> str | None:
        records = record_lookup.get(field_path, [])
        categories = set(review_flag_lookup.get(field_path, []))
        candidates = candidate_lookup.get(field_path, [])

        if any(self._is_terminal_record(record) for record in records):
            return None
        if "CONFLICTING_FIELD" in categories:
            return "conflicting_extracted_values_require_human_resolution"
        if "MISSING_FIELD" in categories:
            return "missing_after_extraction"
        if "LOW_CONFIDENCE_FIELD" in categories:
            return "low_confidence_after_extraction"
        if any(record.get("status") == "conflicting" for record in records):
            return "conflicting_extracted_values_require_human_resolution"
        if any(record.get("status") == "review_required" for record in records):
            return "review_required_after_extraction"
        if any(record.get("status") == "missing" for record in records):
            return "missing_after_extraction"
        if candidates and not any(getattr(candidate, "value", None) is not None and float(getattr(candidate, "confidence", 0.0) or 0.0) >= 0.60 for candidate in candidates):
            return "low_confidence_after_extraction"
        if not records and not candidates:
            return "missing_after_extraction"
        return None

    def _infer_triggering_status(self, field_path: str, record_lookup: dict[str, list[dict[str, Any]]]) -> str | None:
        records = record_lookup.get(field_path, [])
        if not records:
            return None
        status = records[0].get("status")
        return status if isinstance(status, str) else None

    def _collect_related_artifact_ids(self, field_path: str, record_lookup: dict[str, list[dict[str, Any]]], candidate_lookup: dict[str, list[Any]]) -> set[str]:
        artifact_ids: set[str] = set()
        for record in record_lookup.get(field_path, []):
            source_artifact_id = record.get("source_artifact_id")
            if isinstance(source_artifact_id, str) and source_artifact_id.strip():
                artifact_ids.add(source_artifact_id.strip())
        for candidate in candidate_lookup.get(field_path, []):
            source_artifact_id = str(getattr(candidate, "source_artifact_id", "")).strip()
            if source_artifact_id:
                artifact_ids.add(source_artifact_id)
        return artifact_ids

    def _build_field_record_lookup(self, field_records: list[dict[str, Any]], normalize_field_path: Any) -> dict[str, list[dict[str, Any]]]:
        lookup: dict[str, list[dict[str, Any]]] = {}
        for record in field_records:
            field_path = record.get("field_path")
            if not isinstance(field_path, str) or not field_path.strip():
                continue
            normalized_field_path = normalize_field_path(field_path)
            lookup.setdefault(normalized_field_path, []).append(record)
        return lookup

    def _build_review_flag_lookup(self, review_flags: list[dict[str, Any]], normalize_field_path: Any) -> dict[str, list[str]]:
        lookup: dict[str, list[str]] = {}
        for flag in review_flags:
            field_path = flag.get("field_path")
            category = flag.get("category")
            if not isinstance(field_path, str) or not field_path.strip():
                continue
            if not isinstance(category, str) or not category.strip():
                continue
            normalized_field_path = normalize_field_path(field_path)
            lookup.setdefault(normalized_field_path, []).append(category.strip())
        return lookup

    def _build_candidate_lookup(self, candidates: list[Any], normalize_field_path: Any) -> dict[str, list[Any]]:
        lookup: dict[str, list[Any]] = {}
        for candidate in candidates:
            normalized_field_path = normalize_field_path(getattr(candidate, "field_path", ""))
            lookup.setdefault(normalized_field_path, []).append(candidate)
        return lookup

    def _coerce_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def _is_terminal_record(self, record: dict[str, Any]) -> bool:
        return record.get("status") in {"validated", "interview_confirmed"}

    def _decorate_interview_questions(self, *, questions: list[Any], intake_input: Any, canonical_state: dict[str, Any]) -> list[Any]:
        decorated: list[Any] = []

        requested_field_paths = {
            str(field_path).strip()
            for field_path in intake_input.field_paths
            if isinstance(field_path, str) and str(field_path).strip()
        }
        unresolved_field_paths = {
            question.field_path
            for question in questions
            if isinstance(getattr(question, "field_path", None), str) and question.field_path.strip()
        }

        for question in questions:
            metadata = dict(question.metadata) if isinstance(question.metadata, dict) else {}
            metadata.setdefault("requested_by_intake_resolution", question.field_path in requested_field_paths)
            metadata.setdefault("still_unresolved", question.field_path in unresolved_field_paths)
            metadata.setdefault("intake_resolution_stage", "post_extraction_pipeline")
            metadata.setdefault("artifact_count", len(intake_input.artifacts))
            metadata.setdefault("canonical_state_field_record_count", self._field_record_count(canonical_state))
            metadata.setdefault("candidate_summary", self._candidate_summary_for_field(canonical_state, question.field_path))
            metadata.setdefault("record_summary", self._record_summary_for_field(canonical_state, question.field_path))
            metadata.setdefault("review_flag_categories", self._review_flag_categories_for_field(canonical_state, question.field_path))
            seeded_record = {
                "field_path": question.field_path,
                "reason": getattr(question, "reason", None),
                "triggering_status": getattr(question, "triggering_status", None),
                "required": getattr(question, "required", True),
                "metadata": metadata,
            }
            category = _classify_question_category(seeded_record)
            priority = _question_priority(seeded_record)
            question.question_category = category
            question.priority = priority
            question.requires_confirmation = category in {"confirmation", "low_confidence", "review_required", "conflicting"}
            metadata["question_category"] = category
            metadata["priority"] = priority
            metadata["requires_confirmation"] = question.requires_confirmation
            question.metadata = metadata
            decorated.append(question)

        return decorated

    def _apply_agent_question_enrichment(self, *, questions: list[Any], intake_input: Any, canonical_state: dict[str, Any]) -> list[Any]:
        if not self._can_run_agent(getattr(intake_input, "context", None)):
            return questions
        return [
            self._enrich_question_with_agent(question=question, intake_input=intake_input, canonical_state=canonical_state)
            for question in questions
        ]

    def _enrich_question_with_agent(self, *, question: Any, intake_input: Any, canonical_state: dict[str, Any]) -> Any:
        metadata = dict(question.metadata) if isinstance(question.metadata, dict) else {}
        candidate_summary = metadata.get("candidate_summary", [])
        record_summary = metadata.get("record_summary", [])
        review_flag_categories = metadata.get("review_flag_categories", [])
        if not isinstance(candidate_summary, list):
            candidate_summary = []
        if not isinstance(record_summary, list):
            record_summary = []
        if not isinstance(review_flag_categories, list):
            review_flag_categories = []

        artifact_ids = sorted({
            str(item.get("artifact_id", "")).strip()
            for item in getattr(intake_input, "artifacts", [])
            if isinstance(item, dict) and str(item.get("artifact_id", "")).strip()
        })

        trigger_reason = self._resolve_intake_agent_trigger(question.reason)

        agent_result = run_agent(
            context=getattr(intake_input, "context", None),
            request=AgentRequest(
                agent_id="intake_clarification_agent",
                stage_name=GAP_RESOLUTION_INTERVIEW_STAGE,
                task_name="question_explanation",
                inputs={
                    "field_path": question.field_path,
                    "question_id": question.question_id,
                    "question_text": question.prompt,
                    "reason": question.reason,
                    "triggering_status": question.triggering_status,
                    "related_artifact_ids": list(question.related_artifact_ids),
                    "candidate_summary": candidate_summary,
                    "record_summary": record_summary,
                    "review_flag_categories": [
                        str(item).strip()
                        for item in review_flag_categories
                        if isinstance(item, str) and str(item).strip()
                    ],
                    "artifact_ids": artifact_ids,
                    "artifact_count": len(getattr(intake_input, "artifacts", [])),
                    "canonical_state_field_record_count": self._field_record_count(canonical_state),
                },
                metadata={
                    "service": "interview_service",
                    "owner": "InterviewResolutionCoordinator",
                    "requested_field_count": len(getattr(intake_input, "field_paths", [])),
                },
                trigger_reason=trigger_reason,
                associated_field_paths=[question.field_path],
                evidence_anchors=self._build_evidence_anchors(candidate_summary, record_summary),
                suggested_output_fields=[
                    "clarified_question_text",
                    "explained_question",
                    "clarification_prompt",
                    "candidate_structured_answer",
                    "needs_human_reask",
                    "rationale",
                    "confidence",
                ],
            ),
        )

        structured_output = agent_result.get("structured_output", {})
        if not isinstance(structured_output, dict):
            structured_output = {}

        explained_question = structured_output.get("explained_question")
        clarified_question_text = structured_output.get("clarified_question_text")
        clarification_prompt = structured_output.get("clarification_prompt")
        candidate_structured_answer = structured_output.get("candidate_structured_answer")
        needs_human_reask = structured_output.get("needs_human_reask")
        review_notes = structured_output.get("review_notes", [])
        rationale = structured_output.get("rationale")
        confidence = structured_output.get("confidence")

        if isinstance(clarified_question_text, str) and clarified_question_text.strip():
            question.help_text = clarified_question_text.strip()
        elif isinstance(explained_question, str) and explained_question.strip():
            question.help_text = explained_question.strip()

        if isinstance(clarification_prompt, str) and clarification_prompt.strip():
            question.clarification_prompt = clarification_prompt.strip()

        question.agent_id = str(agent_result.get("agent_id", "")).strip() or "intake_clarification_agent"
        question.agent_status = str(agent_result.get("status", "")).strip() or None
        question.agent_audit_path = str(agent_result.get("audit_path", "")).strip() or None

        if candidate_structured_answer is not None:
            metadata["candidate_structured_answer"] = candidate_structured_answer
        if isinstance(needs_human_reask, bool):
            metadata["needs_human_reask"] = needs_human_reask
        if isinstance(rationale, str) and rationale.strip():
            metadata["agent_rationale"] = rationale.strip()
        if isinstance(confidence, str) and confidence.strip():
            metadata["agent_confidence"] = confidence.strip()
        if isinstance(review_notes, list) and review_notes:
            existing_notes = metadata.get("agent_review_notes", [])
            if not isinstance(existing_notes, list):
                existing_notes = []
            metadata["agent_review_notes"] = [
                str(item).strip()
                for item in [*existing_notes, *review_notes]
                if isinstance(item, str) and str(item).strip()
            ]

        metadata["agent_policy"] = agent_result.get("policy", {})
        metadata["agent_task_name"] = "question_explanation"
        question.metadata = metadata
        return question

    def _resolve_intake_agent_trigger(self, resolution_reason: str) -> str:
        normalized = str(resolution_reason or "").strip().lower()
        if normalized in {
            "conflicting_extracted_values_require_human_resolution",
            "review_required_after_extraction",
            "multiple_candidates_require_confirmation",
        }:
            return "review_required_after_extraction"
        return "post_extraction_question_generation"

    def _candidate_summary_for_field(self, canonical_state: dict[str, Any], field_path: str) -> list[dict[str, Any]]:
        extraction_candidates = canonical_state.get("extraction_candidates", [])
        if not isinstance(extraction_candidates, list):
            return []
        summaries: list[dict[str, Any]] = []
        for item in extraction_candidates:
            if not isinstance(item, dict):
                continue
            candidate_field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
            if candidate_field_path != field_path:
                continue
            summaries.append({
                "field_path": candidate_field_path,
                "value": item.get("value"),
                "confidence": item.get("confidence"),
                "method": str(item.get("method", "")).strip(),
                "source_artifact_id": str(item.get("source_artifact_id", "")).strip(),
                "candidate_id": str(item.get("candidate_id", "")).strip(),
            })
        return summaries

    def _record_summary_for_field(self, canonical_state: dict[str, Any], field_path: str) -> list[dict[str, Any]]:
        field_records = canonical_state.get("field_records", [])
        if not isinstance(field_records, list):
            return []
        summaries: list[dict[str, Any]] = []
        for item in field_records:
            if not isinstance(item, dict):
                continue
            record_field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
            if record_field_path != field_path:
                continue
            summaries.append({
                "field_path": record_field_path,
                "value": item.get("value"),
                "status": str(item.get("status", "")).strip(),
                "validation_status": str(item.get("validation_status", "")).strip(),
                "review_status": str(item.get("review_status", "")).strip(),
                "source_artifact_id": str(item.get("source_artifact_id", "")).strip(),
                "field_record_id": str(item.get("field_record_id", "")).strip(),
            })
        return summaries

    def _review_flag_categories_for_field(self, canonical_state: dict[str, Any], field_path: str) -> list[str]:
        review_flags = canonical_state.get("review_flags", [])
        if not isinstance(review_flags, list):
            return []
        categories: set[str] = set()
        for item in review_flags:
            if not isinstance(item, dict):
                continue
            candidate_field_path = _canonicalize_retrieval_field_path(item.get("field_path", ""), retrieval_result)
            if candidate_field_path != field_path:
                continue
            category = str(item.get("category", "")).strip()
            if category:
                categories.add(category)
        return sorted(categories)

    def _field_record_count(self, canonical_state: dict[str, Any]) -> int:
        field_records = canonical_state.get("field_records", [])
        if not isinstance(field_records, list):
            return 0
        return len([record for record in field_records if isinstance(record, dict)])

    def _is_ready_for_interview(self, questions: list[Any]) -> bool:
        if not questions:
            return False
        blocking_categories = {"missing", "low_confidence", "review_required", "conflicting", "confirmation"}
        for item in questions:
            category = getattr(item, "question_category", None)
            if not category and isinstance(getattr(item, "metadata", None), dict):
                category = item.metadata.get("question_category")
            if str(category or "missing").strip().lower() in blocking_categories:
                return True
        return bool(questions)
