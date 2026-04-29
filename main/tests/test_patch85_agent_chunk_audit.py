import json
from pathlib import Path

from services.agent_models.models import AgentDecision, AgentPolicyDecision, AgentRequest
from services.agent_runtime_service.audit import write_agent_audit


class _Context:
    pass


def test_agent_audit_records_prompt_health_and_chunk_telemetry(tmp_path: Path) -> None:
    request = AgentRequest(
        agent_id="translation_support_agent",
        stage_name="translation",
        task_name="parameter_review",
    )
    policy = AgentPolicyDecision(
        allowed=True,
        status="ALLOWED",
        reason="ok",
        agent_id="planner_support_agent",
        stage_name="translation",
        task_name="parameter_review",
        max_prompt_chars=24000,
    )
    decision = AgentDecision(
        run_id="run_audit_test",
        agent_id="translation_support_agent",
        stage_name="translation",
        task_name="parameter_review",
        status="COMPLETED",
        provider_mode="llama_cpp_local",
        agent_family_id="planner_support_agent",
        requested_agent_id="translation_support_agent",
        structured_output={"agent_chunking": {"chunking_enabled": True, "chunk_count": 3, "failed_chunk_count": 1, "largest_chunk_chars": 9000}},
        runtime_payload={"chunking_enabled": True, "chunk_count": 3, "failed_chunk_count": 1},
    )
    audit_path = write_agent_audit(
        run_id="run_audit_test",
        run_dir=tmp_path,
        request=request,
        policy=policy,
        prompt_payload={"prompt_telemetry": {"max_prompt_chars": 24000, "total_input_chars_before_compaction": 2000000, "total_prompt_chars_after_compaction": 18000}},
        prompt_input_preview={},
        decision=decision,
    )
    payload = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    health = payload["response_payload"]["agent_prompt_health"]
    assert health["requested_agent_id"] == "translation_support_agent"
    assert health["agent_family_id"] == "planner_support_agent"
    assert health["chunking_enabled"] is True
    assert health["chunk_count"] == 3
    assert health["failed_chunk_count"] == 1
    assert health["total_input_chars_before_compaction"] == 2000000
