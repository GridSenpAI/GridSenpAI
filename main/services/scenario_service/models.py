# services/scenario_service/models.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ScenarioChangeRecord:
    parameter_path: str
    baseline_parameter_path: str
    baseline_value: Any
    new_value: Any
    delta: float | None
    units: str
    change_reason: str
    dependency_paths: list[str] = field(default_factory=list)
    source_field_paths: list[str] = field(default_factory=list)
    supporting_snippet_ids: list[str] = field(default_factory=list)
    assumption_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_path": self.parameter_path,
            "baseline_parameter_path": self.baseline_parameter_path,
            "baseline_value": self.baseline_value,
            "new_value": self.new_value,
            "delta": self.delta,
            "units": self.units,
            "change_reason": self.change_reason,
            "dependency_paths": list(self.dependency_paths),
            "source_field_paths": list(self.source_field_paths),
            "supporting_snippet_ids": list(self.supporting_snippet_ids),
            "assumption_ids": list(self.assumption_ids),
        }


@dataclass(slots=True)
class ScenarioMetadata:
    source_confidence_summary: dict[str, int] = field(default_factory=dict)
    parameter_count: int = 0
    changed_parameter_count: int = 0
    changed_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_confidence_summary": dict(self.source_confidence_summary),
            "parameter_count": self.parameter_count,
            "changed_parameter_count": self.changed_parameter_count,
            "changed_paths": list(self.changed_paths),
        }


@dataclass(slots=True)
class ScenarioVariantRecord:
    label: str
    description: str
    outputs: dict[str, Any] = field(default_factory=dict)
    confidence: str = "LOW"
    changes: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "outputs": dict(self.outputs),
            "confidence": self.confidence,
            "changes": list(self.changes),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ScenarioServiceResult:
    run_id: str
    scenarios: dict[str, Any] = field(default_factory=dict)
    scenario_variants: list[dict[str, Any]] = field(default_factory=list)
    status: str = "SCENARIOS_GENERATED"
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenarios": dict(self.scenarios),
            "scenario_variants": list(self.scenario_variants),
            "status": self.status,
            "generated_at": self.generated_at,
        }