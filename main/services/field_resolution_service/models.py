from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FieldResolutionCandidate:
    candidate_id: str
    field_id: str
    field_path: str
    label: str
    value: Any = None
    field_family: str = "general"
    unit: str = ""
    source_stage: str = ""
    source_type: str = ""
    source_stream: str = "record"
    source_hierarchy: str = "applicant_inferred_document"
    source_ref: list[str] = field(default_factory=list)
    source_anchor: str = ""
    specificity: str = "context_inferred"
    confidence: float | None = None
    confidence_band: str = "UNRESOLVED"
    evidence_strength: str = "UNKNOWN"
    corroboration_count: int = 1
    context_score: float = 0.0
    consistency_notes: list[str] = field(default_factory=list)
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "field_id": self.field_id,
            "field_path": self.field_path,
            "label": self.label,
            "value": self.value,
            "field_family": self.field_family,
            "unit": self.unit,
            "source_stage": self.source_stage,
            "source_type": self.source_type,
            "source_stream": self.source_stream,
            "source_hierarchy": self.source_hierarchy,
            "source_ref": list(self.source_ref),
            "source_anchor": self.source_anchor,
            "specificity": self.specificity,
            "confidence": self.confidence,
            "confidence_band": self.confidence_band,
            "evidence_strength": self.evidence_strength,
            "corroboration_count": self.corroboration_count,
            "context_score": self.context_score,
            "consistency_notes": list(self.consistency_notes),
            "score": self.score,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class FieldResolutionLedgerEntry:
    field_id: str
    field_path: str
    label: str
    packet_section: str
    packet_section_label: str
    requiredness: str
    planner_critical: bool
    field_family: str = "general"
    accepted_value: Any = None
    accepted_unit: str = ""
    accepted_status: str = "unresolved"
    accepted_confidence: float | None = None
    confidence_band: str = "UNRESOLVED"
    accepted_candidate_id: str = ""
    why_accepted: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    source_anchors: list[str] = field(default_factory=list)
    accepted_source_hierarchy: str = ""
    accepted_specificity: str = ""
    candidate_evidence_appendix: list[dict[str, Any]] = field(default_factory=list)
    supporting_sources: list[dict[str, Any]] = field(default_factory=list)
    source_stream_counts: dict[str, int] = field(default_factory=dict)
    applicant_answer_state: str = ""
    contradiction_summary: str = ""
    decision_basis: str = ""
    accepted_value_kind: str = "unresolved"
    planner_attention_tier: str = "information"
    field_policy_class: str = "supporting"
    field_materiality_class: str = "descriptive"
    conflict_materiality: str = "none"
    acceptance_margin: float = 0.0
    runner_up_candidate_id: str = ""
    unresolved_reason: str = ""
    candidate_summary: dict[str, Any] = field(default_factory=dict)
    needs_applicant_confirmation: bool = False
    planner_review_flag: bool = False
    dominance_profile: dict[str, Any] = field(default_factory=dict)
    runner_up_profile: dict[str, Any] = field(default_factory=dict)
    conflict_profile: dict[str, Any] = field(default_factory=dict)
    applicant_question_profile: dict[str, Any] = field(default_factory=dict)
    planner_trust_row: dict[str, Any] = field(default_factory=dict)
    acceptance_policy_result: dict[str, Any] = field(default_factory=dict)
    field_release_profile: dict[str, Any] = field(default_factory=dict)
    adjudication_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "field_path": self.field_path,
            "label": self.label,
            "packet_section": self.packet_section,
            "packet_section_label": self.packet_section_label,
            "requiredness": self.requiredness,
            "planner_critical": self.planner_critical,
            "field_family": self.field_family,
            "accepted_value": self.accepted_value,
            "accepted_unit": self.accepted_unit,
            "accepted_status": self.accepted_status,
            "accepted_confidence": self.accepted_confidence,
            "confidence_band": self.confidence_band,
            "accepted_candidate_id": self.accepted_candidate_id,
            "why_accepted": list(self.why_accepted),
            "candidates": list(self.candidates),
            "alternatives": list(self.alternatives),
            "source_anchors": list(self.source_anchors),
            "accepted_source_hierarchy": self.accepted_source_hierarchy,
            "accepted_specificity": self.accepted_specificity,
            "candidate_evidence_appendix": list(self.candidate_evidence_appendix),
            "supporting_sources": list(self.supporting_sources),
            "source_stream_counts": dict(self.source_stream_counts),
            "applicant_answer_state": self.applicant_answer_state,
            "contradiction_summary": self.contradiction_summary,
            "decision_basis": self.decision_basis,
            "accepted_value_kind": self.accepted_value_kind,
            "planner_attention_tier": self.planner_attention_tier,
            "field_policy_class": self.field_policy_class,
            "field_materiality_class": self.field_materiality_class,
            "conflict_materiality": self.conflict_materiality,
            "acceptance_margin": self.acceptance_margin,
            "runner_up_candidate_id": self.runner_up_candidate_id,
            "unresolved_reason": self.unresolved_reason,
            "candidate_summary": dict(self.candidate_summary),
            "needs_applicant_confirmation": self.needs_applicant_confirmation,
            "planner_review_flag": self.planner_review_flag,
            "dominance_profile": dict(self.dominance_profile),
            "runner_up_profile": dict(self.runner_up_profile),
            "conflict_profile": dict(self.conflict_profile),
            "applicant_question_profile": dict(self.applicant_question_profile),
            "planner_trust_row": dict(self.planner_trust_row),
            "acceptance_policy_result": dict(self.acceptance_policy_result),
            "field_release_profile": dict(self.field_release_profile),
            "adjudication_trace": dict(self.adjudication_trace),
        }
