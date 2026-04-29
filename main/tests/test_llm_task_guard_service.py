from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from services.agent_models.models import AgentRequest
from services.agent_policy_service.service import evaluate_agent_request_policy


@dataclass(slots=True)
class _TestContext:
    run_id: str = "agent_policy_test"
    run_dir: Path = Path("/tmp/agent_policy_test")


def test_agent_policy_allows_bounded_translation_support_requests() -> None:
    decision = evaluate_agent_request_policy(
        context=_TestContext(),
        request=AgentRequest(
            agent_id="translation_support_agent",
            stage_name="translation",
            task_name="parameter_review",
            inputs={"output_parameters": []},
            requested_capabilities=["structured_candidate_fields", "confidence"],
        ),
    )

    assert decision.allowed is True
    assert decision.status == "ALLOWED"
    assert decision.blocked_requested_capabilities == []


def test_agent_policy_blocks_disallowed_override_capabilities() -> None:
    decision = evaluate_agent_request_policy(
        context=_TestContext(),
        request=AgentRequest(
            agent_id="translation_support_agent",
            stage_name="translation",
            task_name="parameter_review",
            inputs={"output_parameters": []},
            requested_capabilities=["deterministic_override"],
        ),
    )

    assert decision.allowed is False
    assert decision.status == "POLICY_BLOCKED"
    assert "deterministic_override" in decision.blocked_requested_capabilities
