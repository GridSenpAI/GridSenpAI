from __future__ import annotations

import re

from copy import deepcopy
from typing import Any

from shared.gap_resolution_utils import resolve_gap_resolution_stage_inputs
from shared.planner_registry import build_planner_packet_field_rows, planner_registry_open_items, planner_registry_resolution_queue, summarize_registry_packet_coverage, summarize_field_resolution_governance

from services.audit_logging_service.service import initialize_audit_logger
from services.canonical_state_service.service import build_canonical_state

from services.calibration_comparison_service.service import (
    run_service as run_calibration_comparison_service,
)
from services.calibration_dataset_service.service import (
    run_service as run_calibration_dataset_service,
)
from services.validation_service.engineering_checks import run_engineering_validation
from services.field_resolution_service.service import build_field_resolution_result
from services.validation_service.models import (
    ValidationIssue,
    ValidationReport,
    ValidationServiceResult,
)
from services.validation_service.utils import (
    append_issue,
    build_validation_summary,
    coerce_dict,
    coerce_list,
    normalize_issue,
    utc_now_iso,
)


FIELD_STAGE_PRIORITY: dict[str, int] = {
    "validation": 700,
    "interview": 650,
    "normalization": 600,
    "translation": 500,
    "retrieval": 450,
    "canonical_state": 425,
    "extraction": 400,
}

FIELD_SOURCE_TYPE_PRIORITY: dict[str, int] = {
    "interview_answer": 120,
    "normalized_input": 110,
    "translation_output": 90,
    "calibration_dataset": 85,
    "schema_field_candidate": 70,
}

EVIDENCE_STRENGTH_PRIORITY: dict[str, int] = {
    "STRONG": 30,
    "MODERATE": 20,
    "WEAK": 10,
    "UNKNOWN": 0,
}

INVENTORY_PATH_HINTS = {
    "transformers",
    "generators",
    "ups",
    "ups_systems",
    "switchgear",
    "feeders",
    "panels",
    "batteries",
    "cooling_units",
    "cooling_systems",
    "chillers",
    "pumps",
    "equipment",
    "assets",
    "units",
    "instances",
}

ARTIFACT_TYPE_PRIORITY: dict[str, int] = {
    "one_line_diagram": 40,
    "equipment_schedule": 35,
    "spec_sheet": 30,
    "relay_setting_table": 28,
    "protection_diagram": 26,
    "engineering_report": 20,
    "narrative_document": 10,
    "appendix": -10,
}

REGION_TYPE_PRIORITY: dict[str, int] = {
    "TITLE_BLOCK_REGION": 30,
    "TABLE_EVIDENCE_REGION": 25,
    "DIAGRAM_EVIDENCE_REGION": 20,
    "TEXT_EVIDENCE_REGION": 10,
}

DOCUMENT_ROLE_PRIORITY: dict[str, int] = {
    "primary": 25,
    "main": 25,
    "application": 22,
    "study": 20,
    "supporting": 8,
    "reference": 5,
    "appendix": -20,
    "attachment": -8,
}

SECTION_LABEL_PRIORITY: dict[str, int] = {
    "title block": 20,
    "equipment schedule": 18,
    "load schedule": 18,
    "single line": 16,
    "one line": 16,
    "interconnection summary": 14,
    "facility summary": 14,
    "relay settings": 12,
    "specification": 10,
    "narrative": 0,
    "appendix": -15,
}


def _require_run_id(context: Any) -> str:
    run_id = getattr(context, "run_id", None)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("context.run_id must be a non-empty string.")
    return run_id.strip()


def _read_existing_report(canonical_state: dict[str, Any]) -> tuple[
    list[ValidationIssue],
    list[ValidationIssue],
    list[ValidationIssue],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    existing_report = coerce_dict(
        canonical_state.get("validation_report"),
        "canonical_state.validation_report",
    )

    errors = [
        normalize_issue(item)
        for item in coerce_list(existing_report.get("errors"), "validation_report.errors")
        if isinstance(item, (dict, ValidationIssue))
    ]
    warnings = [
        normalize_issue(item)
        for item in coerce_list(existing_report.get("warnings"), "validation_report.warnings")
        if isinstance(item, (dict, ValidationIssue))
    ]
    info = [
        normalize_issue(item)
        for item in coerce_list(existing_report.get("info"), "validation_report.info")
        if isinstance(item, (dict, ValidationIssue))
    ]

    missing_fields = [
        item
        for item in coerce_list(existing_report.get("missing_fields"), "validation_report.missing_fields")
        if isinstance(item, dict)
    ]
    conflicts = [
        item
        for item in coerce_list(existing_report.get("conflicts"), "validation_report.conflicts")
        if isinstance(item, dict)
    ]

    return errors, warnings, info, missing_fields, conflicts


def _flatten_scalar_paths(payload: Any, prefix: str = "") -> list[tuple[str, Any]]:
    paths: list[tuple[str, Any]] = []

    if isinstance(payload, dict):
        for key, value in payload.items():
            if not isinstance(key, str) or not key.strip():
                continue
            next_prefix = f"{prefix}.{key}" if prefix else key
            paths.extend(_flatten_scalar_paths(value, next_prefix))
        return paths

    if isinstance(payload, list):
        for index, item in enumerate(payload):
            next_prefix = f"{prefix}[{index}]"
            paths.extend(_flatten_scalar_paths(item, next_prefix))
        return paths

    paths.append((prefix, payload))
    return paths


def _normalize_field_path(field_path: Any) -> str:
    if not isinstance(field_path, str):
        return ""
    return field_path.strip()


def _normalized_path_tokens(field_path: str) -> list[str]:
    normalized = re.sub(r"\[\d+\]", "", field_path)
    return [token for token in normalized.split(".") if token]


def _is_inventory_like_path(field_path: str) -> bool:
    normalized = _normalize_field_path(field_path)
    if not normalized:
        return False

    if "[" in normalized and "]" in normalized:
        return True

    tokens = _normalized_path_tokens(normalized)
    if not tokens:
        return False

    if any(token in INVENTORY_PATH_HINTS for token in tokens[:-1]):
        return True

    return tokens[-1] in {"instances", "equipment", "assets", "units"}


def _is_scalar_record_candidate(record: dict[str, Any]) -> bool:
    source_type = _normalize_field_path(record.get("source_type"))
    if source_type in {"engineering_validation"}:
        return False

    field_path = _normalize_field_path(record.get("field_path"))
    if not field_path or _is_inventory_like_path(field_path):
        return False

    return True


def _field_record_source_method(record: dict[str, Any]) -> str:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return ""

    method = metadata.get("source_method")
    if isinstance(method, str) and method.strip():
        return method.strip()

    candidate_metadata = metadata.get("candidate_metadata")
    if isinstance(candidate_metadata, dict):
        candidate_method = candidate_metadata.get("source_method") or candidate_metadata.get("method")
        if isinstance(candidate_method, str) and candidate_method.strip():
            return candidate_method.strip()

    return ""

def _section_label_priority_score(section_label: str) -> float:
    normalized = section_label.strip().lower()
    if not normalized:
        return 0.0

    score = 0.0
    for label_fragment, weight in SECTION_LABEL_PRIORITY.items():
        if label_fragment in normalized:
            score += float(weight)
    return score


def _record_requires_review_after_selection(
    *,
    winner: dict[str, Any],
    winner_score: float,
    runner_up_score: float | None,
    distinct_values: set[Any],
) -> bool:
    if _is_malformed_scalar_record(winner):
        return True

    metadata = winner.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}

    confidence_score = winner.get("confidence_score")
    confidence_value = float(confidence_score) if isinstance(confidence_score, (int, float)) else None

    section_label = str(metadata.get("section_label", "")).strip().lower()
    document_role = str(
        metadata.get("document_role")
        or metadata.get("source_document_role")
        or ""
    ).strip().lower()
    method = _field_record_source_method(winner).lower()

    if "appendix" in section_label or document_role == "appendix":
        return True

    if "llm" in method and confidence_value is not None and confidence_value < 0.85:
        return True

    if len(distinct_values) > 1:
        if runner_up_score is None:
            return True
        if winner_score - runner_up_score < 20.0:
            return True

    if confidence_value is not None and confidence_value < 0.70:
        return True

    return False


def _build_scalar_review_flag(
    *,
    field_path: str,
    winner: dict[str, Any],
) -> dict[str, Any]:
    field_record_id = str(winner.get("field_record_id", "")).strip() or "unknown_field_record"

    return {
        "review_flag_id": f"{field_record_id}__review_flag",
        "category": "SCALAR_REVIEW_REQUIRED",
        "severity": "warning",
        "status": "OPEN",
        "message": f"Selected scalar value for '{field_path}' still requires engineering review.",
        "field_path": field_path,
        "record_ids": [field_record_id],
        "metadata": {
            "selected_field_record_id": field_record_id,
            "reason": "Selected scalar winner remained weak, narrow, or appendix-derived after reconciliation.",
        },
    }

def _is_malformed_scalar_record(record: dict[str, Any]) -> bool:
    if not _is_scalar_record_candidate(record):
        return False

    value = record.get("value")
    if value is None:
        return bool(record.get("is_missing"))

    if isinstance(value, str) and not value.strip():
        return True

    source_ref = record.get("source_ref")
    if source_ref is not None and not isinstance(source_ref, list):
        return True

    metadata = record.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        return True

    return False


def _field_record_score(record: dict[str, Any]) -> float:
    score = 0.0

    score += FIELD_STAGE_PRIORITY.get(str(record.get("source_stage", "")).strip(), 0)
    score += FIELD_SOURCE_TYPE_PRIORITY.get(str(record.get("source_type", "")).strip(), 0)
    score += EVIDENCE_STRENGTH_PRIORITY.get(str(record.get("evidence_strength", "UNKNOWN")).strip().upper(), 0)

    confidence_score = record.get("confidence_score")
    if isinstance(confidence_score, (int, float)):
        score += float(confidence_score) * 100.0

    confidence_tag = str(record.get("confidence_tag", "")).strip().upper()
    if confidence_tag == "HIGH":
        score += 10.0
    elif confidence_tag == "MODERATE":
        score += 5.0
    elif confidence_tag == "LOW":
        score -= 5.0
    elif confidence_tag == "UNRESOLVED":
        score -= 10.0

    source_type = str(record.get("source_type", "")).strip()
    if source_type == "calibration_comparison":
        score += 95.0

        metadata = record.get("metadata")
        if isinstance(metadata, dict):
            deviation = metadata.get("deviation")
            if isinstance(deviation, dict):
                deviation_percent = deviation.get("percent")
                if isinstance(deviation_percent, (int, float)):
                    absolute_deviation_percent = abs(float(deviation_percent))
                    if absolute_deviation_percent <= 5.0:
                        score += 15.0
                    elif absolute_deviation_percent <= 10.0:
                        score += 5.0
                    else:
                        score -= 10.0

    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        artifact_type = str(metadata.get("artifact_type", "")).strip()
        score += ARTIFACT_TYPE_PRIORITY.get(artifact_type, 0)

        region_type = str(metadata.get("region_type", "")).strip()
        score += REGION_TYPE_PRIORITY.get(region_type, 0)

        page_number = metadata.get("page_number")
        if isinstance(page_number, int):
            if page_number == 1:
                score += 8.0
            elif page_number <= 3:
                score += 4.0

        section_label = str(metadata.get("section_label", "")).strip()
        score += _section_label_priority_score(section_label)

        document_role = str(
            metadata.get("document_role")
            or metadata.get("source_document_role")
            or ""
        ).strip().lower()
        score += DOCUMENT_ROLE_PRIORITY.get(document_role, 0)

        document_version = metadata.get("document_version")
        if isinstance(document_version, (int, float)):
            score += float(document_version) * 2.0

        artifact_priority = metadata.get("artifact_priority")
        if isinstance(artifact_priority, (int, float)):
            score += float(artifact_priority)

        if "appendix" in section_label.lower():
            score -= 10.0

    source_ref = record.get("source_ref")
    if isinstance(source_ref, list):
        score += min(len([item for item in source_ref if str(item).strip()]), 5) * 2.0

    method = _field_record_source_method(record).lower()
    if method:
        if "llm" in method:
            score -= 8.0
        if any(token in method for token in {"deterministic", "rule", "regex", "normalized", "interview"}):
            score += 6.0
        if any(token in method for token in {"table", "spec", "title_block", "region_scoped"}):
            score += 4.0

    if record.get("value") is None:
        score -= 250.0
    if bool(record.get("is_missing")):
        score -= 300.0
    if _is_malformed_scalar_record(record):
        score -= 1000.0

    return score


def _reconciliation_status_text(record: dict[str, Any]) -> str:
    status = record.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip().lower()

    validation_status = str(record.get("validation_status", "")).strip().upper()
    if validation_status == "VALIDATED":
        return "validated"
    if validation_status == "MISSING":
        return "missing"
    if validation_status in {"CONFLICTED", "CONFLICTING", "REVIEW_REQUIRED"}:
        return "review_required"
    return ""


def _next_reconciliation_id(existing_records: list[dict[str, Any]]) -> int:
    highest = 0
    for item in existing_records:
        if not isinstance(item, dict):
            continue
        reconciliation_id = item.get("reconciliation_id")
        if not isinstance(reconciliation_id, str):
            continue
        match = re.search(r"(\d+)$", reconciliation_id.strip())
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _next_change_id(existing_entries: list[dict[str, Any]]) -> int:
    highest = 0
    for item in existing_entries:
        if not isinstance(item, dict):
            continue
        change_id = item.get("change_id")
        if not isinstance(change_id, str):
            continue
        match = re.search(r"(\d+)$", change_id.strip())
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _filter_resolved_conflicts(
    conflict_records: list[dict[str, Any]],
    resolved_fields: set[str],
) -> list[dict[str, Any]]:
    if not resolved_fields:
        return conflict_records

    filtered: list[dict[str, Any]] = []
    for item in conflict_records:
        if not isinstance(item, dict):
            continue
        field_path = _normalize_field_path(item.get("field_path"))
        conflict_type = str(item.get("conflict_type", "")).strip().upper()
        if field_path in resolved_fields and conflict_type == "VALUE_MISMATCH":
            continue
        filtered.append(item)
    return filtered


def _filter_resolved_review_flags(
    review_flags: list[dict[str, Any]],
    resolved_fields: set[str],
) -> list[dict[str, Any]]:
    if not resolved_fields:
        return review_flags

    filtered: list[dict[str, Any]] = []
    for item in review_flags:
        if not isinstance(item, dict):
            continue
        field_path = _normalize_field_path(item.get("field_path"))
        category = str(item.get("category", "")).strip().upper()
        if field_path in resolved_fields and category == "CONFLICT":
            continue
        filtered.append(item)
    return filtered

def _count_field_record_statuses(field_records: list[dict[str, Any]]) -> dict[str, int]:
    primary_count = 0
    superseded_count = 0
    review_required_count = 0
    conflicting_count = 0
    calibrated_count = 0

    for record in field_records:
        if not isinstance(record, dict):
            continue

        if record.get("is_primary") is True:
            primary_count += 1

        validation_status = str(record.get("validation_status", "")).strip().upper()
        review_status = str(record.get("review_status", "")).strip().upper()
        conflict_status = str(record.get("conflict_status", "")).strip().upper()

        if validation_status == "SUPERSEDED":
            superseded_count += 1

        if validation_status == "CALIBRATED":
            calibrated_count += 1

        if review_status == "REVIEW_REQUIRED":
            review_required_count += 1

        if conflict_status in {"CONFLICT", "CONFLICT_PRESENT"}:
            conflicting_count += 1

    valid_field_record_count = len([record for record in field_records if isinstance(record, dict)])

    return {
        "field_record_count": valid_field_record_count,
        "primary_field_record_count": primary_count,
        "superseded_record_count": superseded_count,
        "review_required_record_count": review_required_count,
        "conflicting_record_count": conflicting_count,
        "calibrated_record_count": calibrated_count,
    }

def _collapse_reconciled_scalar_noise(
    *,
    field_records: list[dict[str, Any]],
    warnings: list[ValidationIssue],
    info: list[ValidationIssue],
) -> list[dict[str, Any]]:
    grouped = _field_record_lookup(field_records)
    cleaned_records: list[dict[str, Any]] = []
    collapsed_count = 0

    for field_path, records in grouped.items():
        scalar_records = [record for record in records if _is_scalar_record_candidate(record)]
        non_scalar_records = [record for record in records if not _is_scalar_record_candidate(record)]

        if non_scalar_records:
            cleaned_records.extend(non_scalar_records)

        if not scalar_records:
            continue

        primary_records = [record for record in scalar_records if record.get("is_primary") is True]

        if len(primary_records) != 1:
            cleaned_records.extend(scalar_records)
            continue

        winner = primary_records[0]

        unresolved_records = [
            record
            for record in scalar_records
            if record is not winner
            and str(record.get("validation_status", "")).strip().upper() == "CONFLICTING"
            and _is_malformed_scalar_record(record)
        ]
        if unresolved_records:
            cleaned_records.extend(scalar_records)
            continue

        cleaned_records.append(winner)

        for record in scalar_records:
            if record is winner:
                continue

            prior_validation_status = str(record.get("validation_status", "")).strip().upper()
            prior_review_status = str(record.get("review_status", "")).strip().upper()
            prior_conflict_status = str(record.get("conflict_status", "")).strip().upper()

            should_collapse = prior_validation_status in {"CONFLICTING", "REVIEW_REQUIRED", "VALIDATED", "VALID"}

            if should_collapse:
                _apply_superseded_record(record)
                collapsed_count += 1
            else:
                cleaned_records.append(record)
                continue

            cleaned_records.append(record)

            if (
                prior_validation_status != "SUPERSEDED"
                or prior_review_status != "CLEAR"
                or prior_conflict_status != "NO_CONFLICT"
            ):
                append_issue(
                    info,
                    code="SCALAR_NOISE_COLLAPSED",
                    severity="info",
                    message=f"Collapsed non-primary scalar record for '{field_path}' to superseded after reconciliation.",
                    field_path=field_path,
                    source_stage="validation",
                )

    if collapsed_count > 0:
        append_issue(
            warnings,
            code="SCALAR_NOISE_REDUCED",
            severity="warning",
            message=f"Validation cleanup collapsed {collapsed_count} non-primary scalar record(s) to superseded.",
            source_stage="validation",
            recommendation="Review remaining review-required scalar winners and unresolved malformed records only.",
        )

    return cleaned_records

def _apply_primary_record(record: dict[str, Any], *, review_required: bool = False) -> None:
    record["is_primary"] = True
    record["conflict_status"] = "NO_CONFLICT"

    if bool(record.get("is_missing")) or record.get("value") is None:
        record["status"] = "missing"
        record["validation_status"] = "MISSING"
        record["review_status"] = "REVIEW_REQUIRED"
        return

    if review_required or _is_malformed_scalar_record(record):
        record["status"] = "review_required"
        record["validation_status"] = "REVIEW_REQUIRED"
        record["review_status"] = "REVIEW_REQUIRED"
        return

    record["status"] = "validated"
    record["validation_status"] = "VALIDATED"
    record["review_status"] = "CLEAR"


def _apply_superseded_record(record: dict[str, Any]) -> None:
    record["is_primary"] = False
    record["status"] = "superseded"
    record["validation_status"] = "SUPERSEDED"
    record["review_status"] = "CLEAR"
    record["conflict_status"] = "NO_CONFLICT"


def _apply_conflicting_record(record: dict[str, Any]) -> None:
    record["is_primary"] = False
    record["status"] = "conflicting"
    record["validation_status"] = "CONFLICTING"
    record["review_status"] = "REVIEW_REQUIRED"
    record["conflict_status"] = "CONFLICT_PRESENT"


def _reconcile_scalar_field_records(
    *,
    field_records: list[dict[str, Any]],
    conflict_records: list[dict[str, Any]],
    existing_reconciliation_records: list[dict[str, Any]],
    existing_change_log: list[dict[str, Any]],
    warnings: list[ValidationIssue],
    info: list[ValidationIssue],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[str], list[dict[str, Any]]]:
    grouped = _field_record_lookup(field_records)
    reconciliation_records: list[dict[str, Any]] = []
    change_entries: list[dict[str, Any]] = []
    generated_review_flags: list[dict[str, Any]] = []
    resolved_fields: set[str] = set()
    next_reconciliation_index = _next_reconciliation_id(existing_reconciliation_records)
    next_change_index = _next_change_id(existing_change_log)

    for field_path in sorted(grouped.keys()):
        records = [record for record in grouped[field_path] if isinstance(record, dict)]
        scalar_records = [record for record in records if _is_scalar_record_candidate(record)]
        if not scalar_records:
            continue

        scored_records = sorted(
            scalar_records,
            key=lambda record: (
                _field_record_score(record),
                str(record.get("source_stage", "")).strip(),
                str(record.get("source_type", "")).strip(),
                str(record.get("field_record_id", "")).strip(),
            ),
            reverse=True,
        )

        distinct_values = {
            _canonical_compare_value(record.get("value"))
            for record in scored_records
            if record.get("value") is not None and not _is_malformed_scalar_record(record)
        }
        winner = scored_records[0]
        runner_up = scored_records[1] if len(scored_records) > 1 else None
        winner_score = _field_record_score(winner)
        runner_up_score = _field_record_score(runner_up) if runner_up is not None else None
        authoritative_winner = (
            str(winner.get("source_stage", "")).strip() in {"interview", "normalization", "validation"}
            or str(winner.get("source_type", "")).strip() in {"interview_answer", "normalized_input"}
        )

        score_gap = winner_score - runner_up_score if runner_up_score is not None else None

        strongly_resolvable = len(distinct_values) <= 1 or (
            runner_up_score is None
            or (score_gap is not None and score_gap >= 15.0)
            or authoritative_winner
        )

        narrowly_resolvable = (
            not strongly_resolvable
            and runner_up_score is not None
            and score_gap is not None
            and score_gap >= 1.5
        )

        resolvable = strongly_resolvable or narrowly_resolvable

        if _is_malformed_scalar_record(winner):
            append_issue(
                warnings,
                code="MALFORMED_FIELD_RECORD_SUPPRESSED",
                severity="warning",
                message=f"Malformed candidate for '{field_path}' was suppressed during validation reconciliation.",
                field_path=field_path,
                source_stage="validation",
                recommendation="Inspect worker output and preserve only schema-compatible scalar values.",
            )
            for record in scored_records:
                _apply_conflicting_record(record)
            continue

        if not resolvable:
            append_issue(
                warnings,
                code="SCALAR_RECONCILIATION_REVIEW_REQUIRED",
                severity="warning",
                message=f"Field '{field_path}' still has unresolved competing scalar candidates after validation reconciliation.",
                field_path=field_path,
                source_stage="validation",
                recommendation="Require engineering review or structured interview confirmation before export.",
            )
            for record in scored_records:
                _apply_conflicting_record(record)
            continue

        review_required = narrowly_resolvable or _record_requires_review_after_selection(
            winner=winner,
            winner_score=winner_score,
            runner_up_score=runner_up_score,
            distinct_values=distinct_values,
        )

        for record in scored_records:
            prior_status = _reconciliation_status_text(record)
            if record is winner:
                _apply_primary_record(record, review_required=review_required)
            else:
                _apply_superseded_record(record)

            if prior_status != _reconciliation_status_text(record):
                change_entries.append(
                    {
                        "change_id": f"change_{next_change_index:05d}",
                        "change_type": "FIELD_RECORD_RECONCILIATION",
                        "field_path": field_path,
                        "prior_value": prior_status or None,
                        "new_value": _reconciliation_status_text(record),
                        "rationale": "Validation reconciliation ranked competing scalar field records.",
                        "changed_at": utc_now_iso(),
                        "metadata": {
                            "field_record_id": record.get("field_record_id"),
                            "selected_field_record_id": winner.get("field_record_id"),
                        },
                    }
                )
                next_change_index += 1

        if review_required:
            generated_review_flags.append(
                _build_scalar_review_flag(
                    field_path=field_path,
                    winner=winner,
                )
            )
            append_issue(
                warnings,
                code="SCALAR_PRIMARY_REVIEW_REQUIRED",
                severity="warning",
                message=f"Field '{field_path}' selected a primary scalar value but still requires review.",
                field_path=field_path,
                source_stage="validation",
                recommendation="Confirm the selected winner before planner-facing export.",
            )

        resolved_fields.add(field_path)
        reconciliation_records.append(
            {
                "reconciliation_id": f"reconciliation_{next_reconciliation_index:05d}",
                "field_path": field_path,
                "reconciliation_type": "SCALAR_FIELD_RANKING",
                "reconciliation_status": "REVIEW_REQUIRED" if review_required else "RESOLVED",
                "selected_field_record_id": winner.get("field_record_id"),
                "selected_value": winner.get("value"),
                "candidate_values": [record.get("value") for record in scored_records],
                "superseded_field_record_ids": [
                    str(record.get("field_record_id")).strip()
                    for record in scored_records
                    if record is not winner and str(record.get("field_record_id", "")).strip()
                ],
                "rationale": "Validation reconciliation selected the highest-ranked scalar candidate using stage priority, provenance strength, document precedence, section precedence, and confidence.",
                "metadata": {
                    "winner_score": round(winner_score, 3),
                    "runner_up_score": round(runner_up_score, 3) if runner_up_score is not None else None,
                    "authoritative_winner": authoritative_winner,
                    "review_required": review_required,
                },
            }
        )
        next_reconciliation_index += 1

        append_issue(
            info,
            code="SCALAR_RECONCILIATION_RESOLVED",
            severity="info",
            message=f"Validation reconciliation resolved scalar field '{field_path}'.",
            field_path=field_path,
            source_stage="validation",
        )

    filtered_conflicts = _filter_resolved_conflicts(conflict_records, resolved_fields)
    return (
        field_records,
        filtered_conflicts,
        reconciliation_records,
        change_entries,
        resolved_fields,
        generated_review_flags,
    )

def _normalize_record_id_set(records: list[dict[str, Any]], key: str) -> set[str]:
    normalized: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            normalized.add(value.strip())
    return normalized

def _issue_key(issue: ValidationIssue) -> tuple[str, str, str, str, str, str]:
    return (
        issue.code,
        issue.severity,
        issue.message,
        issue.field_path,
        issue.source_stage,
        issue.recommendation,
    )


def _deduplicate_validation_issues(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    deduped: list[ValidationIssue] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()

    for issue in issues:
        if not isinstance(issue, ValidationIssue):
            continue
        key = _issue_key(issue)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)

    return deduped


def _review_flag_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("category", "")).strip(),
        str(item.get("field_path", "")).strip(),
        str(item.get("message", "")).strip(),
    )


def _deduplicate_review_flags(review_flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for item in review_flags:
        if not isinstance(item, dict):
            continue
        key = _review_flag_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped

def _field_record_lookup(field_records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}
    for record in field_records:
        if not isinstance(record, dict):
            continue
        field_path = record.get("field_path")
        if not isinstance(field_path, str) or not field_path.strip():
            continue
        normalized_field_path = field_path.strip()
        lookup.setdefault(normalized_field_path, []).append(record)
    return lookup


def _canonical_compare_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return tuple(_canonical_compare_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(
            (str(key), _canonical_compare_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    return value


def _contains_nested_path(payload: dict[str, Any], dotted_path: str) -> bool:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _validate_required_sections(
    canonical_state: dict[str, Any],
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    required_sections = [
        "artifacts",
        "entities",
        "normalized_input",
        "validation_report",
        "stage_status",
    ]

    for section_name in required_sections:
        if section_name not in canonical_state:
            append_issue(
                errors,
                code="MISSING_SECTION",
                severity="error",
                message=f"Canonical state is missing required section '{section_name}'.",
                field_path=section_name,
                recommendation=f"Populate canonical_state.{section_name} before downstream modeling.",
            )

    if "source_anchors" not in canonical_state:
        append_issue(
            warnings,
            code="MISSING_SOURCE_ANCHOR_SECTION",
            severity="warning",
            message="Canonical state is missing the source_anchors section.",
            field_path="source_anchors",
            recommendation="Preserve source anchors for evidence lineage.",
        )

    if "field_records" not in canonical_state:
        append_issue(
            warnings,
            code="MISSING_FIELD_RECORDS_SECTION",
            severity="warning",
            message="Canonical state does not yet contain governed field records.",
            field_path="field_records",
            recommendation="Populate governed field records to support Phase 3 provenance and review workflows.",
        )

    if "conflict_records" not in canonical_state:
        append_issue(
            warnings,
            code="MISSING_CONFLICT_RECORDS_SECTION",
            severity="warning",
            message="Canonical state does not yet contain governed conflict records.",
            field_path="conflict_records",
            recommendation="Populate conflict records to support review and clarification workflows.",
        )

    if "review_flags" not in canonical_state:
        append_issue(
            warnings,
            code="MISSING_REVIEW_FLAGS_SECTION",
            severity="warning",
            message="Canonical state does not yet contain review flags.",
            field_path="review_flags",
            recommendation="Populate review flags for missing, conflicting, or low-confidence data.",
        )

    if "output_parameters" not in canonical_state:
        append_issue(
            warnings,
            code="MISSING_OUTPUT_PARAMETERS",
            severity="warning",
            message="Canonical state does not yet contain translated output parameters.",
            field_path="output_parameters",
            recommendation="Run translation after canonical state validation passes.",
        )


def _validate_stage_statuses(
    canonical_state: dict[str, Any],
    warnings: list[ValidationIssue],
) -> None:
    stage_status = coerce_dict(canonical_state.get("stage_status"), "canonical_state.stage_status")
    expected_stage_keys = [
        "ingestion",
        "extraction",
        "normalization",
        "gap_resolution::retrieval",
        "gap_resolution::interview",
        "validation",
        "canonical_state",
    ]

    for stage_name in expected_stage_keys:
        stage_value = stage_status.get(stage_name)
        if not isinstance(stage_value, str) or not stage_value.strip():
            append_issue(
                warnings,
                code="MISSING_STAGE_STATUS",
                severity="warning",
                message=f"No stage status recorded for '{stage_name}'.",
                field_path=f"stage_status.{stage_name}",
                source_stage="canonical_state",
                recommendation=f"Ensure the {stage_name} stage sets a meaningful status.",
            )

    governance_status = stage_status.get("canonical_state_governance")
    if governance_status is None:
        append_issue(
            warnings,
            code="MISSING_GOVERNANCE_STAGE_STATUS",
            severity="warning",
            message="No stage status recorded for canonical_state_governance.",
            field_path="stage_status.canonical_state_governance",
            source_stage="canonical_state",
            recommendation="Record governance completion after field/conflict/review synthesis.",
        )


def _validate_core_collections(
    canonical_state: dict[str, Any],
    warnings: list[ValidationIssue],
) -> None:
    artifacts = coerce_list(canonical_state.get("artifacts"), "canonical_state.artifacts")
    entities = coerce_list(canonical_state.get("entities"), "canonical_state.entities")
    source_anchors = coerce_list(canonical_state.get("source_anchors"), "canonical_state.source_anchors")
    evidence_snippets = coerce_list(canonical_state.get("evidence_snippets"), "canonical_state.evidence_snippets")

    if not artifacts:
        append_issue(
            warnings,
            code="EMPTY_ARTIFACT_SET",
            severity="warning",
            message="Canonical state contains zero discovered artifacts.",
            field_path="artifacts",
            source_stage="ingestion",
            recommendation="Provide at least one artifact to support evidence-backed processing.",
        )

    if not entities:
        append_issue(
            warnings,
            code="EMPTY_ENTITY_SET",
            severity="warning",
            message="Canonical state contains zero extracted engineering entities.",
            field_path="entities",
            source_stage="extraction",
            recommendation="Improve extraction coverage or provide richer source material.",
        )

    if not source_anchors:
        append_issue(
            warnings,
            code="NO_SOURCE_ANCHORS",
            severity="warning",
            message="Canonical state has no source anchors for extracted data.",
            field_path="source_anchors",
            source_stage="extraction",
            recommendation="Retain document anchors for engineering traceability.",
        )

    if not evidence_snippets:
        append_issue(
            warnings,
            code="NO_EVIDENCE_SNIPPETS",
            severity="warning",
            message="Canonical state has no supporting evidence snippets.",
            field_path="evidence_snippets",
            source_stage="retrieval",
            recommendation="Populate retrieval evidence to support planner review.",
        )


def _validate_normalized_input(
    canonical_state: dict[str, Any],
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    normalized_input = coerce_dict(
        canonical_state.get("normalized_input"),
        "canonical_state.normalized_input",
    )

    if not normalized_input:
        append_issue(
            errors,
            code="EMPTY_NORMALIZED_INPUT",
            severity="error",
            message="Canonical state normalized_input is empty.",
            field_path="normalized_input",
            source_stage="normalization",
            recommendation="Normalization must produce an accepted deterministic input set.",
        )
        return

    flattened_paths = {path for path, _value in _flatten_scalar_paths(normalized_input) if path}

    if not flattened_paths:
        append_issue(
            errors,
            code="NORMALIZED_INPUT_HAS_NO_SCALARS",
            severity="error",
            message="Normalized input does not contain any scalar values.",
            field_path="normalized_input",
            source_stage="normalization",
            recommendation="Populate normalized input with structured scalar fields for downstream services.",
        )
        return

    likely_required_nested_paths = [
        "facility.project_name",
        "facility.frequency_hz",
    ]

    for field_path in likely_required_nested_paths:
        if field_path not in flattened_paths:
            append_issue(
                warnings,
                code="LIKELY_REQUIRED_FIELD_MISSING",
                severity="warning",
                message=f"Normalized input is missing likely required field '{field_path}'.",
                field_path=f"normalized_input.{field_path}",
                source_stage="normalization",
                recommendation=f"Capture or infer '{field_path}' before planner-facing export.",
            )

    if not _contains_nested_path(normalized_input, "facility"):
        append_issue(
            warnings,
            code="MISSING_FACILITY_OBJECT",
            severity="warning",
            message="Normalized input does not contain a facility object.",
            field_path="normalized_input.facility",
            source_stage="normalization",
            recommendation="Normalize facility data into the expected nested facility object.",
        )

    validation_report = coerce_dict(
        canonical_state.get("validation_report"),
        "canonical_state.validation_report",
    )
    missing_fields = coerce_list(validation_report.get("missing_fields"), "validation_report.missing_fields")

    if not missing_fields:
        append_issue(
            warnings,
            code="NO_MISSING_FIELD_TRACKING",
            severity="warning",
            message="Validation report does not track missing fields.",
            field_path="validation_report.missing_fields",
            source_stage="normalization",
            recommendation="Carry forward missing-field tracking for interview generation and planner review.",
        )


def _validate_translation_outputs(
    canonical_state: dict[str, Any],
    warnings: list[ValidationIssue],
) -> None:
    model_outputs = coerce_dict(canonical_state.get("model_outputs"), "canonical_state.model_outputs")
    output_parameters = coerce_list(canonical_state.get("output_parameters"), "canonical_state.output_parameters")
    assumptions = coerce_list(canonical_state.get("assumptions"), "canonical_state.assumptions")

    if model_outputs and not output_parameters:
        append_issue(
            warnings,
            code="MODEL_OUTPUTS_WITHOUT_PARAMETERS",
            severity="warning",
            message="model_outputs exist but output_parameters is empty.",
            field_path="output_parameters",
            source_stage="translation",
            recommendation="Ensure translation writes normalized parameter records as well as aggregate outputs.",
        )

    if not assumptions:
        append_issue(
            warnings,
            code="NO_TRANSLATION_ASSUMPTIONS",
            severity="warning",
            message="No explicit assumptions were captured for translated outputs.",
            field_path="assumptions",
            source_stage="translation",
            recommendation="Record assumptions explicitly for planner review.",
        )

    for index, parameter in enumerate(output_parameters, start=1):
        if not isinstance(parameter, dict):
            append_issue(
                warnings,
                code="INVALID_OUTPUT_PARAMETER",
                severity="warning",
                message=f"Output parameter #{index} is not an object.",
                field_path=f"output_parameters[{index - 1}]",
                source_stage="translation",
                recommendation="Ensure each output parameter is represented as a dict.",
            )
            continue

        parameter_path = parameter.get("parameter_path")
        if not isinstance(parameter_path, str) or not parameter_path.strip():
            append_issue(
                warnings,
                code="OUTPUT_PARAMETER_MISSING_PATH",
                severity="warning",
                message=f"Output parameter #{index} is missing parameter_path.",
                field_path=f"output_parameters[{index - 1}].parameter_path",
                source_stage="translation",
                recommendation="Each output parameter should declare its parameter_path.",
            )


def _validate_scenarios(
    canonical_state: dict[str, Any],
    warnings: list[ValidationIssue],
) -> None:
    scenarios = coerce_dict(canonical_state.get("scenarios"), "canonical_state.scenarios")
    expected = {"typical", "conservative", "best_case"}

    if not scenarios:
        append_issue(
            warnings,
            code="NO_SCENARIOS",
            severity="warning",
            message="No scenarios were generated.",
            field_path="scenarios",
            source_stage="scenario",
            recommendation="Generate bounded scenarios for output completeness.",
        )
        return

    scenario_keys = {str(key).strip().lower() for key in scenarios.keys()}
    missing = sorted(expected - scenario_keys)

    for scenario_name in missing:
        append_issue(
            warnings,
            code="MISSING_SCENARIO",
            severity="warning",
            message=f"Expected scenario '{scenario_name}' is missing.",
            field_path=f"scenarios.{scenario_name}",
            source_stage="scenario",
            recommendation="Provide all bounded scenarios.",
        )


def _extract_project_identifiers(canonical_state: dict[str, Any]) -> list[str]:
    identifiers: set[str] = set()

    artifacts = coerce_list(canonical_state.get("artifacts"), "canonical_state.artifacts")
    field_records = coerce_list(canonical_state.get("field_records"), "canonical_state.field_records")

    project_pattern = re.compile(r"\b[A-Z]{2,3}\d?-\d{3}\b")

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue

        for key in ("artifact_id", "source_name", "file_name", "artifact_name", "display_name"):
            value = artifact.get(key)
            if isinstance(value, str):
                for match in project_pattern.findall(value.upper()):
                    identifiers.add(match)

    for record in field_records:
        if not isinstance(record, dict):
            continue

        field_path = str(record.get("field_path", "")).strip().lower()
        value = record.get("value")

        if "project" not in field_path:
            continue

        if isinstance(value, str):
            for match in project_pattern.findall(value.upper()):
                identifiers.add(match)

    return sorted(identifiers)


def _validate_multi_project_scope(
    canonical_state: dict[str, Any],
    warnings: list[ValidationIssue],
) -> None:
    project_ids = _extract_project_identifiers(canonical_state)

    if len(project_ids) <= 1:
        return

    append_issue(
        warnings,
        code="MULTI_PROJECT_SCOPE_CONFLICT",
        severity="warning",
        message=(
            "Multiple distinct project identifiers were detected in a single canonical facility state: "
            + ", ".join(project_ids)
        ),
        field_path="artifacts",
        source_stage="validation",
        recommendation=(
            "Split the run by project/document scope or require human review before treating outputs "
            "as a single-facility model."
        ),
    )


def _validate_artifact_classification(
    canonical_state: dict[str, Any],
    warnings: list[ValidationIssue],
) -> None:
    artifacts = coerce_list(canonical_state.get("artifacts"), "canonical_state.artifacts")

    for index, artifact in enumerate(artifacts, start=1):
        if not isinstance(artifact, dict):
            continue

        artifact_type = artifact.get("artifact_type")
        artifact_category = artifact.get("artifact_category")

        if isinstance(artifact_type, str) and artifact_type.strip():
            continue
        if isinstance(artifact_category, str) and artifact_category.strip():
            continue

        append_issue(
            warnings,
            code="ARTIFACT_CLASSIFICATION_MISSING",
            severity="warning",
            message=f"Artifact #{index} is missing artifact_type/artifact_category classification.",
            field_path=f"artifacts[{index - 1}]",
            source_stage="ingestion",
            recommendation="Classify each artifact so routing, validation, and intake completeness checks are meaningful.",
        )


def _validate_single_value_field_cardinality(
    canonical_state: dict[str, Any],
    warnings: list[ValidationIssue],
) -> None:
    field_records = coerce_list(canonical_state.get("field_records"), "canonical_state.field_records")
    field_records_by_path = _field_record_lookup(field_records)

    single_value_fields = {
        "facility.project_name",
        "facility.poi_voltage_kv",
        "facility.load_schedule.phase_1_mw",
        "facility.topology",
    }

    for field_path in single_value_fields:
        records = field_records_by_path.get(field_path, [])
        comparable_values = {
            _canonical_compare_value(record.get("value"))
            for record in records
            if isinstance(record, dict) and record.get("value") is not None
        }

        if len(comparable_values) <= 1:
            continue

        append_issue(
            warnings,
            code="SINGLE_VALUE_FIELD_CARDINALITY_CONFLICT",
            severity="warning",
            message=f"Field '{field_path}' contains multiple competing values but should resolve to one value.",
            field_path=field_path,
            source_stage="validation",
            recommendation="Create or preserve conflict records and require human review before export.",
        )


def _validate_numeric_sanity(
    canonical_state: dict[str, Any],
    warnings: list[ValidationIssue],
) -> None:
    field_records = coerce_list(canonical_state.get("field_records"), "canonical_state.field_records")

    allowed_poi_voltages = {69, 115, 138, 161, 230, 345, 500, 765}

    for record in field_records:
        if not isinstance(record, dict):
            continue

        field_path = str(record.get("field_path", "")).strip()
        value = record.get("value")

        if field_path == "facility.poi_voltage_kv":
            numeric_value = None
            if isinstance(value, (int, float)):
                numeric_value = float(value)
            elif isinstance(value, str):
                try:
                    numeric_value = float(value.strip())
                except ValueError:
                    numeric_value = None

            if numeric_value is not None and int(round(numeric_value)) not in allowed_poi_voltages:
                append_issue(
                    warnings,
                    code="POI_VOLTAGE_OUTSIDE_EXPECTED_SET",
                    severity="warning",
                    message=f"POI voltage '{numeric_value}' kV is outside the expected transmission voltage set.",
                    field_path=field_path,
                    source_stage="validation",
                    recommendation="Review POI extraction and confirm the correct interconnection voltage.",
                )

        if field_path == "facility.load_schedule.phase_1_mw":
            numeric_value = None
            if isinstance(value, (int, float)):
                numeric_value = float(value)
            elif isinstance(value, str):
                try:
                    numeric_value = float(value.strip())
                except ValueError:
                    numeric_value = None

            if numeric_value is not None and numeric_value > 500:
                append_issue(
                    warnings,
                    code="PHASE_1_MW_SANITY_REVIEW",
                    severity="warning",
                    message=f"Phase 1 MW value '{numeric_value}' exceeds normal single-phase sanity threshold.",
                    field_path=field_path,
                    source_stage="validation",
                    recommendation="Confirm that this MW value belongs to the intended facility and phase.",
                )


def _validate_field_records(
    canonical_state: dict[str, Any],
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    field_records = coerce_list(canonical_state.get("field_records"), "canonical_state.field_records")
    conflict_records = coerce_list(canonical_state.get("conflict_records"), "canonical_state.conflict_records")

    if not field_records:
        append_issue(
            warnings,
            code="NO_FIELD_RECORDS",
            severity="warning",
            message="Canonical state has no governed field records.",
            field_path="field_records",
            source_stage="canonical_state",
            recommendation="Synthesize field records from extraction, normalization, and translation outputs.",
        )
        return

    field_records_by_path = _field_record_lookup(field_records)

    for index, record in enumerate(field_records, start=1):
        if not isinstance(record, dict):
            append_issue(
                errors,
                code="INVALID_FIELD_RECORD",
                severity="error",
                message=f"field_records[{index - 1}] is not an object.",
                field_path=f"field_records[{index - 1}]",
                source_stage="canonical_state",
                recommendation="Ensure each field record is represented as a dict.",
            )
            continue

        field_path = record.get("field_path")
        source_stage = record.get("source_stage")
        source_type = record.get("source_type")
        validation_status = record.get("validation_status")
        review_status = record.get("review_status")
        conflict_status = record.get("conflict_status")
        source_ref = record.get("source_ref")
        metadata = record.get("metadata", {})

        if not isinstance(record.get("field_record_id"), str) or not str(record.get("field_record_id")).strip():
            append_issue(
                errors,
                code="FIELD_RECORD_MISSING_ID",
                severity="error",
                message=f"field_records[{index - 1}] is missing field_record_id.",
                field_path=f"field_records[{index - 1}].field_record_id",
                source_stage="canonical_state",
                recommendation="Assign stable IDs to governed field records.",
            )

        if not isinstance(field_path, str) or not field_path.strip():
            append_issue(
                errors,
                code="FIELD_RECORD_MISSING_PATH",
                severity="error",
                message=f"field_records[{index - 1}] is missing field_path.",
                field_path=f"field_records[{index - 1}].field_path",
                source_stage="canonical_state",
                recommendation="Each field record should identify its canonical field path.",
            )

        if not isinstance(source_stage, str) or not source_stage.strip():
            append_issue(
                warnings,
                code="FIELD_RECORD_MISSING_SOURCE_STAGE",
                severity="warning",
                message=f"field_records[{index - 1}] is missing source_stage.",
                field_path=str(field_path or ""),
                source_stage="canonical_state",
                recommendation="Track the originating pipeline stage for each field record.",
            )

        if not isinstance(source_type, str) or not source_type.strip():
            append_issue(
                warnings,
                code="FIELD_RECORD_MISSING_SOURCE_TYPE",
                severity="warning",
                message=f"field_records[{index - 1}] is missing source_type.",
                field_path=str(field_path or ""),
                source_stage="canonical_state",
                recommendation="Track the originating record type for each field record.",
            )

        if not isinstance(validation_status, str) or not validation_status.strip():
            append_issue(
                warnings,
                code="FIELD_RECORD_MISSING_VALIDATION_STATUS",
                severity="warning",
                message=f"field_records[{index - 1}] is missing validation_status.",
                field_path=str(field_path or ""),
                source_stage="canonical_state",
                recommendation="Populate validation_status on each governed field record.",
            )

        if not isinstance(review_status, str) or not review_status.strip():
            append_issue(
                warnings,
                code="FIELD_RECORD_MISSING_REVIEW_STATUS",
                severity="warning",
                message=f"field_records[{index - 1}] is missing review_status.",
                field_path=str(field_path or ""),
                source_stage="canonical_state",
                recommendation="Populate review_status on each governed field record.",
            )

        if not isinstance(conflict_status, str) or not conflict_status.strip():
            append_issue(
                warnings,
                code="FIELD_RECORD_MISSING_CONFLICT_STATUS",
                severity="warning",
                message=f"field_records[{index - 1}] is missing conflict_status.",
                field_path=str(field_path or ""),
                source_stage="canonical_state",
                recommendation="Populate conflict_status on each governed field record.",
            )

        if source_ref is not None and not isinstance(source_ref, list):
            append_issue(
                warnings,
                code="FIELD_RECORD_INVALID_SOURCE_REF",
                severity="warning",
                message=f"field_records[{index - 1}] has non-list source_ref.",
                field_path=str(field_path or ""),
                source_stage="canonical_state",
                recommendation="Store field record source_ref as a list of lineage references.",
            )

        if metadata is not None and not isinstance(metadata, dict):
            append_issue(
                warnings,
                code="FIELD_RECORD_INVALID_METADATA",
                severity="warning",
                message=f"field_records[{index - 1}] has non-dict metadata.",
                field_path=str(field_path or ""),
                source_stage="canonical_state",
                recommendation="Store field record metadata as a dict.",
            )

    for field_path, records in field_records_by_path.items():
        comparable_values = {
            _canonical_compare_value(record.get("value"))
            for record in records
            if isinstance(record, dict)
        }

        if len(comparable_values) <= 1:
            continue

        has_conflict_record = any(
            isinstance(conflict, dict)
            and isinstance(conflict.get("field_path"), str)
            and conflict.get("field_path", "").strip() == field_path
            for conflict in conflict_records
        )

        if not has_conflict_record:
            append_issue(
                warnings,
                code="UNTRACKED_FIELD_VALUE_MISMATCH",
                severity="warning",
                message=f"Multiple differing values exist for '{field_path}' but no conflict record was created.",
                field_path=field_path,
                source_stage="canonical_state",
                recommendation="Generate conflict records when governed field records disagree.",
            )


def _normalize_assumption_registry_entry(item: dict[str, Any], index: int) -> dict[str, Any]:
    assumption_id = item.get("assumption_id")
    if not isinstance(assumption_id, str) or not assumption_id.strip():
        assumption_id = f"assumption_{index}"

    field_path = item.get("field_path")
    if not isinstance(field_path, str) or not field_path.strip():
        field_path = item.get("parameter_path", "")
    if not isinstance(field_path, str):
        field_path = ""

    evidence_refs = [
        value
        for value in (
            str(entry).strip()
            for entry in coerce_list(item.get("evidence_refs"), "assumption_registry.evidence_refs")
        )
        if value
    ]

    metadata = coerce_dict(item.get("metadata"), "assumption_registry.metadata")

    normalized = deepcopy(item)
    normalized["assumption_id"] = assumption_id.strip()
    normalized["field_path"] = field_path.strip()
    normalized["parameter_path"] = field_path.strip()
    normalized["status"] = str(item.get("status", "ACTIVE")).strip() or "ACTIVE"
    normalized["evidence_refs"] = evidence_refs
    normalized["metadata"] = metadata
    return normalized


def _build_assumption_registry(canonical_state: dict[str, Any]) -> list[dict[str, Any]]:
    registry = [
        deepcopy(item)
        for item in coerce_list(canonical_state.get("assumption_registry"), "canonical_state.assumption_registry")
        if isinstance(item, dict)
    ]
    normalized_registry: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, item in enumerate(registry, start=1):
        normalized = _normalize_assumption_registry_entry(item, index)
        assumption_id = normalized["assumption_id"]
        if assumption_id in seen_ids:
            continue
        normalized_registry.append(normalized)
        seen_ids.add(assumption_id)

    assumptions = coerce_list(canonical_state.get("assumptions"), "canonical_state.assumptions")
    for index, item in enumerate(assumptions, start=1):
        if not isinstance(item, dict):
            continue

        assumption_id = item.get("assumption_id")
        if not isinstance(assumption_id, str) or not assumption_id.strip():
            assumption_id = f"translation_assumption_{index}"

        field_path = item.get("parameter_path")
        if not isinstance(field_path, str) or not field_path.strip():
            field_path = item.get("field_path", "")
        if not isinstance(field_path, str):
            field_path = ""

        normalized = {
            "assumption_id": assumption_id.strip(),
            "field_path": field_path.strip(),
            "parameter_path": field_path.strip(),
            "assumption_value": item.get("nominal_value"),
            "nominal_value": item.get("nominal_value"),
            "bounds": deepcopy(coerce_dict(item.get("bounds"), "assumptions.bounds")),
            "rationale": str(item.get("rationale", "")).strip(),
            "created_by_stage": str(item.get("created_by", "translation")).strip() or "translation",
            "created_by": str(item.get("created_by", "translation")).strip() or "translation",
            "status": str(item.get("status", "ACTIVE")).strip() or "ACTIVE",
            "evidence_refs": [
                value
                for value in (
                    str(entry).strip()
                    for entry in coerce_list(item.get("evidence_refs"), "assumptions.evidence_refs")
                )
                if value
            ],
            "metadata": deepcopy(coerce_dict(item.get("metadata"), "assumptions.metadata")),
        }

        if normalized["assumption_id"] in seen_ids:
            continue

        normalized_registry.append(normalized)
        seen_ids.add(normalized["assumption_id"])

    return normalized_registry


def _record_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(record.get("field_path", "")).strip(),
        _canonical_compare_value(record.get("value")),
        str(record.get("source_stage", "")).strip(),
        str(record.get("source_type", "")).strip(),
        tuple(
            item
            for item in (
                str(value).strip()
                for value in coerce_list(record.get("source_ref"), "field_record.source_ref")
            )
            if item
        ),
        str(record.get("validation_status", "")).strip(),
        str(record.get("review_status", "")).strip(),
        str(record.get("conflict_status", "")).strip(),
    )


def _build_calibration_field_records(
    *,
    calibration_records: list[dict[str, Any]],
    existing_field_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_ids = _normalize_record_id_set(existing_field_records, "field_record_id")
    existing_keys = {_record_key(record) for record in existing_field_records if isinstance(record, dict)}

    new_records: list[dict[str, Any]] = []

    for item in calibration_records:
        if not isinstance(item, dict):
            continue

        field_path = item.get("field_path")
        calibration_record_id = item.get("calibration_record_id")
        if not isinstance(field_path, str) or not field_path.strip():
            continue
        if not isinstance(calibration_record_id, str) or not calibration_record_id.strip():
            continue

        status = str(item.get("status", "CALIBRATION_REVIEW_REQUIRED")).strip() or "CALIBRATION_REVIEW_REQUIRED"

        validation_status = "CALIBRATED"
        review_status = "PENDING_REVIEW"
        conflict_status = "NO_CONFLICT"
        confidence_tag = "MODERATE"

        if status == "CALIBRATED_MATCH":
            review_status = "NO_REVIEW_REQUIRED"
            confidence_tag = "HIGH"
        elif status == "CALIBRATION_CONFLICT":
            validation_status = "CONFLICTING"
            review_status = "PENDING_REVIEW"
            conflict_status = "CONFLICT_PRESENT"
            confidence_tag = "LOW"

        proposed_record = {
            "field_record_id": f"{calibration_record_id.strip()}__field_record",
            "field_path": field_path.strip(),
            "value": item.get("adjusted_value"),
            "source_stage": "validation",
            "source_type": "calibration_comparison",
            "source_ref": [
                calibration_record_id.strip(),
                *[
                    value
                    for value in (
                        str(entry).strip()
                        for entry in coerce_list(item.get("evidence_refs"), "calibration_record.evidence_refs")
                    )
                    if value
                ],
            ],
            "confidence_score": None,
            "confidence_tag": confidence_tag,
            "validation_status": validation_status,
            "review_status": review_status,
            "evidence_strength": "MODERATE",
            "conflict_status": conflict_status,
            "is_missing": False,
            "metadata": {
                "origin": "phase_four_calibration",
                "calibration_record_id": calibration_record_id.strip(),
                "dataset_id": item.get("dataset_id"),
                "expected_value": item.get("expected_value"),
                "observed_value": item.get("observed_value"),
                "tolerance": deepcopy(coerce_dict(item.get("tolerance"), "calibration_record.tolerance")),
                "deviation": deepcopy(coerce_dict(item.get("deviation"), "calibration_record.deviation")),
                "linked_field_record_ids": [
                    value
                    for value in (
                        str(entry).strip()
                        for entry in coerce_list(item.get("linked_field_record_ids"), "calibration_record.linked_field_record_ids")
                    )
                    if value
                ],
                "linked_assumption_ids": [
                    value
                    for value in (
                        str(entry).strip()
                        for entry in coerce_list(item.get("linked_assumption_ids"), "calibration_record.linked_assumption_ids")
                    )
                    if value
                ],
            },
        }

        if proposed_record["field_record_id"] in existing_ids:
            continue

        record_key = _record_key(proposed_record)
        if record_key in existing_keys:
            continue

        existing_ids.add(proposed_record["field_record_id"])
        existing_keys.add(record_key)
        new_records.append(proposed_record)

    return new_records

def _engineering_issue_record_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("code", "")).strip(),
        str(item.get("field_path", "")).strip(),
        str(item.get("message", "")).strip(),
    )


def _next_engineering_field_record_index(existing_field_records: list[dict[str, Any]]) -> int:
    highest = 0

    for record in existing_field_records:
        if not isinstance(record, dict):
            continue

        field_record_id = record.get("field_record_id")
        if not isinstance(field_record_id, str):
            continue

        match = re.search(r"eng_validation_field_(\d+)$", field_record_id.strip())
        if match:
            highest = max(highest, int(match.group(1)))

    return highest + 1


def _deduce_engineering_validation_status(severity: str) -> tuple[str, str, str]:
    normalized = str(severity).strip().lower()

    if normalized == "error":
        return ("REVIEW_REQUIRED", "REVIEW_REQUIRED", "NO_CONFLICT")

    if normalized == "warning":
        return ("REVIEW_REQUIRED", "REVIEW_REQUIRED", "NO_CONFLICT")

    return ("VALIDATED", "CLEAR", "NO_CONFLICT")


def _build_engineering_validation_field_records(
    *,
    engineering_payload: dict[str, Any],
    existing_field_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_ids = _normalize_record_id_set(existing_field_records, "field_record_id")
    existing_keys = {_record_key(record) for record in existing_field_records if isinstance(record, dict)}

    existing_engineering_issue_keys: set[tuple[str, str, str]] = set()
    for record in existing_field_records:
        if not isinstance(record, dict):
            continue

        source_type = str(record.get("source_type", "")).strip()
        if source_type != "engineering_validation":
            continue

        metadata = record.get("metadata", {})
        if not isinstance(metadata, dict):
            continue

        issue_code = str(metadata.get("engineering_issue_code", "")).strip()
        field_path = str(record.get("field_path", "")).strip()
        message = str(metadata.get("engineering_issue_message", "")).strip()

        if issue_code or field_path or message:
            existing_engineering_issue_keys.add((issue_code, field_path, message))

    synthesized_records: list[dict[str, Any]] = []
    next_index = _next_engineering_field_record_index(existing_field_records)

    for bucket_name in ("errors", "warnings", "info"):
        payload_items = coerce_list(
            engineering_payload.get(bucket_name),
            f"engineering_validation.{bucket_name}",
        )

        for item in payload_items:
            if not isinstance(item, dict):
                continue

            issue_code = str(item.get("code", "")).strip()
            field_path = str(item.get("field_path", "")).strip()
            message = str(item.get("message", "")).strip()

            if not issue_code or not field_path or not message:
                continue

            issue_key = (issue_code, field_path, message)
            if issue_key in existing_engineering_issue_keys:
                continue

            severity = str(item.get("severity", bucket_name[:-1] if bucket_name.endswith("s") else bucket_name)).strip().lower()
            validation_status, review_status, conflict_status = _deduce_engineering_validation_status(severity)

            metadata = {
                "record_origin": "engineering_validation",
                "engineering_issue_code": issue_code,
                "engineering_issue_message": message,
                "engineering_issue_severity": severity,
                "engineering_issue_source_stage": str(item.get("source_stage", "validation")).strip() or "validation",
                "recommendation": str(item.get("recommendation", "")).strip(),
                "engineering_issue_metadata": deepcopy(
                    coerce_dict(item.get("metadata"), "engineering_validation.issue.metadata")
                ),
            }

            proposed_record = {
                "field_record_id": f"eng_validation_field_{next_index:05d}",
                "field_path": field_path,
                "value": None,
                "source_stage": "validation",
                "source_type": "engineering_validation",
                "source_ref": [issue_code],
                "confidence_score": None,
                "confidence_tag": "UNRESOLVED" if severity in {"error", "warning"} else "MODERATE",
                "validation_status": validation_status,
                "review_status": review_status,
                "evidence_strength": "UNKNOWN",
                "conflict_status": conflict_status,
                "is_missing": False,
                "metadata": metadata,
            }

            record_key = _record_key(proposed_record)
            if proposed_record["field_record_id"] in existing_ids:
                continue
            if record_key in existing_keys:
                continue

            synthesized_records.append(proposed_record)
            existing_ids.add(proposed_record["field_record_id"])
            existing_keys.add(record_key)
            existing_engineering_issue_keys.add(issue_key)
            next_index += 1

    return synthesized_records

def _build_calibration_governance_summary(
    calibration_records: list[dict[str, Any]],
) -> dict[str, int]:
    calibration_record_count = 0
    calibrated_match_count = 0
    calibration_review_required_count = 0
    calibration_conflict_count = 0
    calibration_open_review_count = 0
    calibration_closed_review_count = 0
    error_severity_count = 0
    warning_severity_count = 0
    info_severity_count = 0

    for item in calibration_records:
        if not isinstance(item, dict):
            continue

        calibration_record_count += 1
        status = str(item.get("status", "")).strip().upper()
        reviewer_status = str(item.get("reviewer_status", "")).strip().upper()
        severity = str(item.get("severity", "")).strip().lower()

        if status == "CALIBRATED_MATCH":
            calibrated_match_count += 1
        elif status == "CALIBRATION_REVIEW_REQUIRED":
            calibration_review_required_count += 1
        elif status == "CALIBRATION_CONFLICT":
            calibration_conflict_count += 1

        if reviewer_status == "OPEN":
            calibration_open_review_count += 1
        elif reviewer_status == "CLOSED":
            calibration_closed_review_count += 1

        if severity == "error":
            error_severity_count += 1
        elif severity == "warning":
            warning_severity_count += 1
        elif severity == "info":
            info_severity_count += 1

    return {
        "calibration_record_count": calibration_record_count,
        "calibrated_match_count": calibrated_match_count,
        "calibration_review_required_count": calibration_review_required_count,
        "calibration_conflict_count": calibration_conflict_count,
        "calibration_open_review_count": calibration_open_review_count,
        "calibration_closed_review_count": calibration_closed_review_count,
        "calibration_error_severity_count": error_severity_count,
        "calibration_warning_severity_count": warning_severity_count,
        "calibration_info_severity_count": info_severity_count,
    }


def _build_reconciliation_governance_summary(
    reconciliation_records: list[dict[str, Any]],
) -> dict[str, int]:
    reconciliation_record_count = 0
    reconciliation_open_count = 0
    reconciliation_closed_count = 0
    reconciliation_conflict_count = 0
    reconciliation_review_required_count = 0
    reconciliation_error_severity_count = 0
    reconciliation_warning_severity_count = 0

    for item in reconciliation_records:
        if not isinstance(item, dict):
            continue

        reconciliation_record_count += 1
        reviewer_status = str(item.get("reviewer_status", "")).strip().upper()
        reconciliation_status = str(item.get("reconciliation_status", "")).strip().upper()
        severity = str(item.get("severity", "")).strip().lower()

        if reviewer_status == "OPEN":
            reconciliation_open_count += 1
        elif reviewer_status == "CLOSED":
            reconciliation_closed_count += 1

        if reconciliation_status == "CALIBRATION_CONFLICT":
            reconciliation_conflict_count += 1
        elif reconciliation_status == "CALIBRATION_REVIEW_REQUIRED":
            reconciliation_review_required_count += 1

        if severity == "error":
            reconciliation_error_severity_count += 1
        elif severity == "warning":
            reconciliation_warning_severity_count += 1

    return {
        "reconciliation_record_count": reconciliation_record_count,
        "reconciliation_open_count": reconciliation_open_count,
        "reconciliation_closed_count": reconciliation_closed_count,
        "reconciliation_conflict_count": reconciliation_conflict_count,
        "reconciliation_review_required_count": reconciliation_review_required_count,
        "reconciliation_error_severity_count": reconciliation_error_severity_count,
        "reconciliation_warning_severity_count": reconciliation_warning_severity_count,
    }

def _merge_conflicts(
    *,
    existing_conflicts: list[dict[str, Any]],
    calibration_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_conflicts: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, tuple[Any, ...]]] = set()

    for item in existing_conflicts:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("field_path", "")).strip(),
            str(item.get("conflict_type", "")).strip(),
            tuple(
                _canonical_compare_value(value)
                for value in coerce_list(item.get("candidate_values"), "conflict.candidate_values")
            ),
        )
        if key in seen_keys:
            continue
        merged_conflicts.append(deepcopy(item))
        seen_keys.add(key)

    for calibration_record in calibration_records:
        if not isinstance(calibration_record, dict):
            continue

        status = str(calibration_record.get("status", "")).strip()
        if status != "CALIBRATION_CONFLICT":
            continue

        field_path = str(calibration_record.get("field_path", "")).strip()
        candidate_values = [
            calibration_record.get("expected_value"),
            calibration_record.get("observed_value"),
        ]

        key = (
            field_path,
            "CALIBRATION_CONFLICT",
            tuple(_canonical_compare_value(value) for value in candidate_values),
        )
        if key in seen_keys:
            continue

        merged_conflicts.append(
            {
                "field_path": field_path,
                "conflict_type": "CALIBRATION_CONFLICT",
                "severity": "error",
                "status": "OPEN",
                "record_ids": [
                    value
                    for value in (
                        str(entry).strip()
                        for entry in coerce_list(
                            calibration_record.get("linked_field_record_ids"),
                            "calibration_record.linked_field_record_ids",
                        )
                    )
                    if value
                ],
                "candidate_values": candidate_values,
                "source_stages": ["validation"],
                "details": {
                    "dataset_id": calibration_record.get("dataset_id"),
                    "deviation": deepcopy(coerce_dict(calibration_record.get("deviation"), "calibration_record.deviation")),
                },
            }
        )
        seen_keys.add(key)

    return merged_conflicts


def _merge_review_flags(
    *,
    canonical_state: dict[str, Any],
    engineering_review_flags: list[dict[str, Any]],
    calibration_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_flags = [
        deepcopy(item)
        for item in coerce_list(canonical_state.get("review_flags"), "canonical_state.review_flags")
        if isinstance(item, dict)
    ]

    merged = list(existing_flags)
    existing_keys: set[tuple[str, str, str]] = set()

    for item in merged:
        key = (
            str(item.get("category", "")).strip(),
            str(item.get("field_path", "")).strip(),
            str(item.get("message", "")).strip(),
        )
        existing_keys.add(key)

    for item in engineering_review_flags:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("category", "")).strip(),
            str(item.get("field_path", "")).strip(),
            str(item.get("message", "")).strip(),
        )
        if key in existing_keys:
            continue
        merged.append(deepcopy(item))
        existing_keys.add(key)

    for calibration_record in calibration_records:
        if not isinstance(calibration_record, dict):
            continue

        status = str(calibration_record.get("status", "")).strip()
        if status not in {"CALIBRATION_REVIEW_REQUIRED", "CALIBRATION_CONFLICT"}:
            continue

        field_path = str(calibration_record.get("field_path", "")).strip()
        message = f"Calibration comparison requires review for '{field_path}'."
        key = ("CALIBRATION_REVIEW_REQUIRED", field_path, message)
        if key in existing_keys:
            continue

        merged.append(
            {
                "review_flag_id": f"{str(calibration_record.get('calibration_record_id', 'calibration')).strip()}__review_flag",
                "category": "CALIBRATION_REVIEW_REQUIRED",
                "severity": "warning" if status == "CALIBRATION_REVIEW_REQUIRED" else "error",
                "status": "OPEN",
                "message": message,
                "field_path": field_path,
                "record_ids": [
                    value
                    for value in (
                        str(entry).strip()
                        for entry in coerce_list(
                            calibration_record.get("linked_field_record_ids"),
                            "calibration_record.linked_field_record_ids",
                        )
                    )
                    if value
                ],
                "metadata": {
                    "calibration_record_id": calibration_record.get("calibration_record_id"),
                    "dataset_id": calibration_record.get("dataset_id"),
                    "status": status,
                },
            }
        )
        existing_keys.add(key)

    return merged


def _merge_reconciliation_records(
    *,
    canonical_state: dict[str, Any],
    comparison_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    existing_records = [
        deepcopy(item)
        for item in coerce_list(
            canonical_state.get("reconciliation_records"),
            "canonical_state.reconciliation_records",
        )
        if isinstance(item, dict)
    ]

    new_records = [
        deepcopy(item)
        for item in coerce_list(
            comparison_payload.get("reconciliation_records"),
            "calibration_comparison.reconciliation_records",
        )
        if isinstance(item, dict)
    ]

    merged = list(existing_records)
    existing_ids = _normalize_record_id_set(existing_records, "reconciliation_id")
    existing_keys = {
        (
            str(item.get("field_path", "")).strip(),
            str(item.get("reconciliation_status", "")).strip(),
            str(item.get("rationale", "")).strip(),
        )
        for item in existing_records
        if isinstance(item, dict)
    }

    for item in new_records:
        reconciliation_id = item.get("reconciliation_id")
        if isinstance(reconciliation_id, str) and reconciliation_id.strip() in existing_ids:
            continue

        key = (
            str(item.get("field_path", "")).strip(),
            str(item.get("reconciliation_status", "")).strip(),
            str(item.get("rationale", "")).strip(),
        )
        if key in existing_keys:
            continue

        merged.append(item)
        if isinstance(reconciliation_id, str) and reconciliation_id.strip():
            existing_ids.add(reconciliation_id.strip())
        existing_keys.add(key)

    return merged


def _merge_change_log(
    *,
    canonical_state: dict[str, Any],
    comparison_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    existing_entries = [
        deepcopy(item)
        for item in coerce_list(canonical_state.get("change_log"), "canonical_state.change_log")
        if isinstance(item, dict)
    ]
    new_entries = [
        deepcopy(item)
        for item in coerce_list(comparison_payload.get("change_log"), "calibration_comparison.change_log")
        if isinstance(item, dict)
    ]

    merged = list(existing_entries)
    existing_ids = _normalize_record_id_set(existing_entries, "change_id")
    existing_keys = {
        (
            str(item.get("change_type", "")).strip(),
            str(item.get("field_path", "")).strip(),
            _canonical_compare_value(item.get("prior_value")),
            _canonical_compare_value(item.get("new_value")),
            str(item.get("rationale", "")).strip(),
        )
        for item in existing_entries
        if isinstance(item, dict)
    }

    for item in new_entries:
        change_id = item.get("change_id")
        if isinstance(change_id, str) and change_id.strip() in existing_ids:
            continue

        normalized = deepcopy(item)
        changed_at = normalized.get("changed_at")
        if not isinstance(changed_at, str) or not changed_at.strip():
            normalized["changed_at"] = utc_now_iso()

        key = (
            str(normalized.get("change_type", "")).strip(),
            str(normalized.get("field_path", "")).strip(),
            _canonical_compare_value(normalized.get("prior_value")),
            _canonical_compare_value(normalized.get("new_value")),
            str(normalized.get("rationale", "")).strip(),
        )
        if key in existing_keys:
            continue

        merged.append(normalized)
        if isinstance(change_id, str) and change_id.strip():
            existing_ids.add(change_id.strip())
        existing_keys.add(key)

    return merged


def _merge_validation_runs(
    *,
    canonical_state: dict[str, Any],
    run_id: str,
    report_status: str,
    engineering_payload: dict[str, Any],
    dataset_payload: dict[str, Any],
    comparison_payload: dict[str, Any],
    validation_summary: dict[str, Any],
    reconciliation_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    existing_runs = [
        deepcopy(item)
        for item in coerce_list(canonical_state.get("validation_runs"), "canonical_state.validation_runs")
        if isinstance(item, dict)
    ]

    validation_run_id = f"{run_id}__phase4_validation"
    existing_ids = _normalize_record_id_set(existing_runs, "validation_run_id")
    if validation_run_id in existing_ids:
        return existing_runs

    datasets_used = [
        value
        for value in (
            str(entry).strip()
            for entry in coerce_list(
                coerce_dict(dataset_payload.get("summary"), "calibration_dataset.summary").get("dataset_ids"),
                "calibration_dataset.summary.dataset_ids",
            )
        )
        if value
    ]

    existing_runs.append(
        {
            "validation_run_id": validation_run_id,
            "rule_set_version": "phase_four_engineering_validation_v2",
            "executed_at": utc_now_iso(),
            "status": report_status,
            "datasets_used": datasets_used,
            "summary": {
                "engineering_validation": deepcopy(coerce_dict(engineering_payload.get("summary"), "engineering_validation.summary")),
                "calibration_summary": deepcopy(coerce_dict(comparison_payload.get("summary"), "calibration_comparison.summary")),
                "reconciliation_summary": deepcopy(reconciliation_summary),
                "validation_summary": deepcopy(validation_summary),
            },
            "metadata": {
                "phase": "phase_four",
                "source_stage": "validation",
                "engineering_validation_status": engineering_payload.get("status"),
                "calibration_comparison_status": comparison_payload.get("status"),
                "comparison_run_id": comparison_payload.get("comparison_run_id"),
                "compared_at": comparison_payload.get("compared_at"),
            },
        }
    )

    return existing_runs


def _extend_report_for_phase_four(
    *,
    report: ValidationReport,
    engineering_payload: dict[str, Any],
    comparison_payload: dict[str, Any],
    reconciliation_summary: dict[str, Any],
) -> None:
    engineering_errors = [
        item
        for item in coerce_list(engineering_payload.get("errors"), "engineering_validation.errors")
        if isinstance(item, dict)
    ]
    engineering_warnings = [
        item
        for item in coerce_list(engineering_payload.get("warnings"), "engineering_validation.warnings")
        if isinstance(item, dict)
    ]
    engineering_info = [
        item
        for item in coerce_list(engineering_payload.get("info"), "engineering_validation.info")
        if isinstance(item, dict)
    ]
    engineering_review_flags = [
        item
        for item in coerce_list(engineering_payload.get("review_flags"), "engineering_validation.review_flags")
        if isinstance(item, dict)
    ]

    calibration_summary = deepcopy(
        coerce_dict(comparison_payload.get("summary"), "calibration_comparison.summary")
    )
    change_log = [
        item
        for item in coerce_list(comparison_payload.get("change_log"), "calibration_comparison.change_log")
        if isinstance(item, dict)
    ]
    reconciliation_records = [
        item
        for item in coerce_list(comparison_payload.get("reconciliation_records"), "calibration_comparison.reconciliation_records")
        if isinstance(item, dict)
    ]

    report.engineering_validation = {
        "status": engineering_payload.get("status"),
        "summary": deepcopy(
            coerce_dict(engineering_payload.get("summary"), "engineering_validation.summary")
        ),
        "review_flag_count": len(engineering_review_flags),
        "error_count": len(engineering_errors),
        "warning_count": len(engineering_warnings),
        "info_count": len(engineering_info),
    }

    report.calibration_summary = {
        "status": comparison_payload.get("status"),
        "comparison_run_id": comparison_payload.get("comparison_run_id"),
        "compared_at": comparison_payload.get("compared_at"),
        "summary": calibration_summary,
        "calibration_record_count": calibration_summary.get("calibration_record_count", 0),
        "reconciliation_record_count": reconciliation_summary.get("reconciliation_record_count", 0),
        "reconciliation_open_count": reconciliation_summary.get("reconciliation_open_count", 0),
        "reconciliation_closed_count": reconciliation_summary.get("reconciliation_closed_count", 0),
        "calibration_conflict_count": calibration_summary.get("calibration_conflict_count", 0),
        "calibration_review_required_count": calibration_summary.get("calibration_review_required_count", 0),
        "change_log_count": len(change_log),
        "open_reconciliation_field_paths": sorted({
            str(item.get("field_path", "")).strip()
            for item in reconciliation_records
            if isinstance(item, dict) and str(item.get("reviewer_status", "")).strip().upper() == "OPEN" and str(item.get("field_path", "")).strip()
        }),
    }


def _merge_phase_four_issues(
    *,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
    info: list[ValidationIssue],
    engineering_payload: dict[str, Any],
    comparison_payload: dict[str, Any],
) -> None:
    for item in coerce_list(engineering_payload.get("errors"), "engineering_validation.errors"):
        if isinstance(item, (dict, ValidationIssue)):
            normalized = normalize_issue(item)
            append_issue(
                errors,
                code=normalized.code,
                severity=normalized.severity,
                message=normalized.message,
                field_path=normalized.field_path,
                source_stage=normalized.source_stage or "validation",
                recommendation=normalized.recommendation,
            )

    for item in coerce_list(engineering_payload.get("warnings"), "engineering_validation.warnings"):
        if isinstance(item, (dict, ValidationIssue)):
            normalized = normalize_issue(item)
            append_issue(
                warnings,
                code=normalized.code,
                severity=normalized.severity,
                message=normalized.message,
                field_path=normalized.field_path,
                source_stage=normalized.source_stage or "validation",
                recommendation=normalized.recommendation,
            )

    for item in coerce_list(engineering_payload.get("info"), "engineering_validation.info"):
        if isinstance(item, (dict, ValidationIssue)):
            normalized = normalize_issue(item)
            append_issue(
                info,
                code=normalized.code,
                severity=normalized.severity,
                message=normalized.message,
                field_path=normalized.field_path,
                source_stage=normalized.source_stage or "validation",
                recommendation=normalized.recommendation,
            )

    comparison_summary = coerce_dict(comparison_payload.get("summary"), "calibration_comparison.summary")
    calibration_record_count = comparison_summary.get("calibration_record_count", 0)
    if isinstance(calibration_record_count, int) and calibration_record_count > 0:
        append_issue(
            info,
            code="CALIBRATION_COMPARISON_COMPLETE",
            severity="info",
            message=f"Calibration comparison generated {calibration_record_count} calibration record(s).",
            source_stage="validation",
        )

    reconciliation_record_count = comparison_summary.get("reconciliation_record_count", 0)
    if isinstance(reconciliation_record_count, int) and reconciliation_record_count > 0:
        append_issue(
            warnings,
            code="CALIBRATION_RECONCILIATION_REQUIRED",
            severity="warning",
            message=f"Calibration comparison generated {reconciliation_record_count} reconciliation record(s).",
            source_stage="validation",
            recommendation="Review calibration mismatches before final export.",
        )



def validate_canonical_state(
    context: Any,
    canonical_state_result: dict[str, Any] | None = None,
    ingestion_result: dict[str, Any] | None = None,
    extraction_result: dict[str, Any] | None = None,
    interview_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = _require_run_id(context)
    audit_logger = initialize_audit_logger(context)

    audit_logger.log_event(
        event_type="validation_started",
        stage_name="validation",
        status="STARTED",
        message="Canonical state validation started.",
        metadata={"run_id": run_id},
    )

    try:
        if canonical_state_result is not None:
            if not isinstance(canonical_state_result, dict):
                raise TypeError(
                    f"canonical_state_result must be a dict, got {type(canonical_state_result).__name__}."
                )

            payload_run_id = canonical_state_result.get("run_id")
            if payload_run_id is not None and str(payload_run_id) != run_id:
                raise ValueError(
                    f"canonical_state_result run_id mismatch: expected {run_id}, got {payload_run_id}."
                )

            canonical_state = coerce_dict(
                canonical_state_result.get("canonical_state"),
                "canonical_state_result.canonical_state",
            )
            canonical_state = deepcopy(canonical_state)
        else:
            from services.canonical_state_service.service import build_canonical_state

            candidate_state_result = build_canonical_state(
                context=context,
                ingestion_result=ingestion_result,
                extraction_result=extraction_result,
                interview_result=interview_result,
                normalization_result=normalization_result,
                retrieval_result=retrieval_result,
            )
            canonical_state = coerce_dict(
                candidate_state_result.get("canonical_state"),
                "candidate_state_result.canonical_state",
            )
            canonical_state = deepcopy(canonical_state)

        errors, warnings, info, missing_fields, conflicts = _read_existing_report(canonical_state)

        _validate_required_sections(canonical_state, errors, warnings)
        _validate_stage_statuses(canonical_state, warnings)
        _validate_core_collections(canonical_state, warnings)
        _validate_normalized_input(canonical_state, errors, warnings)
        _validate_translation_outputs(canonical_state, warnings)
        _validate_scenarios(canonical_state, warnings)
        _validate_field_records(canonical_state, errors, warnings)
        _validate_multi_project_scope(canonical_state, warnings)
        _validate_artifact_classification(canonical_state, warnings)
        _validate_single_value_field_cardinality(canonical_state, warnings)
        _validate_numeric_sanity(canonical_state, warnings)

        assumption_registry = _build_assumption_registry(canonical_state)
        canonical_state["assumption_registry"] = assumption_registry

        dataset_payload = run_calibration_dataset_service(
            context=context,
            canonical_state=canonical_state,
            ingestion_result=None,
        )
        calibration_datasets = [
            deepcopy(item)
            for item in coerce_list(
                dataset_payload.get("calibration_datasets"),
                "calibration_dataset.calibration_datasets",
            )
            if isinstance(item, dict)
        ]
        canonical_state["calibration_datasets"] = calibration_datasets

        audit_logger.log_event(
            event_type="validation_calibration_dataset_complete",
            stage_name="validation",
            substage_name="calibration_dataset",
            status=str(dataset_payload.get("status", "COMPLETED")),
            message="Calibration dataset generation completed.",
            metadata={
                "calibration_dataset_count": len(calibration_datasets),
            },
        )

        engineering_payload = run_engineering_validation(
            canonical_state=canonical_state,
        )

        audit_logger.log_event(
            event_type="validation_engineering_checks_complete",
            stage_name="validation",
            substage_name="engineering_validation",
            status=str(engineering_payload.get("status", "COMPLETED")),
            message="Engineering validation completed.",
            metadata={
                "engineering_error_count": len(
                    [
                        item
                        for item in coerce_list(
                            engineering_payload.get("errors"),
                            "engineering_validation.errors",
                        )
                        if isinstance(item, dict)
                    ]
                ),
                "engineering_warning_count": len(
                    [
                        item
                        for item in coerce_list(
                            engineering_payload.get("warnings"),
                            "engineering_validation.warnings",
                        )
                        if isinstance(item, dict)
                    ]
                ),
                "engineering_review_flag_count": len(
                    [
                        item
                        for item in coerce_list(
                            engineering_payload.get("review_flags"),
                            "engineering_validation.review_flags",
                        )
                        if isinstance(item, dict)
                    ]
                ),
            },
        )

        comparison_payload = run_calibration_comparison_service(
            context=context,
            canonical_state=canonical_state,
            calibration_datasets=calibration_datasets,
        )
        calibration_records = [
            deepcopy(item)
            for item in coerce_list(
                comparison_payload.get("calibration_records"),
                "calibration_comparison.calibration_records",
            )
            if isinstance(item, dict)
        ]
        calibration_governance_summary = _build_calibration_governance_summary(
            calibration_records
        )

        audit_logger.log_event(
            event_type="validation_calibration_comparison_complete",
            stage_name="validation",
            substage_name="calibration_comparison",
            status=str(comparison_payload.get("status", "COMPLETED")),
            message="Calibration comparison completed.",
            metadata={
                "calibration_record_count": len(calibration_records),
                "reconciliation_record_count": int(
                    calibration_governance_summary.get("reconciliation_record_count", 0)
                )
                if isinstance(calibration_governance_summary, dict)
                else 0,
            },
        )

        field_records = [
            deepcopy(item)
            for item in coerce_list(
                canonical_state.get("field_records"),
                "canonical_state.field_records",
            )
            if isinstance(item, dict)
        ]

        generated_engineering_field_records = _build_engineering_validation_field_records(
            engineering_payload=engineering_payload,
            existing_field_records=field_records,
        )
        field_records.extend(generated_engineering_field_records)

        generated_calibration_field_records = _build_calibration_field_records(
            calibration_records=calibration_records,
            existing_field_records=field_records,
        )
        field_records.extend(generated_calibration_field_records)

        merged_conflicts = _merge_conflicts(
            existing_conflicts=conflicts,
            calibration_records=calibration_records,
        )
        merged_review_flags = _merge_review_flags(
            canonical_state=canonical_state,
            engineering_review_flags=[
                deepcopy(item)
                for item in coerce_list(
                    engineering_payload.get("review_flags"),
                    "engineering_validation.review_flags",
                )
                if isinstance(item, dict)
            ],
            calibration_records=calibration_records,
        )
        reconciliation_records = _merge_reconciliation_records(
            canonical_state=canonical_state,
            comparison_payload=comparison_payload,
        )
        change_log = _merge_change_log(
            canonical_state=canonical_state,
            comparison_payload=comparison_payload,
        )
        reconciliation_governance_summary = _build_reconciliation_governance_summary(
            reconciliation_records
        )

        (
            field_records,
            merged_conflicts,
            generated_reconciliation_records,
            generated_change_log,
            resolved_scalar_fields,
            generated_review_flags,
        ) = _reconcile_scalar_field_records(
            field_records=field_records,
            conflict_records=merged_conflicts,
            existing_reconciliation_records=reconciliation_records,
            existing_change_log=change_log,
            warnings=warnings,
            info=info,
        )
        reconciliation_records = reconciliation_records + generated_reconciliation_records
        change_log = change_log + generated_change_log

        merged_review_flags = _filter_resolved_review_flags(
            merged_review_flags,
            resolved_scalar_fields,
        )
        merged_review_flags.extend(generated_review_flags)

        field_records = _collapse_reconciled_scalar_noise(
            field_records=field_records,
            warnings=warnings,
            info=info,
        )

        _merge_phase_four_issues(
            errors=errors,
            warnings=warnings,
            info=info,
            engineering_payload=engineering_payload,
            comparison_payload=comparison_payload,
        )

        errors = _deduplicate_validation_issues(errors)
        warnings = _deduplicate_validation_issues(warnings)
        info = _deduplicate_validation_issues(info)
        merged_review_flags = _deduplicate_review_flags(merged_review_flags)

        canonical_state["field_records"] = field_records
        canonical_state["conflict_records"] = merged_conflicts
        canonical_state["review_flags"] = merged_review_flags
        canonical_state["calibration_datasets"] = calibration_datasets
        canonical_state["calibration_records"] = calibration_records
        canonical_state["assumption_registry"] = assumption_registry
        canonical_state["reconciliation_records"] = reconciliation_records
        canonical_state["change_log"] = change_log
        canonical_state["updated_at"] = utc_now_iso()

        field_record_summary = _count_field_record_statuses(field_records)

        summary = build_validation_summary(
            errors=errors,
            warnings=warnings,
            info=info,
            missing_fields=missing_fields,
            conflicts=merged_conflicts,
            field_records=field_records,
            reconciliation_records=reconciliation_records,
            engineering_validation=engineering_payload,
            calibration_summary=calibration_governance_summary,
        )
        summary.update(field_record_summary)
        summary.update(calibration_governance_summary)
        summary.update(reconciliation_governance_summary)
        planner_registry_coverage = summarize_registry_packet_coverage(
            canonical_state,
            {
                "missing_fields": missing_fields,
                "conflicts": merged_conflicts,
            },
        )
        summary["planner_registry_coverage"] = planner_registry_coverage
        summary["planner_registry_total_field_count"] = planner_registry_coverage.get("total_field_count", 0)
        summary["planner_registry_required_field_count"] = planner_registry_coverage.get("required_field_count", 0)
        summary["planner_registry_planner_critical_field_count"] = planner_registry_coverage.get("planner_critical_field_count", 0)
        summary["planner_registry_resolved_count"] = planner_registry_coverage.get("resolved_count", 0)
        summary["planner_registry_review_required_count"] = planner_registry_coverage.get("review_required_count", 0)
        summary["planner_registry_conflicting_count"] = planner_registry_coverage.get("conflicting_count", 0)
        summary["planner_registry_missing_count"] = planner_registry_coverage.get("missing_count", 0)
        summary["planner_registry_unresolved_count"] = planner_registry_coverage.get("unresolved_count", 0)
        registry_open_items = planner_registry_open_items(
            canonical_state,
            {
                "missing_fields": missing_fields,
                "conflicts": merged_conflicts,
            },
        )
        summary["planner_registry_open_items"] = registry_open_items
        summary["planner_registry_planner_critical_open_count"] = int(registry_open_items.get("planner_critical_open_count", 0))
        summary["planner_registry_required_missing_count"] = int(registry_open_items.get("required_missing_count", 0))
        summary["planner_registry_planner_critical_open_field_ids"] = list(registry_open_items.get("planner_critical_open_field_ids", []))
        resolution_queue = planner_registry_resolution_queue(
            canonical_state,
            {
                "missing_fields": missing_fields,
                "conflicts": merged_conflicts,
            },
        )
        summary["planner_registry_resolution_queue"] = resolution_queue
        summary["planner_registry_resolution_queue_count"] = len(resolution_queue)
        summary["planner_registry_resolution_queue_field_ids"] = [
            str(item.get("field_id", "")).strip()
            for item in resolution_queue
            if isinstance(item, dict) and str(item.get("field_id", "")).strip()
        ]
        field_resolution = build_field_resolution_result(
            canonical_state,
            {
                "missing_fields": missing_fields,
                "conflicts": merged_conflicts,
            },
        )
        summary["field_resolution_summary"] = dict(field_resolution.get("summary", {}))
        summary["field_resolution_backlog_count"] = int(field_resolution.get("backlog_count", 0))
        summary["field_resolution_backlog_field_ids"] = list(field_resolution.get("backlog_field_ids", []))
        summary["field_resolution_accepted_field_count"] = int(field_resolution.get("summary", {}).get("accepted_field_index_count", 0))
        summary["field_resolution_planner_review_count"] = int(field_resolution.get("summary", {}).get("planner_review_count", 0))
        summary["field_resolution_confirmation_needed_count"] = int(field_resolution.get("summary", {}).get("applicant_confirmation_needed_count", 0))
        summary["field_resolution_blocked_field_count"] = int(field_resolution.get("summary", {}).get("blocked_field_count", 0))
        summary["field_resolution_provisional_field_count"] = int(field_resolution.get("summary", {}).get("provisional_field_count", 0))
        summary["field_resolution_governance_posture"] = dict(field_resolution.get("governance_posture_summary", {})) if isinstance(field_resolution.get("governance_posture_summary"), dict) else {}
        summary["field_resolution_top_backlog_field_ids"] = list(field_resolution.get("backlog_field_ids", [])[:10])
        translation_schema_validation = {}
        translation_result_payload = canonical_state.get("translation_result") if isinstance(canonical_state.get("translation_result"), dict) else None
        if isinstance(translation_result_payload, dict):
            payload = translation_result_payload.get("schema_validation")
            if isinstance(payload, dict):
                translation_schema_validation = payload
        summary["translation_registry_parameter_count"] = int(translation_schema_validation.get("configured_parameter_count", 0))
        summary["translation_registry_present_parameter_count"] = int(translation_schema_validation.get("present_parameter_count", 0))
        summary["translation_registry_missing_parameter_count"] = int(translation_schema_validation.get("missing_parameter_count", 0))
        summary["review_flag_count"] = len(
            [item for item in merged_review_flags if isinstance(item, dict)]
        )
        summary["conflict_record_count"] = len(
            [item for item in merged_conflicts if isinstance(item, dict)]
        )
        summary["change_log_count"] = len([item for item in change_log if isinstance(item, dict)])
        summary["phase_four_status"] = {
            "engineering_validation_status": engineering_payload.get("status"),
            "calibration_comparison_status": comparison_payload.get("status"),
            "comparison_run_id": comparison_payload.get("comparison_run_id"),
            "compared_at": comparison_payload.get("compared_at"),
        }

        status = "VALIDATION_FAILED" if summary["is_blocked"] else "VALIDATED"

        report = ValidationReport(
            status=status,
            errors=errors,
            warnings=warnings,
            info=info,
            missing_fields=missing_fields,
            conflicts=merged_conflicts,
            summary=summary,
            engineering_validation={},
            calibration_summary={},
        )
        _extend_report_for_phase_four(
            report=report,
            engineering_payload=engineering_payload,
            comparison_payload=comparison_payload,
            reconciliation_summary=reconciliation_governance_summary,
        )
        report.calibration_summary.update(calibration_governance_summary)
        report.calibration_summary.update(reconciliation_governance_summary)

        validation_runs = _merge_validation_runs(
            canonical_state=canonical_state,
            run_id=run_id,
            report_status=status,
            engineering_payload=engineering_payload,
            dataset_payload=dataset_payload,
            comparison_payload=comparison_payload,
            validation_summary=summary,
            reconciliation_summary=reconciliation_governance_summary,
        )

        canonical_state["validation_runs"] = validation_runs
        canonical_state["field_resolution"] = field_resolution
        accepted_field_index = field_resolution.get("accepted_field_index") if isinstance(field_resolution, dict) else {}
        canonical_state["accepted_planner_field_index"] = dict(accepted_field_index) if isinstance(accepted_field_index, dict) else {}
        planner_packet_rows = build_planner_packet_field_rows(
            canonical_state,
            {
                "missing_fields": missing_fields,
                "conflicts": merged_conflicts,
                "summary": summary,
            },
            include_optional=True,
        )
        canonical_state["planner_packet_field_rows"] = {
            str(section_id): [dict(row) for row in rows if isinstance(row, dict)]
            for section_id, rows in planner_packet_rows.items()
        }
        packet_coverage_summary = summarize_registry_packet_coverage(
            canonical_state,
            {
                "missing_fields": missing_fields,
                "conflicts": merged_conflicts,
                "summary": summary,
            },
            include_optional=True,
        )
        summary["planner_registry_packet_coverage"] = packet_coverage_summary
        governance_summary = summarize_field_resolution_governance(
            canonical_state,
            {
                "missing_fields": missing_fields,
                "conflicts": merged_conflicts,
                "summary": summary,
            },
            include_optional=True,
        )
        summary["planner_registry_value_kind_counts"] = dict(governance_summary.get("value_kind_counts", {})) if isinstance(governance_summary.get("value_kind_counts"), dict) else {}
        summary["planner_registry_attention_tier_counts"] = dict(governance_summary.get("attention_tier_counts", {})) if isinstance(governance_summary.get("attention_tier_counts"), dict) else {}
        summary["planner_registry_source_stream_counts"] = dict(governance_summary.get("source_stream_counts", {})) if isinstance(governance_summary.get("source_stream_counts"), dict) else {}
        report.summary = summary
        canonical_state["validation_report"] = report.to_dict()

        stage_status = coerce_dict(
            canonical_state.get("stage_status"),
            "canonical_state.stage_status",
        )
        stage_status["validation"] = status
        canonical_state["stage_status"] = stage_status

        result = ValidationServiceResult(
            run_id=run_id,
            status=status,
            validation_report=report,
            canonical_state=canonical_state,
            validated_at=utc_now_iso(),
        )

        audit_logger.log_event(
            event_type="validation_completed",
            stage_name="validation",
            status=status,
            message="Canonical state validation completed.",
            metadata={
                "error_count": len(errors),
                "warning_count": len(warnings),
                "info_count": len(info),
                "missing_field_count": len(missing_fields),
                "review_flag_count": summary.get("review_flag_count", 0),
                "conflict_record_count": summary.get("conflict_record_count", 0),
                "is_blocked": bool(summary.get("is_blocked", False)),
                "validation_run_count": len(
                    [item for item in validation_runs if isinstance(item, dict)]
                ),
            },
        )

        return result.to_dict()

    except Exception as exc:
        audit_logger.log_event(
            event_type="validation_failed",
            stage_name="validation",
            status="FAILED",
            message="Canonical state validation failed with exception.",
            metadata={
                "error": str(exc),
            },
        )
        raise




def _extract_interview_readiness(interview_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(interview_result, dict):
        return {}

    readiness = interview_result.get("interview_readiness")
    if isinstance(readiness, dict) and readiness:
        return deepcopy(readiness)

    oversight = interview_result.get("interview_oversight")
    if isinstance(oversight, dict):
        readiness = oversight.get("interview_readiness_summary")
        if isinstance(readiness, dict) and readiness:
            return deepcopy(readiness)

    session = interview_result.get("interview_session")
    if isinstance(session, dict):
        readiness = session.get("interview_oversight")
        if isinstance(readiness, dict):
            summary = readiness.get("interview_readiness_summary")
            if isinstance(summary, dict) and summary:
                return deepcopy(summary)

    return {}


def _apply_interview_readiness_to_validation_result(
    *,
    result_payload: dict[str, Any],
    interview_result: dict[str, Any] | None,
) -> dict[str, Any]:
    readiness = _extract_interview_readiness(interview_result)
    if not readiness:
        return result_payload

    validation_report = coerce_dict(result_payload.get("validation_report"), "validation_report")
    summary = coerce_dict(validation_report.get("summary"), "validation_report.summary")
    warnings = coerce_list(validation_report.get("warnings"), "validation_report.warnings")
    errors = coerce_list(validation_report.get("errors"), "validation_report.errors")

    blocking_categories = [
        str(item).strip()
        for item in coerce_list(readiness.get("blocking_categories"), "interview_readiness.blocking_categories")
        if str(item).strip()
    ]
    ready_for_validation = bool(readiness.get("ready_for_validation", False))
    ready_for_final_output = bool(readiness.get("ready_for_final_output", False))
    completion_state = str(readiness.get("completion_state", "UNKNOWN")).strip() or "UNKNOWN"

    summary["interview_readiness"] = deepcopy(readiness)
    summary["interview_ready_for_validation"] = ready_for_validation
    summary["interview_ready_for_final_output"] = ready_for_final_output
    summary["interview_completion_state"] = completion_state
    summary["interview_blocking_category_count"] = len(blocking_categories)
    summary["interview_planner_critical_remaining_question_count"] = int(readiness.get("planner_critical_remaining_question_count", 0) or 0)
    summary["interview_planner_critical_open_clarification_count"] = int(readiness.get("planner_critical_open_clarification_count", 0) or 0)
    summary["interview_planner_critical_conflicting_field_count"] = int(readiness.get("planner_critical_conflicting_field_count", 0) or 0)
    summary["final_export_ready"] = ready_for_final_output
    summary["final_export_blockers"] = {
        "blocking_categories": list(blocking_categories),
        "planner_critical_remaining_question_count": int(readiness.get("planner_critical_remaining_question_count", 0) or 0),
        "planner_critical_open_clarification_count": int(readiness.get("planner_critical_open_clarification_count", 0) or 0),
        "planner_critical_conflicting_field_count": int(readiness.get("planner_critical_conflicting_field_count", 0) or 0),
    }

    if not ready_for_validation:
        issue = ValidationIssue(
            code="INTERVIEW_INCOMPLETE",
            severity="ERROR",
            message=(
                "Applicant interview is not sufficiently complete for validation or final export."
            ),
            source_stage="interview",
            recommendation=(
                "Complete the applicant interview for missing, conflicting, or low-confidence fields before final export."
            ),
        ).to_dict()
        if issue not in errors:
            errors.append(issue)
        result_payload["status"] = "VALIDATION_FAILED"

    elif not ready_for_final_output or blocking_categories:
        issue = ValidationIssue(
            code="INTERVIEW_REVIEW_REQUIRED",
            severity="WARNING",
            message=(
                "Applicant interview indicates remaining review-required or low-confidence items."
            ),
            source_stage="interview",
            recommendation=(
                "Carry interview blockers forward into planner review and final packet notes."
            ),
        ).to_dict()
        if issue not in warnings:
            warnings.append(issue)

    validation_report["summary"] = summary
    validation_report["warnings"] = warnings
    validation_report["errors"] = errors
    validation_report["interview_readiness"] = deepcopy(readiness)
    result_payload["validation_report"] = validation_report

    result_summary = coerce_dict(result_payload.get("summary"), "result.summary")
    result_summary.update(summary)
    result_payload["summary"] = result_summary

    canonical_state = result_payload.get("canonical_state")
    if isinstance(canonical_state, dict):
        canonical_state["interview_readiness"] = deepcopy(readiness)
        canonical_state["validation_report"] = deepcopy(validation_report)

    return result_payload
def run_service(
    context: Any,
    canonical_state_result: dict[str, Any] | None = None,
    ingestion_result: dict[str, Any] | None = None,
    extraction_result: dict[str, Any] | None = None,
    interview_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    gap_resolution_result: dict[str, Any] | None = None,
    translation_result: dict[str, Any] | None = None,
    scenario_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_canonical_state_result = canonical_state_result

    retrieval_result, interview_result = resolve_gap_resolution_stage_inputs(
        retrieval_result=retrieval_result,
        interview_result=interview_result,
        gap_resolution_result=gap_resolution_result,
    )

    if effective_canonical_state_result is None:
        effective_canonical_state_result = build_canonical_state(
            context=context,
            ingestion_result=ingestion_result,
            extraction_result=extraction_result,
            interview_result=interview_result,
            normalization_result=normalization_result,
            retrieval_result=retrieval_result,
            translation_result=translation_result,
            scenario_result=scenario_result,
        )

    return validate_canonical_state(
        context=context,
        canonical_state_result=effective_canonical_state_result,
    )
