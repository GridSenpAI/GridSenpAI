from __future__ import annotations

import json
import os
import shutil
from argparse import Namespace
from pathlib import Path
from typing import Any, Iterable

from app.config import CONFIG, apply_llm_runtime_overrides
from app.orchestration.run_pipeline import run_from_args
from shared.runtime_stage_contract import GAP_RESOLUTION_RETRIEVAL_STAGE
from services.interview_service.models import InterviewQuestion
from services.interview_service.utils import process_raw_answer
from shared.planner_registry import field_label




def discover_local_gguf_models(project_root: Path) -> list[Path]:
    models_root = project_root / "models"
    if not models_root.exists():
        return []
    return sorted((path for path in models_root.rglob("*.gguf") if path.is_file()), key=lambda item: str(item).lower())


def infer_model_alias_from_path(model_path: str | Path | None) -> str:
    raw = str(model_path or "").strip()
    if not raw:
        return "local-gguf-model"
    name = Path(raw).stem.lower()
    if "granite" in name:
        return "granite-local"
    if "qwen" in name:
        return "local-qwen"
    if "llama" in name:
        return "llama-local"
    if "mistral" in name:
        return "mistral-local"
    return _slugify(Path(raw).stem).replace("_", "-") or "local-gguf-model"


def apply_ui_llm_runtime_selection(
    *,
    runtime_mode: str,
    model_path: str | Path | None = None,
    model_alias: str | None = None,
    n_ctx: int | None = None,
    n_batch: int | None = None,
    watsonx_url: str | None = None,
    watsonx_api_key: str | None = None,
    watsonx_project_id: str | None = None,
    watsonx_space_id: str | None = None,
    watsonx_model_id: str | None = None,
    watsonx_api_version: str | None = None,
    watsonx_iam_url: str | None = None,
) -> None:
    normalized_mode = str(runtime_mode or "llama_cpp").strip().lower()
    if normalized_mode == "deterministic":
        apply_llm_runtime_overrides(enabled=False)
        return

    if normalized_mode == "ibm_watsonx":
        alias_value = str(model_alias or "").strip() or "granite-watsonx"
        apply_llm_runtime_overrides(
            enabled=True,
            provider="ibm_watsonx",
            model_path="",
            model_alias=alias_value,
            n_ctx=n_ctx,
            n_batch=n_batch,
            watsonx_url=watsonx_url,
            watsonx_api_key=watsonx_api_key,
            watsonx_project_id=watsonx_project_id,
            watsonx_space_id=watsonx_space_id,
            watsonx_model_id=watsonx_model_id,
            watsonx_api_version=watsonx_api_version,
            watsonx_iam_url=watsonx_iam_url,
        )
        return

    path_value = str(model_path or "").strip()
    alias_value = str(model_alias or "").strip() or infer_model_alias_from_path(path_value)
    apply_llm_runtime_overrides(
        enabled=True,
        provider="llama_cpp",
        model_path=path_value,
        model_alias=alias_value,
        n_ctx=n_ctx,
        n_batch=n_batch,
    )

def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value).strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "gridsenpai_project"


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _format_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple, set)):
        items = [_format_scalar(item) for item in value]
        return ", ".join(item for item in items if item)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            formatted = _format_scalar(item)
            if formatted:
                parts.append(f"{key}: {formatted}")
        return "; ".join(parts)
    return str(value).strip()


def _humanize_token(value: str) -> str:
    return str(value).replace("_", " ").strip().title()


def build_default_input_dir() -> Path:
    return CONFIG.paths.sample_data_dir / "current_application"


def ensure_clean_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)
    return path


def stage_output_path(run_dir: Path, stage_name: str, substage_name: str | None = None) -> Path:
    if substage_name:
        return run_dir / "stages" / f"{stage_name}__{substage_name}.json"
    return run_dir / "stages" / f"{stage_name}.json"


def build_interview_session_path(project_root: Path, project_name: str) -> Path:
    return project_root / "runs" / "interview_sessions" / f"{_slugify(project_name)}_interview_session.json"


def resolve_interview_session_path(
    *,
    project_root: Path,
    project_name: str,
    run_id: str | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Resolve the exact persisted interview session for a run.

    The applicant UI must write skip/answer state into the same session file
    produced by the interview service.  For unresolved project identity, the
    service keys sessions by source run id (for example
    ``UNRESOLVED_PROJECT::run_...``), while the desktop UI historically used
    the display project name.  Prefer the session_path embedded in the run's
    interview stage artifact, then fall back to a run-id scan, and only then
    use the legacy project-name path.
    """
    normalized_run_id = str(run_id or "").strip()
    if normalized_run_id and output_dir is not None:
        stage_payload = load_json(stage_output_path(Path(output_dir) / normalized_run_id, "gap_resolution", "interview"))
        session_candidate = str(stage_payload.get("session_path", "")).strip()
        if session_candidate:
            return Path(session_candidate)

    session_root = project_root / "runs" / "interview_sessions"
    if normalized_run_id and session_root.exists():
        for candidate in sorted(session_root.glob("*_interview_session.json")):
            payload = load_json(candidate)
            ui_state = payload.get("ui_state", {}) if isinstance(payload.get("ui_state"), dict) else {}
            project_id = str(payload.get("project_id", "")).strip()
            if (
                str(ui_state.get("run_id", "")).strip() == normalized_run_id
                or normalized_run_id in project_id
                or normalized_run_id in candidate.name
            ):
                return candidate

    return build_interview_session_path(project_root, project_name)


def reset_interview_session(project_root: Path, project_name: str) -> Path:
    session_path = build_interview_session_path(project_root, project_name)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.unlink(missing_ok=True)
    return session_path


def prepare_uploaded_files(destination_dir: Path, selected_files: Iterable[Path]) -> list[Path]:
    destination_dir = ensure_clean_directory(destination_dir)
    copied_paths: list[Path] = []
    for source in selected_files:
        source_path = Path(source)
        if not source_path.exists() or not source_path.is_file():
            continue
        target = destination_dir / source_path.name
        stem = source_path.stem
        suffix = source_path.suffix
        counter = 1
        while target.exists():
            target = destination_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        shutil.copy2(source_path, target)
        copied_paths.append(target)
    return copied_paths


def build_run_args(
    *,
    input_dir: Path,
    output_dir: Path,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    replay_run_id: str | None = None,
    replay_stage_boundary: str | None = None,
    log_level: str = "INFO",
) -> Namespace:
    return Namespace(
        input_dir=str(input_dir),
        output_dir=str(output_dir),
        run_id=run_id,
        parent_run_id=parent_run_id,
        replay_run_id=replay_run_id,
        replay_stage_boundary=replay_stage_boundary,
        diff_baseline_run_id=None,
        diff_candidate_run_id=None,
        log_level=log_level,
    )


def run_pipeline_for_ui(
    *,
    input_dir: Path,
    output_dir: Path,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    replay_run_id: str | None = None,
    replay_stage_boundary: str | None = None,
) -> dict[str, Any]:
    args = build_run_args(
        input_dir=input_dir,
        output_dir=output_dir,
        run_id=run_id,
        parent_run_id=parent_run_id,
        replay_run_id=replay_run_id,
        replay_stage_boundary=replay_stage_boundary,
    )
    return run_from_args(args)


def run_post_interview_pipeline_for_ui(
    *,
    input_dir: Path,
    output_dir: Path,
    source_run_id: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Continue after applicant interview by replaying through retrieval and rerunning interview/downstream stages.

    The initial run already completed ingestion, extraction, normalization, and retrieval before
    stopping for applicant input.  This continuation reuses those persisted outputs and reruns
    only the interview-dependent stages so skip, partial answers, and full answers do not trigger
    another expensive intake/extraction/OCR pass.
    """
    normalized_source_run_id = str(source_run_id or "").strip()
    if not normalized_source_run_id:
        raise ValueError("source_run_id is required for post-interview continuation.")

    return run_pipeline_for_ui(
        input_dir=input_dir,
        output_dir=output_dir,
        run_id=run_id,
        parent_run_id=normalized_source_run_id,
        replay_run_id=normalized_source_run_id,
        replay_stage_boundary=GAP_RESOLUTION_RETRIEVAL_STAGE,
    )


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_interview_stage_payload(run_dir: Path) -> dict[str, Any]:
    return load_json(stage_output_path(run_dir, "gap_resolution", "interview"))


def extract_interview_questions(run_dir: Path) -> list[dict[str, Any]]:
    payload = load_interview_stage_payload(run_dir)
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in questions:
        if isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def extract_interview_overview(run_dir: Path) -> dict[str, Any]:
    payload = load_interview_stage_payload(run_dir)
    oversight = _coerce_dict(payload.get("interview_oversight"))
    session_summary = _coerce_dict(payload.get("session_summary"))
    readiness = _coerce_dict(oversight.get("interview_readiness_summary"))

    question_count = len(extract_interview_questions(run_dir))
    planner_blocking = int(session_summary.get("planner_critical_blocking_question_count", 0) or 0)
    clarification_count = int(session_summary.get("high_value_clarification_question_count", 0) or 0)
    informational_count = int(session_summary.get("informational_question_count", 0) or 0)
    readiness_state = str(readiness.get("interview_readiness") or oversight.get("interview_readiness") or "UNKNOWN").strip() or "UNKNOWN"
    sufficiency = str(oversight.get("sufficiency_assessment", "UNKNOWN")).strip() or "UNKNOWN"
    rationale = str(oversight.get("rationale", "")).strip()
    review_notes = _coerce_str_list(oversight.get("review_notes", []))
    sequence = _coerce_str_list(oversight.get("question_sequence", []))

    initial_focus = int(oversight.get("initial_focus_question_count", planner_blocking + clarification_count) or 0)
    deferred_count = int(oversight.get("deferred_question_count", informational_count) or 0)
    status_line = (
        f"Agent-directed interview plan: {question_count} open question(s) | "
        f"ask first {initial_focus} | later {deferred_count}"
    )
    if readiness_state != "UNKNOWN" or sufficiency != "UNKNOWN":
        status_line += f" | readiness {readiness_state} | sufficiency {sufficiency}"

    details: list[str] = []
    if rationale:
        details.append(f"Rationale: {rationale}")
    if review_notes:
        details.append("Review notes: " + " ".join(review_notes[:2]))
    if sequence:
        details.append("Agent sequence: " + ", ".join(sequence[:6]))

    return {
        "question_count": question_count,
        "planner_critical_blocking_count": planner_blocking,
        "high_value_clarification_count": clarification_count,
        "informational_count": informational_count,
        "readiness": readiness_state,
        "sufficiency": sufficiency,
        "rationale": rationale,
        "review_notes": review_notes,
        "question_sequence": sequence,
        "status_line": status_line,
        "detail_text": "\n".join(details).strip(),
    }


def _build_question_from_payload(question_payload: dict[str, Any]) -> InterviewQuestion:
    metadata = question_payload.get("metadata", {})
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    return InterviewQuestion(
        question_id=str(question_payload.get("question_id", "")).strip(),
        field_path=str(question_payload.get("field_path", "")).strip(),
        prompt=str(question_payload.get("question") or question_payload.get("prompt") or "").strip(),
        answer_type=str(question_payload.get("answer_type", "string") or "string").strip(),
        required=bool(question_payload.get("required", True)),
        allowed_values=list(question_payload.get("allowed_values", []) or []),
        help_text=(str(question_payload.get("help_text", "")).strip() or None),
        clarification_prompt=(str(question_payload.get("clarification_prompt", "")).strip() or None),
        examples=[str(item) for item in (question_payload.get("examples", []) or []) if str(item).strip()],
        follow_up_on_missing=bool(question_payload.get("follow_up_on_missing", True)),
        reason=(str(question_payload.get("reason", "")).strip() or None),
        triggering_status=(str(question_payload.get("triggering_status", "")).strip() or None),
        question_category=(str(question_payload.get("question_category", "")).strip() or None),
        priority=int(question_payload.get("priority", 0) or 0),
        requires_confirmation=bool(question_payload.get("requires_confirmation", False)),
        related_artifact_ids=[str(item) for item in (question_payload.get("related_artifact_ids", []) or []) if str(item).strip()],
        metadata=metadata,
        agent_id=(str(question_payload.get("agent_id", "")).strip() or None),
        agent_status=(str(question_payload.get("agent_status", "")).strip() or None),
        agent_audit_path=(str(question_payload.get("agent_audit_path", "")).strip() or None),
    )


def build_question_display_context(question_payload: dict[str, Any]) -> dict[str, Any]:
    metadata = _coerce_dict(question_payload.get("metadata"))
    field_path = str(question_payload.get("field_path", "")).strip()
    label = field_label(field_path) if field_path else "Unknown field"
    packet_section = str(metadata.get("packet_section_label") or metadata.get("packet_section") or "").strip()
    triage_bucket = str(metadata.get("triage_bucket", "")).strip()
    planner_critical = bool(metadata.get("planner_critical", False))
    confidence_band = str(metadata.get("confidence_band", "")).strip()
    conflict_materiality = str(metadata.get("conflict_materiality", "")).strip()
    accepted_value = _format_scalar(metadata.get("accepted_value"))
    allowed_values = _coerce_str_list(question_payload.get("allowed_values", []))
    examples = _coerce_str_list(question_payload.get("examples", []))
    suggested_sources = _coerce_str_list(question_payload.get("suggested_sources", []))
    applicant_profile = _coerce_dict(metadata.get("applicant_question_profile"))
    conflict_profile = _coerce_dict(metadata.get("conflict_profile"))

    answer_type = str(question_payload.get("answer_type", "string")).strip() or "string"
    expected_format = {
        "number": "Enter a numeric engineering value.",
        "integer": "Enter a whole-number count.",
        "boolean": "Enter yes or no.",
        "enum": "Choose one of the allowed values.",
        "string": "Enter a concise structured text answer.",
    }.get(answer_type.lower(), "Enter a direct structured answer.")

    summary_bits = [f"Field: {label}"]
    if packet_section:
        summary_bits.append(f"Section: {packet_section}")
    if planner_critical:
        summary_bits.append("Planner-critical")
    if triage_bucket:
        summary_bits.append(f"Route: {_humanize_token(triage_bucket)}")

    question_text = str(question_payload.get("question") or question_payload.get("prompt") or "").strip()
    help_text = str(question_payload.get("help_text") or metadata.get("help_text") or "").strip()
    clarification_prompt = str(question_payload.get("clarification_prompt") or metadata.get("clarification_prompt") or "").strip()
    reason = str(question_payload.get("reason", "")).strip()

    prompt_lines: list[str] = []
    if question_text:
        prompt_lines.append(question_text)
    if help_text:
        prompt_lines.extend(["", help_text])
    if clarification_prompt:
        prompt_lines.extend(["", clarification_prompt])
    prompt_lines.extend(["", f"Expected answer format: {expected_format}"])
    if allowed_values:
        prompt_lines.append("Allowed values: " + ", ".join(allowed_values))
    if examples:
        prompt_lines.append("Examples: " + " | ".join(examples))

    context_lines: list[str] = []
    if reason:
        context_lines.append(f"Why GridSenpAI is asking: {reason}")
    elif conflict_materiality:
        context_lines.append(f"Why GridSenpAI is asking: this field still has a {_humanize_token(conflict_materiality).lower()} conflict to resolve.")
    elif accepted_value:
        context_lines.append("Why GridSenpAI is asking: the current field value still needs applicant confirmation.")
    if accepted_value:
        context_lines.append(f"Current best value on file: {accepted_value}")
    selection_rationale = _coerce_str_list(applicant_profile.get("selection_rationale", []))
    if selection_rationale:
        context_lines.append(selection_rationale[0])
    if suggested_sources:
        context_lines.append("Check if needed: " + ", ".join(suggested_sources[:2]))
    context_lines.append(
        "Your answer will be recorded as applicant confirmation and then checked against the governed evidence pipeline before final export."
    )

    agent_status = str(question_payload.get("agent_status", "")).strip() or "READY"
    agent_id = str(question_payload.get("agent_id", "")).strip() or "applicant_interview_agent"
    agent_line = f"Question owner: {agent_id} | status: {agent_status}"

    return {
        "field_label": label,
        "summary_line": " | ".join(summary_bits),
        "prompt_text": "\n".join(prompt_lines).strip(),
        "context_text": "\n".join(context_lines).strip() or "Answer the question using the applicant's direct knowledge or source documents.",
        "agent_line": agent_line,
        "field_path": field_path,
    }


def preview_interview_answer(question_payload: dict[str, Any], raw_answer: str) -> dict[str, Any]:
    question = _build_question_from_payload(question_payload)
    candidate, confirmed, clarification = process_raw_answer(
        question=question,
        raw_answer=str(raw_answer or ""),
        source_name="ui_preview",
    )
    if clarification is not None:
        return {
            "status": "CLARIFICATION_REQUIRED",
            "message": f"Clarification required: {clarification.clarification_prompt}",
            "normalized_value": "",
        }
    if confirmed is not None:
        normalized = _format_scalar(confirmed.confirmed_answer)
        return {
            "status": "CONFIRMED",
            "message": f"Structured preview accepted: {normalized}",
            "normalized_value": normalized,
        }
    if candidate is not None:
        normalized = _format_scalar(candidate.interpreted_candidate)
        return {
            "status": "NEEDS_CONFIRMATION",
            "message": f"Candidate preview: {normalized}",
            "normalized_value": normalized,
        }
    return {
        "status": "EMPTY",
        "message": "Enter an applicant response to preview how GridSenpAI will parse it.",
        "normalized_value": "",
    }




def normalize_question_ids(questions: list[dict[str, Any]]) -> list[str]:
    normalized: list[str] = []
    for payload in questions:
        if not isinstance(payload, dict):
            continue
        question_id = str(payload.get("question_id", "")).strip()
        if question_id:
            normalized.append(question_id)
    return normalized


def load_interview_ui_state(
    project_root: Path,
    project_name: str,
    run_id: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    payload = load_json(
        resolve_interview_session_path(
            project_root=project_root,
            project_name=project_name,
            run_id=run_id,
            output_dir=output_dir,
        )
    )
    ui_state = payload.get("ui_state", {})
    return dict(ui_state) if isinstance(ui_state, dict) else {}


def clear_interview_ui_state(
    project_root: Path,
    project_name: str,
    run_id: str | None = None,
    output_dir: Path | None = None,
) -> Path:
    session_path = resolve_interview_session_path(
        project_root=project_root,
        project_name=project_name,
        run_id=run_id,
        output_dir=output_dir,
    )
    payload = load_json(session_path)
    if not payload:
        return session_path
    payload.pop("ui_state", None)
    session_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return session_path


def mark_interview_ui_skipped(
    *,
    project_root: Path,
    project_name: str,
    run_id: str,
    questions: list[dict[str, Any]],
    answers_by_question_id: dict[str, str],
    current_question_index: int,
    decision_reason: str,
    output_dir: Path | None = None,
) -> Path:
    return save_interview_ui_state(
        project_root=project_root,
        project_name=project_name,
        run_id=run_id,
        questions=questions,
        answers_by_question_id=answers_by_question_id,
        current_question_index=current_question_index,
        status="SKIPPED_BY_USER",
        decision_reason=decision_reason,
        output_dir=output_dir,
    )


def save_interview_ui_state(
    *,
    project_root: Path,
    project_name: str,
    run_id: str,
    questions: list[dict[str, Any]],
    answers_by_question_id: dict[str, str],
    current_question_index: int,
    status: str = "IN_PROGRESS",
    decision_reason: str = "",
    output_dir: Path | None = None,
) -> Path:
    session_path = resolve_interview_session_path(
        project_root=project_root,
        project_name=project_name,
        run_id=run_id,
        output_dir=output_dir,
    )
    session_path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_json(session_path)
    payload["ui_state"] = {
        "run_id": str(run_id or "").strip(),
        "status": str(status or "IN_PROGRESS").strip() or "IN_PROGRESS",
        "decision_reason": str(decision_reason or "").strip(),
        "current_question_index": max(int(current_question_index or 0), 0),
        "question_ids": normalize_question_ids(questions),
        "answer_drafts": {
            str(key).strip(): str(value).strip()
            for key, value in dict(answers_by_question_id or {}).items()
            if str(key).strip() and str(value).strip()
        },
    }
    session_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return session_path


def load_pending_interview_resume_bundle(
    *,
    project_root: Path,
    project_name: str,
    output_dir: Path,
) -> dict[str, Any]:
    session_root = project_root / "runs" / "interview_sessions"
    candidate_paths: list[Path] = [
        resolve_interview_session_path(
            project_root=project_root,
            project_name=project_name,
            output_dir=output_dir,
        )
    ]
    if session_root.exists():
        candidate_paths.extend(sorted(session_root.glob("*_interview_session.json"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True))

    seen: set[str] = set()
    for session_path in candidate_paths:
        path_key = str(session_path)
        if path_key in seen:
            continue
        seen.add(path_key)
        payload = load_json(session_path)
        ui_state = payload.get("ui_state", {}) if isinstance(payload.get("ui_state"), dict) else {}
        run_id = str(ui_state.get("run_id", "")).strip()
        if str(ui_state.get("status", "")).strip().upper() == "SKIPPED_BY_USER":
            continue
        if not run_id:
            continue
        run_dir = output_dir / run_id
        if not run_dir.exists():
            continue
        questions = extract_interview_questions(run_dir)
        if not questions:
            continue
        pending_ids = normalize_question_ids(questions)
        stored_ids = [str(item).strip() for item in ui_state.get("question_ids", []) if str(item).strip()]
        if stored_ids and stored_ids != pending_ids:
            continue
        drafts = {
            str(key).strip(): str(value).strip()
            for key, value in dict(ui_state.get("answer_drafts", {})).items()
            if str(key).strip() and str(value).strip()
        }
        index = int(ui_state.get("current_question_index", 0) or 0)
        if pending_ids:
            index = max(0, min(index, len(pending_ids) - 1))
        return {
            "run_id": run_id,
            "run_dir": run_dir,
            "session_path": session_path,
            "questions": questions,
            "overview": extract_interview_overview(run_dir),
            "answer_drafts": drafts,
            "current_question_index": index,
        }

    return {}


def save_interview_answers(
    *,
    project_root: Path,
    project_name: str,
    questions: list[dict[str, Any]],
    answers_by_question_id: dict[str, str],
    run_id: str | None = None,
    output_dir: Path | None = None,
    source_name: str = "applicant_ui_response",
) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]]:
    session_path = resolve_interview_session_path(
        project_root=project_root,
        project_name=project_name,
        run_id=run_id,
        output_dir=output_dir,
    )
    session_path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_json(session_path)
    existing_answers = existing.get("answers_confirmed", [])
    if not isinstance(existing_answers, list):
        existing_answers = []
    existing_clarifications = existing.get("clarifications", [])
    if not isinstance(existing_clarifications, list):
        existing_clarifications = []

    confirmed_records: list[dict[str, Any]] = []
    clarification_records: list[dict[str, Any]] = []

    for payload in questions:
        question_id = str(payload.get("question_id", "")).strip()
        raw_answer = str(answers_by_question_id.get(question_id, "")).strip()
        if not question_id or not raw_answer:
            continue
        question = _build_question_from_payload(payload)
        _, confirmed, clarification = process_raw_answer(
            question=question,
            raw_answer=raw_answer,
            source_name=source_name,
        )
        if confirmed is not None:
            confirmed_records.append(confirmed.to_dict())
        if clarification is not None:
            clarification_records.append(clarification.to_dict())

    deduped_answers: dict[tuple[str, str], dict[str, Any]] = {}
    for item in existing_answers + confirmed_records:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("question_id", "")).strip(),
            str(item.get("field_path", "")).strip(),
        )
        if key == ("", ""):
            continue
        deduped_answers[key] = dict(item)

    deduped_clarifications: dict[tuple[str, str], dict[str, Any]] = {}
    for item in existing_clarifications + clarification_records:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("question_id", "")).strip(),
            str(item.get("field_path", "")).strip(),
        )
        if key == ("", ""):
            continue
        deduped_clarifications[key] = dict(item)

    payload = {
        "session_id": str(existing.get("session_id") or f"{_slugify(project_name)}_ui_session").strip(),
        "project_id": project_name,
        "session_path": str(session_path),
        "created_at": str(existing.get("created_at") or "").strip() or "",
        "updated_at": "",
        "status": "SUBMITTED_CONTINUE",
        "sources": [
            {
                "source_name": source_name,
                "source_path": str(session_path),
                "source_suffix": ".json",
            }
        ],
        "questions": questions,
        "answers_confirmed": list(deduped_answers.values()),
        "clarifications": list(deduped_clarifications.values()),
        "ui_state": {
            "status": "SUBMITTED_CONTINUE",
            "decision_reason": "User submitted available applicant answers and chose to continue the governed pipeline.",
            "run_id": str(existing.get("ui_state", {}) .get("run_id", "")).strip() if isinstance(existing.get("ui_state", {}), dict) else "",
            "question_ids": normalize_question_ids(questions),
            "answer_drafts": {},
            "current_question_index": 0,
        },
    }
    session_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return session_path, confirmed_records, clarification_records


def build_interview_review_rows(
    questions: list[dict[str, Any]],
    answers_by_question_id: dict[str, str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for payload in questions:
        question_id = str(payload.get("question_id", "")).strip()
        if not question_id:
            continue
        context = build_question_display_context(payload)
        raw_answer = str(answers_by_question_id.get(question_id, "")).strip()
        preview = preview_interview_answer(payload, raw_answer)
        rows.append(
            {
                "question_id": question_id,
                "field_label": str(context.get("field_label", "")).strip() or question_id,
                "question": str(payload.get("question") or payload.get("prompt") or "").strip(),
                "raw_answer": raw_answer,
                "parse_status": str(preview.get("status", "EMPTY")).strip() or "EMPTY",
                "parse_message": str(preview.get("message", "")).strip(),
                "normalized_value": str(preview.get("normalized_value", "")).strip(),
            }
        )
    return rows


def build_interview_review_text(
    questions: list[dict[str, Any]],
    answers_by_question_id: dict[str, str],
) -> str:
    rows = build_interview_review_rows(questions, answers_by_question_id)
    if not rows:
        return "No applicant answers are ready to review yet."

    lines = [
        "Review applicant responses before GridSenpAI continues.",
        "These answers will be recorded and then pushed back into the governed pipeline.",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(f"{index}. {row['field_label']}")
        if row["question"]:
            lines.append(f"   Question: {row['question']}")
        lines.append(f"   Answer: {row['raw_answer'] or '[no answer]'}")
        lines.append(f"   Parse check: {row['parse_message'] or row['parse_status']}")
        if row["normalized_value"]:
            lines.append(f"   Parsed value: {row['normalized_value']}")
        lines.append("")
    lines.append("Select Continue if everything looks right, or go back and edit any answer.")
    return "\n".join(lines).strip()


def build_run_completion_snapshot(run_dir: Path, pipeline_summary: dict[str, Any] | None = None) -> dict[str, str]:
    manifest = load_json(run_dir / "exports" / "run_manifest.json")

    summary = manifest.get("summary", {}) if isinstance(manifest.get("summary"), dict) else {}
    exports = manifest.get("exports", {}) if isinstance(manifest.get("exports"), dict) else {}

    release_state = str(summary.get("governed_release_state", "")).strip() or "UNKNOWN"
    packet_readiness = str(summary.get("planner_packet_readiness", "")).strip() or ("READY" if bool(summary.get("planner_packet_ready", False)) else "UNKNOWN")
    tldr_path = determine_tldr_path(run_dir)
    tldr_ready = "ready" if tldr_path is not None else "not generated"
    manual_review_total = int(summary.get("manual_review_queue_count", 0) or 0)
    planner_action_total = int(summary.get("planner_action_queue_count", 0) or 0)
    unresolved_count = int(summary.get("field_governance_registry_unresolved_field_count", 0) or 0)
    review_required_count = int(summary.get("planner_registry_review_required_count", 0) or 0)
    export_variants = summary.get("human_readable_packet_variants", []) if isinstance(summary.get("human_readable_packet_variants"), list) else []
    tldr_variants = summary.get("tldr_human_readable_variants", []) if isinstance(summary.get("tldr_human_readable_variants"), list) else []

    headline = (
        f"Run complete. Release state: {release_state}. "
        f"Packet readiness: {packet_readiness}."
    )
    lines = [
        f"TLDR summary: {tldr_ready}.",
        f"Unresolved governed fields: {unresolved_count}.",
        f"Planner review-required fields: {review_required_count}.",
        f"Manual review queue items: {manual_review_total}.",
        f"Planner action items: {planner_action_total}.",
    ]
    if export_variants:
        lines.append("Planner packet outputs: " + ", ".join(str(item) for item in export_variants if str(item).strip()))
    if tldr_variants:
        lines.append("TLDR outputs: " + ", ".join(str(item) for item in tldr_variants if str(item).strip()))
    if bool(summary.get("audit_artifacts_enabled", False)):
        lines.append("Audit artifacts: enabled (stored under exports/audit when generated).")
    if bool(summary.get("debug_artifacts_enabled", False)):
        lines.append("Debug artifacts: enabled (stored under exports/debug when generated).")
    if pipeline_summary:
        run_status = str(pipeline_summary.get("status", "")).strip()
        if run_status:
            lines.insert(0, f"Pipeline status: {run_status}.")
    interview_audit_path = determine_interview_audit_path(run_dir)
    lines.append("Interview audit trail: ready." if interview_audit_path is not None else "Interview audit trail: not generated.")
    lines.append("Use Open TLDR, Open exports folder, or Open latest manifest for the handoff artifacts. Open interview audit when available.")
    return {
        "headline": headline,
        "detail_text": "\n".join(lines).strip(),
    }

def determine_tldr_path(run_dir: Path) -> Path | None:
    run_manifest = load_json(run_dir / "exports" / "run_manifest.json")
    exports = run_manifest.get("exports", {}) if isinstance(run_manifest.get("exports"), dict) else {}
    for key in ("planner_tldr_markdown", "planner_tldr_docx"):
        candidate = str(exports.get(key, "")).strip()
        if candidate:
            path = Path(candidate)
            if path.exists():
                return path
    return None


def determine_export_manifest_path(run_dir: Path) -> Path:
    return run_dir / "exports" / "run_manifest.json"


def determine_interview_audit_path(run_dir: Path) -> Path | None:
    run_manifest = load_json(run_dir / "exports" / "run_manifest.json")
    exports = run_manifest.get("exports", {}) if isinstance(run_manifest.get("exports"), dict) else {}
    for key in ("interview_audit_trail_markdown", "interview_audit_trail_json"):
        candidate = str(exports.get(key, "")).strip()
        if candidate:
            path = Path(candidate)
            if path.exists():
                return path
    return None


def open_path_on_host(path: Path) -> bool:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True

        import subprocess

        if sys.platform == "darwin":  # pragma: no cover - non-Windows convenience
            subprocess.Popen(["open", str(path)])
            return True

        subprocess.Popen(["xdg-open", str(path)])  # pragma: no cover - non-Windows convenience
        return True
    except Exception:
        return False


import sys
