from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_run_id(context: Any) -> str:
    run_id = getattr(context, "run_id", None)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("context.run_id must be a non-empty string.")
    return run_id.strip()


def _require_run_dir(context: Any) -> Path:
    run_dir = getattr(context, "run_dir", None)
    if run_dir is None:
        raise ValueError("context.run_dir is required.")
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


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


class AuditLoggingManager:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.run_id = _require_run_id(context)
        self.run_dir = _require_run_dir(context)
        self.audit_dir = self.run_dir / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log_path = self.audit_dir / "audit_log.jsonl"

    def _append(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "run_id": self.run_id,
            "recorded_at": utc_now_iso(),
            **_json_safe(payload),
        }

        with self.audit_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str))
            handle.write("\n")

        return event

    def log_event(
        self,
        *,
        event_type: str,
        stage_name: str | None = None,
        substage_name: str | None = None,
        status: str | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._append(
            {
                "event_type": event_type,
                "stage_name": stage_name,
                "substage_name": substage_name,
                "status": status,
                "message": message,
                "metadata": metadata or {},
            }
        )

    def log_pipeline_start(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.log_event(
            event_type="pipeline_start",
            status="STARTED",
            metadata=metadata or {},
        )

    def log_pipeline_complete(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.log_event(
            event_type="pipeline_complete",
            status="SUCCESS",
            metadata=metadata or {},
        )

    def log_pipeline_failure(
        self,
        *,
        error: str,
        traceback_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(metadata or {})
        payload["error"] = error
        payload["traceback"] = traceback_text
        return self.log_event(
            event_type="pipeline_failure",
            status="FAILED",
            metadata=payload,
        )

    def log_stage_start(
        self,
        *,
        stage_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.log_event(
            event_type="stage_start",
            stage_name=stage_name,
            status="STARTED",
            metadata=metadata or {},
        )

    def log_stage_complete(
        self,
        *,
        stage_name: str,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.log_event(
            event_type="stage_complete",
            stage_name=stage_name,
            status=status or "COMPLETED",
            metadata=metadata or {},
        )

    def log_stage_reused(
        self,
        *,
        stage_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.log_event(
            event_type="stage_reused",
            stage_name=stage_name,
            status="REUSED",
            metadata=metadata or {},
        )

    def log_stage_failure(
        self,
        *,
        stage_name: str,
        error: str,
        traceback_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(metadata or {})
        payload["error"] = error
        payload["traceback"] = traceback_text
        return self.log_event(
            event_type="stage_failure",
            stage_name=stage_name,
            status="FAILED",
            metadata=payload,
        )

    def log_substage_start(
        self,
        *,
        stage_name: str,
        substage_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.log_event(
            event_type="substage_start",
            stage_name=stage_name,
            substage_name=substage_name,
            status="STARTED",
            metadata=metadata or {},
        )

    def log_substage_complete(
        self,
        *,
        stage_name: str,
        substage_name: str,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.log_event(
            event_type="substage_complete",
            stage_name=stage_name,
            substage_name=substage_name,
            status=status or "COMPLETED",
            metadata=metadata or {},
        )

    def log_substage_failure(
        self,
        *,
        stage_name: str,
        substage_name: str,
        error: str,
        traceback_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(metadata or {})
        payload["error"] = error
        payload["traceback"] = traceback_text
        return self.log_event(
            event_type="substage_failure",
            stage_name=stage_name,
            substage_name=substage_name,
            status="FAILED",
            metadata=payload,
        )


def initialize_audit_logger(context: Any) -> AuditLoggingManager:
    return AuditLoggingManager(context)