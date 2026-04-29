from __future__ import annotations

import re
from typing import Any


NARRATIVE_TERMS: set[str] = {
    "study",
    "report",
    "analysis",
    "summary",
    "application",
    "request",
    "description",
    "scope",
    "facility",
    "interconnection",
    "guidance",
    "requirement",
    "standard",
    "planning",
}

TABLE_TERMS: set[str] = {
    "schedule",
    "table",
    "rating",
    "equipment",
    "specification",
    "specifications",
    "parameter",
    "voltage",
    "current",
    "breaker",
    "transformer",
    "generator",
    "ups",
    "mw",
    "mva",
    "kv",
    "amps",
}

DIAGRAM_TERMS: set[str] = {
    "diagram",
    "schematic",
    "one-line",
    "one",
    "line",
    "single-line",
    "single",
    "switchyard",
    "relay",
    "protection",
    "feeder",
    "bus",
    "xfmr",
    "substation",
}

TITLE_BLOCK_TERMS: set[str] = {
    "drawn",
    "checked",
    "approved",
    "revision",
    "rev",
    "sheet",
    "drawing",
    "project",
    "date",
    "scale",
}

OCR_HEAVY_TERMS: set[str] = {
    "diagram",
    "schematic",
    "one-line",
    "single-line",
    "protection",
    "relay",
    "switchyard",
}


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_.-]+", text.lower())


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_region_id(*, artifact_id: str, page_number: int, region_index: int) -> str:
    return f"{artifact_id}_p{page_number:04d}_layout_{region_index:05d}"


def bbox_union(boxes: list[dict[str, Any]]) -> dict[str, float]:
    if not boxes:
        return {"x0": 0.0, "top": 0.0, "x1": 0.0, "bottom": 0.0}

    return {
        "x0": min(safe_float(box.get("x0")) for box in boxes),
        "top": min(safe_float(box.get("top")) for box in boxes),
        "x1": max(safe_float(box.get("x1")) for box in boxes),
        "bottom": max(safe_float(box.get("bottom")) for box in boxes),
    }


def score_term_overlap(tokens: list[str], lexicon: set[str]) -> tuple[float, list[str]]:
    matched = sorted({token for token in tokens if token in lexicon})
    if not lexicon:
        return 0.0, matched
    return min(len(matched) / max(len(lexicon) / 4, 1), 1.0), matched


def classify_page(
    *,
    page_text: str,
    route_hint: str,
    block_count: int,
) -> tuple[str, float, dict[str, list[str]]]:
    tokens = tokenize(page_text)
    narrative_score, narrative_terms = score_term_overlap(tokens, NARRATIVE_TERMS)
    table_score, table_terms = score_term_overlap(tokens, TABLE_TERMS)
    diagram_score, diagram_terms = score_term_overlap(tokens, DIAGRAM_TERMS)
    title_score, title_terms = score_term_overlap(tokens, TITLE_BLOCK_TERMS)

    if route_hint in {"OCR_REQUIRED", "HYBRID_PARSE_AND_OCR"}:
        diagram_score = min(diagram_score + 0.15, 1.0)

    if block_count <= 6 and title_score > 0.2:
        diagram_score = min(diagram_score + 0.1, 1.0)

    scores: dict[str, float] = {
        "NARRATIVE_PAGE": float(narrative_score),
        "TABLE_PAGE": float(table_score),
        "DIAGRAM_PAGE": float(diagram_score),
    }

    classification: str = max(scores, key=lambda key: scores[key])
    confidence: float = scores[classification]

    if confidence < 0.2:
        classification = "MIXED_PAGE"
        confidence = 0.25

    return classification, round(confidence, 4), {
        "narrative_terms": narrative_terms,
        "table_terms": table_terms,
        "diagram_terms": diagram_terms,
        "title_block_terms": title_terms,
    }


def extraction_profiles_for_classification(
    classification: str,
    route_hint: str,
) -> list[str]:
    profiles: list[str] = []

    if classification in {"NARRATIVE_PAGE", "MIXED_PAGE"}:
        profiles.append("TEXT_EVIDENCE_RETRIEVAL")
    if classification in {"TABLE_PAGE", "MIXED_PAGE"}:
        profiles.append("TABLE_EVIDENCE_EXTRACTION")
    if classification in {"DIAGRAM_PAGE", "MIXED_PAGE"}:
        profiles.append("DIAGRAM_EVIDENCE_EXTRACTION")
    if route_hint in {"OCR_REQUIRED", "HYBRID_PARSE_AND_OCR"}:
        profiles.append("TARGETED_OCR")

    return profiles


def document_classification_from_pages(
    page_classifications: list[str],
) -> tuple[str, float]:
    if not page_classifications:
        return "UNCLASSIFIED_DOCUMENT", 0.0

    counts: dict[str, int] = {}

    for classification in page_classifications:
        counts[classification] = counts.get(classification, 0) + 1

    winner: str = max(counts, key=lambda key: counts[key])
    confidence: float = counts[winner] / len(page_classifications)

    mapping: dict[str, str] = {
        "NARRATIVE_PAGE": "NARRATIVE_DOCUMENT",
        "TABLE_PAGE": "TABLE_DOCUMENT",
        "DIAGRAM_PAGE": "DIAGRAM_DOCUMENT",
        "MIXED_PAGE": "MIXED_DOCUMENT",
    }

    return mapping.get(winner, "UNCLASSIFIED_DOCUMENT"), round(confidence, 4)

    return mapping.get(winner, "UNCLASSIFIED_DOCUMENT"), round(confidence, 4)


def merge_extraction_profiles(page_profiles: list[list[str]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    for profiles in page_profiles:
        for profile in profiles:
            if profile in seen:
                continue
            seen.add(profile)
            ordered.append(profile)

    return ordered