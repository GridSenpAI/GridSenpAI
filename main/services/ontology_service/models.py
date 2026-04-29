from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ArtifactClassification:
    artifact_id: str
    file_name: str
    file_suffix: str
    document_type: str
    confidence: str
    matched_signals: list[str] = field(default_factory=list)
    retrieval_domains: list[str] = field(default_factory=list)
    likely_fields: list[str] = field(default_factory=list)
    document_role: str = "UNCLASSIFIED"
    document_family: str = "unknown"
    worker_bias: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "file_name": self.file_name,
            "file_suffix": self.file_suffix,
            "document_type": self.document_type,
            "confidence": self.confidence,
            "matched_signals": list(self.matched_signals),
            "retrieval_domains": list(self.retrieval_domains),
            "likely_fields": list(self.likely_fields),
            "document_role": self.document_role,
            "document_family": self.document_family,
            "worker_bias": list(self.worker_bias),
            "metadata": dict(self.metadata),
        }
