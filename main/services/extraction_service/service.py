"""
GridSenpAI Extraction Service

Responsibility
--------------
Extract structured electrical engineering entities from facility artifacts.

Extracted entities include:
- transformers
- generators
- UPS systems
- electrical ratings
- protection settings
- topology cues

Phase 3 evolution added:
- optional document_parser_service input
- optional layout_analysis_service input
- optional ocr_service input
- schema-first candidate extraction aligned to the canonical facility model
- evidence/provenance candidate records while preserving Phase 2 outputs
- planner registry coverage visibility for extraction targets

Phase 4 extension:
- drawing interpretation integration for drawing-class artifacts
- orchestrated worker routing for drawings, specs, tables, and retrieval-oriented artifacts
- region-scoped extraction based on layout candidate regions
- optional LLM-assisted extraction through specialized workers
"""

from __future__ import annotations

import os
from typing import Any

from app.config import CONFIG

from services.drawing_interpretation_service.service import DrawingInterpretationService
from services.extraction_service.domain import ExtractionDomainCoordinator
from services.extraction_service.models import ExtractionResult
from services.extraction_service.utils import (
    build_planner_registry_coverage,
    build_schema_field_candidates,
    build_source_anchor,
    deduplicate_anchors,
    deduplicate_entities,
    deduplicate_topology_cues,
    extract_mw_entities,
    extract_named_entities,
    extract_topology_cues,
    extract_transformer_rating_entities,
    extract_voltage_entities,
    layout_warnings,
    load_canonical_schema,
    merge_text_sources,
    utc_now_iso,
)
from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent
from services.extraction_service.review_packets import build_extraction_review_packet_plan
from services.ontology_service.service import classify_artifacts
from shared.planner_registry import worker_routing_table

DISABLE_LEGACY_REGEX = os.getenv("GRIDSENPAI_DISABLE_LEGACY_REGEX", "false").lower() == "true"

_PHASE4_ROUTING = worker_routing_table()

PHASE4_DRAWING_FIELD_PATHS = list(_PHASE4_ROUTING.get("drawing_worker", ()))

PHASE4_TABLE_FIELD_PATHS = list(_PHASE4_ROUTING.get("table_worker", ()))

PHASE4_SPEC_FIELD_PATHS = list(_PHASE4_ROUTING.get("spec_worker", ()))

PHASE4_RETRIEVAL_FIELD_PATHS = list(_PHASE4_ROUTING.get("retrieval_worker", ()))

DRAWING_REGION_TYPES = {"DIAGRAM_EVIDENCE_REGION"}
TABLE_REGION_TYPES = {"TABLE_EVIDENCE_REGION"}
TEXT_REGION_TYPES = {"TEXT_EVIDENCE_REGION", "TITLE_BLOCK_REGION"}

SCALAR_FIELD_MAX_CANDIDATES_PER_ARTIFACT = 3


def _can_run_agent(context: Any | None) -> bool:
    if context is None:
        return False
    run_id = getattr(context, "run_id", None)
    return isinstance(run_id, str) and bool(run_id.strip())


def _agent_skip_result(agent_id: str, reason: str) -> dict[str, Any]:
    return {
        "status": "NOT_RUN",
        "agent_id": agent_id,
        "policy": {
            "allowed": False,
            "reason": reason,
            "provider_mode": "not_requested",
        },
        "audit_path": "",
        "bounded_response": {
            "review_notes": [reason],
            "rationale": reason,
            "confidence": "HIGH",
        },
    }


def _normalized_candidate_value_key(value: Any) -> str:
    return _normalize_candidate_value(value)


def _has_material_candidate_conflict(schema_field_candidates: list[dict[str, Any]]) -> bool:
    by_field: dict[str, list[dict[str, Any]]] = {}
    for candidate in schema_field_candidates:
        if not isinstance(candidate, dict):
            continue
        field_path = _safe_str(candidate.get("field_path"))
        if not field_path or _is_empty_value(candidate.get("value")):
            continue
        by_field.setdefault(field_path, []).append(candidate)

    for candidates in by_field.values():
        strong = [
            candidate
            for candidate in candidates
            if _candidate_numeric_confidence(candidate) >= 0.60
        ]
        if len(strong) < 2:
            continue
        values = {_normalized_candidate_value_key(candidate.get("value")) for candidate in strong}
        if len(values) > 1:
            return True
    return False


def _has_low_confidence_planner_candidates(schema_field_candidates: list[dict[str, Any]]) -> bool:
    for candidate in schema_field_candidates:
        if not isinstance(candidate, dict):
            continue
        if _is_empty_value(candidate.get("value")):
            continue
        if _candidate_numeric_confidence(candidate) < 0.60:
            return True
    return False


def _warnings_indicate_extraction_uncertainty(warnings: list[str]) -> bool:
    for warning in warnings:
        lowered = _safe_str(warning).lower()
        if any(token in lowered for token in ("conflict", "ambiguous", "uncertain", "unresolved", "low confidence")):
            return True
    return False


def _should_request_extraction_review_agent(
    *,
    schema_field_candidates: list[dict[str, Any]],
    uncovered_planner_registry_fields: list[str],
    warnings: list[str],
) -> tuple[bool, str]:
    if not bool(getattr(CONFIG.model, "allow_model_assistance", False)):
        return False, "model assistance is disabled by configuration"
    if _has_material_candidate_conflict(schema_field_candidates):
        return True, "material extraction candidate conflict requires advisory review"
    if _has_low_confidence_planner_candidates(schema_field_candidates):
        return True, "low-confidence extraction candidates require advisory review"
    if uncovered_planner_registry_fields:
        return True, "planner registry coverage gaps require advisory review"
    if _warnings_indicate_extraction_uncertainty(warnings):
        return True, "extraction warnings indicate uncertainty requiring advisory review"
    return False, "deterministic extraction evidence is sufficient; advisory review was not requested"


def _should_request_document_interpretation_agent(
    *,
    schema_field_candidates: list[dict[str, Any]],
    uncovered_planner_registry_fields: list[str],
    warnings: list[str],
) -> tuple[bool, str]:
    if not bool(getattr(CONFIG.model, "allow_model_assistance", False)):
        return False, "model assistance is disabled by configuration"
    if not schema_field_candidates:
        return True, "no deterministic schema candidates were produced"
    if _has_material_candidate_conflict(schema_field_candidates):
        return True, "material extraction conflict requires advisory document interpretation"
    if _warnings_indicate_extraction_uncertainty(warnings):
        return True, "extraction warnings indicate ambiguity requiring advisory document interpretation"
    if len(uncovered_planner_registry_fields) >= 8:
        return True, "broad planner registry coverage gaps require advisory document interpretation"
    return False, "deterministic/project-primary evidence is sufficient; document interpretation was not requested"


def _run_document_interpretation_agent(
    *,
    context: Any,
    artifacts: list[dict[str, Any]],
    schema_field_candidates: list[dict[str, Any]],
    topology_cues: list[dict[str, Any]],
    warnings: list[str],
    uncovered_planner_registry_fields: list[str] | None = None,
) -> dict[str, Any]:
    should_run, skip_reason = _should_request_document_interpretation_agent(
        schema_field_candidates=schema_field_candidates,
        uncovered_planner_registry_fields=uncovered_planner_registry_fields or [],
        warnings=warnings,
    )
    if not should_run:
        return _agent_skip_result("document_interpretation_agent", skip_reason)

    if not _can_run_agent(context):
        return {
            "status": "NOT_RUN",
            "agent_id": "document_interpretation_agent",
            "policy": {},
            "audit_path": "",
            "bounded_response": {},
        }

    sample_artifact = artifacts[0] if artifacts else {}
    sample_candidate = schema_field_candidates[0] if schema_field_candidates else {}
    result = run_agent(
        context=context,
        request=AgentRequest(
            agent_id="document_interpretation_agent",
            stage_name="extraction",
            task_name="document_interpretation",
            inputs={
                "artifact_kind": str(sample_artifact.get("artifact_type", sample_artifact.get("classification", "engineering_document"))).strip() or "engineering_document",
                "region_id": str(sample_artifact.get("artifact_id", "extraction_fragment")).strip() or "extraction_fragment",
                "field_path": str(sample_candidate.get("field_path", "")).strip(),
                "raw_text": "\n".join(
                    str(item.get("text", item.get("parsed_text", ""))).strip()
                    for item in artifacts[:3]
                    if isinstance(item, dict) and str(item.get("text", item.get("parsed_text", ""))).strip()
                )[:1500],
                "source_anchor": {
                    "artifact_ids": [
                        str(item.get("artifact_id", "")).strip()
                        for item in artifacts[:5]
                        if isinstance(item, dict) and str(item.get("artifact_id", "")).strip()
                    ],
                    "candidate_field_paths": [
                        str(item.get("field_path", "")).strip()
                        for item in schema_field_candidates[:8]
                        if isinstance(item, dict) and str(item.get("field_path", "")).strip()
                    ],
                    "topology_labels": [
                        str(item.get("label", item.get("cue", ""))).strip()
                        for item in topology_cues[:8]
                        if isinstance(item, dict) and str(item.get("label", item.get("cue", ""))).strip()
                    ],
                },
                "warnings": warnings[:8],
            },
            metadata={
                "service": "extraction_service",
            },
            trigger_reason="bounded_document_interpretation_requested",
            associated_field_paths=[
                str(candidate.get("field_path", "")).strip()
                for candidate in schema_field_candidates[:12]
                if isinstance(candidate, dict) and str(candidate.get("field_path", "")).strip()
            ],
            evidence_anchors=[
                {
                    "anchor_type": "artifact",
                    "artifact_id": str(artifact.get("artifact_id", "")).strip(),
                    "artifact_type": str(artifact.get("artifact_type", artifact.get("classification", ""))).strip(),
                }
                for artifact in artifacts[:8]
                if isinstance(artifact, dict) and str(artifact.get("artifact_id", "")).strip()
            ],
            suggested_output_fields=[
                "candidate_text",
                "candidate_label",
                "candidate_value",
                "candidate_interpretations",
                "interpretation_notes",
                "rationale",
                "confidence",
            ],
        ),
    )

    return {
        "run_id": str(result.get("run_id", "")).strip(),
        "status": str(result.get("status", "NOT_RUN")).strip() or "NOT_RUN",
        "policy": result.get("policy", {}),
        "audit_path": str(result.get("audit_path", "")).strip(),
        "bounded_response": result.get("structured_output", {}),
        "agent_id": str(result.get("agent_id", "document_interpretation_agent")).strip() or "document_interpretation_agent",
    }


def _run_extraction_review_agent(
    *,
    context: Any,
    artifacts: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    schema_field_candidates: list[dict[str, Any]],
    topology_cues: list[dict[str, Any]],
    ontology: dict[str, Any],
    planner_registry_summary: dict[str, Any],
    uncovered_planner_registry_fields: list[str],
    relevance_plan: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    should_run, skip_reason = _should_request_extraction_review_agent(
        schema_field_candidates=schema_field_candidates,
        uncovered_planner_registry_fields=uncovered_planner_registry_fields,
        warnings=warnings,
    )
    if not should_run:
        return _agent_skip_result("extraction_review_agent", skip_reason)

    packet_plan = build_extraction_review_packet_plan(
        artifacts=artifacts,
        schema_field_candidates=schema_field_candidates,
        warnings=warnings,
        uncovered_planner_registry_fields=uncovered_planner_registry_fields,
    )
    packet_plan_dict = packet_plan.to_dict()
    if not packet_plan.packets:
        skipped = _agent_skip_result("extraction_review_agent", packet_plan.status.lower())
        skipped["extraction_review_packet_plan"] = packet_plan_dict
        return skipped

    if not _can_run_agent(context):
        return {
            "status": "NOT_RUN",
            "agent_id": "extraction_review_agent",
            "policy": {},
            "audit_path": "",
            "bounded_response": {},
            "extraction_review_packet_plan": packet_plan_dict,
        }

    packet_results: list[dict[str, Any]] = []
    for packet in packet_plan.packets:
        fields = packet.get("review_targets") if isinstance(packet.get("review_targets"), list) else []
        field_paths = [
            str(field.get("field_path", "")).strip()
            for field in fields
            if isinstance(field, dict) and str(field.get("field_path", "")).strip()
        ]
        candidate_anchors: list[dict[str, Any]] = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            for candidate in field.get("candidates", []):
                if not isinstance(candidate, dict):
                    continue
                source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
                artifact_id = str(source.get("artifact_id", "")).strip()
                if not artifact_id:
                    continue
                candidate_anchors.append(
                    {
                        "anchor_type": "schema_field_candidate",
                        "artifact_id": artifact_id,
                        "field_path": str(field.get("field_path", "")).strip(),
                        "method": str(candidate.get("method", "")).strip(),
                    }
                )
        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="extraction_review_agent",
                stage_name="extraction",
                task_name="entity_review",
                inputs=packet,
                metadata={
                    "service": "extraction_service",
                    "packet_version": packet.get("extraction_review_packet_version"),
                    "packet_index": packet.get("packet_index"),
                    "packet_target_count": len(field_paths),
                    "packet_plan_status": packet_plan.status,
                },
                trigger_reason="compact_extraction_review_requested",
                associated_field_paths=field_paths,
                evidence_anchors=candidate_anchors[:30],
                suggested_output_fields=[
                    "recommended_candidate",
                    "candidate_rankings",
                    "review_flag",
                    "rationale",
                    "confidence",
                    "per_field_review",
                ],
            ),
        )
        packet_results.append(
            {
                "packet_index": packet.get("packet_index"),
                "status": str(result.get("status", "NOT_RUN")).strip() or "NOT_RUN",
                "policy": result.get("policy", {}),
                "audit_path": str(result.get("audit_path", "")).strip(),
                "bounded_response": result.get("structured_output", {}),
            }
        )

    statuses = [str(item.get("status", "")).strip() for item in packet_results]
    completed = [status for status in statuses if status in {"COMPLETED", "ALLOWED", "SUCCESS"}]
    blocked = [status for status in statuses if "PROMPT_TOO_LARGE" in status or "BLOCK" in status.upper()]
    status = "COMPLETED" if completed and len(completed) == len(packet_results) else "PARTIAL" if completed else "BLOCKED" if blocked else (statuses[0] if statuses else "NOT_RUN")
    return {
        "run_id": str(getattr(context, "run_id", "")).strip(),
        "status": status,
        "policy": packet_results[0].get("policy", {}) if packet_results else {},
        "audit_path": packet_results[0].get("audit_path", "") if packet_results else "",
        "bounded_response": {
            "packet_results": packet_results,
            "review_notes": [
                "Extraction review used compact field-level packets; full artifacts/entities/schema blobs were not sent to the agent."
            ],
        },
        "agent_id": "extraction_review_agent",
        "extraction_review_packet_plan": packet_plan_dict,
    }

def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_confidence(value: Any) -> str:
    if isinstance(value, (int, float)):
        if value >= 0.8:
            return "HIGH"
        if value >= 0.5:
            return "MODERATE"
        if value > 0:
            return "LOW"
        return "LOW"

    text = _safe_str(value).upper()
    if text in {"HIGH", "MODERATE", "LOW"}:
        return text
    return "LOW"


def _confidence_score(value: Any) -> int:
    text = _normalize_confidence(value)
    if text == "HIGH":
        return 3
    if text == "MODERATE":
        return 2
    if text == "LOW":
        return 1
    return 0

def _numeric_value_key(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(round(float(value), 6))
    text = _safe_str(value).lower().replace(",", "")
    return text


def _candidate_numeric_confidence(candidate: dict[str, Any]) -> float:
    value = candidate.get("confidence")
    if isinstance(value, (int, float)):
        return float(value)
    label = _normalize_confidence(value)
    return {"HIGH": 0.86, "MODERATE": 0.62, "LOW": 0.35}.get(label, 0.0)


def _candidate_source_family(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    source_family = _safe_str(metadata.get("source_family")).upper()
    if source_family:
        return source_family
    method = _safe_str(candidate.get("method") or candidate.get("source_method")).lower()
    if method.startswith("project_primary"):
        return "PROJECT_PRIMARY"
    if "schedule" in method or "table" in method:
        return "PROJECT_SUPPORTING"
    if "drawing" in method:
        return "PROJECT_DRAWING"
    return "UNKNOWN"


_DRAWING_POLICY_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "facility.generators.count": ("generator_unit_count", "facility.generators.count", "facility.generator_count"),
    "facility.ups.count": ("ups_unit_count", "facility.ups.count", "facility.ups_count"),
    "facility.transformers.count": ("interconnection_transformer_unit_count", "facility.transformers.count", "facility.transformer_count"),
    "facility.poi_voltage_kv": ("nominal_poi_voltage_kv", "facility.poi_voltage_kv"),
    "facility.electrical_configuration.internal_voltage_levels": (
        "facility_nominal_medium_voltage_kv",
        "facility.electrical_configuration.internal_voltage_levels",
    ),
}


def _build_drawing_escalation_policy(schema_field_candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build field-level evidence sufficiency gates for drawing LLM interpretation.

    Drawing LLM calls are still allowed when a field is unresolved or materially
    conflicted. They are suppressed when project-primary form/schedule evidence
    already provides one strong answer and there is no comparable strong conflict.
    """
    by_field: dict[str, list[dict[str, Any]]] = {}
    for candidate in schema_field_candidates:
        if not isinstance(candidate, dict):
            continue
        field_path = _safe_str(candidate.get("field_path"))
        if not field_path:
            continue
        by_field.setdefault(field_path, []).append(candidate)

    policy: dict[str, dict[str, Any]] = {}
    for drawing_field, aliases in _DRAWING_POLICY_FIELD_ALIASES.items():
        relevant: list[dict[str, Any]] = []
        for alias in aliases:
            relevant.extend(by_field.get(alias, []))
        strong_project = [
            candidate
            for candidate in relevant
            if _candidate_source_family(candidate) in {"PROJECT_PRIMARY", "PROJECT_SUPPORTING"}
            and _candidate_numeric_confidence(candidate) >= 0.82
            and not _is_empty_value(candidate.get("value"))
        ]
        if not strong_project:
            continue
        strong_project.sort(key=lambda item: _candidate_numeric_confidence(item), reverse=True)
        best = strong_project[0]
        best_key = _numeric_value_key(best.get("value"))
        comparable_conflicts = [
            candidate
            for candidate in strong_project[1:]
            if _candidate_numeric_confidence(candidate) >= 0.78
            and _numeric_value_key(candidate.get("value")) != best_key
        ]
        if comparable_conflicts:
            policy[drawing_field] = {
                "evidence_sufficient": False,
                "reason": "comparable project-primary candidates conflict; LLM escalation remains allowed",
                "best_value": best.get("value"),
                "conflict_count": len(comparable_conflicts),
            }
            continue
        policy[drawing_field] = {
            "evidence_sufficient": True,
            "reason": "high-confidence project-primary evidence already resolves this drawing-routed field",
            "best_value": best.get("value"),
            "best_candidate_id": best.get("candidate_id"),
            "best_artifact_id": best.get("artifact_id") or best.get("source_artifact_id"),
            "confidence": _candidate_numeric_confidence(best),
        }
    return policy


def _summarize_drawing_escalation_decisions(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    skipped = [item for item in decisions if item.get("decision") == "SKIPPED"]
    escalated = [item for item in decisions if item.get("decision") == "ESCALATED"]
    return {
        "skipped_count": len(skipped),
        "escalated_count": len(escalated),
        "skip_reasons": sorted({str(item.get("reason", "")).strip() for item in skipped if str(item.get("reason", "")).strip()}),
        "escalated_fields": sorted({str(item.get("field_path", "")).strip() for item in escalated if str(item.get("field_path", "")).strip()}),
    }


def _coerce_page_number(value: Any, evidence: dict[str, Any] | None = None) -> int:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(evidence, dict):
        evidence_page = evidence.get("page")
        if isinstance(evidence_page, int) and evidence_page > 0:
            return evidence_page
    return 1


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _region_priority_from_value(value: Any) -> int:
    text = _safe_str(value).upper()
    if text in {"DIAGRAM_EVIDENCE_REGION", "DIAGRAM_PAGE", "DRAWING"}:
        return 4
    if text in {"TITLE_BLOCK_REGION"}:
        return 3
    if text in {"TABLE_EVIDENCE_REGION", "TABLE_PAGE"}:
        return 3
    if text in {"TEXT_EVIDENCE_REGION", "NARRATIVE_PAGE"}:
        return 2
    return 1


def _score_region_plan_item(
    *,
    region_type: str,
    extraction_profiles: list[str],
    page_classification: str,
    field_paths: list[str],
    text: str,
) -> tuple[int, str]:
    priority = 0

    priority += _region_priority_from_value(region_type)
    priority += _region_priority_from_value(page_classification)

    if "DIAGRAM_EVIDENCE_EXTRACTION" in extraction_profiles:
        priority += 2
    if "TABLE_EVIDENCE_EXTRACTION" in extraction_profiles:
        priority += 2
    if "TEXT_EVIDENCE_EXTRACTION" in extraction_profiles:
        priority += 1

    if len(field_paths) >= 3:
        priority += 2
    elif len(field_paths) >= 1:
        priority += 1

    normalized_text = _safe_str(text)
    if normalized_text:
        if len(normalized_text) >= 80:
            priority += 2
        elif len(normalized_text) >= 20:
            priority += 1

    if priority >= 8:
        confidence = "HIGH"
    elif priority >= 5:
        confidence = "MODERATE"
    else:
        confidence = "LOW"

    return priority, confidence


def _method_priority(method: str) -> int:
    method_lower = _safe_str(method).lower()
    if "drawing" in method_lower:
        return 5
    if "table" in method_lower:
        return 4
    if "spec" in method_lower:
        return 4
    if "retrieval" in method_lower:
        return 3
    if "llm" in method_lower:
        return 2
    if "regex" in method_lower:
        return 1
    return 1


def _is_inventory_like_field(field_path: str) -> bool:
    normalized = _safe_str(field_path).lower()
    return (
        normalized.endswith(".count")
        or ".ratings" in normalized
        or normalized.endswith(".ratings_mva")
        or normalized.endswith(".relay_settings")
    )


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int, int, int]:
    evidence = candidate.get("evidence", {})
    if isinstance(evidence, list) and evidence:
        first_evidence = evidence[0] if isinstance(evidence[0], dict) else {}
    elif isinstance(evidence, dict):
        first_evidence = evidence
    else:
        first_evidence = {}

    region = first_evidence.get("region") or first_evidence.get("region_type")
    page = candidate.get("page_number")
    if not isinstance(page, int) or page <= 0:
        page = _coerce_page_number(first_evidence.get("page"), first_evidence)

    recommended_score = 1 if bool(candidate.get("recommended")) else 0

    return (
        recommended_score,
        _region_priority_from_value(region),
        _method_priority(_safe_str(candidate.get("method"))),
        _confidence_score(candidate.get("confidence")),
        -page,
    )


def _normalize_candidate_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, dict):
        parts = [f"{_safe_str(key).lower()}={_normalize_candidate_value(value[key])}" for key in sorted(value.keys())]
        return "|".join(parts)
    if isinstance(value, (list, tuple)):
        return "|".join(_normalize_candidate_value(item) for item in value)
    return repr(value)




def _candidate_artifact_id(candidate: dict[str, Any]) -> str:
    artifact_id = _safe_str(candidate.get("artifact_id")) or _safe_str(candidate.get("source_artifact_id"))
    if artifact_id:
        return artifact_id
    evidence = candidate.get("evidence")
    if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
        return _safe_str(evidence[0].get("artifact_id"))
    if isinstance(evidence, dict):
        return _safe_str(evidence.get("artifact_id"))
    return ""


def _enrich_schema_candidate_source_metadata(
    candidate: dict[str, Any],
    ontology_by_artifact_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach document-role/source-authority signals to schema candidates.

    Downstream field resolution uses these hints when ranking project forms, drawings,
    equipment schedules, OEM references, and applicant/interview evidence.
    """
    enriched = dict(candidate)
    artifact_id = _candidate_artifact_id(enriched)
    ontology = ontology_by_artifact_id.get(artifact_id, {}) if artifact_id else {}
    if not isinstance(ontology, dict):
        ontology = {}

    metadata = dict(enriched.get("metadata", {}) if isinstance(enriched.get("metadata"), dict) else {})
    ontology_metadata = ontology.get("metadata", {}) if isinstance(ontology.get("metadata"), dict) else {}

    document_role = _safe_str(ontology.get("document_role")) or _safe_str(metadata.get("document_role"))
    document_type = _safe_str(ontology.get("document_type")) or _safe_str(metadata.get("document_type"))
    document_family = _safe_str(ontology.get("document_family")) or _safe_str(metadata.get("document_family"))
    source_authority_hint = (
        _safe_str(ontology_metadata.get("source_authority_hint"))
        or _safe_str(metadata.get("source_authority_hint"))
        or "applicant_inferred_document"
    )

    if document_role:
        enriched["document_role"] = document_role
        enriched["source_role"] = document_role
        metadata["document_role"] = document_role
    if document_type:
        enriched["document_type"] = document_type
        metadata["document_type"] = document_type
    if document_family:
        enriched["document_family"] = document_family
        metadata["document_family"] = document_family
    metadata["source_authority_hint"] = source_authority_hint
    enriched["source_authority_hint"] = source_authority_hint

    matched_signals = ontology.get("matched_signals")
    if isinstance(matched_signals, list) and matched_signals:
        metadata["document_role_matched_signals"] = [_safe_str(item) for item in matched_signals if _safe_str(item)]

    enriched["metadata"] = metadata
    return enriched


def _candidate_to_entity(candidate: dict[str, Any]) -> dict[str, Any] | None:
    field_path = _safe_str(candidate.get("field_path"))
    artifact_id = _safe_str(candidate.get("artifact_id")) or _safe_str(candidate.get("source_artifact_id"))
    candidate_id = _safe_str(candidate.get("candidate_id"))

    evidence = candidate.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}

    page_number = _coerce_page_number(candidate.get("page_number"), evidence)

    if not field_path or not artifact_id:
        return None
    if _is_empty_value(candidate.get("value")):
        return None

    if not candidate_id:
        safe_field_fragment = field_path.replace(".", "_")
        candidate_id = f"candidate_{artifact_id}_{safe_field_fragment}"

    source_refs = candidate.get("source_ref", [])
    if not isinstance(source_refs, list):
        source_refs = []

    source_anchor_id = f"{artifact_id}_anchor_{int(page_number):03d}"
    if source_refs:
        first_ref = _safe_str(source_refs[0])
        if first_ref:
            source_anchor_id = first_ref

    value = candidate.get("value")
    confidence = _normalize_confidence(candidate.get("confidence"))
    rationale = _safe_str(candidate.get("rationale"))
    method = _safe_str(candidate.get("method")) or "schema_extraction"
    candidate_type = _safe_str(candidate.get("candidate_type")) or "schema_candidate"

    attributes = {
        "value": value,
        "parameter_path": field_path,
        "normalized_value": value,
        "confidence": confidence,
        "rationale": rationale,
        "extraction_method": method,
        "metadata": candidate.get("metadata", {}) if isinstance(candidate.get("metadata"), dict) else {},
    }

    review_notes = candidate.get("review_notes", [])
    if isinstance(review_notes, list) and review_notes:
        attributes["review_notes"] = [
            _safe_str(item) for item in review_notes if _safe_str(item)
        ]

    if bool(candidate.get("recommended")):
        attributes["recommended_candidate"] = True

    return {
        "entity_id": candidate_id,
        "type": candidate_type,
        "name": field_path,
        "attributes": attributes,
        "units": {},
        "source_anchor_id": source_anchor_id,
    }


def _candidate_to_schema_field_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    field_path = _safe_str(candidate.get("field_path"))
    artifact_id = _safe_str(candidate.get("artifact_id")) or _safe_str(candidate.get("source_artifact_id"))
    if not field_path or not artifact_id:
        return None
    if _is_empty_value(candidate.get("value")):
        return None

    raw_evidence = candidate.get("evidence", {})
    evidence_dict = raw_evidence if isinstance(raw_evidence, dict) else {}

    page_number = _coerce_page_number(candidate.get("page_number"), evidence_dict)
    candidate_id = _safe_str(candidate.get("candidate_id"))
    if not candidate_id:
        safe_field_fragment = field_path.replace(".", "_")
        candidate_id = f"schema_{artifact_id}_{safe_field_fragment}_{page_number:03d}"

    rationale = _safe_str(candidate.get("rationale"))
    method = _safe_str(candidate.get("method")) or "schema_extraction"
    confidence = _normalize_confidence(candidate.get("confidence"))

    source_ref = candidate.get("source_ref")
    if isinstance(source_ref, list):
        source_refs = [_safe_str(item) for item in source_ref if _safe_str(item)]
    elif source_ref:
        source_refs = [_safe_str(source_ref)]
    else:
        source_refs = [f"{artifact_id}_anchor_{page_number:03d}"]

    evidence_list: list[dict[str, Any]] = []
    if evidence_dict:
        evidence_entry = dict(evidence_dict)
        evidence_entry.setdefault("page", page_number)
        evidence_entry.setdefault("source_refs", source_refs)
        evidence_entry.setdefault("method", method)
        evidence_list.append(evidence_entry)

    metadata = candidate.get("metadata", {}) if isinstance(candidate.get("metadata"), dict) else {}
    review_notes = candidate.get("review_notes", [])
    if isinstance(review_notes, list) and review_notes:
        metadata = dict(metadata)
        metadata["review_notes"] = [_safe_str(item) for item in review_notes if _safe_str(item)]

    if bool(candidate.get("recommended")):
        metadata = dict(metadata)
        metadata["recommended_candidate"] = True

    return {
        "candidate_id": candidate_id,
        "artifact_id": artifact_id,
        "field_path": field_path,
        "value": candidate.get("value"),
        "confidence": confidence,
        "candidate_type": _safe_str(candidate.get("candidate_type")) or "schema_candidate",
        "method": method,
        "rationale": rationale,
        "page_number": page_number,
        "source_ref": source_refs,
        "evidence": evidence_list,
        "metadata": metadata,
        "review_notes": [_safe_str(item) for item in review_notes if _safe_str(item)] if isinstance(review_notes, list) else [],
        "recommended": bool(candidate.get("recommended")),
    }


def _normalize_schema_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None

    artifact_id = _safe_str(candidate.get("artifact_id")) or _safe_str(candidate.get("source_artifact_id"))
    field_path = _safe_str(candidate.get("field_path"))
    if not artifact_id or not field_path:
        return None
    if _is_empty_value(candidate.get("value")):
        return None

    normalized = dict(candidate)
    normalized["artifact_id"] = artifact_id
    normalized["confidence"] = _normalize_confidence(candidate.get("confidence"))

    source_ref = candidate.get("source_ref")
    if isinstance(source_ref, list):
        source_refs = [_safe_str(item) for item in source_ref if _safe_str(item)]
    elif source_ref:
        source_refs = [_safe_str(source_ref)]
    else:
        source_refs = []

    page_number = candidate.get("page_number")
    if not isinstance(page_number, int) or page_number <= 0:
        evidence = candidate.get("evidence")
        if isinstance(evidence, list) and evidence:
            first_evidence = evidence[0]
            if isinstance(first_evidence, dict):
                page_number = _coerce_page_number(first_evidence.get("page"), first_evidence)
            else:
                page_number = 1
        elif isinstance(evidence, dict):
            page_number = _coerce_page_number(evidence.get("page"), evidence)
        else:
            page_number = 1
    normalized["page_number"] = page_number

    if not source_refs:
        source_refs = [f"{artifact_id}_anchor_{page_number:03d}"]
    normalized["source_ref"] = source_refs

    evidence_payload = candidate.get("evidence")
    if evidence_payload is None:
        normalized["evidence"] = []
    elif isinstance(evidence_payload, list):
        normalized["evidence"] = evidence_payload
    elif isinstance(evidence_payload, dict):
        evidence_entry = dict(evidence_payload)
        evidence_entry.setdefault("page", page_number)
        evidence_entry.setdefault("source_refs", source_refs)
        evidence_entry.setdefault("method", _safe_str(candidate.get("method")) or "schema_extraction")
        normalized["evidence"] = [evidence_entry]
    else:
        normalized["evidence"] = []

    review_notes = candidate.get("review_notes", [])
    if isinstance(review_notes, list):
        normalized["review_notes"] = [_safe_str(item) for item in review_notes if _safe_str(item)]
    else:
        normalized["review_notes"] = []

    normalized["recommended"] = bool(candidate.get("recommended"))
    return normalized


def _deduplicate_orchestrated_schema_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, int]] = set()

    for raw_candidate in candidates:
        candidate = _normalize_schema_candidate(raw_candidate)
        if candidate is None:
            continue

        artifact_id = _safe_str(candidate.get("artifact_id"))
        field_path = _safe_str(candidate.get("field_path"))
        method = _safe_str(candidate.get("method")) or "schema_extraction"
        value_key = _normalize_candidate_value(candidate.get("value"))
        page = int(candidate.get("page_number", 1))

        key = (artifact_id, field_path, method, value_key, page)
        if key in seen:
            continue

        seen.add(key)
        deduped.append(candidate)

    return deduped


def _filter_orchestrated_schema_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_field: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for raw_candidate in candidates:
        candidate = _normalize_schema_candidate(raw_candidate)
        if candidate is None:
            continue

        field_path = _safe_str(candidate.get("field_path"))
        artifact_id = _safe_str(candidate.get("artifact_id"))
        if not artifact_id or not field_path:
            continue

        key = (artifact_id, field_path)
        by_field.setdefault(key, []).append(candidate)

    filtered: list[dict[str, Any]] = []

    for (_, field_path), items in by_field.items():
        if _is_inventory_like_field(field_path):
            unique_inventory: dict[tuple[str, int], dict[str, Any]] = {}
            for item in items:
                page = int(item.get("page_number", 1))
                value_key = _normalize_candidate_value(item.get("value"))
                inventory_key = (value_key, page)
                best_existing = unique_inventory.get(inventory_key)
                if best_existing is None or _candidate_sort_key(item) > _candidate_sort_key(best_existing):
                    unique_inventory[inventory_key] = item

            filtered.extend(sorted(unique_inventory.values(), key=_candidate_sort_key, reverse=True))
            continue

        ranked = sorted(items, key=_candidate_sort_key, reverse=True)
        kept_values: set[str] = set()
        kept_count = 0

        for item in ranked:
            value_key = _normalize_candidate_value(item.get("value"))
            if value_key in kept_values:
                continue

            kept_values.add(value_key)
            filtered.append(item)
            kept_count += 1

            if kept_count >= SCALAR_FIELD_MAX_CANDIDATES_PER_ARTIFACT:
                break

    return filtered


def _build_anchor_from_candidate(
    candidate: dict[str, Any],
    artifacts_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    artifact_id = _safe_str(candidate.get("artifact_id")) or _safe_str(candidate.get("source_artifact_id"))
    if not artifact_id:
        return None

    artifact = artifacts_by_id.get(artifact_id, {})
    file_name = _safe_str(artifact.get("file_name")) or artifact_id
    evidence = candidate.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}
    page_number = _coerce_page_number(candidate.get("page_number"), evidence)

    excerpt = _safe_str(candidate.get("rationale"))
    if not excerpt:
        excerpt = _safe_str(evidence.get("excerpt"))

    return build_source_anchor(
        artifact_id=artifact_id,
        file_name=file_name,
        page=page_number,
        source_method=_safe_str(candidate.get("method")) or "extraction_orchestrator",
        excerpt=excerpt or None,
    )


def _extract_layout_summary_by_artifact(
    layout_analysis_result: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(layout_analysis_result, dict):
        return {}

    documents = layout_analysis_result.get("documents", [])
    if not isinstance(documents, list):
        return {}

    summary_by_artifact: dict[str, dict[str, Any]] = {}

    for document in documents:
        if not isinstance(document, dict):
            continue

        artifact_id = _safe_str(document.get("artifact_id"))
        if not artifact_id:
            continue

        document_profiles = document.get("extraction_profiles", [])
        if not isinstance(document_profiles, list):
            document_profiles = []

        pages = document.get("pages", [])
        if not isinstance(pages, list):
            pages = []

        page_classifications: list[str] = []
        candidate_region_types: list[str] = []

        for page in pages:
            if not isinstance(page, dict):
                continue

            page_classification = _safe_str(page.get("page_classification"))
            if page_classification:
                page_classifications.append(page_classification)

            regions = page.get("candidate_regions", [])
            if not isinstance(regions, list):
                regions = []

            for region in regions:
                if not isinstance(region, dict):
                    continue
                region_type = _safe_str(region.get("region_type"))
                if region_type:
                    candidate_region_types.append(region_type)

        summary_by_artifact[artifact_id] = {
            "document_classification": _safe_str(document.get("document_classification")),
            "extraction_profiles": sorted(set(_safe_str(item) for item in document_profiles if _safe_str(item))),
            "page_classifications": sorted(set(page_classifications)),
            "candidate_region_types": sorted(set(candidate_region_types)),
        }

    return summary_by_artifact


def _extract_layout_documents_by_artifact(
    layout_analysis_result: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(layout_analysis_result, dict):
        return {}

    documents = layout_analysis_result.get("documents", [])
    if not isinstance(documents, list):
        return {}

    return {
        _safe_str(document.get("artifact_id")): document
        for document in documents
        if isinstance(document, dict) and _safe_str(document.get("artifact_id"))
    }


def _extract_parser_documents_by_artifact(
    document_parser_result: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(document_parser_result, dict):
        return {}

    documents = document_parser_result.get("parsed_documents", [])
    if not isinstance(documents, list):
        return {}

    return {
        _safe_str(document.get("artifact_id")): document
        for document in documents
        if isinstance(document, dict) and _safe_str(document.get("artifact_id"))
    }


def _extract_ocr_documents_by_artifact(
    ocr_result: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(ocr_result, dict):
        return {}

    documents = ocr_result.get("documents", [])
    if not isinstance(documents, list):
        return {}

    return {
        _safe_str(document.get("artifact_id")): document
        for document in documents
        if isinstance(document, dict) and _safe_str(document.get("artifact_id"))
    }


def _get_ocr_page(ocr_document: dict[str, Any], page_number: int) -> dict[str, Any] | None:
    pages = ocr_document.get("pages", [])
    if not isinstance(pages, list):
        return None

    for page in pages:
        if not isinstance(page, dict):
            continue
        if int(page.get("page_number", 0)) == page_number:
            return page

    return None


def _select_region_text_regions(
    page: dict[str, Any],
    region_bbox: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    text_regions = page.get("text_regions", [])
    if not isinstance(text_regions, list):
        return []

    if not isinstance(region_bbox, dict):
        return [region for region in text_regions if isinstance(region, dict)]

    selected: list[dict[str, Any]] = []
    for region in text_regions:
        if not isinstance(region, dict):
            continue

        region_box = region.get("bbox")
        if not isinstance(region_box, dict):
            selected.append(region)
            continue

        if _bbox_intersects(region_box, region_bbox):
            selected.append(region)

    return selected


def _region_text_from_sources(
    *,
    parser_blocks: list[dict[str, Any]],
    ocr_regions: list[dict[str, Any]],
    parser_fallback_text: str,
    ocr_fallback_text: str,
) -> str:
    parser_text = _region_text_from_blocks(parser_blocks, "")
    ocr_text = _region_text_from_blocks(ocr_regions, "")

    parts: list[str] = []
    for candidate in (parser_text, ocr_text, parser_fallback_text, ocr_fallback_text):
        normalized = _safe_str(candidate)
        if normalized and normalized not in parts:
            parts.append(normalized)

    return "\n".join(parts)


def _fallback_field_paths_for_artifact(
    *,
    artifact: dict[str, Any],
    ontology: dict[str, Any],
) -> list[str]:
    fallback_field_paths: list[str] = []
    file_name = _safe_str(artifact.get("file_name")).lower()
    classification = _safe_str(artifact.get("classification")).lower()
    ontology_type = _safe_str(ontology.get("artifact_type")).lower()

    if any(term in file_name for term in {"one-line", "single-line", "_fac", "schematic"}) or classification in {
        "one_line_diagram",
        "single_line_diagram",
    }:
        fallback_field_paths.extend(PHASE4_DRAWING_FIELD_PATHS)
    elif any(term in file_name for term in {"schedule", "relay", "table"}):
        fallback_field_paths.extend(PHASE4_TABLE_FIELD_PATHS)
    elif classification == "poi_interconnection_documentation" or ontology_type in {
        "supporting_document",
        "spec_sheet",
        "vendor_datasheet",
    } or file_name.endswith(".pdf"):
        fallback_field_paths.extend(PHASE4_RETRIEVAL_FIELD_PATHS)

    deduped_fallback_paths: list[str] = []
    seen_paths: set[str] = set()
    for field_path in fallback_field_paths:
        if field_path not in seen_paths:
            deduped_fallback_paths.append(field_path)
            seen_paths.add(field_path)

    return deduped_fallback_paths


def _build_relevance_plan_entry(
    *,
    artifact: dict[str, Any],
    ontology: dict[str, Any],
    parser_document: dict[str, Any] | None,
    layout_document: dict[str, Any] | None,
    ocr_document: dict[str, Any] | None,
    region_execution_plan: list[dict[str, Any]],
    fallback_field_paths: list[str],
) -> dict[str, Any]:
    planned_regions: list[dict[str, Any]] = []

    for item in region_execution_plan:
        source_preferences: list[str] = []
        if isinstance(parser_document, dict):
            source_preferences.append("parser_text_blocks")
        if isinstance(ocr_document, dict):
            source_preferences.append("ocr_regions")
        source_preferences.append("artifact_merged_text")

        planned_regions.append(
            {
                "page_number": int(item.get("page_number", 0) or 0),
                "region_id": _safe_str(item.get("region_id")),
                "region_type": _safe_str(item.get("region_type")),
                "page_classification": _safe_str(item.get("page_classification")),
                "field_paths": list(item.get("field_paths", []))
                if isinstance(item.get("field_paths"), list)
                else [],
                "extraction_profiles": list(item.get("extraction_profiles", []))
                if isinstance(item.get("extraction_profiles"), list)
                else [],
                "source_preferences": source_preferences,
                "planned_status": "PLANNED",
                "region_priority": int(item.get("region_priority", 0) or 0),
                "region_confidence": _safe_str(item.get("region_confidence")) or "LOW",
            }
        )

    layout_document_classification = ""
    if isinstance(layout_document, dict):
        layout_document_classification = _safe_str(layout_document.get("document_classification"))

    document_role = _safe_str(ontology.get("document_role"))
    if not document_role:
        document_role = (
            _safe_str(artifact.get("document_role"))
            or _safe_str(artifact.get("classification"))
            or _safe_str(ontology.get("artifact_type"))
            or "UNCLASSIFIED"
        )

    document_family = _safe_str(ontology.get("document_family"))
    if not document_family:
        document_family = _safe_str(artifact.get("document_family")) or "unknown"

    worker_bias_raw = ontology.get("worker_bias") if isinstance(ontology, dict) else []
    if not isinstance(worker_bias_raw, list):
        worker_bias_raw = []
    worker_bias = [str(item).strip() for item in worker_bias_raw if str(item).strip()]

    return {
        "artifact_id": _safe_str(artifact.get("artifact_id")),
        "file_name": _safe_str(artifact.get("file_name")),
        "classification": _safe_str(artifact.get("classification")) or _safe_str(ontology.get("artifact_type")),
        "document_role": document_role,
        "document_role_contract": document_role,
        "document_family": document_family,
        "worker_bias": worker_bias,
        "route_hint": _safe_str(parser_document.get("route_hint")) if isinstance(parser_document, dict) else "",
        "document_classification": layout_document_classification,
        "planned_regions": planned_regions,
        "fallback_field_paths": list(fallback_field_paths),
        "fallback_strategy": "artifact_text_fallback" if fallback_field_paths else "none",
    }


def _bbox_value(bbox: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = bbox.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _bbox_intersects(block_bbox: dict[str, Any], region_bbox: dict[str, Any]) -> bool:
    block_x0 = _bbox_value(block_bbox, "x0")
    block_x1 = _bbox_value(block_bbox, "x1")
    block_top = _bbox_value(block_bbox, "top", "y0")
    block_bottom = _bbox_value(block_bbox, "bottom", "y1")

    region_x0 = _bbox_value(region_bbox, "x0")
    region_x1 = _bbox_value(region_bbox, "x1")
    region_top = _bbox_value(region_bbox, "top", "y0")
    region_bottom = _bbox_value(region_bbox, "bottom", "y1")

    if (
        block_x0 is None
        or block_x1 is None
        or block_top is None
        or block_bottom is None
        or region_x0 is None
        or region_x1 is None
        or region_top is None
        or region_bottom is None
    ):
        return True

    return not (
        block_x1 < region_x0
        or block_x0 > region_x1
        or block_bottom < region_top
        or block_top > region_bottom
    )


def _get_parser_page(parser_document: dict[str, Any], page_number: int) -> dict[str, Any] | None:
    pages = parser_document.get("pages", [])
    if not isinstance(pages, list):
        return None

    for page in pages:
        if not isinstance(page, dict):
            continue
        if int(page.get("page_number", 0)) == page_number:
            return page

    return None


def _select_region_blocks(page: dict[str, Any], region_bbox: dict[str, Any] | None) -> list[dict[str, Any]]:
    text_blocks = page.get("text_blocks", [])
    if not isinstance(text_blocks, list):
        return []

    if not isinstance(region_bbox, dict):
        return [block for block in text_blocks if isinstance(block, dict)]

    selected: list[dict[str, Any]] = []
    for block in text_blocks:
        if not isinstance(block, dict):
            continue

        block_bbox = block.get("bbox")
        if not isinstance(block_bbox, dict):
            selected.append(block)
            continue

        if _bbox_intersects(block_bbox, region_bbox):
            selected.append(block)

    return selected


def _region_text_from_blocks(blocks: list[dict[str, Any]], fallback_text: str) -> str:
    parts = [_safe_str(block.get("text")) for block in blocks if isinstance(block, dict) and _safe_str(block.get("text"))]
    if parts:
        return "\n".join(parts)
    return fallback_text


def _region_artifact_type(
    *,
    artifact: dict[str, Any],
    region_type: str,
    extraction_profiles: list[str],
    page_classification: str,
) -> str:
    file_name = _safe_str(artifact.get("file_name")).lower()

    if region_type in DRAWING_REGION_TYPES or "DIAGRAM_EVIDENCE_EXTRACTION" in extraction_profiles:
        return "one_line_diagram"

    if region_type in TABLE_REGION_TYPES or "TABLE_EVIDENCE_EXTRACTION" in extraction_profiles:
        if "relay" in file_name:
            return "relay_schedule"
        return "relay_table"

    if region_type == "TITLE_BLOCK_REGION":
        return "supporting_document"

    if region_type == "TEXT_EVIDENCE_REGION":
        if "TEXT_EVIDENCE_RETRIEVAL" in extraction_profiles:
            return "supporting_document"
        if page_classification == "NARRATIVE_PAGE":
            return "supporting_document"

    return _safe_str(artifact.get("artifact_type")) or _safe_str(artifact.get("classification")) or "supporting_document"


def _field_paths_for_region(
    *,
    artifact: dict[str, Any],
    region_type: str,
    extraction_profiles: list[str],
    page_classification: str,
    ontology: dict[str, Any],
) -> list[str]:
    field_paths: list[str] = []
    file_name = _safe_str(artifact.get("file_name")).lower()
    classification = _safe_str(artifact.get("classification")).lower()
    ontology_type = _safe_str(ontology.get("artifact_type")).lower()

    if region_type in DRAWING_REGION_TYPES or "DIAGRAM_EVIDENCE_EXTRACTION" in extraction_profiles:
        field_paths.extend(PHASE4_DRAWING_FIELD_PATHS)

    elif region_type in TABLE_REGION_TYPES or "TABLE_EVIDENCE_EXTRACTION" in extraction_profiles:
        field_paths.extend(PHASE4_TABLE_FIELD_PATHS)

    elif region_type == "TITLE_BLOCK_REGION":
        field_paths.extend(PHASE4_SPEC_FIELD_PATHS)

    elif region_type == "TEXT_EVIDENCE_REGION":
        if "TEXT_EVIDENCE_RETRIEVAL" in extraction_profiles or page_classification == "NARRATIVE_PAGE":
            field_paths.extend(PHASE4_RETRIEVAL_FIELD_PATHS)

    if not field_paths:
        if any(term in file_name for term in {"one-line", "single-line", "_fac", "schematic"}):
            field_paths.extend(PHASE4_DRAWING_FIELD_PATHS)
        elif any(term in file_name for term in {"schedule", "relay", "table"}):
            field_paths.extend(PHASE4_TABLE_FIELD_PATHS)
        elif classification == "poi_interconnection_documentation" or ontology_type in {
            "supporting_document",
            "spec_sheet",
            "vendor_datasheet",
        }:
            field_paths.extend(PHASE4_RETRIEVAL_FIELD_PATHS)

    deduped: list[str] = []
    seen: set[str] = set()
    for field_path in field_paths:
        if field_path not in seen:
            deduped.append(field_path)
            seen.add(field_path)

    return deduped


def _build_region_execution_plan(
    *,
    artifact: dict[str, Any],
    parser_document: dict[str, Any] | None,
    layout_document: dict[str, Any] | None,
    ocr_document: dict[str, Any] | None,
    ontology: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(layout_document, dict):
        return []

    plan: list[dict[str, Any]] = []
    pages = layout_document.get("pages", [])
    if not isinstance(pages, list):
        return []

    for page in pages:
        if not isinstance(page, dict):
            continue

        page_number = int(page.get("page_number", 0))
        if page_number <= 0:
            continue

        page_classification = _safe_str(page.get("page_classification"))
        extraction_profiles = page.get("extraction_profiles", [])
        if not isinstance(extraction_profiles, list):
            extraction_profiles = []

        parser_page = _get_parser_page(parser_document or {}, page_number) if parser_document else None
        ocr_page = _get_ocr_page(ocr_document or {}, page_number) if ocr_document else None

        parser_fallback_text = _safe_str(parser_page.get("extracted_text")) if isinstance(parser_page, dict) else ""
        ocr_fallback_text = _safe_str(ocr_page.get("extracted_text")) if isinstance(ocr_page, dict) else ""

        regions = page.get("candidate_regions", [])
        if not isinstance(regions, list):
            regions = []

        if not regions and (parser_page is not None or ocr_page is not None):
            field_paths = _field_paths_for_region(
                artifact=artifact,
                region_type="TEXT_EVIDENCE_REGION",
                extraction_profiles=extraction_profiles,
                page_classification=page_classification,
                ontology=ontology,
            )
            if field_paths:
                parser_blocks = _select_region_blocks(parser_page or {}, None)
                ocr_regions = _select_region_text_regions(ocr_page or {}, None)
                region_text = _region_text_from_sources(
                    parser_blocks=parser_blocks,
                    ocr_regions=ocr_regions,
                    parser_fallback_text=parser_fallback_text,
                    ocr_fallback_text=ocr_fallback_text,
                )
                if region_text:
                    region_priority, region_confidence = _score_region_plan_item(
                        region_type="TEXT_EVIDENCE_REGION",
                        extraction_profiles=list(extraction_profiles),
                        page_classification=page_classification,
                        field_paths=field_paths,
                        text=region_text,
                    )
                    plan.append(
                        {
                            "page_number": page_number,
                            "region_id": f"{_safe_str(artifact.get('artifact_id'))}_fallback_{page_number:03d}",
                            "region_type": "TEXT_EVIDENCE_REGION",
                            "extraction_profiles": list(extraction_profiles),
                            "page_classification": page_classification,
                            "text": region_text,
                            "field_paths": field_paths,
                            "bbox": None,
                            "region_priority": region_priority,
                            "region_confidence": region_confidence,
                        }
                    )
            continue

        for region in regions:
            if not isinstance(region, dict):
                continue

            region_type = _safe_str(region.get("region_type"))
            field_paths = _field_paths_for_region(
                artifact=artifact,
                region_type=region_type,
                extraction_profiles=extraction_profiles,
                page_classification=page_classification,
                ontology=ontology,
            )
            if not field_paths:
                continue

            region_bbox = region.get("bbox")
            region_bbox_dict = region_bbox if isinstance(region_bbox, dict) else None

            parser_blocks = _select_region_blocks(parser_page or {}, region_bbox_dict)
            ocr_regions = _select_region_text_regions(ocr_page or {}, region_bbox_dict)

            region_text = _region_text_from_sources(
                parser_blocks=parser_blocks,
                ocr_regions=ocr_regions,
                parser_fallback_text=parser_fallback_text,
                ocr_fallback_text=ocr_fallback_text,
            )
            if not region_text:
                continue

            region_priority, region_confidence = _score_region_plan_item(
                region_type=region_type,
                extraction_profiles=list(extraction_profiles),
                page_classification=page_classification,
                field_paths=field_paths,
                text=region_text,
            )

            plan.append(
                {
                    "page_number": page_number,
                    "region_id": _safe_str(region.get("region_id")) or f"{_safe_str(artifact.get('artifact_id'))}_{page_number:03d}",
                    "region_type": region_type,
                    "extraction_profiles": list(extraction_profiles),
                    "page_classification": page_classification,
                    "text": region_text,
                    "field_paths": field_paths,
                    "bbox": region_bbox_dict,
                    "region_priority": region_priority,
                    "region_confidence": region_confidence,
                }
            )

    plan.sort(
        key=lambda item: (
            int(item.get("region_priority", 0)),
            _region_priority_from_value(item.get("region_type")),
            -int(item.get("page_number", 0) or 0),
        ),
        reverse=True,
    )

    return plan


def _build_scoped_artifact(
    *,
    artifact: dict[str, Any],
    region_plan_item: dict[str, Any],
    ontology: dict[str, Any],
) -> dict[str, Any]:
    page_number = int(region_plan_item.get("page_number", 1))
    region_type = _safe_str(region_plan_item.get("region_type"))
    extraction_profiles = region_plan_item.get("extraction_profiles", [])
    if not isinstance(extraction_profiles, list):
        extraction_profiles = []

    artifact_type = _region_artifact_type(
        artifact=artifact,
        region_type=region_type,
        extraction_profiles=extraction_profiles,
        page_classification=_safe_str(region_plan_item.get("page_classification")),
    )

    scoped = dict(artifact)
    scoped["artifact_type"] = artifact_type
    scoped["page"] = page_number
    scoped["region"] = region_type
    scoped["section"] = _safe_str(region_plan_item.get("region_id"))
    scoped["parsed_text"] = _safe_str(region_plan_item.get("text"))
    scoped["text"] = _safe_str(region_plan_item.get("text"))
    scoped["text_content"] = _safe_str(region_plan_item.get("text"))
    scoped["extracted_text"] = _safe_str(region_plan_item.get("text"))
    scoped["layout_summary"] = {
        "document_classification": _safe_str(artifact.get("classification")) or _safe_str(ontology.get("artifact_type")),
        "page_classification": _safe_str(region_plan_item.get("page_classification")),
        "region_type": region_type,
        "extraction_profiles": list(extraction_profiles),
    }
    scoped["metadata"] = {
        "region_id": _safe_str(region_plan_item.get("region_id")),
        "region_type": region_type,
        "page_number": page_number,
        "bbox": region_plan_item.get("bbox"),
        "ontology": ontology,
    }
    return scoped


def _coerce_extraction_candidate(candidate: Any) -> dict[str, Any]:
    if isinstance(candidate, dict):
        return candidate

    review_notes = getattr(candidate, "review_notes", [])
    if not isinstance(review_notes, list):
        review_notes = []

    agent_policy = getattr(candidate, "agent_policy", {})
    if not isinstance(agent_policy, dict):
        agent_policy = {}

    return {
        "field_path": getattr(candidate, "field_path", ""),
        "value": getattr(candidate, "value", None),
        "confidence": getattr(candidate, "confidence", "LOW"),
        "source_artifact_id": getattr(candidate, "source_artifact_id", ""),
        "method": getattr(candidate, "method", ""),
        "evidence": getattr(candidate, "evidence", {}) or {},
        "review_notes": review_notes,
        "recommended": bool(getattr(candidate, "recommended", False)),
        "agent_id": getattr(candidate, "agent_id", None),
        "agent_status": getattr(candidate, "agent_status", None),
        "agent_audit_path": getattr(candidate, "agent_audit_path", None),
        "agent_policy": agent_policy,
    }


def _is_valid_topology_candidate(candidate: dict[str, Any]) -> bool:
    field_path = _safe_str(candidate.get("field_path"))
    if field_path not in {"facility.substation_configuration", "facility.ups.topology", "facility.topology"}:
        return False

    value = candidate.get("value")
    if _is_empty_value(value):
        return False

    if isinstance(value, dict) and not value:
        return False

    return True


def _extract_minimal_text_fallback_entities(
    *,
    artifact: dict[str, Any],
    anchor_id: str,
    text_content: str,
    ontology: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not _safe_str(text_content):
        return [], []

    fallback_entities: list[dict[str, Any]] = []
    fallback_entities.extend(extract_named_entities(artifact, anchor_id, text_content, ontology=ontology))
    fallback_entities.extend(extract_voltage_entities(artifact, anchor_id, text_content, ontology=ontology))
    fallback_entities.extend(extract_mw_entities(artifact, anchor_id, text_content, ontology=ontology))
    fallback_entities.extend(extract_transformer_rating_entities(artifact, anchor_id, text_content))

    fallback_topology = extract_topology_cues(artifact, text_content, ontology=ontology)

    return fallback_entities, fallback_topology


def run_service(
    context: Any,
    ingestion_result: dict[str, Any],
    document_parser_result: dict[str, Any] | None = None,
    layout_analysis_result: dict[str, Any] | None = None,
    ocr_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifacts = ingestion_result.get("artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []

    artifacts_by_id = {
        _safe_str(item.get("artifact_id")): item
        for item in artifacts
        if isinstance(item, dict) and _safe_str(item.get("artifact_id"))
    }

    schema = load_canonical_schema()

    entities: list[dict[str, Any]] = []
    topology_cues: list[dict[str, Any]] = []
    warnings: list[str] = []

    text_by_artifact_id, source_anchors, evidence_records_by_artifact, source_warnings = merge_text_sources(
        artifacts=artifacts,
        document_parser_result=document_parser_result,
        ocr_result=ocr_result,
    )
    warnings.extend(source_warnings)
    warnings.extend(layout_warnings(artifacts, layout_analysis_result))

    ontology = classify_artifacts(artifacts, text_by_artifact_id=text_by_artifact_id)
    ontology_by_artifact_id = {
        item["artifact_id"]: item
        for item in ontology
        if isinstance(item, dict) and isinstance(item.get("artifact_id"), str)
    }

    layout_summary_by_artifact = _extract_layout_summary_by_artifact(layout_analysis_result)
    layout_documents_by_artifact = _extract_layout_documents_by_artifact(layout_analysis_result)
    parser_documents_by_artifact = _extract_parser_documents_by_artifact(document_parser_result)
    ocr_documents_by_artifact = _extract_ocr_documents_by_artifact(ocr_result)

    relevance_plan: list[dict[str, Any]] = []

    if not DISABLE_LEGACY_REGEX:
        for artifact in artifacts:
            artifact_id = _safe_str(artifact.get("artifact_id"))
            anchor_id = f"{artifact_id}_anchor_001"

            if artifact_id and not any(_safe_str(anchor.get("anchor_id")) == anchor_id for anchor in source_anchors):
                source_anchors.append(
                    build_source_anchor(
                        artifact_id=artifact_id,
                        file_name=_safe_str(artifact.get("file_name")),
                        page=1,
                        source_method="artifact_default",
                    )
                )

            text_content = text_by_artifact_id.get(artifact_id, "")
            artifact_ontology = ontology_by_artifact_id.get(artifact_id, {})

            artifact_entities: list[dict[str, Any]] = []
            artifact_entities.extend(extract_named_entities(artifact, anchor_id, text_content, ontology=artifact_ontology))
            artifact_entities.extend(extract_voltage_entities(artifact, anchor_id, text_content, ontology=artifact_ontology))
            artifact_entities.extend(extract_mw_entities(artifact, anchor_id, text_content, ontology=artifact_ontology))
            artifact_entities.extend(extract_transformer_rating_entities(artifact, anchor_id, text_content))

            entities.extend(artifact_entities)
            topology_cues.extend(extract_topology_cues(artifact, text_content, ontology=artifact_ontology))

    legacy_schema_field_candidates = build_schema_field_candidates(
        artifacts=artifacts,
        schema=schema,
        evidence_records_by_artifact=evidence_records_by_artifact,
    )
    drawing_escalation_policy = _build_drawing_escalation_policy(legacy_schema_field_candidates)

    drawing_service = DrawingInterpretationService()
    drawing_results = drawing_service.extract(
        artifacts,
        PHASE4_DRAWING_FIELD_PATHS,
        context=context,
        escalation_policy=drawing_escalation_policy,
    )
    drawing_escalation_summary = _summarize_drawing_escalation_decisions(drawing_service.escalation_decisions)
    if drawing_escalation_summary["skipped_count"]:
        warnings.append(
            "Drawing interpretation LLM escalation skipped for "
            f"{drawing_escalation_summary['skipped_count']} candidate(s) because deterministic/project-primary evidence was sufficient or drawing signal was weak."
        )
    drawing_topology_artifacts_emitted: set[str] = set()

    for item in drawing_results:
        if not isinstance(item, dict):
            continue
        if _is_empty_value(item.get("value")):
            continue

        drawing_entity = _candidate_to_entity(item)
        if drawing_entity is not None:
            entities.append(drawing_entity)

        drawing_anchor = _build_anchor_from_candidate(item, artifacts_by_id)
        if drawing_anchor is not None:
            source_anchors.append(drawing_anchor)

        candidate_field_path = _safe_str(item.get("field_path"))
        candidate_value = item.get("value")
        drawing_artifact_id = _safe_str(item.get("source_artifact_id"))
        if _is_valid_topology_candidate(item) or (
            candidate_field_path == "facility.substation.configuration" and not _is_empty_value(candidate_value)
        ):
            topology_entry = {
                "type": _safe_str(candidate_value),
                "artifact_id": drawing_artifact_id,
                "confidence": "MODERATE" if candidate_value is not None else "LOW",
                "source": "drawing_interpretation",
            }
            if topology_entry["artifact_id"] and topology_entry["type"]:
                topology_cues.append(topology_entry)

        if drawing_artifact_id and drawing_artifact_id not in drawing_topology_artifacts_emitted:
            drawing_artifact = artifacts_by_id.get(drawing_artifact_id)
            drawing_text = text_by_artifact_id.get(drawing_artifact_id, "")
            if isinstance(drawing_artifact, dict) and _safe_str(drawing_text):
                artifact_ontology = ontology_by_artifact_id.get(drawing_artifact_id, {})
                inferred_topology_cues = extract_topology_cues(
                    drawing_artifact,
                    drawing_text,
                    ontology=artifact_ontology,
                )
                for inferred_topology in inferred_topology_cues:
                    topology_type = _safe_str(inferred_topology.get("type"))
                    if not topology_type:
                        continue
                    topology_cues.append(
                        {
                            "type": topology_type,
                            "artifact_id": drawing_artifact_id,
                            "confidence": _safe_str(inferred_topology.get("confidence")) or "LOW",
                            "source": "drawing_interpretation",
                        }
                    )
                drawing_topology_artifacts_emitted.add(drawing_artifact_id)

    orchestrator = ExtractionDomainCoordinator()
    orchestrated_schema_candidates: list[dict[str, Any]] = []

    for artifact in artifacts:
        artifact_id = _safe_str(artifact.get("artifact_id"))
        if not artifact_id:
            continue

        artifact_ontology = ontology_by_artifact_id.get(artifact_id, {})
        artifact_layout_summary = layout_summary_by_artifact.get(artifact_id, {})
        parser_document = parser_documents_by_artifact.get(artifact_id)
        layout_document = layout_documents_by_artifact.get(artifact_id)
        ocr_document = ocr_documents_by_artifact.get(artifact_id)

        region_plan = _build_region_execution_plan(
            artifact=artifact,
            parser_document=parser_document,
            layout_document=layout_document,
            ocr_document=ocr_document,
            ontology=artifact_ontology,
        )

        deduped_fallback_paths = _fallback_field_paths_for_artifact(
            artifact=artifact,
            ontology=artifact_ontology,
        )

        relevance_plan.append(
            _build_relevance_plan_entry(
                artifact=artifact,
                ontology=artifact_ontology,
                parser_document=parser_document,
                layout_document=layout_document,
                ocr_document=ocr_document,
                region_execution_plan=region_plan,
                fallback_field_paths=deduped_fallback_paths,
            )
        )

        if region_plan:
            for region_plan_item in region_plan:
                scoped_artifact = _build_scoped_artifact(
                    artifact=artifact,
                    region_plan_item=region_plan_item,
                    ontology=artifact_ontology,
                )

                orchestrator_results = orchestrator.run_orchestrated_extraction(
                    artifacts=[scoped_artifact],
                    field_paths=region_plan_item.get("field_paths", []),
                    context=context,
                    escalation_policy=drawing_escalation_policy,
                )

                for raw_candidate in orchestrator_results:
                    candidate = _coerce_extraction_candidate(raw_candidate)
                    candidate["artifact_id"] = _safe_str(candidate.get("artifact_id")) or _safe_str(
                        candidate.get("source_artifact_id")
                    )
                    if _is_empty_value(candidate.get("value")):
                        continue

                    evidence = candidate.get("evidence")
                    if isinstance(evidence, dict):
                        evidence.setdefault("page", int(region_plan_item.get("page_number", 1)))
                        evidence.setdefault("region", _safe_str(region_plan_item.get("region_type")))
                        evidence.setdefault("section", _safe_str(region_plan_item.get("region_id")))
                    else:
                        candidate["evidence"] = {
                            "page": int(region_plan_item.get("page_number", 1)),
                            "region": _safe_str(region_plan_item.get("region_type")),
                            "section": _safe_str(region_plan_item.get("region_id")),
                        }

                    schema_candidate = _candidate_to_schema_field_candidate(candidate)
                    if schema_candidate is not None:
                        orchestrated_schema_candidates.append(schema_candidate)

                    entity = _candidate_to_entity(candidate)
                    if entity is not None:
                        entities.append(entity)

                    anchor = _build_anchor_from_candidate(candidate, artifacts_by_id)
                    if anchor is not None:
                        source_anchors.append(anchor)

                    if _is_valid_topology_candidate(candidate):
                        topology_entry = {
                            "type": _safe_str(candidate.get("value")),
                            "artifact_id": _safe_str(candidate.get("artifact_id")) or _safe_str(
                                candidate.get("source_artifact_id")
                            ),
                            "confidence": _normalize_confidence(candidate.get("confidence")),
                            "source": _safe_str(candidate.get("method")) or "extraction_service",
                        }
                        if topology_entry["artifact_id"]:
                            topology_cues.append(topology_entry)
        else:
            merged_text = text_by_artifact_id.get(artifact_id, "")
            enriched_artifact = dict(artifact)
            enriched_artifact["parsed_text"] = merged_text
            enriched_artifact["text"] = merged_text
            enriched_artifact["text_content"] = merged_text
            enriched_artifact["layout_summary"] = artifact_layout_summary
            enriched_artifact["ontology"] = artifact_ontology

            artifact_emitted_candidates = False

            if deduped_fallback_paths:
                orchestrator_results = orchestrator.run_orchestrated_extraction(
                    artifacts=[enriched_artifact],
                    field_paths=deduped_fallback_paths,
                    context=context,
                    escalation_policy=drawing_escalation_policy,
                )

                for raw_candidate in orchestrator_results:
                    candidate = _coerce_extraction_candidate(raw_candidate)
                    candidate["artifact_id"] = _safe_str(candidate.get("artifact_id")) or _safe_str(
                        candidate.get("source_artifact_id")
                    )
                    if _is_empty_value(candidate.get("value")):
                        continue

                        # unreachable; preserved control structure intentionally not altered
                    artifact_emitted_candidates = True

                    schema_candidate = _candidate_to_schema_field_candidate(candidate)
                    if schema_candidate is not None:
                        orchestrated_schema_candidates.append(schema_candidate)

                    entity = _candidate_to_entity(candidate)
                    if entity is not None:
                        entities.append(entity)

                    anchor = _build_anchor_from_candidate(candidate, artifacts_by_id)
                    if anchor is not None:
                        source_anchors.append(anchor)

                    if _is_valid_topology_candidate(candidate):
                        topology_entry = {
                            "type": _safe_str(candidate.get("value")),
                            "artifact_id": _safe_str(candidate.get("artifact_id")) or _safe_str(
                                candidate.get("source_artifact_id")
                            ),
                            "confidence": _normalize_confidence(candidate.get("confidence")),
                            "source": _safe_str(candidate.get("method")) or "extraction_service",
                        }
                        if topology_entry["artifact_id"]:
                            topology_cues.append(topology_entry)

            if not artifact_emitted_candidates:
                anchor_id = f"{artifact_id}_anchor_001"
                fallback_entities, fallback_topology_cues = _extract_minimal_text_fallback_entities(
                    artifact=artifact,
                    anchor_id=anchor_id,
                    text_content=merged_text,
                    ontology=artifact_ontology,
                )
                entities.extend(fallback_entities)
                topology_cues.extend(fallback_topology_cues)

    normalized_orchestrated_schema_candidates = _filter_orchestrated_schema_candidates(
        _deduplicate_orchestrated_schema_candidates(orchestrated_schema_candidates)
    )

    schema_field_candidates = list(legacy_schema_field_candidates)

    seen_keys: set[tuple[str, str, str, str]] = set()
    for candidate in legacy_schema_field_candidates:
        if not isinstance(candidate, dict):
            continue

        artifact_id = _safe_str(candidate.get("artifact_id")) or _safe_str(candidate.get("source_artifact_id"))
        field_path = _safe_str(candidate.get("field_path"))
        method = _safe_str(candidate.get("method")) or "schema_extraction"
        value_key = repr(candidate.get("value"))

        if artifact_id and field_path:
            seen_keys.add((artifact_id, field_path, method, value_key))

    for candidate in normalized_orchestrated_schema_candidates:
        artifact_id = _safe_str(candidate.get("artifact_id"))
        field_path = _safe_str(candidate.get("field_path"))
        method = _safe_str(candidate.get("method")) or "schema_extraction"
        value_key = repr(candidate.get("value"))

        key = (artifact_id, field_path, method, value_key)
        if key in seen_keys:
            continue

        schema_field_candidates.append(candidate)
        seen_keys.add(key)

    deduped_entities = deduplicate_entities(entities)
    deduped_topology_cues = deduplicate_topology_cues(topology_cues)
    deduped_source_anchors = deduplicate_anchors(source_anchors)

    schema_field_candidates = [
        _enrich_schema_candidate_source_metadata(candidate, ontology_by_artifact_id)
        for candidate in schema_field_candidates
        if isinstance(candidate, dict)
    ]

    planner_registry_field_targets, uncovered_planner_registry_fields, planner_registry_summary = build_planner_registry_coverage(
        schema_field_candidates=schema_field_candidates,
    )

    llm_assistance = _run_extraction_review_agent(
        context=context,
        artifacts=artifacts,
        entities=deduped_entities,
        schema_field_candidates=schema_field_candidates,
        topology_cues=deduped_topology_cues,
        ontology=ontology,
        planner_registry_summary=planner_registry_summary,
        uncovered_planner_registry_fields=uncovered_planner_registry_fields,
        relevance_plan=relevance_plan,
        warnings=warnings,
    )
    document_interpretation = _run_document_interpretation_agent(
        context=context,
        artifacts=artifacts,
        schema_field_candidates=schema_field_candidates,
        topology_cues=deduped_topology_cues,
        warnings=warnings,
        uncovered_planner_registry_fields=uncovered_planner_registry_fields,
    )
    if isinstance(llm_assistance, dict):
        llm_assistance["document_interpretation"] = document_interpretation
        llm_assistance["drawing_escalation_summary"] = drawing_escalation_summary
        llm_assistance["drawing_escalation_policy"] = drawing_escalation_policy

    result = ExtractionResult(
        run_id=context.run_id,
        entities=deduped_entities,
        candidate_entities=deduped_entities,
        schema_field_candidates=schema_field_candidates,
        topology_cues=deduped_topology_cues,
        source_anchors=deduped_source_anchors,
        ontology=ontology,
        llm_assistance=llm_assistance,
        warnings=warnings,
        status="EXTRACTED",
        extracted_at=utc_now_iso(),
        planner_registry_summary=planner_registry_summary,
        planner_registry_field_targets=planner_registry_field_targets,
        uncovered_planner_registry_fields=uncovered_planner_registry_fields,
        relevance_plan=relevance_plan,
        document_parser_result=document_parser_result,
        layout_analysis_result=layout_analysis_result,
        ocr_result=ocr_result,
    )

    return result.to_dict()


def extract_entities(
    context: Any,
    ingestion_result: dict[str, Any],
    document_parser_result: dict[str, Any] | None = None,
    layout_analysis_result: dict[str, Any] | None = None,
    ocr_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_service(
        context=context,
        ingestion_result=ingestion_result,
        document_parser_result=document_parser_result,
        layout_analysis_result=layout_analysis_result,
        ocr_result=ocr_result,
    )