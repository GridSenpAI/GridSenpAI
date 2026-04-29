from __future__ import annotations

import re
from typing import Any, Dict, Optional


RETRIEVAL_ARTIFACT_TYPES = {
    "model_package",
    "dynamic_model_package",
    "pscad_package",
    "psse_package",
    "planning_package",
    "supporting_document",
    "spec_sheet",
    "vendor_datasheet",
    "equipment_specification",
    "vendor_spec",
    "datasheet",
    "equipment_schedule",
}


_FILE_NAME_MARKERS = (
    "pscad",
    "dynamic model",
    "datasheet",
    "spec",
    "schedule",
)


def is_retrieval_artifact(artifact: Dict[str, Any]) -> bool:
    artifact_type = str(artifact.get("artifact_type", "")).strip().lower()
    if artifact_type in RETRIEVAL_ARTIFACT_TYPES:
        return True

    file_name = str(artifact.get("file_name", "")).strip().lower()
    return any(token in file_name for token in _FILE_NAME_MARKERS)


def get_artifact_text(artifact: Dict[str, Any]) -> str:
    for key in ("text", "content", "raw_text", "excerpt", "description", "parsed_text", "ocr_text"):
        value = artifact.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    metadata = artifact.get("metadata", {})
    if isinstance(metadata, dict):
        for key in ("text", "content", "raw_text", "excerpt", "description", "parsed_text", "ocr_text"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""


def infer_dynamic_model_available(text: str) -> Optional[bool]:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return None

    negative_patterns = (
        r"\bno dynamic model\b",
        r"\bdynamic model unavailable\b",
        r"\bmodel unavailable\b",
        r"\bnot available\b",
    )
    positive_patterns = (
        r"\bdynamic model\b",
        r"\buser[-\s]*defined model\b",
        r"\bmodel package\b",
        r"\bpsse model\b",
        r"\bdyr\b",
        r"\bwecc model\b",
    )

    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in negative_patterns):
        return False
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in positive_patterns):
        return True
    return None


def infer_pscad_model_package(text: str) -> Optional[bool]:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return None

    negative_patterns = (
        r"\bno pscad\b",
        r"\bpscad unavailable\b",
        r"\bnot available\b",
    )
    positive_patterns = (
        r"\bpscad\b",
        r"\bemt model\b",
        r"\bsso model\b",
        r"\belectromagnetic transient\b",
        r"\bemtp\b",
    )

    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in negative_patterns):
        return False
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in positive_patterns):
        return True
    return None


def coerce_retrieval_llm_value(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None

    lowered = str(value).strip().lower()
    if lowered in {"true", "yes", "present", "available"}:
        return True
    if lowered in {"false", "no", "absent", "unavailable"}:
        return False
    return None
