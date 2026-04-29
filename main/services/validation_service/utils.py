# services/validation_service/utils.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.validation_service.models import ValidationIssue


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_issue(payload: dict[str, Any] | ValidationIssue) -> ValidationIssue:
    if isinstance(payload, ValidationIssue):
        return payload

    if not isinstance(payload, dict):
        raise TypeError(f"validation issue payload must be dict, got {type(payload).__name__}.")

    return ValidationIssue(
        code=str(payload.get("code", "UNKNOWN")).strip() or "UNKNOWN",
        severity=str(payload.get("severity", "warning")).strip().lower() or "warning",
        message=str(payload.get("message", "")).strip(),
        field_path=str(payload.get("field_path", "")).strip(),
        source_stage=str(payload.get("source_stage", "")).strip(),
        recommendation=str(payload.get("recommendation", "")).strip(),
    )


def build_validation_summary(
    *,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
    info: list[ValidationIssue],
    missing_fields: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    field_records: list[dict[str, Any]] | None = None,
    reconciliation_records: list[dict[str, Any]] | None = None,
    engineering_validation: dict[str, Any] | None = None,
    calibration_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:

    field_records = field_records or []
    reconciliation_records = reconciliation_records or []
    engineering_validation = engineering_validation or {}
    calibration_summary = calibration_summary or {}

    primary_records = 0
    review_required_records = 0
    conflicting_records = 0
    superseded_records = 0
    calibrated_records = 0

    for record in field_records:
        if record.get("is_primary") is True:
            primary_records += 1

        review_status = str(record.get("review_status", "")).upper()
        if review_status == "REVIEW_REQUIRED":
            review_required_records += 1

        conflict_status = str(record.get("conflict_status", "")).upper()
        if conflict_status in {"CONFLICT", "CONFLICT_PRESENT"}:
            conflicting_records += 1

        validation_status = str(record.get("validation_status", "")).upper()
        if validation_status == "SUPERSEDED":
            superseded_records += 1

        if validation_status == "CALIBRATED":
            calibrated_records += 1

    engineering_errors = len(engineering_validation.get("errors", []))
    engineering_warnings = len(engineering_validation.get("warnings", []))
    engineering_review_flags = len(engineering_validation.get("review_flags", []))

    calibration_record_count = int(calibration_summary.get("calibration_record_count", 0) or 0)
    calibration_match_count = int(calibration_summary.get("calibrated_match_count", 0) or 0)
    calibration_review_required_count = int(calibration_summary.get("calibration_review_required_count", 0) or 0)
    calibration_conflict_count = int(calibration_summary.get("calibration_conflict_count", 0) or 0)

    blocked = (
        len(errors) > 0
        or engineering_errors > 0
        or calibration_conflict_count > 0
    )

    if blocked:
        model_readiness = "BLOCKED"
    elif (
        engineering_warnings > 0
        or engineering_review_flags > 0
        or review_required_records > 0
        or conflicting_records > 0
        or len(warnings) > 0
        or calibration_review_required_count > 0
    ):
        model_readiness = "REVIEW_REQUIRED"
    else:
        model_readiness = "READY"

    return {
        "error_count": len(errors),
        "warning_count": len(warnings),
        "info_count": len(info),

        "engineering_error_count": engineering_errors,
        "engineering_warning_count": engineering_warnings,
        "engineering_review_flag_count": engineering_review_flags,

        "calibration_record_count": calibration_record_count,
        "calibrated_match_count": calibration_match_count,
        "calibration_review_required_count": calibration_review_required_count,
        "calibration_conflict_count": calibration_conflict_count,

        "missing_field_count": len(missing_fields),
        "conflict_count": len(conflicts),

        "field_record_count": len(field_records),
        "primary_field_record_count": primary_records,
        "review_required_record_count": review_required_records,
        "conflicting_record_count": conflicting_records,
        "superseded_record_count": superseded_records,
        "calibrated_record_count": calibrated_records,
        "reconciliation_record_count": len(reconciliation_records),

        "is_blocked": blocked,
        "model_readiness": model_readiness,
    }


def coerce_dict(payload: Any, name: str) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TypeError(f"{name} must be a dict, got {type(payload).__name__}.")
    return payload


def coerce_list(payload: Any, name: str) -> list[Any]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise TypeError(f"{name} must be a list, got {type(payload).__name__}.")
    return payload


def append_issue(
    issues: list[ValidationIssue],
    *,
    code: str,
    severity: str,
    message: str,
    field_path: str = "",
    source_stage: str = "validation",
    recommendation: str = "",
) -> None:
    issues.append(
        ValidationIssue(
            code=code,
            severity=severity,
            message=message,
            field_path=field_path,
            source_stage=source_stage,
            recommendation=recommendation,
        )
    )