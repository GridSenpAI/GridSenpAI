from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    field_path: str = ""
    source_stage: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "field_path": self.field_path,
            "source_stage": self.source_stage,
            "recommendation": self.recommendation,
        }


@dataclass(slots=True)
class ValidationReport:
    status: str
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    info: list[ValidationIssue] = field(default_factory=list)
    missing_fields: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    engineering_validation: dict[str, Any] = field(default_factory=dict)
    calibration_summary: dict[str, Any] = field(default_factory=dict)
    interview_readiness: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "info": [issue.to_dict() for issue in self.info],
            "missing_fields": list(self.missing_fields),
            "conflicts": list(self.conflicts),
            "summary": dict(self.summary),
            "engineering_validation": dict(self.engineering_validation),
            "calibration_summary": dict(self.calibration_summary),
            "interview_readiness": dict(self.interview_readiness),
        }


@dataclass(slots=True)
class ValidationServiceResult:
    run_id: str
    status: str
    validation_report: ValidationReport
    canonical_state: dict[str, Any]
    validated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "validation_report": self.validation_report.to_dict(),
            "canonical_state": dict(self.canonical_state),
            "validated_at": self.validated_at,
        }