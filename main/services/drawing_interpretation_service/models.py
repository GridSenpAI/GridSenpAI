from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class DrawingExtractionResult:
    field_path: str
    value: Optional[Any]
    confidence: float
    source_artifact_id: str
    method: str
    evidence: Dict[str, Any]