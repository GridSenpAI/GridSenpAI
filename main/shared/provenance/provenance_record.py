from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


VALID_PROVENANCE_TYPES = {
    "evidence",
    "rule",
    "assumption",
}


VALID_CONFIDENCE_TAGS = {
    "HIGH",
    "MODERATE",
    "LOW",
    "UNRESOLVED",
}


@dataclass(slots=True)
class ProvenanceRecord:
    """
    Canonical provenance record attached to any derived parameter.

    Ensures GridSenpAI outputs remain traceable and non-hallucinatory.
    """

    parameter_path: str
    provenance_type: str
    provenance_ref: str | List[str]
    confidence_score: float
    confidence_tag: str

    def _validate_confidence_score(self) -> None:
        if not isinstance(self.confidence_score, (int, float)):
            raise ValueError(
                "confidence_score must be numeric."
            )

        if not 0.0 <= float(self.confidence_score) <= 1.0:
            raise ValueError(
                "confidence_score must be between 0.0 and 1.0."
            )

    def _validate_confidence_consistency(self) -> None:
        score = float(self.confidence_score)

        if self.confidence_tag == "HIGH" and score < 0.85:
            raise ValueError(
                "confidence_tag HIGH requires confidence_score >= 0.85."
            )

        if self.confidence_tag == "MODERATE" and not (0.60 <= score < 0.85):
            raise ValueError(
                "confidence_tag MODERATE requires 0.60 <= confidence_score < 0.85."
            )

        if self.confidence_tag == "LOW" and score >= 0.60:
            raise ValueError(
                "confidence_tag LOW requires confidence_score < 0.60."
            )

        if self.confidence_tag == "UNRESOLVED" and score != 0.0:
            raise ValueError(
                "confidence_tag UNRESOLVED requires confidence_score == 0.0."
            )

    def validate(self) -> None:
        if self.provenance_type not in VALID_PROVENANCE_TYPES:
            raise ValueError(
                f"Invalid provenance_type '{self.provenance_type}'. "
                f"Allowed: {VALID_PROVENANCE_TYPES}"
            )

        if self.confidence_tag not in VALID_CONFIDENCE_TAGS:
            raise ValueError(
                f"Invalid confidence_tag '{self.confidence_tag}'. "
                f"Allowed: {VALID_CONFIDENCE_TAGS}"
            )

        self._validate_confidence_score()
        self._validate_confidence_consistency()

        if self.provenance_type == "evidence":
            if not isinstance(self.provenance_ref, list) or not self.provenance_ref:
                raise ValueError(
                    "Evidence provenance must reference one or more snippet IDs."
                )

        if self.provenance_type in {"rule", "assumption"}:
            if (
                not isinstance(self.provenance_ref, str)
                or not self.provenance_ref.strip()
            ):
                raise ValueError(
                    "Rule/assumption provenance must contain a non-empty reference string."
                )

    def to_dict(self) -> Dict[str, Any]:
        self.validate()

        return {
            "parameter_path": self.parameter_path,
            "provenance_type": self.provenance_type,
            "provenance_ref": self.provenance_ref,
            "confidence_score": round(float(self.confidence_score), 2),
            "confidence_tag": self.confidence_tag,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ProvenanceRecord":
        record = cls(
            parameter_path=str(payload["parameter_path"]),
            provenance_type=str(payload["provenance_type"]),
            provenance_ref=payload["provenance_ref"],
            confidence_score=float(payload["confidence_score"]),
            confidence_tag=str(payload["confidence_tag"]),
        )
        record.validate()
        return record
