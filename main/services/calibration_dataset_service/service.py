from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any


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


def _normalize_unit(unit: str) -> str:
    normalized = unit.strip().lower()
    mapping = {
        "mw": "MW",
        "kw": "kW",
        "mva": "MVA",
        "kva": "kVA",
        "kv": "kV",
        "v": "V",
        "a": "A",
        "amp": "A",
        "amps": "A",
        "ohm": "ohm",
        "%": "%",
        "pu": "pu",
        "hz": "Hz",
    }
    return mapping.get(normalized, unit.strip())


def _convert_numeric_value(value: float, from_unit: str, to_unit: str) -> float:
    source = from_unit.strip().lower()
    target = to_unit.strip().lower()

    if source == target:
        return value

    conversion_table: dict[tuple[str, str], float] = {
        ("kw", "mw"): 0.001,
        ("mw", "kw"): 1000.0,
        ("kva", "mva"): 0.001,
        ("mva", "kva"): 1000.0,
        ("v", "kv"): 0.001,
        ("kv", "v"): 1000.0,
    }

    factor = conversion_table.get((source, target))
    if factor is None:
        return value
    return value * factor


def _normalize_parameter(item: dict[str, Any]) -> dict[str, Any]:
    field_path = _safe_str(item.get("field_path"))
    value = item.get("value")
    units = _safe_str(item.get("units"))
    target_units = _safe_str(item.get("target_units")) or units

    normalized_units = _normalize_unit(units) if units else ""
    normalized_target_units = _normalize_unit(target_units) if target_units else normalized_units

    numeric_value = _safe_float(value)
    normalized_value: Any = value
    if numeric_value is not None and normalized_units and normalized_target_units:
        normalized_value = _convert_numeric_value(
            numeric_value,
            normalized_units,
            normalized_target_units,
        )
        if isinstance(normalized_value, float):
            normalized_value = round(normalized_value, 6)

    return {
        "field_path": field_path,
        "value": value,
        "normalized_value": normalized_value,
        "units": normalized_units,
        "target_units": normalized_target_units,
        "source_ref": item.get("source_ref", []),
        "metadata": deepcopy(item.get("metadata", {}))
        if isinstance(item.get("metadata"), dict)
        else {},
    }


def _build_dataset_record(
    *,
    dataset: dict[str, Any],
    artifact_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    dataset_id = _safe_str(dataset.get("dataset_id")) or f"calds_{uuid.uuid4().hex[:12]}"
    dataset_type = _safe_str(dataset.get("dataset_type")) or "ENGINEERING_REFERENCE"
    version = _safe_str(dataset.get("version")) or "1.0.0"
    source_artifact_id = _safe_str(dataset.get("source_artifact_id"))
    source_artifact = artifact_lookup.get(source_artifact_id, {}) if source_artifact_id else {}
    source_file_name = _safe_str(dataset.get("source_file_name")) or _safe_str(source_artifact.get("file_name"))

    parameters = dataset.get("parameters", [])
    if not isinstance(parameters, list):
        parameters = []

    normalized_parameters = [
        _normalize_parameter(item)
        for item in parameters
        if isinstance(item, dict) and _safe_str(item.get("field_path"))
    ]

    provenance = dataset.get("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}

    metadata = dataset.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    metadata.setdefault("parameter_count", len(normalized_parameters))
    metadata.setdefault("schema_valid", True)

    return {
        "dataset_id": dataset_id,
        "dataset_type": dataset_type,
        "version": version,
        "source_artifact_id": source_artifact_id,
        "source_file_name": source_file_name,
        "provenance": {
            "source_stage": "calibration_dataset_service",
            **deepcopy(provenance),
        },
        "parameters": normalized_parameters,
        "metadata": metadata,
    }


def build_calibration_datasets(
    *,
    canonical_state: dict[str, Any],
    ingestion_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    artifacts = canonical_state.get("artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []

    artifact_lookup: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = _safe_str(artifact.get("artifact_id"))
        if artifact_id:
            artifact_lookup[artifact_id] = artifact

    candidate_payloads: list[dict[str, Any]] = []

    existing = canonical_state.get("calibration_datasets", [])
    if isinstance(existing, list):
        candidate_payloads.extend(item for item in existing if isinstance(item, dict))

    if isinstance(ingestion_result, dict):
        discovered = ingestion_result.get("calibration_datasets", [])
        if isinstance(discovered, list):
            candidate_payloads.extend(item for item in discovered if isinstance(item, dict))

    normalized_records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for payload in candidate_payloads:
        record = _build_dataset_record(dataset=payload, artifact_lookup=artifact_lookup)
        dataset_id = _safe_str(record.get("dataset_id"))
        if not dataset_id or dataset_id in seen_ids:
            continue
        seen_ids.add(dataset_id)
        normalized_records.append(record)

    return normalized_records


def run_service(
    *,
    context: Any,
    canonical_state: dict[str, Any],
    ingestion_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = _safe_str(getattr(context, "run_id", None))
    if not run_id:
        raise ValueError("context.run_id must be a non-empty string.")

    datasets = build_calibration_datasets(
        canonical_state=canonical_state,
        ingestion_result=ingestion_result,
    )

    return {
        "run_id": run_id,
        "status": "CALIBRATION_DATASETS_READY",
        "calibration_datasets": datasets,
        "summary": {
            "dataset_count": len(datasets),
            "dataset_ids": [item["dataset_id"] for item in datasets],
        },
    }