from __future__ import annotations

import json
from typing import Any

from services.agent_models.models import AgentPolicyDecision, AgentRequest
from services.agent_policy_service.matrix import (
    KNOWN_REQUEST_CAPABILITIES,
    allowed_capabilities_for,
    infer_requested_capabilities,
)
from services.agent_registry_service.service import get_agent_definition
from shared.runtime_stage_contract import stage_name_aliases


AGENT_POLICY_LIST_CAPS = {
    "output_parameters": 40,
    "assumptions": 25,
    "validation_report": 80,
    "backlog": 25,
    "backlog_preview": 25,
    "manual_review_queue": 50,
    "planner_action_queue": 50,
    "planner_packet_excerpt": 1,
    "evidence": 20,
    "candidates": 20,
    "schema_field_candidates": 50,
}


def _truncate_text(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else value[: max(0, max_chars - 3)] + "..."


def _compact_for_policy(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 7:
        return "[truncated:max_depth]"
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_key_str = str(child_key)
            if child_key_str in {"raw_text", "full_text", "page_text", "ocr_text", "canonical_state"}:
                compacted[child_key_str] = _truncate_text(str(child_value), 1200)
                continue
            compacted[child_key_str] = _compact_for_policy(child_value, key=child_key_str, depth=depth + 1)
        return compacted
    if isinstance(value, list):
        cap = AGENT_POLICY_LIST_CAPS.get(key, 60 if depth >= 3 else len(value))
        retained = [_compact_for_policy(item, key=key, depth=depth + 1) for item in value[:cap]]
        if len(value) > cap:
            retained.append({"_truncated": True, "original_count": len(value), "retained_count": cap})
        return retained
    if isinstance(value, str):
        return _truncate_text(value, 1600 if key in {"text", "content", "prompt", "response", "planner_packet_excerpt"} else 4000)
    return value


BLOCKED_CAPABILITIES: list[str] = [
    "canonical_state_write",
    "deterministic_override",
    "conflict_resolution",
    "validated_field_override",
]


class AgentPolicyEvaluator:
    def evaluate(
        self,
        *,
        agent_id: str,
        stage_name: str,
        task_name: str,
        context: Any,
        request: AgentRequest | None = None,
    ) -> AgentPolicyDecision:
        del context
        agent = get_agent_definition(agent_id)
        prompt_size_chars = self._estimate_prompt_size(request)
        blocked_output_fields = self._blocked_output_fields(agent, request)
        requested_capabilities = infer_requested_capabilities(request or AgentRequest(agent_id=agent_id, stage_name=stage_name, task_name=task_name))
        blocked_requested_capabilities = self._blocked_requested_capabilities(agent, requested_capabilities)

        candidate_stage_names = stage_name_aliases(stage_name)

        if agent.allowed_stages and not any(candidate in agent.allowed_stages for candidate in candidate_stage_names):
            return self._build_decision(
                allowed=False,
                status="POLICY_BLOCKED",
                reason=f"Stage '{stage_name}' is not allowed for agent '{agent_id}'.",
                agent_id=agent_id,
                stage_name=stage_name,
                task_name=task_name,
                prompt_size_chars=prompt_size_chars,
                blocked_output_fields=blocked_output_fields,
                requested_capabilities=requested_capabilities,
                blocked_requested_capabilities=blocked_requested_capabilities,
            )

        if agent.allowed_task_types and task_name not in agent.allowed_task_types:
            return self._build_decision(
                allowed=False,
                status="POLICY_BLOCKED",
                reason=f"Task type '{task_name}' is not registered for agent '{agent_id}'.",
                agent_id=agent_id,
                stage_name=stage_name,
                task_name=task_name,
                prompt_size_chars=prompt_size_chars,
                blocked_output_fields=blocked_output_fields,
                requested_capabilities=requested_capabilities,
                blocked_requested_capabilities=blocked_requested_capabilities,
            )

        if not agent.supports(stage_name, task_name):
            return self._build_decision(
                allowed=False,
                status="POLICY_BLOCKED",
                reason=(
                    f"Task '{task_name}' is not allowed for stage '{stage_name}' "
                    f"under agent '{agent_id}'."
                ),
                agent_id=agent_id,
                stage_name=stage_name,
                task_name=task_name,
                prompt_size_chars=prompt_size_chars,
                blocked_output_fields=blocked_output_fields,
                requested_capabilities=requested_capabilities,
                blocked_requested_capabilities=blocked_requested_capabilities,
            )

        if blocked_requested_capabilities:
            return self._build_decision(
                allowed=False,
                status="POLICY_BLOCKED",
                reason=(
                    "The request asked for capabilities that this agent is not allowed to perform: "
                    + ", ".join(blocked_requested_capabilities)
                ),
                agent_id=agent_id,
                stage_name=stage_name,
                task_name=task_name,
                prompt_size_chars=prompt_size_chars,
                blocked_output_fields=blocked_output_fields,
                requested_capabilities=requested_capabilities,
                blocked_requested_capabilities=blocked_requested_capabilities,
            )

        if blocked_output_fields:
            return self._build_decision(
                allowed=False,
                status="POLICY_BLOCKED",
                reason=(
                    "The request asked for output fields that are blocked or outside the agent contract: "
                    + ", ".join(blocked_output_fields)
                ),
                agent_id=agent_id,
                stage_name=stage_name,
                task_name=task_name,
                prompt_size_chars=prompt_size_chars,
                blocked_output_fields=blocked_output_fields,
                requested_capabilities=requested_capabilities,
                blocked_requested_capabilities=blocked_requested_capabilities,
            )

        if prompt_size_chars > agent.max_prompt_chars:
            return self._build_decision(
                allowed=False,
                status="PROMPT_TOO_LARGE",
                reason=(
                    f"Prompt payload size {prompt_size_chars} exceeds the max allowed "
                    f"{agent.max_prompt_chars} chars for agent '{agent_id}'."
                ),
                agent_id=agent_id,
                stage_name=stage_name,
                task_name=task_name,
                prompt_size_chars=prompt_size_chars,
                blocked_output_fields=blocked_output_fields,
                requested_capabilities=requested_capabilities,
                blocked_requested_capabilities=blocked_requested_capabilities,
            )

        return self._build_decision(
            allowed=True,
            status="ALLOWED",
            reason="Agent request is allowed under bounded-assist policy.",
            agent_id=agent_id,
            stage_name=stage_name,
            task_name=task_name,
            prompt_size_chars=prompt_size_chars,
            blocked_output_fields=blocked_output_fields,
            requested_capabilities=requested_capabilities,
            blocked_requested_capabilities=blocked_requested_capabilities,
        )

    def _estimate_prompt_size(self, request: AgentRequest | None) -> int:
        if request is None:
            return 0
        payload = {
            "inputs": _compact_for_policy(request.inputs),
            "metadata": _compact_for_policy(request.metadata),
            "associated_field_paths": request.associated_field_paths,
            "evidence_anchors": _compact_for_policy(request.evidence_anchors, key="evidence_anchors"),
            "suggested_output_fields": request.suggested_output_fields,
            "requested_capabilities": request.requested_capabilities,
            "trigger_reason": request.trigger_reason,
        }
        return len(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str))

    def _blocked_output_fields(self, agent: Any, request: AgentRequest | None) -> list[str]:
        if request is None:
            return []
        allowed = set(agent.structured_candidate_fields_allowed)
        forbidden = set(agent.forbidden_fields)
        blocked: list[str] = []
        for field_name in request.suggested_output_fields:
            candidate = str(field_name).strip()
            if not candidate:
                continue
            if candidate in forbidden or (allowed and candidate not in allowed):
                blocked.append(candidate)
        return sorted(set(blocked))

    def _blocked_requested_capabilities(self, agent: Any, requested_capabilities: list[str]) -> list[str]:
        allowed = allowed_capabilities_for(agent)
        blocked: list[str] = []
        for capability in requested_capabilities:
            normalized = str(capability).strip().lower()
            if not normalized:
                continue
            if normalized not in KNOWN_REQUEST_CAPABILITIES:
                blocked.append(normalized)
                continue
            if normalized not in allowed:
                blocked.append(normalized)
        return sorted(set(blocked))

    def _build_decision(
        self,
        *,
        allowed: bool,
        status: str,
        reason: str,
        agent_id: str,
        stage_name: str,
        task_name: str,
        prompt_size_chars: int,
        blocked_output_fields: list[str],
        requested_capabilities: list[str],
        blocked_requested_capabilities: list[str],
    ) -> AgentPolicyDecision:
        agent = get_agent_definition(agent_id)
        return AgentPolicyDecision(
            allowed=allowed,
            status=status,
            reason=reason,
            agent_id=agent_id,
            stage_name=stage_name,
            task_name=task_name,
            provider_mode=agent.provider_mode,
            max_prompt_chars=agent.max_prompt_chars,
            max_response_chars=agent.max_response_chars,
            advisory_text_only=agent.advisory_text_only,
            structured_candidate_fields_allowed=sorted(list(agent.structured_candidate_fields_allowed)),
            may_suggest_followup_questions=agent.may_suggest_followup_questions,
            may_rank_candidates=agent.may_rank_candidates,
            may_propose_retrieval_queries=agent.may_propose_retrieval_queries,
            blocked_capabilities=list(BLOCKED_CAPABILITIES),
            blocked_output_fields=blocked_output_fields,
            prompt_size_chars=prompt_size_chars,
            response_size_limit_chars=agent.max_response_chars,
            requested_capabilities=requested_capabilities,
            blocked_requested_capabilities=blocked_requested_capabilities,
        )


_POLICY_EVALUATOR = AgentPolicyEvaluator()


def evaluate_agent_policy(
    *,
    agent_id: str,
    stage_name: str,
    task_name: str,
    context: Any,
) -> AgentPolicyDecision:
    return _POLICY_EVALUATOR.evaluate(
        agent_id=agent_id,
        stage_name=stage_name,
        task_name=task_name,
        context=context,
        request=None,
    )


def evaluate_agent_request_policy(
    *,
    context: Any,
    request: AgentRequest,
) -> AgentPolicyDecision:
    return _POLICY_EVALUATOR.evaluate(
        agent_id=request.agent_id,
        stage_name=request.stage_name,
        task_name=request.task_name,
        context=context,
        request=request,
    )
