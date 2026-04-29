from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from services.audit_logging_service.service import AuditLoggingManager, initialize_audit_logger


@dataclass(slots=True)
class _Context:
    run_id: str
    run_dir: Path


@dataclass(slots=True)
class _MissingRunDirContext:
    run_id: str


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_initialize_audit_logger_requires_non_empty_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        initialize_audit_logger(_Context(run_id="", run_dir=tmp_path / "run"))



def test_initialize_audit_logger_requires_run_dir() -> None:
    with pytest.raises(ValueError, match="run_dir"):
        AuditLoggingManager(_MissingRunDirContext(run_id="run_001"))



def test_audit_logger_writes_jsonl_events_with_json_safe_metadata(tmp_path: Path) -> None:
    context = _Context(run_id="run_audit_001", run_dir=tmp_path / "run_audit_001")
    logger = initialize_audit_logger(context)

    event = logger.log_stage_start(
        stage_name="retrieval",
        metadata={
            "artifact_path": context.run_dir / "artifact.pdf",
            "tuple_value": ("alpha", 2),
        },
    )

    assert event["run_id"] == "run_audit_001"
    assert event["event_type"] == "stage_start"
    assert event["status"] == "STARTED"

    payloads = _read_jsonl(logger.audit_log_path)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["run_id"] == "run_audit_001"
    assert payload["stage_name"] == "retrieval"
    assert payload["metadata"]["artifact_path"].endswith("artifact.pdf")
    assert payload["metadata"]["tuple_value"] == ["alpha", 2]
    assert payload["recorded_at"]



def test_audit_logger_records_pipeline_and_stage_failures(tmp_path: Path) -> None:
    context = _Context(run_id="run_audit_002", run_dir=tmp_path / "run_audit_002")
    logger = initialize_audit_logger(context)

    logger.log_pipeline_start(metadata={"mode": "STANDARD"})
    logger.log_stage_failure(
        stage_name="validation",
        error="schema mismatch",
        traceback_text="Traceback: schema mismatch",
        metadata={"stage_attempt": 1},
    )
    logger.log_pipeline_failure(
        error="validation failed",
        traceback_text="Traceback: validation failed",
        metadata={"failed_stage": "validation"},
    )

    payloads = _read_jsonl(logger.audit_log_path)
    assert [item["event_type"] for item in payloads] == [
        "pipeline_start",
        "stage_failure",
        "pipeline_failure",
    ]
    assert payloads[1]["status"] == "FAILED"
    assert payloads[1]["metadata"]["error"] == "schema mismatch"
    assert payloads[1]["metadata"]["traceback"] == "Traceback: schema mismatch"
    assert payloads[2]["metadata"]["failed_stage"] == "validation"
