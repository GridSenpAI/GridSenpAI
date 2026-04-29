from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class StageResult:
    """
    Canonical base stage result contract for GridSenpAI pipeline stages.

    This gives every stage a deterministic minimum structure.
    """

    run_id: str
    status: str
    warnings: List[str] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "warnings": self.warnings,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "StageResult":
        return cls(
            run_id=str(payload["run_id"]),
            status=str(payload["status"]),
            warnings=list(payload.get("warnings", [])),
            errors=list(payload.get("errors", [])),
        )