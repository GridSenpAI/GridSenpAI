from __future__ import annotations

import re
from typing import Any

from .models import EquipmentIdentityCandidate

FAMILY_ALIASES: dict[str, tuple[str, ...]] = {
    "ups": ("ups", "uninterruptible power supply", "static ups"),
    "generators": ("generator", "generators", "genset", "diesel generator", "gen-set"),
    "transformers": ("transformer", "transformers", "xfmr"),
    "switchgear": ("switchgear", "switch gear", "breaker lineup"),
    "relays": ("relay", "relays", "protective relay", "protection relay"),
}


def normalize_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def canonical_family(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    token = normalize_token(lowered)
    for family, aliases in FAMILY_ALIASES.items():
        if token == normalize_token(family):
            return family
        if any(token == normalize_token(alias) for alias in aliases):
            return family
    return lowered


def _append_unique(values: list[str], value: Any) -> None:
    cleaned = str(value or "").strip()
    if cleaned and cleaned not in values:
        values.append(cleaned)


def _walk(node: Any, path: str = ""):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            next_path = f"{path}.{key}" if path else str(key)
            yield from _walk(value, next_path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            next_path = f"{path}[{index}]"
            yield from _walk(value, next_path)


def collect_identity_seeds(
    *,
    extraction_result: dict[str, Any] | None,
    normalization_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    for source_name, payload in (("extraction_result", extraction_result), ("normalization_result", normalization_result)):
        if not isinstance(payload, dict):
            continue
        manufacturers: list[str] = []
        models: list[str] = []
        families: list[str] = []
        voltages: list[str] = []
        frequencies: list[str] = []
        ratings: list[str] = []
        artifact_ids: list[str] = []
        doc_types: list[str] = []

        for path, node in _walk(payload):
            lowered_path = path.lower()
            if isinstance(node, dict):
                if "artifact_id" in node:
                    _append_unique(artifact_ids, node.get("artifact_id"))
                if "document_type" in node:
                    _append_unique(doc_types, node.get("document_type"))

            if not isinstance(node, dict):
                continue
            for key, value in node.items():
                lowered_key = str(key).lower()
                candidate_value = value.get("value") if isinstance(value, dict) and "value" in value else value
                if candidate_value is None or candidate_value == "" or candidate_value == []:
                    continue
                if "manufacturer" in lowered_key:
                    _append_unique(manufacturers, candidate_value)
                elif lowered_key in {"model", "model_or_product_line"} or lowered_key.endswith(".model"):
                    _append_unique(models, candidate_value)
                elif "equipment_family" in lowered_key or lowered_key == "family":
                    _append_unique(families, canonical_family(candidate_value))
                elif "voltage" in lowered_key:
                    _append_unique(voltages, candidate_value)
                elif "frequency" in lowered_key:
                    _append_unique(frequencies, candidate_value)
                elif any(token in lowered_key for token in ("power", "kva", "kw", "mva", "mw")):
                    _append_unique(ratings, candidate_value)

        if manufacturers or models or families:
            seeds.append(
                {
                    "source": source_name,
                    "manufacturers": manufacturers,
                    "models": models,
                    "families": families,
                    "voltages": voltages,
                    "frequencies": frequencies,
                    "ratings": ratings,
                    "artifact_ids": artifact_ids,
                    "document_types": doc_types,
                }
            )
    return seeds


def build_record_aliases(record: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    model = str(record.get("model", "")).strip()
    manufacturer = str(record.get("manufacturer", "")).strip()
    family = str(record.get("equipment_family", "")).strip()
    for candidate in (model, manufacturer, family, f"{manufacturer} {model}"):
        _append_unique(aliases, candidate)
    for candidate in record.get("manufacturer_aliases", []) if isinstance(record.get("manufacturer_aliases"), list) else []:
        _append_unique(aliases, candidate)
    for candidate in record.get("model_aliases", []) if isinstance(record.get("model_aliases"), list) else []:
        _append_unique(aliases, candidate)
    identity = record.get("identity", {})
    if isinstance(identity, dict):
        for payload in identity.values():
            if isinstance(payload, dict):
                _append_unique(aliases, payload.get("value"))
    notes = record.get("notes", [])
    if isinstance(notes, list):
        for item in notes[:8]:
            if isinstance(item, str) and model and model.lower() in item.lower():
                _append_unique(aliases, item)
    return aliases


def rank_identity_candidates(
    *,
    seeds: list[dict[str, Any]],
    spec_records: list[dict[str, Any]],
) -> tuple[list[EquipmentIdentityCandidate], list[dict[str, Any]]]:
    ranked: list[tuple[float, EquipmentIdentityCandidate, dict[str, Any]]] = []
    for seed in seeds:
        seed_families = [canonical_family(value) for value in seed.get("families", []) if str(value).strip()]
        seed_manufacturers = [str(value).strip() for value in seed.get("manufacturers", []) if str(value).strip()]
        seed_models = [str(value).strip() for value in seed.get("models", []) if str(value).strip()]
        seed_voltages = [normalize_token(value) for value in seed.get("voltages", []) if str(value).strip()]
        seed_frequencies = [normalize_token(value) for value in seed.get("frequencies", []) if str(value).strip()]
        seed_ratings = [normalize_token(value) for value in seed.get("ratings", []) if str(value).strip()]

        for record in spec_records:
            manufacturer = str(record.get("manufacturer", "")).strip()
            model = str(record.get("model", "")).strip()
            family = canonical_family(record.get("equipment_family", ""))
            if not manufacturer or not model or not family:
                continue
            score = 0.0
            reasons: list[str] = []
            record_aliases = [normalize_token(item) for item in build_record_aliases(record)]
            record_model = normalize_token(model)
            record_manufacturer = normalize_token(manufacturer)
            record_family = normalize_token(family)

            for seed_model in seed_models:
                normalized = normalize_token(seed_model)
                if not normalized:
                    continue
                if normalized == record_model:
                    score += 0.64
                    reasons.append("exact_model_match")
                elif normalized in record_model or record_model in normalized:
                    score += 0.48
                    reasons.append("partial_model_match")
                elif normalized in record_aliases:
                    score += 0.42
                    reasons.append("alias_model_match")

            for seed_manufacturer in seed_manufacturers:
                normalized = normalize_token(seed_manufacturer)
                if not normalized:
                    continue
                if normalized == record_manufacturer:
                    score += 0.28
                    reasons.append("exact_manufacturer_match")
                elif normalized in record_manufacturer or record_manufacturer in normalized:
                    score += 0.18
                    reasons.append("partial_manufacturer_match")

            for seed_family in seed_families:
                normalized = normalize_token(seed_family)
                if normalized and normalized == record_family:
                    score += 0.16
                    reasons.append("family_match")

            fixed_specs = record.get("fixed_specs", {}) if isinstance(record.get("fixed_specs"), dict) else {}
            if seed_voltages and isinstance(fixed_specs.get("voltage_v"), dict):
                value = normalize_token(fixed_specs["voltage_v"].get("value"))
                if value and value in seed_voltages:
                    score += 0.08
                    reasons.append("voltage_consistency")
            if seed_frequencies and isinstance(fixed_specs.get("frequency_hz"), dict):
                value = normalize_token(fixed_specs["frequency_hz"].get("value"))
                if value and value in seed_frequencies:
                    score += 0.06
                    reasons.append("frequency_consistency")
            for field_name in ("rated_power_kw", "rated_power_kva", "rated_capacity_kva"):
                payload = fixed_specs.get(field_name)
                if seed_ratings and isinstance(payload, dict):
                    value = normalize_token(payload.get("value"))
                    if value and value in seed_ratings:
                        score += 0.06
                        reasons.append(f"{field_name}_consistency")
                        break

            if score < 0.34:
                continue

            confidence = min(0.99, round(score, 3))
            candidate = EquipmentIdentityCandidate(
                equipment_family=family,
                manufacturer=manufacturer,
                model=model,
                source=seed.get("source", "identity_resolution"),
                confidence=confidence,
                source_artifact_ids=list(seed.get("artifact_ids", [])),
                source_document_types=list(seed.get("document_types", [])),
                clues={
                    "seed_families": seed_families,
                    "seed_manufacturers": seed_manufacturers,
                    "seed_models": seed_models,
                    "reasons": reasons,
                },
            )
            ranked.append((score, candidate, record))

    ranked.sort(key=lambda item: item[0], reverse=True)
    deduped_candidates: list[EquipmentIdentityCandidate] = []
    matched_records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, candidate, record in ranked:
        key = (normalize_token(candidate.equipment_family), normalize_token(candidate.manufacturer), normalize_token(candidate.model))
        if key in seen:
            continue
        seen.add(key)
        deduped_candidates.append(candidate)
        matched_records.append(record)
        if len(deduped_candidates) >= 6:
            break
    return deduped_candidates, matched_records
