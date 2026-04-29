from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class InterviewQuestion:
    question_id: str
    field_path: str
    prompt: str
    answer_type: str = "string"
    required: bool = True
    allowed_values: list[Any] = field(default_factory=list)
    help_text: str | None = None
    clarification_prompt: str | None = None
    examples: list[str] = field(default_factory=list)
    follow_up_on_missing: bool = True
    reason: str | None = None
    triggering_status: str | None = None
    question_category: str | None = None
    priority: int = 0
    requires_confirmation: bool = False
    related_artifact_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    agent_id: str | None = None
    agent_status: str | None = None
    agent_audit_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "field_path": self.field_path,
            "prompt": self.prompt,
            "answer_type": self.answer_type,
            "required": self.required,
            "allowed_values": list(self.allowed_values),
            "help_text": self.help_text,
            "clarification_prompt": self.clarification_prompt,
            "examples": list(self.examples),
            "follow_up_on_missing": self.follow_up_on_missing,
            "reason": self.reason,
            "triggering_status": self.triggering_status,
            "question_category": self.question_category,
            "priority": self.priority,
            "requires_confirmation": self.requires_confirmation,
            "related_artifact_ids": list(self.related_artifact_ids),
            "metadata": dict(self.metadata),
            "agent_id": self.agent_id,
            "agent_status": self.agent_status,
            "agent_audit_path": self.agent_audit_path,
        }


@dataclass(slots=True)
class InterviewAnswerCandidate:
    question_id: str
    field_path: str
    raw_answer: str
    interpreted_candidate: Any
    source_name: str
    captured_at: str = field(default_factory=utc_now_iso)
    candidate_status: str = "NEEDS_CONFIRMATION"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "field_path": self.field_path,
            "raw_answer": self.raw_answer,
            "interpreted_candidate": self.interpreted_candidate,
            "source_name": self.source_name,
            "captured_at": self.captured_at,
            "candidate_status": self.candidate_status,
        }


@dataclass(slots=True)
class ConfirmedInterviewAnswer:
    question_id: str
    field_path: str
    confirmed_answer: Any
    raw_answer: str
    source_name: str
    captured_at: str = field(default_factory=utc_now_iso)
    answer_status: str = "CONFIRMED"
    provenance_type: str = "engineer_response"
    confidence_tag: str = "HIGH"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "field_path": self.field_path,
            "confirmed_answer": self.confirmed_answer,
            "raw_answer": self.raw_answer,
            "source_name": self.source_name,
            "captured_at": self.captured_at,
            "answer_status": self.answer_status,
            "provenance_type": self.provenance_type,
            "confidence_tag": self.confidence_tag,
        }


@dataclass(slots=True)
class InterviewClarification:
    question_id: str
    field_path: str
    raw_answer: str
    clarification_prompt: str
    reason: str
    created_at: str = field(default_factory=utc_now_iso)
    status: str = "OPEN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "field_path": self.field_path,
            "raw_answer": self.raw_answer,
            "clarification_prompt": self.clarification_prompt,
            "reason": self.reason,
            "created_at": self.created_at,
            "status": self.status,
        }


@dataclass(slots=True)
class FinalInterviewPlan:
    recommended_missing_fields: list[str] = field(default_factory=list)
    recommended_confirmations: list[str] = field(default_factory=list)
    question_sequence: list[str] = field(default_factory=list)
    sufficiency_assessment: str = "UNKNOWN"
    interview_readiness: str = "NOT_READY"
    should_finalize_interview: bool = False
    rationale: str = ""
    confidence: str = "LOW"

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_missing_fields": list(self.recommended_missing_fields),
            "recommended_confirmations": list(self.recommended_confirmations),
            "question_sequence": list(self.question_sequence),
            "sufficiency_assessment": self.sufficiency_assessment,
            "interview_readiness": self.interview_readiness,
            "should_finalize_interview": self.should_finalize_interview,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


@dataclass(slots=True)
class InterviewFallbackResult:
    unresolved_fields: list[str]
    questions: list[InterviewQuestion]


@dataclass(slots=True)
class IntakeResolutionInput:
    artifacts: list[dict[str, Any]]
    field_paths: list[str]
    canonical_state: dict[str, Any]
    context: Any | None = None


@dataclass(slots=True)
class IntakeResolutionResult:
    canonical_state: dict[str, Any]
    unresolved_fields: list[str]
    interview_questions: list[InterviewQuestion]
    ready_for_interview: bool


@dataclass(slots=True)
class Phase3IntakeOrchestrationInput:
    artifacts: list[dict[str, Any]]
    field_paths: list[str]
    canonical_state: dict[str, Any]
    context: Any | None = None


@dataclass(slots=True)
class Phase3IntakeOrchestrationResult:
    canonical_state: dict[str, Any]
    unresolved_fields: list[str]
    interview_questions: list[InterviewQuestion]
    ready_for_interview: bool
    llm_task_policy: dict[str, str]
    resolved_entities: list[Any]


@dataclass(slots=True)
class Phase3ExecutionBridgeInput:
    artifacts: list[dict[str, Any]]
    requested_field_paths: list[str]
    canonical_state: dict[str, Any]
    context: Any | None = None


@dataclass(slots=True)
class Phase3ExecutionBridgeResult:
    canonical_state: dict[str, Any]
    unresolved_fields: list[str]
    interview_questions: list[dict[str, Any]]
    ready_for_interview: bool
    llm_task_policy: dict[str, str]
    resolved_entities: list[dict[str, Any]]
