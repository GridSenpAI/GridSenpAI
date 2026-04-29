from __future__ import annotations

import re
from typing import Any, Dict, List

from app.config import CONFIG

SPEC_ARTIFACT_TYPES = {
    "spec_sheet",
    "vendor_datasheet",
    "equipment_specification",
}

WHITESPACE_PATTERN = re.compile(r"\s+")
NUMERIC_PATTERN = re.compile(r"[+-]?\d+(?:\.\d+)?")


def llm_enabled() -> bool:
    config = getattr(CONFIG, "llm_runtime", None)
    if config is None:
        return False
    return bool(getattr(config, "enabled", False)) and bool(str(getattr(config, "model_path", "") or "").strip())



def ensure_runtime() -> None:
    from services.llm_runtime_service.models import LLMRuntimeConfig
    from services.llm_runtime_service.service import initialize_runtime

    config = CONFIG.llm_runtime
    initialize_runtime(
        LLMRuntimeConfig(
            model_path=str(config.model_path),
            model_alias=str(config.model_alias),
            n_ctx=int(config.n_ctx),
            n_threads=int(config.n_threads),
            n_batch=int(config.n_batch),
            n_gpu_layers=int(config.n_gpu_layers),
            temperature=float(config.temperature),
            top_p=float(config.top_p),
            max_tokens=int(config.max_tokens),
        )
    )



def normalize_whitespace(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip()



def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default



def get_artifact_text(artifact: Dict[str, Any]) -> str:
    for key in ("parsed_text", "text", "content", "ocr_text"):
        value = artifact.get(key)
        if isinstance(value, str):
            return value

    metadata = artifact.get("metadata", {})
    for key in ("parsed_text", "text", "content", "ocr_text"):
        value = metadata.get(key)
        if isinstance(value, str):
            return value

    return ""



def is_spec_artifact(artifact: Dict[str, Any]) -> bool:
    artifact_type = artifact.get("artifact_type")
    return artifact_type in SPEC_ARTIFACT_TYPES



def infer_transformer_ratings(text: str) -> str | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(MVA|KVA)\s*(?:,|-|/)?\s*(\d+(?:\.\d+)?)\s*(KV|V)?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    rating = match.group(1)
    rating_unit = match.group(2).upper()
    voltage = match.group(3)
    voltage_unit = (match.group(4) or "KV").upper()
    return f"{rating} {rating_unit}, {voltage} {voltage_unit}"



def infer_generator_ratings(text: str) -> str | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(MW|KW|KVA|MVA)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1)} {match.group(2).upper()}"



def infer_ups_topology(text: str) -> str | None:
    for pattern in (
        r"\b(double conversion)\b",
        r"\b(line interactive)\b",
        r"\b(offline)\b",
        r"\b(modular)\b",
        r"\b(redundant)\b",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None



def coerce_spec_llm_value(field_path: str, value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if field_path in {
        "facility.transformers.ratings_mva",
        "facility.transformer_ratings",
        "facility.generators.ratings",
        "facility.generator_ratings",
        "facility.ups.topology",
        "facility.ups_topology",
    }:
        return normalized
    return None



def collect_lines_from_blocks(text_blocks: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for block in text_blocks:
        text = normalize_whitespace(str(block.get("text", "")))
        if text:
            lines.append(text)
    return lines



def collect_lines_from_ocr(ocr_regions: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for region in ocr_regions:
        text = normalize_whitespace(str(region.get("text", "")))
        if text:
            lines.append(text)
    return lines



def extract_schedule_rows(text_blocks: List[Dict[str, Any]], ocr_regions: List[Dict[str, Any]]) -> List[List[str]]:
    lines: List[str] = []
    lines.extend(collect_lines_from_blocks(text_blocks))
    lines.extend(collect_lines_from_ocr(ocr_regions))

    rows: List[List[str]] = []
    for line in lines:
        tokens = normalize_whitespace(line).split()
        if len(tokens) >= 3:
            rows.append(tokens)
    return rows



def detect_schedule_type(rows: List[List[str]]) -> str:
    if not rows:
        return "UNKNOWN_SCHEDULE"
    joined = " ".join(" ".join(row).lower() for row in rows)
    if "motor" in joined or "mtr-" in joined or "hp" in joined:
        return "MOTOR_SCHEDULE"
    if "relay" in joined:
        return "RELAY_SETTINGS"
    if "transformer" in joined:
        return "TRANSFORMER_SCHEDULE"
    if "generator" in joined:
        return "GENERATOR_SCHEDULE"
    if "ups" in joined:
        return "UPS_SCHEDULE"
    if "breaker" in joined:
        return "BREAKER_SCHEDULE"
    return "UNKNOWN_SCHEDULE"



def extract_numeric_values(tokens: List[str]) -> List[float]:
    values: List[float] = []
    for token in tokens:
        match = NUMERIC_PATTERN.search(token)
        if match:
            value = safe_float(match.group())
            if value is not None:
                values.append(value)
    return values



def detect_equipment_name(tokens: List[str]) -> str | None:
    if not tokens:
        return None
    first = tokens[0]
    if re.match(r"[A-Za-z]+[-_]?\d+", first):
        return first
    if len(first) <= 20 and any(char.isalpha() for char in first):
        return first
    return None



def normalize_schedule_row(tokens: List[str]) -> Dict[str, Any]:
    return {
        "equipment_id": detect_equipment_name(tokens),
        "tokens": tokens,
        "numeric_values": extract_numeric_values(tokens),
    }



def normalize_rows(rows: List[List[str]]) -> List[Dict[str, Any]]:
    return [normalize_schedule_row(row) for row in rows]



def summarize_schedule_value(schedule_type: str, normalized_rows: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    if not normalized_rows:
        return None
    return {
        "schedule_type": schedule_type,
        "row_count": len(normalized_rows),
        "equipment_ids": [row.get("equipment_id") for row in normalized_rows if row.get("equipment_id")],
        "rows": normalized_rows,
    }



def coerce_table_llm_value(field_path: str, value: Any) -> Any:
    if value is None:
        return None
    if field_path == "facility.relay_settings":
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"true", "yes", "present"}:
            return True
        if lowered in {"false", "no", "absent"}:
            return False
        return None
    if field_path in {"facility.motor_schedule", "facility.equipment_schedule"}:
        if isinstance(value, dict):
            return value
        return None
    return value
