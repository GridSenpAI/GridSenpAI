from __future__ import annotations

from typing import Any


def normalize_artifacts(raw_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for artifact in raw_artifacts:
        if not isinstance(artifact, dict):
            continue
        record = dict(artifact)
        artifact_id = record.get("artifact_id")
        if artifact_id is not None:
            record["artifact_id"] = str(artifact_id)
        source_path = record.get("source_path")
        if source_path is not None:
            record["source_path"] = str(source_path)
        normalized.append(record)
    return normalized


def serialize_interview_questions(questions: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for question in questions:
        if hasattr(question, "to_dict"):
            serialized.append(question.to_dict())
        elif isinstance(question, dict):
            serialized.append(dict(question))
    return serialized


def serialize_resolved_entities(entities: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for entity in entities:
        if hasattr(entity, "to_dict"):
            serialized.append(entity.to_dict())
        elif isinstance(entity, dict):
            serialized.append(dict(entity))
    return serialized
