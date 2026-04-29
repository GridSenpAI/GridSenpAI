from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EquipmentIdentityCandidate:
    equipment_family: str
    manufacturer: str
    model: str
    source: str
    confidence: float = 0.0
    source_artifact_ids: list[str] = field(default_factory=list)
    source_document_types: list[str] = field(default_factory=list)
    clues: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "equipment_family": self.equipment_family,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "source": self.source,
            "confidence": self.confidence,
            "source_artifact_ids": list(self.source_artifact_ids),
            "source_document_types": list(self.source_document_types),
            "clues": dict(self.clues),
        }


@dataclass(slots=True)
class EquipmentSpecCandidate:
    equipment_family: str
    manufacturer: str
    model: str
    spec_field: str
    value: Any
    source_type: str
    source_ref: str
    source_url: str | None = None
    confidence: float = 1.0
    evidence_text: str | None = None
    review_required: bool = False
    confidence_reason: str | None = None
    matched_field_key: str | None = None
    canonical_field_key: str | None = None
    source_priority: str | None = None
    source_kind: str | None = None
    document_type: str | None = None
    document_path: str | None = None
    evidence_tier: str | None = None
    match_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "equipment_family": self.equipment_family,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "spec_field": self.spec_field,
            "value": self.value,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "source_url": self.source_url,
            "confidence": self.confidence,
            "evidence_text": self.evidence_text,
            "review_required": self.review_required,
            "confidence_reason": self.confidence_reason,
            "matched_field_key": self.matched_field_key,
            "canonical_field_key": self.canonical_field_key,
            "source_priority": self.source_priority,
            "source_kind": self.source_kind,
            "document_type": self.document_type,
            "document_path": self.document_path,
            "evidence_tier": self.evidence_tier,
            "match_reason": self.match_reason,
        }


@dataclass(slots=True)
class EquipmentReferenceResolutionResult:
    status: str
    identity_candidates: list[dict[str, Any]] = field(default_factory=list)
    identity_resolution_summary: dict[str, Any] = field(default_factory=dict)
    matched_records: list[dict[str, Any]] = field(default_factory=list)
    candidate_fields: list[dict[str, Any]] = field(default_factory=list)
    snippets: list[dict[str, Any]] = field(default_factory=list)
    official_source_candidates: list[dict[str, Any]] = field(default_factory=list)
    pdf_repository_candidates: list[dict[str, Any]] = field(default_factory=list)
    pdf_lookup_plans: list[dict[str, Any]] = field(default_factory=list)
    web_lookup_plans: list[dict[str, Any]] = field(default_factory=list)
    unresolved_missing_fields: list[str] = field(default_factory=list)
    target_missing_fields: list[str] = field(default_factory=list)
    out_of_scope_missing_fields: list[str] = field(default_factory=list)
    planner_guidance: dict[str, Any] = field(default_factory=dict)
    review_required_fields: list[str] = field(default_factory=list)
    lookup_strategy: str = "library_then_pdf_then_official_web"
    authenticity_guardrails: dict[str, Any] = field(default_factory=dict)
    trigger_reasons: list[str] = field(default_factory=list)
    web_lookup_required: bool = False
    evidence_gap: bool = False
    knowledge_index_status: dict[str, Any] = field(default_factory=dict)
    library_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "identity_candidates": list(self.identity_candidates),
            "identity_resolution_summary": dict(self.identity_resolution_summary),
            "matched_records": list(self.matched_records),
            "candidate_fields": list(self.candidate_fields),
            "snippets": list(self.snippets),
            "official_source_candidates": list(self.official_source_candidates),
            "pdf_repository_candidates": list(self.pdf_repository_candidates),
            "pdf_lookup_plans": list(self.pdf_lookup_plans),
            "web_lookup_plans": list(self.web_lookup_plans),
            "unresolved_missing_fields": list(self.unresolved_missing_fields),
            "target_missing_fields": list(self.target_missing_fields),
            "out_of_scope_missing_fields": list(self.out_of_scope_missing_fields),
            "planner_guidance": dict(self.planner_guidance),
            "review_required_fields": list(self.review_required_fields),
            "lookup_strategy": self.lookup_strategy,
            "authenticity_guardrails": dict(self.authenticity_guardrails),
            "trigger_reasons": list(self.trigger_reasons),
            "web_lookup_required": self.web_lookup_required,
            "evidence_gap": self.evidence_gap,
            "knowledge_index_status": dict(self.knowledge_index_status),
            "library_summary": dict(self.library_summary),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }
