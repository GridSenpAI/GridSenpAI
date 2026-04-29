from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FieldDiffRecord:
    field_path: str
    change_type: str
    baseline_value: Any
    candidate_value: Any
    baseline_record_ids: list[str] = field(default_factory=list)
    candidate_record_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "change_type": self.change_type,
            "baseline_value": self.baseline_value,
            "candidate_value": self.candidate_value,
            "baseline_record_ids": list(self.baseline_record_ids),
            "candidate_record_ids": list(self.candidate_record_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class RunDiffSummary:
    baseline_run_id: str
    candidate_run_id: str
    created_at: str
    field_diff_count: int
    added_field_count: int
    removed_field_count: int
    changed_field_count: int
    unchanged_field_count: int
    conflict_delta: int
    review_flag_delta: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_run_id": self.baseline_run_id,
            "candidate_run_id": self.candidate_run_id,
            "created_at": self.created_at,
            "field_diff_count": self.field_diff_count,
            "added_field_count": self.added_field_count,
            "removed_field_count": self.removed_field_count,
            "changed_field_count": self.changed_field_count,
            "unchanged_field_count": self.unchanged_field_count,
            "conflict_delta": self.conflict_delta,
            "review_flag_delta": self.review_flag_delta,
        }