"""
GridSenpAI Ingestion Service

Responsibility
--------------
Accept facility engineering artifacts and register them within the
GridSenpAI project workspace.

Responsibilities include:
- artifact registration
- metadata extraction
- storage reference tracking
- indexing preparation
- governed intake session persistence
- required artifact category tracking
- Phase 4 calibration dataset candidate discovery

Inputs
------
Artifact file paths or storage URIs.

Outputs
-------
Artifact metadata records used by downstream extraction services.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.ingestion_service.models import (
    ArtifactRecord,
    ArtifactRequirement,
    IngestionResult,
    IntakeSession,
)
from services.ingestion_service.utils import (
    build_artifact_id,
    build_intake_session_id,
    build_requirement_catalog,
    classify_artifact,
    compute_sha256,
    derive_tags,
    estimate_page_count,
    guess_mime_type,
    intake_session_path,
    iter_supported_artifacts,
    requirement_ids_for_classification,
    requirement_ids_for_file,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_id_from_context(context: Any) -> str:
    config = getattr(context, "config", None)
    project_name = getattr(config, "project_name", None)
    if isinstance(project_name, str) and project_name.strip():
        return project_name.strip()

    for attr in ("replay_source_run_id", "parent_run_id", "run_id"):
        value = getattr(context, attr, None)
        if isinstance(value, str) and value.strip():
            return f"UNRESOLVED_PROJECT::{value.strip()}"

    return "UNRESOLVED_PROJECT"


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def _build_requirement_models() -> list[ArtifactRequirement]:
    requirements: list[ArtifactRequirement] = []
    for item in build_requirement_catalog():
        requirements.append(
            ArtifactRequirement(
                requirement_id=str(item["requirement_id"]),
                label=str(item["label"]),
                description=str(item["description"]),
                guidance=str(item["guidance"]),
                required=bool(item["required"]),
                state="REQUIRED" if bool(item["required"]) else "OPTIONAL",
                accepted_classifications=[str(value) for value in item.get("accepted_classifications", [])],
                uploaded_artifact_ids=[],
                rejected_artifact_ids=[],
            )
        )
    return requirements


def _artifact_record_from_payload(payload: dict[str, Any]) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=str(payload.get("artifact_id", "")).strip(),
        file_name=str(payload.get("file_name", "")).strip(),
        file_path=str(payload.get("file_path", "")).strip(),
        relative_path=str(payload.get("relative_path", "")).strip(),
        file_suffix=str(payload.get("file_suffix", "")).strip(),
        size_bytes=int(payload.get("size_bytes", 0) or 0),
        checksum_sha256=str(payload.get("checksum_sha256", "")).strip(),
        ingested_at=str(payload.get("ingested_at", "")).strip(),
        classification=str(payload.get("classification", "unknown")).strip() or "unknown",
        mime_type=str(payload.get("mime_type", "application/octet-stream")).strip() or "application/octet-stream",
        project_id=(str(payload.get("project_id", "")).strip() or None),
        run_id=(str(payload.get("run_id", "")).strip() or None),
        page_count=(int(payload["page_count"]) if payload.get("page_count") is not None else None),
        index_status=str(payload.get("index_status", "NOT_INDEXED")).strip() or "NOT_INDEXED",
        ingestion_status=str(payload.get("ingestion_status", "INGESTED")).strip() or "INGESTED",
        tags=[str(value) for value in payload.get("tags", []) if str(value).strip()],
        warnings=[str(value) for value in payload.get("warnings", []) if str(value).strip()],
        association_status=str(payload.get("association_status", "UNASSIGNED")).strip() or "UNASSIGNED",
        associated_requirement_ids=[
            str(value) for value in payload.get("associated_requirement_ids", []) if str(value).strip()
        ],
    )


def _requirement_from_payload(payload: dict[str, Any]) -> ArtifactRequirement:
    return ArtifactRequirement(
        requirement_id=str(payload.get("requirement_id", "")).strip(),
        label=str(payload.get("label", "")).strip(),
        description=str(payload.get("description", "")).strip(),
        guidance=str(payload.get("guidance", "")).strip(),
        required=bool(payload.get("required", False)),
        state=str(payload.get("state", "OPTIONAL")).strip() or "OPTIONAL",
        accepted_classifications=[
            str(value) for value in payload.get("accepted_classifications", []) if str(value).strip()
        ],
        uploaded_artifact_ids=[str(value) for value in payload.get("uploaded_artifact_ids", []) if str(value).strip()],
        rejected_artifact_ids=[str(value) for value in payload.get("rejected_artifact_ids", []) if str(value).strip()],
    )


def _load_or_initialize_intake_session(context: Any, project_id: str) -> IntakeSession:
    session_path = intake_session_path(Path(context.project_root), project_id)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    existing_payload = _safe_read_json(session_path)
    now_iso = utc_now_iso()

    if existing_payload is None:
        return IntakeSession(
            session_id=build_intake_session_id(project_id),
            project_id=project_id,
            session_path=str(session_path),
            created_at=now_iso,
            updated_at=now_iso,
            status="IN_PROGRESS",
            required_artifact_count=0,
            uploaded_artifact_count=0,
            missing_required_count=0,
            requirements=_build_requirement_models(),
            artifacts=[],
            warnings=[],
        )

    requirements_payload = existing_payload.get("requirements", [])
    artifacts_payload = existing_payload.get("artifacts", [])

    requirements = [
        _requirement_from_payload(item)
        for item in requirements_payload
        if isinstance(item, dict)
    ]
    if not requirements:
        requirements = _build_requirement_models()

    artifacts = [
        _artifact_record_from_payload(item)
        for item in artifacts_payload
        if isinstance(item, dict)
    ]

    return IntakeSession(
        session_id=str(existing_payload.get("session_id", build_intake_session_id(project_id))).strip(),
        project_id=str(existing_payload.get("project_id", project_id)).strip() or project_id,
        session_path=str(session_path),
        created_at=str(existing_payload.get("created_at", now_iso)).strip() or now_iso,
        updated_at=str(existing_payload.get("updated_at", now_iso)).strip() or now_iso,
        status=str(existing_payload.get("status", "IN_PROGRESS")).strip() or "IN_PROGRESS",
        required_artifact_count=int(existing_payload.get("required_artifact_count", 0) or 0),
        uploaded_artifact_count=int(existing_payload.get("uploaded_artifact_count", 0) or 0),
        missing_required_count=int(existing_payload.get("missing_required_count", 0) or 0),
        requirements=requirements,
        artifacts=artifacts,
        warnings=[str(value) for value in existing_payload.get("warnings", []) if str(value).strip()],
    )


def _build_artifact_record(
    *,
    index: int,
    artifact_path: Path,
    input_dir: Path,
    project_id: str,
    run_id: str,
) -> ArtifactRecord:
    classification = classify_artifact(artifact_path)
    checksum_sha256 = compute_sha256(artifact_path)
    mime_type = guess_mime_type(artifact_path)
    page_count = estimate_page_count(artifact_path)
    requirement_ids = requirement_ids_for_file(artifact_path, classification)

    artifact_warnings: list[str] = []
    association_status = "ASSOCIATED" if requirement_ids else "UNASSIGNED"

    if classification == "unknown":
        artifact_warnings.append(
            "Artifact classification could not be determined from file name heuristics."
        )

    return ArtifactRecord(
        artifact_id=build_artifact_id(index),
        file_name=artifact_path.name,
        file_path=str(artifact_path),
        relative_path=str(artifact_path.relative_to(input_dir)),
        file_suffix=artifact_path.suffix.lower(),
        size_bytes=artifact_path.stat().st_size,
        checksum_sha256=checksum_sha256,
        ingested_at=utc_now_iso(),
        classification=classification,
        mime_type=mime_type,
        project_id=project_id,
        run_id=run_id,
        page_count=page_count,
        index_status="NOT_INDEXED",
        ingestion_status="INGESTED",
        tags=derive_tags(classification, artifact_path),
        warnings=artifact_warnings,
        association_status=association_status,
        associated_requirement_ids=requirement_ids,
    )


def _merge_session_artifacts(
    session: IntakeSession,
    discovered_artifacts: list[ArtifactRecord],
) -> list[ArtifactRecord]:
    existing_by_checksum: dict[str, ArtifactRecord] = {
        artifact.checksum_sha256: artifact
        for artifact in session.artifacts
        if artifact.checksum_sha256
    }

    merged_artifacts: list[ArtifactRecord] = list(session.artifacts)

    for artifact in discovered_artifacts:
        existing = existing_by_checksum.get(artifact.checksum_sha256)
        if existing is None:
            merged_artifacts.append(artifact)
            existing_by_checksum[artifact.checksum_sha256] = artifact
            continue

        existing.file_name = artifact.file_name
        existing.file_path = artifact.file_path
        existing.relative_path = artifact.relative_path
        existing.file_suffix = artifact.file_suffix
        existing.size_bytes = artifact.size_bytes
        existing.ingested_at = artifact.ingested_at
        existing.classification = artifact.classification
        existing.mime_type = artifact.mime_type
        existing.project_id = artifact.project_id
        existing.run_id = artifact.run_id
        existing.page_count = artifact.page_count
        existing.index_status = artifact.index_status
        existing.ingestion_status = artifact.ingestion_status
        existing.tags = list(artifact.tags)
        existing.warnings = list(artifact.warnings)
        existing.association_status = artifact.association_status
        existing.associated_requirement_ids = list(artifact.associated_requirement_ids)

    return merged_artifacts


def _recompute_requirement_states(session: IntakeSession) -> None:
    requirement_map = {requirement.requirement_id: requirement for requirement in session.requirements}

    for requirement in session.requirements:
        requirement.uploaded_artifact_ids = []
        requirement.rejected_artifact_ids = []

    for artifact in session.artifacts:
        for requirement_id in artifact.associated_requirement_ids:
            requirement = requirement_map.get(requirement_id)
            if requirement is None:
                continue
            if artifact.ingestion_status == "REJECTED":
                requirement.rejected_artifact_ids.append(artifact.artifact_id)
            else:
                requirement.uploaded_artifact_ids.append(artifact.artifact_id)

    required_count = 0
    missing_required_count = 0
    uploaded_artifact_count = 0

    for requirement in session.requirements:
        if requirement.required:
            required_count += 1

        has_uploaded = bool(requirement.uploaded_artifact_ids)
        has_rejected_only = bool(requirement.rejected_artifact_ids) and not has_uploaded

        if has_uploaded:
            requirement.state = "UPLOADED"
        elif has_rejected_only:
            requirement.state = "REJECTED"
        elif requirement.required:
            requirement.state = "MISSING"
            missing_required_count += 1
        else:
            requirement.state = "OPTIONAL"

        uploaded_artifact_count += len(requirement.uploaded_artifact_ids)

    session.required_artifact_count = required_count
    session.missing_required_count = missing_required_count
    session.uploaded_artifact_count = uploaded_artifact_count
    session.updated_at = utc_now_iso()
    session.status = "COMPLETE" if missing_required_count == 0 else "IN_PROGRESS"


def _persist_session(session: IntakeSession) -> None:
    session_path = Path(session.session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _artifact_name_tokens(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("-", " ")


def _guess_calibration_dataset_type(artifact: ArtifactRecord) -> str | None:
    classification = artifact.classification.strip().lower()
    file_name = _artifact_name_tokens(artifact.file_name)
    relative_path = _artifact_name_tokens(artifact.relative_path)
    combined = f"{file_name} {relative_path}".strip()

    if classification == "transformer_datasheet":
        return "VENDOR_PERFORMANCE_CURVE"

    if classification in {"commissioning_notes", "load_study"}:
        return "PLANNING_BENCHMARK"

    if classification == "equipment_schedule":
        if any(token in combined for token in ("benchmark", "reference", "baseline")):
            return "PLANNING_BENCHMARK"
        return "FACILITY_REFERENCE"

    if classification in {"generator_specification", "ups_documentation", "cooling_documentation"}:
        return "FACILITY_REFERENCE"

    if classification == "poi_interconnection_documentation":
        if any(token in combined for token in ("telemetry", "ops", "operations model", "nomcr")):
            return "PLANNING_BENCHMARK"

    if any(token in combined for token in ("curve", "benchmark", "reference", "telemetry", "commissioning")):
        return "FACILITY_REFERENCE"

    return None


def _build_calibration_dataset_candidates(
    artifacts: list[ArtifactRecord],
) -> tuple[list[dict[str, Any]], list[str]]:
    dataset_candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_dataset_ids: set[str] = set()

    for artifact in artifacts:
        dataset_type = _guess_calibration_dataset_type(artifact)
        if dataset_type is None:
            continue

        dataset_id = f"calds_{artifact.artifact_id}"
        if dataset_id in seen_dataset_ids:
            continue
        seen_dataset_ids.add(dataset_id)

        candidate_warning: list[str] = []
        if artifact.classification == "unknown":
            candidate_warning.append(
                "Calibration dataset candidate was inferred from file naming heuristics only."
            )

        dataset_candidates.append(
            {
                "dataset_id": dataset_id,
                "dataset_type": dataset_type,
                "version": "1.0.0",
                "source_artifact_id": artifact.artifact_id,
                "source_file_name": artifact.file_name,
                "provenance": {
                    "source_stage": "ingestion",
                    "artifact_id": artifact.artifact_id,
                    "classification": artifact.classification,
                    "checksum_sha256": artifact.checksum_sha256,
                    "mime_type": artifact.mime_type,
                },
                "parameters": [],
                "metadata": {
                    "discovery_method": "artifact_classification_heuristics",
                    "relative_path": artifact.relative_path,
                    "candidate_warning_count": len(candidate_warning),
                    "candidate_warnings": candidate_warning,
                },
            }
        )

    if not dataset_candidates:
        warnings.append("No calibration dataset candidates were discovered during ingestion.")

    return dataset_candidates, warnings


def run_service(context: Any) -> dict[str, Any]:
    """
    Real ingestion service for GridSenpAI.

    Responsibilities:
    - scan the input directory for supported artifacts
    - register stable artifact metadata
    - classify artifacts at a basic level
    - compute checksum for reproducibility
    - persist governed intake session state for start/resume workflows
    - discover Phase 4 calibration dataset candidates
    - return structured ingestion output
    """

    input_dir = Path(context.input_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    project_id = _project_id_from_context(context)
    session = _load_or_initialize_intake_session(context, project_id)

    discovered_artifacts: list[ArtifactRecord] = []
    warnings: list[str] = list(session.warnings)

    for index, artifact_path in enumerate(iter_supported_artifacts(input_dir), start=1):
        discovered_artifacts.append(
            _build_artifact_record(
                index=index,
                artifact_path=artifact_path,
                input_dir=input_dir,
                project_id=project_id,
                run_id=context.run_id,
            )
        )

    if not discovered_artifacts:
        warnings.append("No supported artifacts were found in the input directory.")

    calibration_datasets, calibration_warnings = _build_calibration_dataset_candidates(discovered_artifacts)
    warnings.extend(calibration_warnings)

    session.artifacts = _merge_session_artifacts(session, discovered_artifacts)
    session.warnings = warnings
    _recompute_requirement_states(session)
    _persist_session(session)

    result = IngestionResult(
        run_id=context.run_id,
        artifact_count=len(discovered_artifacts),
        artifacts=discovered_artifacts,
        artifacts_discovered=discovered_artifacts,
        warnings=warnings,
        status="ARTIFACTS_INGESTED",
        intake_session=session,
    )

    payload = result.to_dict()
    payload["calibration_datasets"] = calibration_datasets
    payload["calibration_dataset_count"] = len(calibration_datasets)

    return payload


def ingest_artifacts(context: Any) -> dict[str, Any]:
    """
    Alias for compatibility with the pipeline resolver.
    """
    return run_service(context)