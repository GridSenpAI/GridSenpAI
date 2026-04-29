import re
from typing import Any, Dict, List, Optional

MAX_DRAWING_CANDIDATES_PER_FIELD = 4
LOW_VALUE_DRAWING_PATTERNS = (
    r"\blegend\b",
    r"\bgeneral notes?\b",
    r"\brevision(?:s| history)?\b",
    r"\btitle block\b",
    r"\bsheet index\b",
    r"\bissue(?:d| date)?\b",
    r"\bapproved by\b",
)

FIELD_RELEVANCE_RULES: Dict[str, Dict[str, Any]] = {
    "facility.poi_voltage_kv": {
        "keywords": ("poi", "point of interconnection", "service", "utility", "substation", "interconnect", "kv"),
        "patterns": (r"\b\d+(?:\.\d+)?\s*kV\b",),
    },
    "facility.electrical_configuration.internal_voltage_levels": {
        "keywords": ("kv", "voltage", "distribution", "switchgear", "bus", "service"),
        "patterns": (r"\b\d+(?:\.\d+)?\s*kV\b",),
    },
    "facility.substation.configuration": {
        "keywords": ("ring bus", "breaker and a half", "double bus", "single bus", "main tie main", "radial", "substation", "bus tie", "main bus", "breaker", "bus a", "bus b"),
        "patterns": tuple(),
    },
    "facility.transformers.count": {
        "keywords": ("xfmr", "transformer", "tx", "mva", "kva"),
        "patterns": (r"\b(?:TX|XFMR|TRANSFORMER)[-\s_]*[A-Z]?\d+\b", r"\b\d+\s+transformers?\b"),
    },
    "facility.generators.count": {
        "keywords": ("gen", "generator", "genset", "standby", "prime"),
        "patterns": (r"\b(?:GEN|GENERATOR)[-\s_]*[A-Z]?\d+\b", r"\b\d+\s+generators?\b"),
    },
    "facility.ups.count": {
        "keywords": ("ups", "module", "cabinet", "unit", "n+1", "2n", "static ups"),
        "patterns": (r"\bUPS[-\s_]*[A-Z]?\d+\b", r"\b\d+\s+UPS(?:\s+systems?)?\b"),
    },
    "facility.transformers.ratings_mva": {
        "keywords": ("xfmr", "transformer", "mva", "kva"),
        "patterns": (r"\b\d+(?:\.\d+)?\s*MVA\b", r"\b\d+(?:\.\d+)?\s*kVA\b"),
    },
    "facility.ups.topology": {
        "keywords": ("ups", "2n", "n+1", "distributed redundant", "block redundant"),
        "patterns": tuple(),
    },
}

FIELD_ALIASES = {
    "facility.substation_configuration": "facility.substation.configuration",
    "facility.transformer_count": "facility.transformers.count",
    "facility.generator_count": "facility.generators.count",
    "facility.ups_count": "facility.ups.count",
    "facility.transformer_ratings": "facility.transformers.ratings_mva",
    "facility.ups_topology": "facility.ups.topology",
}


DRAWING_ARTIFACT_TYPES = {
    "one_line_diagram",
    "site_plan",
    "electrical_drawing",
    "single_line_diagram",
}


DRAWING_FILENAME_HINTS = (
    "one-line",
    "one line",
    "single-line",
    "single line",
    "site plan",
    "electrical drawing",
    "schematic",
    "substation",
    "switchyard",
)

FIELD_RELEVANCE_THRESHOLDS: Dict[str, float] = {
    "facility.poi_voltage_kv": 3.0,
    "facility.electrical_configuration.internal_voltage_levels": 3.0,
    "facility.substation.configuration": 3.0,
    "facility.transformers.count": 2.0,
    "facility.generators.count": 2.0,
    "facility.ups.count": 2.0,
    "facility.transformers.ratings_mva": 2.5,
    "facility.ups.topology": 2.5,
}

FIELD_CANDIDATE_BUDGETS: Dict[str, int] = {
    "facility.poi_voltage_kv": 3,
    "facility.electrical_configuration.internal_voltage_levels": 3,
    "facility.substation.configuration": 3,
    "facility.transformers.count": 4,
    "facility.generators.count": 4,
    "facility.ups.count": 4,
    "facility.transformers.ratings_mva": 3,
    "facility.ups.topology": 3,
}

FIELD_FAMILIES: Dict[str, str] = {
    "facility.poi_voltage_kv": "poi_interconnection",
    "facility.electrical_configuration.internal_voltage_levels": "topology_configuration",
    "facility.substation.configuration": "topology_configuration",
    "facility.transformers.count": "equipment_count",
    "facility.generators.count": "equipment_count",
    "facility.ups.count": "equipment_count",
    "facility.transformers.ratings_mva": "nameplate_rating",
    "facility.ups.topology": "topology_configuration",
}


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", _safe_str(text)).strip()


def is_drawing_artifact(artifact: Dict[str, Any]) -> bool:
    artifact_type = _safe_str(artifact.get("artifact_type")).lower()
    if artifact_type in DRAWING_ARTIFACT_TYPES:
        return True

    classification = _safe_str(artifact.get("classification")).lower()
    if classification in DRAWING_ARTIFACT_TYPES:
        return True

    file_name = _safe_str(artifact.get("file_name")).lower()
    relative_path = _safe_str(artifact.get("relative_path")).lower()
    combined = f"{file_name} {relative_path}".strip()

    return any(hint in combined for hint in DRAWING_FILENAME_HINTS)


def get_artifact_text(artifact: Dict[str, Any]) -> str:
    for key in ("parsed_text", "text", "content", "ocr_text", "raw_text"):
        value = artifact.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_space(value)

    metadata = artifact.get("metadata", {})
    if isinstance(metadata, dict):
        for key in ("parsed_text", "text", "content", "ocr_text", "raw_text"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_space(value)

    return ""


def _unique_matches(pattern: str, text: str) -> List[str]:
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    normalized = {str(match).upper() for match in matches}
    return sorted(normalized)


def _explicit_count(pattern: str, text: str) -> Optional[int]:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return _safe_int(match.group(1))


def infer_transformer_count(text: str) -> Optional[int]:
    normalized_text = _normalize_space(text)
    matches = _unique_matches(r"\b(?:TX|XFMR|TRANSFORMER)[-\s_]*([A-Z]?\d+)\b", normalized_text)
    if matches:
        return len(matches)

    explicit = _explicit_count(r"\b(\d+)\s+transformers?\b", normalized_text)
    if explicit is not None:
        return explicit

    explicit = _explicit_count(r"\btransformer\s+count\b[^\n\r]{0,20}?(\d+)", normalized_text)
    if explicit is not None:
        return explicit

    return None


def infer_generator_count(text: str) -> Optional[int]:
    normalized_text = _normalize_space(text)
    matches = _unique_matches(r"\b(?:GEN|GENERATOR)[-\s_]*([A-Z]?\d+)\b", normalized_text)
    if matches:
        return len(matches)

    explicit = _explicit_count(r"\b(\d+)\s+generators?\b", normalized_text)
    if explicit is not None:
        return explicit

    explicit = _explicit_count(r"\bgenerator\s+count\b[^\n\r]{0,20}?(\d+)", normalized_text)
    if explicit is not None:
        return explicit

    return None


def infer_ups_count(text: str) -> Optional[int]:
    normalized_text = _normalize_space(text)
    matches = _unique_matches(r"\bUPS[-\s_]*([A-Z]?\d+)\b", normalized_text)
    if matches:
        return len(matches)

    explicit = _explicit_count(r"\b(\d+)\s+UPS(?:\s+systems?)?\b", normalized_text)
    if explicit is not None:
        return explicit

    explicit = _explicit_count(r"\bUPS\s+count\b[^\n\r]{0,20}?(\d+)", normalized_text)
    if explicit is not None:
        return explicit

    return None


def infer_poi_voltage_kv(text: str) -> Optional[float]:
    normalized_text = _normalize_space(text)
    patterns = [
        r"(?:point\s+of\s+interconnection|POI|interconnect(?:ion)?|utility|substation)[^\n\r]{0,80}?(\d+(?:\.\d+)?)\s*kV",
        r"(\d+(?:\.\d+)?)\s*kV[^\n\r]{0,80}?(?:point\s+of\s+interconnection|POI|interconnect(?:ion)?|utility|substation)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized_text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            continue
    return None


def infer_internal_voltage_levels(text: str) -> List[float]:
    normalized_text = _normalize_space(text)
    levels: List[float] = []
    for match in re.findall(r"\b(\d+(?:\.\d+)?)\s*kV\b", normalized_text, flags=re.IGNORECASE):
        try:
            value = float(match)
        except ValueError:
            continue
        if value not in levels:
            levels.append(value)
    return levels


def infer_substation_configuration(text: str) -> Optional[str]:
    normalized_text = _normalize_space(text)

    patterns = [
        r"\b(ring bus)\b",
        r"\b(breaker and a half)\b",
        r"\b(double bus(?: double breaker)?)\b",
        r"\b(single bus)\b",
        r"\b(main[-\s]+tie[-\s]+main)\b",
        r"\b(radial)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized_text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def infer_transformer_ratings(text: str) -> List[float]:
    normalized_text = _normalize_space(text)
    results: List[float] = []

    patterns = [
        r"\b(\d+(?:\.\d+)?)\s*MVA\b",
        r"\b(\d+(?:\.\d+)?)\s*kVA\b",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, normalized_text, flags=re.IGNORECASE):
            try:
                value = float(match)
            except ValueError:
                continue

            if "kva" in pattern.lower():
                value = round(value / 1000.0, 6)

            if value not in results:
                results.append(value)

    return results


def infer_ups_topology(text: str) -> Optional[str]:
    normalized_text = _normalize_space(text).lower()

    if "2n" in normalized_text:
        return "2N"
    if "n+1" in normalized_text or "n + 1" in normalized_text:
        return "N+1"
    if "distributed redundant" in normalized_text:
        return "distributed_redundant"
    if "block redundant" in normalized_text:
        return "block_redundant"

    return None


def build_evidence_payload(artifact: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "page": artifact.get("page"),
        "region": artifact.get("region"),
        "file_name": artifact.get("file_name"),
        "classification": artifact.get("classification"),
        "artifact_type": artifact.get("artifact_type"),
    }


def coerce_drawing_llm_value(field_path: str, value: Any) -> Any:
    if value is None:
        return None

    if field_path in {"facility.transformers.count", "facility.transformer_count", "facility.generators.count", "facility.generator_count", "facility.ups.count", "facility.ups_count"}:
        return _safe_int(value)

    if field_path in {"facility.substation.configuration", "facility.substation_configuration", "facility.ups.topology", "facility.ups_topology"}:
        normalized = _normalize_space(str(value))
        return normalized or None

    if field_path in {"facility.transformers.ratings_mva", "facility.transformer_ratings"}:
        if isinstance(value, list):
            ratings: List[float] = []
            for item in value:
                try:
                    ratings.append(float(item))
                except (TypeError, ValueError):
                    continue
            return ratings or None
        try:
            return [float(value)]
        except (TypeError, ValueError):
            return None

    return value


def normalize_field_path(field_path: str) -> str:
    value = _safe_str(field_path)
    return FIELD_ALIASES.get(value, value)


def field_family_for_drawing_path(field_path: str) -> str:
    return FIELD_FAMILIES.get(normalize_field_path(field_path), "general")


def drawing_relevance_threshold_for_field(field_path: str) -> float:
    return FIELD_RELEVANCE_THRESHOLDS.get(normalize_field_path(field_path), 2.0)


def drawing_candidate_budget_for_field(field_path: str) -> int:
    return FIELD_CANDIDATE_BUDGETS.get(normalize_field_path(field_path), MAX_DRAWING_CANDIDATES_PER_FIELD)


def document_role_for_artifact(artifact: Dict[str, Any]) -> str:
    ontology = artifact.get("ontology") if isinstance(artifact.get("ontology"), dict) else {}
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    return (
        _safe_str(ontology.get("document_role"))
        or _safe_str(metadata.get("document_role"))
        or _safe_str(artifact.get("document_role"))
        or "unknown"
    )


def document_family_for_artifact(artifact: Dict[str, Any]) -> str:
    ontology = artifact.get("ontology") if isinstance(artifact.get("ontology"), dict) else {}
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    return (
        _safe_str(ontology.get("document_family"))
        or _safe_str(metadata.get("document_family"))
        or _safe_str(artifact.get("document_family"))
        or "general"
    )


def artifact_relevance_score(field_path: str, artifact: Dict[str, Any], text: str) -> float:
    normalized_field_path = normalize_field_path(field_path)
    normalized_text = _normalize_space(text).lower()
    if not normalized_text:
        return 0.0

    score = 0.0
    file_name = _safe_str(artifact.get("file_name")).lower()
    classification = _safe_str(artifact.get("classification")).lower()
    artifact_type = _safe_str(artifact.get("artifact_type")).lower()
    combined_meta = f"{file_name} {classification} {artifact_type}"
    document_role = document_role_for_artifact(artifact).lower()
    document_family = document_family_for_artifact(artifact).lower()
    field_family = field_family_for_drawing_path(normalized_field_path)

    if any(re.search(pattern, normalized_text, flags=re.IGNORECASE) for pattern in LOW_VALUE_DRAWING_PATTERNS):
        score -= 3.0
    if any(token in combined_meta for token in ("legend", "revision", "title", "index", "cover")):
        score -= 3.0
    if document_role in {"legend_notes", "revision_block", "title_block", "admin_noise"}:
        score -= 4.0
    if document_family == "drawing":
        score += 1.0
    if field_family == "topology_configuration" and document_role in {"primary_topology", "official_interconnection"}:
        score += 2.5
    if field_family == "equipment_count" and document_role == "authoritative_schedule":
        score -= 1.5
    if field_family == "poi_interconnection" and document_role == "official_interconnection":
        score += 2.5

    rules = FIELD_RELEVANCE_RULES.get(normalized_field_path, {})
    keywords = rules.get("keywords", ())
    patterns = rules.get("patterns", ())

    for keyword in keywords:
        if keyword in normalized_text:
            score += 2.0
    for pattern in patterns:
        if re.search(pattern, normalized_text, flags=re.IGNORECASE):
            score += 3.0

    if normalized_field_path == "facility.poi_voltage_kv" and any(token in normalized_text for token in ("service entrance", "utility", "interconnect", "substation")):
        score += 2.0
    if normalized_field_path == "facility.electrical_configuration.internal_voltage_levels":
        voltage_matches = re.findall(r"\b\d+(?:\.\d+)?\s*kV\b", normalized_text, flags=re.IGNORECASE)
        if len(voltage_matches) >= 2:
            score += 3.0
    if normalized_field_path in {"facility.transformers.count", "facility.generators.count", "facility.ups.count"}:
        if any(token in normalized_text for token in ("schedule", "one-line", "single line", "electrical")):
            score += 1.0

    return max(score, 0.0)


def artifact_is_relevant_for_field(field_path: str, artifact: Dict[str, Any], text: str) -> bool:
    return artifact_relevance_score(field_path, artifact, text) >= drawing_relevance_threshold_for_field(field_path)


def rank_candidate_artifacts_for_field(artifacts: List[Dict[str, Any]], field_path: str) -> List[Dict[str, Any]]:
    ranked: List[tuple[float, Dict[str, Any]]] = []
    seen_signatures: set[tuple[str, str]] = set()
    for artifact in artifacts:
        text = get_artifact_text(artifact)
        score = artifact_relevance_score(field_path, artifact, text)
        if score <= 0.0:
            continue
        signature = (
            _safe_str(artifact.get("file_name")).lower(),
            normalized_text := _normalize_space(text).lower()[:240],
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        ranked.append((score, artifact))

    ranked.sort(key=lambda item: (item[0], _safe_int(item[1].get("page")) or 0), reverse=True)
    budget = drawing_candidate_budget_for_field(field_path)
    return [artifact for _, artifact in ranked[:budget]]
