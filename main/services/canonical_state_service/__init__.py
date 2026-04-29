from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "CanonicalFieldRecord",
    "CanonicalFieldUpdate",
    "CanonicalStateBuildInputs",
    "CanonicalStateBuildSummary",
    "CanonicalStateServiceResult",
    "ConflictRecord",
    "ReviewFlag",
    "build_canonical_state",
    "merge_extraction_candidates",
    "run_service",
    "canonical_state_summary_from_payload",
    "normalize_field_path",
    "passes_confidence_threshold",
    "select_best_candidate",
    "utc_now_iso",
    "write_canonical_state_snapshot",
]

_ATTRIBUTE_MODULE_MAP = {
    "CanonicalFieldRecord": ("services.canonical_state_service.models", "CanonicalFieldRecord"),
    "CanonicalFieldUpdate": ("services.canonical_state_service.models", "CanonicalFieldUpdate"),
    "CanonicalStateBuildInputs": ("services.canonical_state_service.models", "CanonicalStateBuildInputs"),
    "CanonicalStateBuildSummary": ("services.canonical_state_service.models", "CanonicalStateBuildSummary"),
    "CanonicalStateServiceResult": ("services.canonical_state_service.models", "CanonicalStateServiceResult"),
    "ConflictRecord": ("services.canonical_state_service.models", "ConflictRecord"),
    "ReviewFlag": ("services.canonical_state_service.models", "ReviewFlag"),
    "build_canonical_state": ("services.canonical_state_service.service", "build_canonical_state"),
    "merge_extraction_candidates": ("services.canonical_state_service.service", "merge_extraction_candidates"),
    "run_service": ("services.canonical_state_service.service", "run_service"),
    "canonical_state_summary_from_payload": ("services.canonical_state_service.utils", "canonical_state_summary_from_payload"),
    "normalize_field_path": ("services.canonical_state_service.utils", "normalize_field_path"),
    "passes_confidence_threshold": ("services.canonical_state_service.utils", "passes_confidence_threshold"),
    "select_best_candidate": ("services.canonical_state_service.utils", "select_best_candidate"),
    "utc_now_iso": ("services.canonical_state_service.utils", "utc_now_iso"),
    "write_canonical_state_snapshot": ("services.canonical_state_service.utils", "write_canonical_state_snapshot"),
}


def __getattr__(name: str) -> Any:
    target = _ATTRIBUTE_MODULE_MAP.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
