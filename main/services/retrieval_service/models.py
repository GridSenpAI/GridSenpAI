from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(slots=True)
class RetrievalExtractionResult:
    field_path: str
    value: Optional[Any]
    confidence: float
    source_artifact_id: str
    method: str
    evidence: Dict[str, Any]
