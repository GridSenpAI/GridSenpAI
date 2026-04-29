from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.runtime_stage_contract import stage_name_aliases


@dataclass(slots=True)
class AgentDefinition:
    agent_id: str
    display_name: str
    role_summary: str
    allowed_stage_tasks: dict[str, set[str]] = field(default_factory=dict)
    allowed_task_types: set[str] = field(default_factory=set)
    provider_mode: str = "bounded_local"
    max_prompt_chars: int = 4000
    max_response_chars: int = 2500
    forbidden_fields: set[str] = field(default_factory=set)
    advisory_text_only: bool = False
    structured_candidate_fields_allowed: set[str] = field(default_factory=set)
    may_suggest_followup_questions: bool = False
    may_rank_candidates: bool = False
    may_propose_retrieval_queries: bool = False
    may_emit_confidence: bool = True
    may_emit_rationale: bool = True
    allowed_stages: set[str] = field(default_factory=set)

    def supports(self, stage_name: str, task_name: str) -> bool:
        for candidate_stage_name in stage_name_aliases(stage_name):
            allowed = self.allowed_stage_tasks.get(candidate_stage_name, set())
            if task_name in allowed:
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "role_summary": self.role_summary,
            "allowed_stage_tasks": {
                stage_name: sorted(list(task_names))
                for stage_name, task_names in self.allowed_stage_tasks.items()
            },
            "allowed_task_types": sorted(list(self.allowed_task_types)),
            "provider_mode": self.provider_mode,
            "max_prompt_chars": self.max_prompt_chars,
            "max_response_chars": self.max_response_chars,
            "forbidden_fields": sorted(list(self.forbidden_fields)),
            "advisory_text_only": self.advisory_text_only,
            "structured_candidate_fields_allowed": sorted(list(self.structured_candidate_fields_allowed)),
            "may_suggest_followup_questions": self.may_suggest_followup_questions,
            "may_rank_candidates": self.may_rank_candidates,
            "may_propose_retrieval_queries": self.may_propose_retrieval_queries,
            "may_emit_confidence": self.may_emit_confidence,
            "may_emit_rationale": self.may_emit_rationale,
            "allowed_stages": sorted(list(self.allowed_stages)),
        }


@dataclass(slots=True)
class AgentRequest:
    agent_id: str
    stage_name: str
    task_name: str
    inputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    trigger_reason: str | None = None
    associated_field_paths: list[str] = field(default_factory=list)
    evidence_anchors: list[dict[str, Any]] = field(default_factory=list)
    suggested_output_fields: list[str] = field(default_factory=list)
    requested_capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "stage_name": self.stage_name,
            "task_name": self.task_name,
            "inputs": dict(self.inputs),
            "metadata": dict(self.metadata),
            "trigger_reason": self.trigger_reason,
            "associated_field_paths": list(self.associated_field_paths),
            "evidence_anchors": list(self.evidence_anchors),
            "suggested_output_fields": list(self.suggested_output_fields),
            "requested_capabilities": list(self.requested_capabilities),
        }


@dataclass(slots=True)
class AgentPolicyDecision:
    allowed: bool
    status: str
    reason: str
    agent_id: str
    stage_name: str
    task_name: str
    provider_mode: str = "bounded_local"
    max_prompt_chars: int = 4000
    max_response_chars: int = 2500
    advisory_text_only: bool = False
    structured_candidate_fields_allowed: list[str] = field(default_factory=list)
    may_suggest_followup_questions: bool = False
    may_rank_candidates: bool = False
    may_propose_retrieval_queries: bool = False
    blocked_capabilities: list[str] = field(default_factory=list)
    blocked_output_fields: list[str] = field(default_factory=list)
    prompt_size_chars: int = 0
    response_size_limit_chars: int = 2500
    requested_capabilities: list[str] = field(default_factory=list)
    blocked_requested_capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
            "agent_id": self.agent_id,
            "stage_name": self.stage_name,
            "task_name": self.task_name,
            "provider_mode": self.provider_mode,
            "max_prompt_chars": self.max_prompt_chars,
            "max_response_chars": self.max_response_chars,
            "advisory_text_only": self.advisory_text_only,
            "structured_candidate_fields_allowed": list(self.structured_candidate_fields_allowed),
            "may_suggest_followup_questions": self.may_suggest_followup_questions,
            "may_rank_candidates": self.may_rank_candidates,
            "may_propose_retrieval_queries": self.may_propose_retrieval_queries,
            "blocked_capabilities": list(self.blocked_capabilities),
            "blocked_output_fields": list(self.blocked_output_fields),
            "prompt_size_chars": self.prompt_size_chars,
            "response_size_limit_chars": self.response_size_limit_chars,
            "requested_capabilities": list(self.requested_capabilities),
            "blocked_requested_capabilities": list(self.blocked_requested_capabilities),
        }


@dataclass(slots=True)
class AgentDecision:
    run_id: str
    agent_id: str
    stage_name: str
    task_name: str
    status: str
    provider_mode: str
    agent_family_id: str = ""
    requested_agent_id: str = ""
    structured_output: dict[str, Any] = field(default_factory=dict)
    runtime_payload: dict[str, Any] = field(default_factory=dict)
    audit_path: str = ""
    used_runtime: bool = False
    used_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "agent_family_id": self.agent_family_id,
            "requested_agent_id": self.requested_agent_id,
            "stage_name": self.stage_name,
            "task_name": self.task_name,
            "status": self.status,
            "provider_mode": self.provider_mode,
            "structured_output": dict(self.structured_output),
            "runtime_payload": dict(self.runtime_payload),
            "audit_path": self.audit_path,
            "used_runtime": self.used_runtime,
            "used_fallback": self.used_fallback,
        }


@dataclass(slots=True)
class AgentAuditRecord:
    run_id: str
    created_at: str
    agent_id: str
    stage_name: str
    task_name: str
    status: str
    provider_mode: str
    policy: dict[str, Any]
    request: dict[str, Any] = field(default_factory=dict)
    prompt_payload: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] = field(default_factory=dict)
    trigger_reason: str | None = None
    associated_field_paths: list[str] = field(default_factory=list)
    evidence_anchors: list[dict[str, Any]] = field(default_factory=list)
    prompt_input_preview: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "agent_id": self.agent_id,
            "stage_name": self.stage_name,
            "task_name": self.task_name,
            "status": self.status,
            "provider_mode": self.provider_mode,
            "policy": dict(self.policy),
            "request": dict(self.request),
            "prompt_payload": dict(self.prompt_payload),
            "response_payload": dict(self.response_payload),
            "trigger_reason": self.trigger_reason,
            "associated_field_paths": list(self.associated_field_paths),
            "evidence_anchors": list(self.evidence_anchors),
            "prompt_input_preview": dict(self.prompt_input_preview),
            "blocked": self.blocked,
        }


@dataclass(slots=True)
class AgentResponse:
    run_id: str
    agent_id: str
    stage_name: str
    task_name: str
    status: str
    policy: dict[str, Any]
    audit_path: str
    agent_family_id: str = ""
    requested_agent_id: str = ""
    structured_output: dict[str, Any] = field(default_factory=dict)
    runtime_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "agent_family_id": self.agent_family_id,
            "requested_agent_id": self.requested_agent_id,
            "stage_name": self.stage_name,
            "task_name": self.task_name,
            "status": self.status,
            "policy": dict(self.policy),
            "audit_path": self.audit_path,
            "structured_output": dict(self.structured_output),
            "runtime_payload": dict(self.runtime_payload),
        }
