from __future__ import annotations

from typing import Any

from services.ontology_service.models import ArtifactClassification
from services.ontology_service.utils import (
    DOCUMENT_TYPE_RULES,
    artifact_suffix,
    build_text_for_classification,
    classify_confidence,
    score_document_rule,
    source_authority_for_role,
    unique_str_list,
    worker_bias_for_rule,
)


def classify_single_artifact(
    artifact: dict[str, Any],
    text_content: str | None = None,
) -> dict[str, Any]:
    artifact_id = str(artifact.get("artifact_id", "")).strip()
    file_name = str(artifact.get("file_name", "")).strip()
    file_suffix = artifact_suffix(artifact)

    classification_text = build_text_for_classification(artifact, text_content=text_content)
    file_text = " ".join(
        str(item or "").strip().lower()
        for item in (
            file_name,
            artifact.get("classification", ""),
            artifact.get("artifact_type", ""),
            artifact.get("document_role", ""),
        )
    )

    best_document_type = "UNCLASSIFIED"
    best_score = -1
    best_rule: dict[str, Any] | None = None
    best_matched_signals: list[str] = []
    best_retrieval_domains: list[str] = []
    best_likely_fields: list[str] = []

    for document_type, rule in DOCUMENT_TYPE_RULES.items():
        score, matched_signals = score_document_rule(
            rule=rule,
            classification_text=classification_text,
            file_text=file_text,
        )

        if score > best_score:
            best_document_type = document_type
            best_score = score
            best_rule = rule
            best_matched_signals = matched_signals
            best_retrieval_domains = list(rule["retrieval_domains"])
            best_likely_fields = list(rule["likely_fields"])

    if best_score <= 0:
        best_document_type = "UNCLASSIFIED"
        best_rule = None
        best_matched_signals = []
        best_retrieval_domains = []
        best_likely_fields = []

    document_role = str((best_rule or {}).get("document_role", "UNCLASSIFIED")).strip() or "UNCLASSIFIED"
    document_family = str((best_rule or {}).get("document_family", "unknown")).strip() or "unknown"
    worker_bias = worker_bias_for_rule(best_rule)

    result = ArtifactClassification(
        artifact_id=artifact_id,
        file_name=file_name,
        file_suffix=file_suffix,
        document_type=best_document_type,
        confidence=classify_confidence(max(best_score, 0)),
        matched_signals=best_matched_signals,
        retrieval_domains=best_retrieval_domains,
        likely_fields=best_likely_fields,
        document_role=document_role,
        document_family=document_family,
        worker_bias=worker_bias,
        metadata={
            "signal_score": max(best_score, 0),
            "source_authority_hint": source_authority_for_role(document_role),
        },
    )
    return result.to_dict()


def classify_artifacts(
    artifacts: list[dict[str, Any]],
    text_by_artifact_id: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    text_by_artifact_id = text_by_artifact_id or {}
    results: list[dict[str, Any]] = []

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue

        artifact_id = str(artifact.get("artifact_id", "")).strip()
        results.append(
            classify_single_artifact(
                artifact,
                text_content=text_by_artifact_id.get(artifact_id, ""),
            )
        )

    normalized_results: list[dict[str, Any]] = []
    for item in results:
        item["matched_signals"] = unique_str_list(item.get("matched_signals", []))
        item["retrieval_domains"] = unique_str_list(item.get("retrieval_domains", []))
        item["likely_fields"] = unique_str_list(item.get("likely_fields", []))
        item["worker_bias"] = unique_str_list(item.get("worker_bias", []))
        normalized_results.append(item)

    return normalized_results
