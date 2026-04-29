from __future__ import annotations

import re
from typing import Any, Iterable

from services.extraction_service.models import EntityObservationRecord, ResolvedEntity


def get_artifact_text(artifact: dict[str, Any]) -> str:
    for key in ("parsed_text", "text", "content", "ocr_text"):
        value = artifact.get(key)
        if isinstance(value, str) and value.strip():
            return value
    metadata = artifact.get("metadata", {})
    if isinstance(metadata, dict):
        for key in ("parsed_text", "text", "content", "ocr_text"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def extract_transformer_aliases(text: str) -> list[str]:
    matches = re.findall(r"\b(?:TX|XFMR|TRANSFORMER)[-\s_]*([A-Z]?\d+)\b", text, flags=re.IGNORECASE)
    aliases: list[str] = []
    for match in matches:
        aliases.append(f"T{match}".upper())
        aliases.append(f"TX-{match}".upper())
    return sorted(set(aliases))


def extract_generator_aliases(text: str) -> list[str]:
    matches = re.findall(r"\b(?:GEN|GENERATOR)[-\s_]*([A-Z]?\d+)\b", text, flags=re.IGNORECASE)
    aliases: list[str] = []
    for match in matches:
        aliases.append(f"GEN-{match}".upper())
        aliases.append(f"GENERATOR {match}".upper())
    return sorted(set(aliases))


def extract_ups_aliases(text: str) -> list[str]:
    matches = re.findall(r"\bUPS[-\s_]*([A-Z]?\d+)\b", text, flags=re.IGNORECASE)
    aliases: list[str] = []
    for match in matches:
        aliases.append(f"UPS-{match}".upper())
        aliases.append(f"UPS {match}".upper())
    return sorted(set(aliases))


def normalize_alias(alias: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(alias).upper())


def build_canonical_entity_id(entity_type: str, aliases: list[str]) -> str:
    normalized_aliases = sorted(normalize_alias(alias) for alias in aliases if alias)
    if not normalized_aliases:
        return f"{entity_type}_unknown"
    return f"{entity_type}_{normalized_aliases[0].lower()}"


def merge_aliases(left: list[str], right: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for alias in [*left, *right]:
        normalized = normalize_alias(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(alias)
    return merged


def aliases_overlap(left: list[str], right: list[str]) -> bool:
    left_normalized = {normalize_alias(alias) for alias in left if alias}
    right_normalized = {normalize_alias(alias) for alias in right if alias}
    return bool(left_normalized.intersection(right_normalized))


def group_observations_by_type(observations: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        entity_type = str(observation.get("entity_type", "")).strip()
        if not entity_type:
            continue
        grouped.setdefault(entity_type, []).append(observation)
    return grouped


class EntityResolutionCoordinator:
    def collect_entity_observations(self, artifacts: list[dict[str, Any]]) -> list[EntityObservationRecord]:
        observations: list[EntityObservationRecord] = []
        for artifact in artifacts:
            artifact_id = str(artifact.get("artifact_id", "unknown_artifact"))
            text = get_artifact_text(artifact)
            transformer_aliases = extract_transformer_aliases(text)
            if transformer_aliases:
                observations.append(
                    EntityObservationRecord(
                        entity_type="transformer",
                        entity_id=f"{artifact_id}::transformer",
                        aliases=transformer_aliases,
                        source_artifact_id=artifact_id,
                    )
                )
            generator_aliases = extract_generator_aliases(text)
            if generator_aliases:
                observations.append(
                    EntityObservationRecord(
                        entity_type="generator",
                        entity_id=f"{artifact_id}::generator",
                        aliases=generator_aliases,
                        source_artifact_id=artifact_id,
                    )
                )
            ups_aliases = extract_ups_aliases(text)
            if ups_aliases:
                observations.append(
                    EntityObservationRecord(
                        entity_type="ups",
                        entity_id=f"{artifact_id}::ups",
                        aliases=ups_aliases,
                        source_artifact_id=artifact_id,
                    )
                )
        return observations

    def resolve_entities(self, observations: Iterable[EntityObservationRecord | dict[str, Any]]) -> list[ResolvedEntity]:
        normalized = [self._normalize_observation(observation) for observation in observations]
        grouped = group_observations_by_type(normalized)
        resolved_entities: list[ResolvedEntity] = []
        for entity_type, typed_observations in grouped.items():
            buckets: list[dict[str, Any]] = []
            for observation in typed_observations:
                matched_bucket = None
                for bucket in buckets:
                    if aliases_overlap(bucket["aliases"], observation["aliases"]):
                        matched_bucket = bucket
                        break
                if matched_bucket is None:
                    buckets.append(
                        {
                            "entity_type": entity_type,
                            "aliases": list(observation["aliases"]),
                            "source_artifact_ids": [observation["source_artifact_id"]],
                        }
                    )
                    continue
                matched_bucket["aliases"] = merge_aliases(matched_bucket["aliases"], observation["aliases"])
                source_artifact_id = observation["source_artifact_id"]
                if source_artifact_id not in matched_bucket["source_artifact_ids"]:
                    matched_bucket["source_artifact_ids"].append(source_artifact_id)
            for bucket in buckets:
                resolved_entities.append(
                    ResolvedEntity(
                        entity_type=bucket["entity_type"],
                        canonical_entity_id=build_canonical_entity_id(bucket["entity_type"], bucket["aliases"]),
                        aliases=bucket["aliases"],
                        source_artifact_ids=bucket["source_artifact_ids"],
                    )
                )
        return resolved_entities

    def _normalize_observation(self, observation: EntityObservationRecord | dict[str, Any]) -> dict[str, Any]:
        if isinstance(observation, EntityObservationRecord):
            return {
                "entity_type": observation.entity_type,
                "entity_id": observation.entity_id,
                "aliases": list(observation.aliases),
                "source_artifact_id": observation.source_artifact_id,
            }
        aliases = observation.get("aliases", []) if isinstance(observation, dict) else []
        return {
            "entity_type": str(observation.get("entity_type", "")).strip() if isinstance(observation, dict) else "",
            "entity_id": str(observation.get("entity_id", "")).strip() if isinstance(observation, dict) else "",
            "aliases": [str(alias) for alias in aliases if str(alias).strip()],
            "source_artifact_id": str(observation.get("source_artifact_id", "")).strip() if isinstance(observation, dict) else "",
        }
