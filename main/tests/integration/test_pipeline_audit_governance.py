from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from services.audit_logging_service.service import initialize_audit_logger
from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent


@dataclass(slots=True)
class _Config:
    schema_version_output: str = "1.0.0"


@dataclass(slots=True)
class _Context:
    run_id: str
    run_dir: Path
    config: _Config = field(default_factory=_Config)



def test_agent_runtime_and_audit_logger_write_governance_artifacts(tmp_path: Path) -> None:
    context = _Context(run_id="governance_001", run_dir=tmp_path / "governance_001")
    logger = initialize_audit_logger(context)
    logger.log_pipeline_start(metadata={"execution_mode": "STANDARD"})

    result = run_agent(
        context=context,
        request=AgentRequest(
            agent_id="retrieval_planning_agent",
            stage_name="retrieval",
            task_name="query_review",
            inputs={
                "queries": ["UPS topology"],
                "snippets": [],
                "warnings": ["no vendor snippets found"],
                "validation_report": {"missing_fields": ["facility.ups.topology"]},
            },
        ),
    )

    logger.log_stage_complete(
        stage_name="retrieval",
        metadata={"agent_status": result["status"], "agent_id": result["agent_id"]},
    )
    logger.log_pipeline_complete(metadata={"final_status": "SUCCESS"})

    audit_lines = logger.audit_log_path.read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 3
    assert result["audit_path"]
    assert Path(result["audit_path"]).exists()
