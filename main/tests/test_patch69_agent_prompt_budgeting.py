from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config import CONFIG
from services.agent_policy_service.service import evaluate_agent_request_policy
from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent


@dataclass(slots=True)
class _TestConfig:
    schema_version_output: str = "1.0.0"


@dataclass(slots=True)
class _TestContext:
    run_id: str
    run_dir: Path
    config: _TestConfig = field(default_factory=_TestConfig)


def test_policy_estimate_uses_compacted_payload_for_large_artifacts(tmp_path: Path) -> None:
    context = _TestContext(run_id="agent_budget_policy", run_dir=tmp_path / "agent_budget_policy")
    request = AgentRequest(
        agent_id="translation_support_agent",
        stage_name="translation",
        task_name="parameter_review",
        inputs={
            "output_parameters": [
                {"parameter_path": f"p{i}", "confidence_tag": "LOW"} for i in range(200)
            ],
            "canonical_state": "x" * 2_000_000,
        },
    )
    policy = evaluate_agent_request_policy(context=context, request=request)
    assert policy.status == "ALLOWED"
    assert policy.prompt_size_chars < policy.max_prompt_chars


def test_runtime_skips_oversized_llm_prompt_but_uses_deterministic_fallback(tmp_path: Path) -> None:
    original_model_flag = CONFIG.model.allow_model_assistance
    original_llm_flag = CONFIG.llm_runtime.enabled
    original_model_path = CONFIG.llm_runtime.model_path
    CONFIG.model.allow_model_assistance = True
    CONFIG.llm_runtime.enabled = True
    CONFIG.llm_runtime.model_path = "fake-model.gguf"
    try:
        context = _TestContext(run_id="agent_budget_runtime", run_dir=tmp_path / "agent_budget_runtime")
        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="packet_review_agent",
                stage_name="export",
                task_name="planner_packet_review",
                inputs={
                    "planner_packet_excerpt": "packet " * 100000,
                    "field_resolution_summary": {"planner_review_count": 1},
                },
            ),
        )
        assert result["status"] == "COMPLETED"
        assert result["policy"]["allowed"] is True
        assert result["structured_output"]["deterministic_override_allowed"] is False
        assert result["runtime_payload"].get("status") in {"SKIPPED_PROMPT_BUDGET_EXCEEDED", "error"}
    finally:
        CONFIG.model.allow_model_assistance = original_model_flag
        CONFIG.llm_runtime.enabled = original_llm_flag
        CONFIG.llm_runtime.model_path = original_model_path
