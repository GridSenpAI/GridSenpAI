from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ConfidenceFactors:
    engineer_confirmed: bool = False
    direct_evidence_count: int = 0
    derived_from_rule: bool = False
    assumption_used: bool = False
    conflict_present: bool = False
    missing_dependency: bool = False
    uses_default_rule: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "engineer_confirmed": self.engineer_confirmed,
            "direct_evidence_count": self.direct_evidence_count,
            "derived_from_rule": self.derived_from_rule,
            "assumption_used": self.assumption_used,
            "conflict_present": self.conflict_present,
            "missing_dependency": self.missing_dependency,
            "uses_default_rule": self.uses_default_rule,
        }


@dataclass(slots=True)
class OutputParameterRecord:
    parameter_path: str
    value: Any
    units: str
    provenance_type: str
    provenance_ref: str | list[str]
    dependency_paths: list[str] = field(default_factory=list)
    source_field_paths: list[str] = field(default_factory=list)
    supporting_snippet_ids: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    confidence_tag: str = "LOW"
    confidence_factors: ConfidenceFactors | dict[str, Any] = field(
        default_factory=ConfidenceFactors
    )
    planner_note: str = ""
    review_note: str = ""
    confidence_explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        confidence_factors_payload: dict[str, Any]
        if isinstance(self.confidence_factors, ConfidenceFactors):
            confidence_factors_payload = self.confidence_factors.to_dict()
        else:
            confidence_factors_payload = dict(self.confidence_factors)

        return {
            "parameter_path": self.parameter_path,
            "value": self.value,
            "units": self.units,
            "provenance_type": self.provenance_type,
            "provenance_ref": self.provenance_ref,
            "dependency_paths": list(self.dependency_paths),
            "source_field_paths": list(self.source_field_paths),
            "supporting_snippet_ids": list(self.supporting_snippet_ids),
            "confidence_score": round(float(self.confidence_score), 2),
            "confidence_tag": self.confidence_tag,
            "confidence_factors": confidence_factors_payload,
            "planner_note": self.planner_note,
            "review_note": self.review_note,
            "confidence_explanation": self.confidence_explanation,
        }


@dataclass(slots=True)
class AssumptionRecord:
    assumption_id: str
    parameter_path: str
    nominal_value: Any
    bounds: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    created_by: str = "system"
    planner_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "parameter_path": self.parameter_path,
            "nominal_value": self.nominal_value,
            "bounds": dict(self.bounds),
            "rationale": self.rationale,
            "created_by": self.created_by,
            "planner_note": self.planner_note,
        }


@dataclass(slots=True)
class TranslationServiceResult:
    run_id: str
    model_outputs: dict[str, Any] = field(default_factory=dict)
    output_parameters: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    confidence_summary: dict[str, int] = field(default_factory=dict)
    schema_validation: dict[str, Any] = field(default_factory=dict)
    translation_support: dict[str, Any] = field(default_factory=dict)
    llm_assistance: dict[str, Any] = field(default_factory=dict)
    status: str = "TRANSLATED"
    translated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model_outputs": dict(self.model_outputs),
            "output_parameters": list(self.output_parameters),
            "assumptions": list(self.assumptions),
            "confidence_summary": dict(self.confidence_summary),
            "schema_validation": dict(self.schema_validation),
            "translation_support": dict(self.translation_support),
            "llm_assistance": dict(self.llm_assistance),
            "status": self.status,
            "translated_at": self.translated_at,
        }