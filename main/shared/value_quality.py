from __future__ import annotations

import re
from typing import Any


_CONTAMINATION_PATTERNS = [
    r"\bpage\s+\d+\b",
    r"\bsheet\s+\d+\b",
    r"\brevision\b",
    r"\brev\.?\b",
    r"\bdrawn\s+by\b",
    r"\bchecked\s+by\b",
    r"\bdate\b",
    r"\btitle\s+block\b",
]

# Only narrative/summary-like fields should reject isolated scalars. Do not treat
# every field nested under facility.load_schedule as a summary field; phase MW and
# peak demand values are intentionally scalar planner fields.
_SUMMARY_FIELD_HINTS = ("summary", "plan", "sequence", "narrative")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _is_scalar_summary_field(field: str) -> bool:
    return any(token in field for token in _SUMMARY_FIELD_HINTS) or field.endswith(".schedule") or field.endswith("_schedule")


def contamination_reasons(field_path: str, value: Any, metadata: dict[str, Any] | None = None) -> list[str]:
    reasons: list[str] = []
    field = _clean(field_path).lower()
    text = _clean(value)
    lowered = text.lower()
    metadata = metadata if isinstance(metadata, dict) else {}

    if not text and value not in (False, 0):
        return ["empty candidate value"]

    for pattern in _CONTAMINATION_PATTERNS:
        if re.search(pattern, lowered):
            reasons.append(f"value contains likely document-control artifact: {pattern}")

    if any(token in field for token in ("customer", "applicant", "owner", "name")):
        if re.search(r"\bpage\s+\d+\b", lowered) or len(text) > 160:
            reasons.append("identity/name field appears contaminated by page/header/footer text")

    if _is_scalar_summary_field(field):
        if isinstance(value, bool):
            pass
        elif isinstance(value, (int, float)):
            reasons.append("summary/schedule field received an isolated scalar value")
        elif isinstance(value, str) and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
            reasons.append("summary/schedule field received a numeric string without context")

    if isinstance(value, dict):
        non_empty = sum(1 for item in value.values() if item not in (None, "", [], {}))
        if non_empty <= 1 and _is_scalar_summary_field(field):
            reasons.append("summary/schedule field received a mostly empty object")
        keys_blob = " ".join(str(key).lower() for key in value.keys())
        if any(token in keys_blob for token in ("rev", "revision", "drawn", "checked")):
            reasons.append("candidate object resembles a drawing revision/title-block table")

    source_method = _clean(metadata.get("source_method") or metadata.get("document_role") or metadata.get("source_role")).lower()
    if "revision" in source_method or "title_block" in source_method:
        reasons.append("candidate source method indicates revision/title-block context")

    seen: set[str] = set()
    deduped: list[str] = []
    for reason in reasons:
        if reason not in seen:
            deduped.append(reason)
            seen.add(reason)
    return deduped


def is_value_contaminated(field_path: str, value: Any, metadata: dict[str, Any] | None = None) -> bool:
    return bool(contamination_reasons(field_path, value, metadata))
