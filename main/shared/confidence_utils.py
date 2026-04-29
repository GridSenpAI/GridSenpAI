from __future__ import annotations

from typing import Any


_BAND_DEFAULTS: dict[str, float] = {
    "HIGH": 0.90,
    "MODERATE": 0.65,
    "MEDIUM": 0.65,
    "LOW": 0.35,
    "UNRESOLVED": 0.0,
    "MISSING": 0.0,
    "UNKNOWN": 0.0,
}


def normalize_confidence_score(
    value: Any,
    *,
    band: str = "",
    default: float = 0.0,
) -> float:
    """Normalize planner-facing confidence to the probability-like 0.0-1.0 scale.

    GridSenpAI internally uses some weighted evidence/support scores that can be
    much larger than 1.0. Those must never leak into planner-facing confidence
    fields because they distort governance, adjudication, translation, and export
    readiness decisions.
    """
    raw_band = str(band or "").strip().upper()
    if isinstance(value, bool):
        score = default
    else:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = _BAND_DEFAULTS.get(raw_band, default)

    if score > 1.0:
        # Percent-like scores are common. Very large internal support/rank scores
        # are not valid probabilities, so cap after converting plausible percents.
        score = score / 100.0 if score <= 100.0 else 1.0

    if score < 0.0:
        score = 0.0
    if score > 1.0:
        score = 1.0
    return round(score, 4)


def confidence_band_from_score(score: Any, *, fallback: str = "") -> str:
    normalized = normalize_confidence_score(score, band=fallback)
    fallback_norm = str(fallback or "").strip().upper()
    if fallback_norm == "UNRESOLVED" and normalized <= 0.0:
        return "UNRESOLVED"
    if normalized >= 0.85:
        return "HIGH"
    if normalized >= 0.60:
        return "MODERATE"
    if normalized > 0.0:
        return "LOW"
    return fallback_norm or "UNRESOLVED"


def confidence_normalization_note(value: Any, normalized: float) -> str:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return ""
    if raw < 0.0 or raw > 1.0:
        return f"Raw confidence {raw} normalized to planner-facing confidence {normalized}."
    return ""
