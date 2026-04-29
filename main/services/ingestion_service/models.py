from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ArtifactRecord:
    """
    Canonical artifact metadata produced by the ingestion service.
    """

    artifact_id: str
    file_name: str
    file_path: str
    relative_path: str
    file_suffix: str
    size_bytes: int
    checksum_sha256: str
    ingested_at: str
    classification: str
    mime_type: str
    project_id: str | None = None
    run_id: str | None = None
    page_count: int | None = None
    index_status: str = "NOT_INDEXED"
    ingestion_status: str = "INGESTED"
    tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    association_status: str = "UNASSIGNED"
    associated_requirement_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArtifactRequirement:
    """
    Required or optional artifact category tracked by governed intake.
    """

    requirement_id: str
    label: str
    description: str
    guidance: str
    required: bool
    state: str
    accepted_classifications: list[str] = field(default_factory=list)
    uploaded_artifact_ids: list[str] = field(default_factory=list)
    rejected_artifact_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IntakeSession:
    """
    Persisted artifact intake session state for start/resume workflows.
    """

    session_id: str
    project_id: str
    session_path: str
    created_at: str
    updated_at: str
    status: str
    required_artifact_count: int
    uploaded_artifact_count: int
    missing_required_count: int
    requirements: list[ArtifactRequirement] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "project_id": self.project_id,
            "session_path": self.session_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "required_artifact_count": self.required_artifact_count,
            "uploaded_artifact_count": self.uploaded_artifact_count,
            "missing_required_count": self.missing_required_count,
            "requirements": [requirement.to_dict() for requirement in self.requirements],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class IngestionResult:
    """
    Output contract for the ingestion service.
    """

    run_id: str
    artifact_count: int
    artifacts: list[ArtifactRecord]
    artifacts_discovered: list[ArtifactRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "ARTIFACTS_INGESTED"
    intake_session: IntakeSession | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "artifact_count": self.artifact_count,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "artifacts_discovered": [
                artifact.to_dict() for artifact in self.artifacts_discovered
            ],
            "warnings": self.warnings,
            "status": self.status,
        }
        if self.intake_session is not None:
            payload["intake_session"] = self.intake_session.to_dict()
        return payload