from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _field_record_lookup(field_records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}
    for record in field_records:
        if not isinstance(record, dict):
            continue
        field_path = _safe_str(record.get("field_path"))
        if not field_path:
            continue
        lookup.setdefault(field_path, []).append(record)
    return lookup


def _primary_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None

    for record in records:
        if record.get("is_primary") is True:
            return record

    return records[0]


def _deviation_payload(expected: float, observed: float) -> dict[str, Any]:
    absolute = observed - expected
    percent = 0.0
    if not math.isclose(expected, 0.0):
        percent = (absolute / expected) * 100.0
    return {
        "absolute": round(absolute, 6),
        "percent": round(percent, 6),
    }


def _determine_status(percent_delta: float, tolerance_percent: float) -> str:
    if abs(percent_delta) <= tolerance_percent:
        return "CALIBRATED_MATCH"
    if abs(percent_delta) <= tolerance_percent * 2:
        return "CALIBRATION_REVIEW_REQUIRED"
    return "CALIBRATION_CONFLICT"


def _status_severity(status: str) -> str:
    if status == "CALIBRATION_CONFLICT":
        return "error"
    if status == "CALIBRATION_REVIEW_REQUIRED":
        return "warning"
    return "info"


def _recommended_action(status: str) -> str:
    if status == "CALIBRATION_CONFLICT":
        return "Preserve the governed value, surface the conflict, and require engineering reconciliation before export sign-off."
    if status == "CALIBRATION_REVIEW_REQUIRED":
        return "Keep the governed value provisional and request engineering review of the observed deviation."
    return "No reconciliation action is required beyond recording calibration lineage."


def _reviewer_status(status: str) -> str:
    if status == "CALIBRATION_MATCH":
        return "CLOSED"
    if status == "CALIBRATED_MATCH":
        return "CLOSED"
    if status == "CALIBRATION_REVIEW_REQUIRED":
        return "OPEN"
    if status == "CALIBRATION_CONFLICT":
        return "OPEN"
    return "OPEN"


def _source_anchor_summary(parameter: dict[str, Any]) -> list[dict[str, Any]]:
    source_ref = parameter.get("source_ref", [])
    if not isinstance(source_ref, list):
        return []

    anchors: list[dict[str, Any]] = []
    for item in source_ref:
        if not isinstance(item, dict):
            continue
        anchors.append(
            {
                "artifact_id": _safe_str(item.get("artifact_id")),
                "page": item.get("page"),
                "snippet_id": _safe_str(item.get("snippet_id")),
                "source_name": _safe_str(item.get("source_name")),
            }
        )
    return anchors


def _record_lineage(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}

    metadata = _coerce_dict(record.get("metadata"))
    return {
        "field_record_id": _safe_str(record.get("field_record_id")),
        "source_stage": _safe_str(record.get("source_stage")),
        "source_type": _safe_str(record.get("source_type")),
        "validation_status": _safe_str(record.get("validation_status")),
        "review_status": _safe_str(record.get("review_status")),
        "conflict_status": _safe_str(record.get("conflict_status")),
        "evidence_strength": _safe_str(record.get("evidence_strength")),
        "source_artifact_id": _safe_str(record.get("source_artifact_id")),
        "source_method": _safe_str(metadata.get("source_method")),
    }


def _linked_record_ids(records_for_path: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for record in records_for_path:
        if not isinstance(record, dict):
            continue
        field_record_id = _safe_str(record.get("field_record_id"))
        if field_record_id:
            result.append(field_record_id)
    return result


def _assumption_ids_by_path(assumptions: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for assumption in assumptions:
        if not isinstance(assumption, dict):
            continue

        path = _safe_str(assumption.get("field_path") or assumption.get("parameter_path"))
        assumption_id = _safe_str(assumption.get("assumption_id"))
        if path and assumption_id:
            result.setdefault(path, []).append(assumption_id)

    return result


def _comparison_reason(status: str, deviation_percent: float, tolerance_percent: float) -> str:
    if status == "CALIBRATED_MATCH":
        return (
            f"Observed value is within the allowed tolerance band. "
            f"Deviation {round(deviation_percent, 6)}% is within ±{round(tolerance_percent, 6)}%."
        )
    if status == "CALIBRATION_REVIEW_REQUIRED":
        return (
            f"Observed value exceeds the primary tolerance band but remains within the review band. "
            f"Deviation {round(deviation_percent, 6)}% exceeds ±{round(tolerance_percent, 6)}% "
            f"but does not exceed ±{round(tolerance_percent * 2, 6)}%."
        )
    return (
        f"Observed value materially deviates from the governed value. "
        f"Deviation {round(deviation_percent, 6)}% exceeds the conflict threshold of ±{round(tolerance_percent * 2, 6)}%."
    )


def compare_against_datasets(
    *,
    canonical_state: dict[str, Any],
    calibration_datasets: list[dict[str, Any]],
    comparison_run_id: str,
) -> dict[str, Any]:
    field_records = canonical_state.get("field_records", [])
    if not isinstance(field_records, list):
        field_records = []

    assumptions = canonical_state.get("assumption_registry", [])
    if not isinstance(assumptions, list):
        assumptions = []

    field_lookup = _field_record_lookup(field_records)
    assumption_lookup = _assumption_ids_by_path(assumptions)

    calibration_records: list[dict[str, Any]] = []
    reconciliation_records: list[dict[str, Any]] = []
    change_log: list[dict[str, Any]] = []

    matched_count = 0
    review_required_count = 0
    conflict_count = 0
    skipped_count = 0

    for dataset in calibration_datasets:
        if not isinstance(dataset, dict):
            continue

        dataset_id = _safe_str(dataset.get("dataset_id"))
        dataset_type = _safe_str(dataset.get("dataset_type")) or "ENGINEERING_REFERENCE"
        dataset_version = _safe_str(dataset.get("version")) or "1.0.0"
        source_artifact_id = _safe_str(dataset.get("source_artifact_id"))
        source_file_name = _safe_str(dataset.get("source_file_name"))

        parameters = dataset.get("parameters", [])
        if not isinstance(parameters, list):
            parameters = []

        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue

            field_path = _safe_str(parameter.get("field_path"))
            if not field_path:
                skipped_count += 1
                continue

            observed_value = parameter.get("normalized_value", parameter.get("value"))
            observed_numeric = _safe_float(observed_value)

            records_for_path = field_lookup.get(field_path, [])
            primary = _primary_record(records_for_path)
            expected_value = primary.get("value") if isinstance(primary, dict) else None
            expected_numeric = _safe_float(expected_value)

            if observed_numeric is None or expected_numeric is None:
                skipped_count += 1
                continue

            parameter_metadata = _coerce_dict(parameter.get("metadata"))
            tolerance_percent = _safe_float(parameter_metadata.get("tolerance_percent"))
            if tolerance_percent is None:
                tolerance_percent = 5.0

            deviation = _deviation_payload(expected_numeric, observed_numeric)
            status = _determine_status(
                percent_delta=float(deviation["percent"]),
                tolerance_percent=tolerance_percent,
            )
            severity = _status_severity(status)
            reviewer_status = _reviewer_status(status)
            recommendation = _recommended_action(status)
            rationale = _comparison_reason(
                status=status,
                deviation_percent=float(deviation["percent"]),
                tolerance_percent=tolerance_percent,
            )

            if status == "CALIBRATED_MATCH":
                matched_count += 1
            elif status == "CALIBRATION_REVIEW_REQUIRED":
                review_required_count += 1
            elif status == "CALIBRATION_CONFLICT":
                conflict_count += 1

            linked_field_record_ids = _linked_record_ids(records_for_path)
            linked_assumption_ids = assumption_lookup.get(field_path, [])
            source_anchors = _source_anchor_summary(parameter)

            calibration_record_id = f"calrec_{uuid.uuid4().hex[:12]}"
            calibration_records.append(
                {
                    "calibration_record_id": calibration_record_id,
                    "comparison_run_id": comparison_run_id,
                    "field_path": field_path,
                    "expected_value": expected_value,
                    "observed_value": observed_value,
                    "adjusted_value": expected_value if status == "CALIBRATED_MATCH" else observed_value,
                    "tolerance": {
                        "percent": tolerance_percent,
                        "units": "%",
                    },
                    "deviation": deviation,
                    "status": status,
                    "severity": severity,
                    "reviewer_status": reviewer_status,
                    "recommended_action": recommendation,
                    "dataset_id": dataset_id,
                    "dataset_type": dataset_type,
                    "dataset_version": dataset_version,
                    "source_artifact_id": source_artifact_id,
                    "source_file_name": source_file_name,
                    "linked_field_record_ids": linked_field_record_ids,
                    "linked_assumption_ids": linked_assumption_ids,
                    "evidence_refs": parameter.get("source_ref", []),
                    "source_anchors": source_anchors,
                    "lineage": {
                        "comparison_recorded_at": _utc_now_iso(),
                        "primary_record": _record_lineage(primary),
                    },
                    "metadata": {
                        "parameter_metadata": parameter_metadata,
                        "comparison_rationale": rationale,
                    },
                }
            )

            if status != "CALIBRATED_MATCH":
                reconciliation_id = f"recon_{uuid.uuid4().hex[:12]}"
                reconciliation_records.append(
                    {
                        "reconciliation_id": reconciliation_id,
                        "comparison_run_id": comparison_run_id,
                        "field_path": field_path,
                        "reconciliation_status": status,
                        "severity": severity,
                        "reviewer_status": reviewer_status,
                        "recommended_action": recommendation,
                        "rationale": rationale,
                        "conflicting_record_ids": linked_field_record_ids,
                        "linked_assumption_ids": linked_assumption_ids,
                        "evidence_refs": parameter.get("source_ref", []),
                        "source_anchors": source_anchors,
                        "metadata": {
                            "dataset_id": dataset_id,
                            "dataset_type": dataset_type,
                            "dataset_version": dataset_version,
                            "source_artifact_id": source_artifact_id,
                            "source_file_name": source_file_name,
                            "expected_value": expected_value,
                            "observed_value": observed_value,
                            "deviation_percent": deviation["percent"],
                            "tolerance_percent": tolerance_percent,
                            "primary_record_lineage": _record_lineage(primary),
                        },
                    }
                )

                change_log.append(
                    {
                        "change_id": f"chg_{uuid.uuid4().hex[:12]}",
                        "changed_at": _utc_now_iso(),
                        "change_type": "CALIBRATION_COMPARISON_RECORDED",
                        "field_path": field_path,
                        "prior_value": expected_value,
                        "new_value": observed_value,
                        "rationale": "Observed calibration comparison recorded without overwriting governed value.",
                        "metadata": {
                            "comparison_run_id": comparison_run_id,
                            "dataset_id": dataset_id,
                            "dataset_type": dataset_type,
                            "dataset_version": dataset_version,
                            "calibration_record_id": calibration_record_id,
                            "status": status,
                            "severity": severity,
                            "recommended_action": recommendation,
                        },
                    }
                )

    return {
        "status": "CALIBRATION_COMPARISON_COMPLETE",
        "comparison_run_id": comparison_run_id,
        "compared_at": _utc_now_iso(),
        "calibration_records": calibration_records,
        "reconciliation_records": reconciliation_records,
        "change_log": change_log,
        "summary": {
            "dataset_count": len([item for item in calibration_datasets if isinstance(item, dict)]),
            "calibration_record_count": len(calibration_records),
            "reconciliation_record_count": len(reconciliation_records),
            "change_log_count": len(change_log),
            "matched_count": matched_count,
            "review_required_count": review_required_count,
            "conflict_count": conflict_count,
            "skipped_count": skipped_count,
        },
    }


def run_service(
    *,
    context: Any,
    canonical_state: dict[str, Any],
    calibration_datasets: list[dict[str, Any]],
) -> dict[str, Any]:
    run_id = _safe_str(getattr(context, "run_id", None))
    if not run_id:
        raise ValueError("context.run_id must be a non-empty string.")

    comparison_run_id = f"{run_id}::calibration_compare"
    payload = compare_against_datasets(
        canonical_state=canonical_state,
        calibration_datasets=calibration_datasets,
        comparison_run_id=comparison_run_id,
    )
    payload["run_id"] = run_id
    return payload