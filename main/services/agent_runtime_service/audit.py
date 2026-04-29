from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_models.models import AgentAuditRecord, AgentDecision, AgentPolicyDecision, AgentRequest


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(_json_safe(payload), file, indent=2, ensure_ascii=False, default=str)


def write_agent_audit(
    *,
    run_id: str,
    run_dir: Path | None,
    request: AgentRequest,
    policy: AgentPolicyDecision,
    prompt_payload: dict[str, Any],
    prompt_input_preview: dict[str, Any],
    decision: AgentDecision,
) -> str:
    if run_dir is None:
        return ""

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    audit_file_path = run_dir / "agent_audit" / f"{request.agent_id}_{request.task_name}_{timestamp}.json"
    runtime_payload = decision.runtime_payload if isinstance(decision.runtime_payload, dict) else {}
    structured_output = decision.structured_output if isinstance(decision.structured_output, dict) else {}
    prompt_telemetry = prompt_payload.get("prompt_telemetry") if isinstance(prompt_payload.get("prompt_telemetry"), dict) else {}
    chunking = structured_output.get("agent_chunking") if isinstance(structured_output.get("agent_chunking"), dict) else {}
    if not chunking and isinstance(runtime_payload, dict):
        chunking = {
            "chunking_enabled": bool(runtime_payload.get("chunking_enabled", False)),
            "chunk_count": int(runtime_payload.get("chunk_count", 0) or 0),
            "failed_chunk_count": int(runtime_payload.get("failed_chunk_count", 0) or 0),
            "largest_chunk_chars": int(runtime_payload.get("largest_chunk_chars", 0) or 0),
            "policy_blocked_chunks": int(runtime_payload.get("policy_blocked_chunks", 0) or 0),
        }
    agent_prompt_health = {
        "requested_agent_id": request.agent_id,
        "agent_family_id": getattr(decision, "agent_family_id", ""),
        "provider_mode": decision.provider_mode,
        "chunking_enabled": bool(chunking.get("chunking_enabled", False)),
        "chunk_count": int(chunking.get("chunk_count", 0) or 0),
        "failed_chunk_count": int(chunking.get("failed_chunk_count", 0) or 0),
        "policy_blocked_chunks": int(chunking.get("policy_blocked_chunks", 0) or 0),
        "largest_chunk_chars": int(chunking.get("largest_chunk_chars", 0) or 0),
        "max_prompt_chars": int(prompt_telemetry.get("max_prompt_chars", 0) or 0),
        "total_input_chars_before_compaction": int(prompt_telemetry.get("total_input_chars_before_compaction", 0) or 0),
        "total_prompt_chars_after_compaction": int(prompt_telemetry.get("total_prompt_chars_after_compaction", 0) or 0),
        "fallback_used": bool(getattr(decision, "used_fallback", False)),
        "deterministic_output_continued": True,
    }

    audit_record = AgentAuditRecord(
        run_id=run_id,
        created_at=utc_now_iso(),
        agent_id=request.agent_id,
        stage_name=request.stage_name,
        task_name=request.task_name,
        status=decision.status,
        provider_mode=decision.provider_mode,
        policy=policy.to_dict(),
        request=request.to_dict(),
        prompt_payload=prompt_payload,
        response_payload={
            **decision.structured_output,
            "runtime_payload": decision.runtime_payload,
            "agent_prompt_health": agent_prompt_health,
        },
        trigger_reason=request.trigger_reason,
        associated_field_paths=list(request.associated_field_paths),
        evidence_anchors=list(request.evidence_anchors),
        prompt_input_preview=prompt_input_preview,
        blocked=not policy.allowed,
    )
    write_json(audit_file_path, audit_record.to_dict())
    return str(audit_file_path)
