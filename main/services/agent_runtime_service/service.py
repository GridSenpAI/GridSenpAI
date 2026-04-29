from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import CONFIG
from services.agent_policy_service.service import evaluate_agent_request_policy
from services.agent_runtime_service.base import BaseBoundedAgent
from services.agent_registry_service.service import (
    DISALLOWED_OVERRIDE_FIELDS,
    build_agent_registry,
    get_agent_definition,
    get_agent_family_id,
    resolve_agent_id,
)
from services.agent_models.models import AgentDecision, AgentPolicyDecision, AgentRequest, AgentResponse
from services.agent_runtime_service.audit import write_agent_audit
from services.llm_runtime_service.models import LLMTaskRequest
from services.llm_runtime_service.service import run_llm_task
from shared.planner_registry import preferred_sources_for_field
from services.agent_runtime_service.chunking import (
    build_advisory_chunks,
    estimate_prompt_chars,
    merge_chunk_outputs,
)




def evaluate_agent_policy(*, agent_id: str, stage_name: str, task_name: str, context: Any) -> AgentPolicyDecision:
    request = AgentRequest(agent_id=agent_id, stage_name=stage_name, task_name=task_name)
    return evaluate_agent_request_policy(context=context, request=request)

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_run_id(context: Any) -> str:
    run_id = getattr(context, "run_id", None)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("context.run_id must be a non-empty string.")
    return run_id.strip()


def _optional_run_dir(context: Any) -> Path | None:
    run_dir = getattr(context, "run_dir", None)
    if run_dir is None:
        return None
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(_json_safe(payload), file, indent=2, ensure_ascii=False, default=str)


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return value[:max_chars]
    return value[: max_chars - 3] + "..."


def _trim_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if isinstance(item, str) and str(item).strip()]


def sanitize_agent_payload(
    payload: dict[str, Any],
    forbidden_fields: set[str] | None = None,
) -> dict[str, Any]:
    safe_payload = dict(payload)
    blocked_fields = set(DISALLOWED_OVERRIDE_FIELDS)
    if forbidden_fields:
        blocked_fields.update(str(item).strip() for item in forbidden_fields if str(item).strip())

    for forbidden_key in blocked_fields:
        safe_payload.pop(forbidden_key, None)

    safe_payload["deterministic_override_allowed"] = False
    return safe_payload


AGENT_INPUT_LIST_CAPS = {
    "output_parameters": 40,
    "assumptions": 25,
    "validation_report": 80,
    "backlog_preview": 25,
    "manual_review_queue": 50,
    "planner_action_queue": 50,
    "evidence": 20,
    "candidates": 20,
}


def _compact_agent_inputs(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 7:
        return "[truncated:max_depth]"
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_key_str = str(child_key)
            if child_key_str in {"raw_text", "full_text", "page_text", "ocr_text", "canonical_state"}:
                compacted[child_key_str] = _truncate_text(str(child_value), 1200)
                continue
            compacted[child_key_str] = _compact_agent_inputs(child_value, key=child_key_str, depth=depth + 1)
        return compacted
    if isinstance(value, list):
        cap = AGENT_INPUT_LIST_CAPS.get(key, 60 if depth >= 3 else len(value))
        retained = [_compact_agent_inputs(item, key=key, depth=depth + 1) for item in value[:cap]]
        if len(value) > cap:
            retained.append({"_truncated": True, "original_count": len(value), "retained_count": cap})
        return retained
    if isinstance(value, str):
        return _truncate_text(value, 1600 if key in {"text", "content", "prompt", "response"} else 4000)
    return value


def _build_prompt_payload(
    request: AgentRequest,
    max_prompt_chars: int,
) -> dict[str, Any]:
    agent_family_id = get_agent_family_id(request.agent_id)
    compact_inputs = _compact_agent_inputs(request.inputs)
    raw_text = json.dumps(_json_safe(compact_inputs), sort_keys=True, ensure_ascii=False, default=str)
    telemetry = _prompt_telemetry_for_request(request, max_prompt_chars)
    return {
        "agent_id": request.agent_id,
        "agent_family_id": agent_family_id,
        "stage_name": request.stage_name,
        "task_name": request.task_name,
        "trigger_reason": request.trigger_reason,
        "associated_field_paths": list(request.associated_field_paths),
        "evidence_anchor_count": len(request.evidence_anchors),
        "suggested_output_fields": list(request.suggested_output_fields),
        "requested_capabilities": list(request.requested_capabilities),
        "input_preview": _truncate_text(raw_text, max_prompt_chars),
        "metadata": _json_safe(request.metadata),
        "prompt_telemetry": telemetry,
    }



def _agent_max_evidence_chars() -> int:
    budgets = getattr(CONFIG, "agent_budgets", None)
    try:
        return int(getattr(budgets, "max_evidence_chars", 1200) or 1200)
    except Exception:
        return 1200


def _chunking_enabled_for_request(request: AgentRequest) -> bool:
    return request.agent_id in {
        "translation_support_agent",
        "planner_support_agent",
        "packet_review_agent",
        "adjudication_support_agent",
        "retrieval_planning_agent",
    } or resolve_agent_id(request.agent_id) in {
        "planner_support_agent",
        "adjudication_support_agent",
        "evidence_resolution_agent",
    }


def _prompt_telemetry_for_request(request: AgentRequest, max_prompt_chars: int) -> dict[str, Any]:
    compact_inputs = _compact_agent_inputs(request.inputs)
    raw_text = json.dumps(_json_safe(compact_inputs), sort_keys=True, ensure_ascii=False, default=str)
    return {
        "total_input_chars_before_compaction": estimate_prompt_chars(request.inputs),
        "total_prompt_chars_after_compaction": len(raw_text),
        "max_prompt_chars": max_prompt_chars,
        "chunking_enabled": _chunking_enabled_for_request(request),
    }

def _coerce_missing_fields(validation_report: dict[str, Any]) -> list[str]:
    missing_fields: list[str] = []
    raw_missing = validation_report.get("missing_fields", [])

    if not isinstance(raw_missing, list):
        return missing_fields

    for item in raw_missing:
        if isinstance(item, str) and item.strip():
            missing_fields.append(item.strip())
            continue

        if isinstance(item, dict):
            field_path = str(item.get("field_path", "")).strip()
            if field_path:
                missing_fields.append(field_path)

    return missing_fields


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"yes", "y", "true", "1", "present", "available"}:
        return True
    if normalized in {"no", "n", "false", "0", "absent", "unavailable"}:
        return False
    return None


def _infer_candidate_answer(field_path: str, raw_answer: str) -> Any:
    normalized_field = field_path.strip().lower()
    normalized_answer = raw_answer.strip()
    if not normalized_answer:
        return None

    bool_candidate = _coerce_bool(normalized_answer)
    if any(token in normalized_field for token in (".present", "_present", "capable", "available", "enabled")):
        return bool_candidate

    if any(token in normalized_field for token in ("count", "quantity", "modules", "units")):
        numeric = _to_float(normalized_answer)
        if numeric is None:
            return None
        return int(numeric)

    if any(token in normalized_field for token in ("_mw", ".mw", "_mva", ".mva", "_kv", ".kv", "_hz", ".hz", "ramp", "duration")):
        return _to_float(normalized_answer)

    if normalized_answer.lower() in {"2n", "n+1", "double_conversion", "eco_mode", "unknown"}:
        return normalized_answer.upper()

    return normalized_answer


def _confidence_bucket(value: float) -> str:
    if value >= 0.85:
        return "HIGH"
    if value >= 0.60:
        return "MODERATE"
    return "LOW"


def _build_extraction_review_output(inputs: dict[str, Any]) -> dict[str, Any]:
    field_path = str(inputs.get("field_path", "")).strip()
    artifacts = inputs.get("artifacts", [])
    candidate_values = inputs.get("candidate_values", [])
    warnings = _trim_string_list(inputs.get("warnings", []))

    normalized_candidates: list[dict[str, Any]] = []
    for index, item in enumerate(candidate_values):
        if not isinstance(item, dict):
            continue
        confidence = _to_float(item.get("confidence")) or 0.0
        normalized_candidates.append(
            {
                "index": index,
                "value": item.get("value"),
                "confidence": confidence,
                "method": str(item.get("method", "")).strip(),
                "source_artifact_id": str(item.get("source_artifact_id", "")).strip(),
            }
        )

    ranked_candidates = sorted(
        normalized_candidates,
        key=lambda item: (item["confidence"], bool(item["value"]), item["index"]),
        reverse=True,
    )

    recommended_candidate: int | None = None
    rationale_parts: list[str] = []
    review_notes = list(warnings)

    if ranked_candidates:
        top_candidate = ranked_candidates[0]
        recommended_candidate = int(top_candidate["index"])
        rationale_parts.append(
            "Recommended the highest-confidence deterministic extraction candidate for downstream validation."
        )
        if len(ranked_candidates) > 1:
            review_notes.append("Multiple extraction candidates were produced for the same field path.")
        if top_candidate["confidence"] < 0.60:
            review_notes.append("All available extraction candidates remain low-confidence and should be reviewed.")
    else:
        review_notes.append("No extraction candidates were provided for bounded review.")
        rationale_parts.append("No candidate ranking was possible because no candidates were available.")

    focus_areas: list[str] = []
    lowered_field = field_path.lower()
    if "topology" in lowered_field or "poi" in lowered_field:
        focus_areas.append("diagram_topology")
    if "relay" in lowered_field or "protection" in lowered_field:
        focus_areas.append("protection_settings")
    if "schedule" in lowered_field or "count" in lowered_field:
        focus_areas.append("equipment_schedule")

    candidate_rankings = [
        {
            "candidate_index": item["index"],
            "value": item["value"],
            "confidence": item["confidence"],
            "method": item["method"],
            "source_artifact_id": item["source_artifact_id"],
        }
        for item in ranked_candidates
    ]

    aggregate_confidence = ranked_candidates[0]["confidence"] if ranked_candidates else 0.0

    return {
        "agent_role": "extraction_review",
        "field_path": field_path,
        "review_notes": review_notes,
        "candidate_focus_areas": focus_areas,
        "recommended_candidate": recommended_candidate,
        "candidate_rankings": candidate_rankings,
        "review_flag": bool(review_notes),
        "artifact_count": len(artifacts) if isinstance(artifacts, list) else 0,
        "candidate_count": len(candidate_rankings),
        "rationale": " ".join(rationale_parts).strip(),
        "confidence": _confidence_bucket(aggregate_confidence),
    }


def _build_retrieval_planning_output(inputs: dict[str, Any]) -> dict[str, Any]:
    queries = inputs.get("queries", [])
    snippets = inputs.get("snippets", [])
    warnings = _trim_string_list(inputs.get("warnings", []))
    normalized_input = inputs.get("normalized_input", {})
    validation_report = inputs.get("validation_report", {})
    equipment_reference_resolution = inputs.get("equipment_reference_resolution", {})

    missing_fields = _coerce_missing_fields(validation_report) if isinstance(validation_report, dict) else []
    suggested_query_topics: list[str] = []
    knowledge_family_route: list[str] = []
    suggested_queries: list[dict[str, Any]] = []
    web_lookup_recommendations: list[dict[str, Any]] = []

    for field_path in missing_fields:
        lowered = field_path.lower()
        if "poi_voltage_kv" in lowered:
            suggested_query_topics.append("point of interconnection voltage")
            knowledge_family_route.append("interconnection_guidance")
        elif "phase_1_mw" in lowered:
            suggested_query_topics.append("phase 1 MW buildout schedule")
            knowledge_family_route.append("modeling_references")
        elif "ups" in lowered or "generator" in lowered or "switchgear" in lowered or "transformer" in lowered:
            suggested_query_topics.append(field_path.replace("_", " ").replace(".", " "))
            knowledge_family_route.extend(["equipment_catalog", "vendor_documents"])
        else:
            suggested_query_topics.append(field_path.replace("_", " ").replace(".", " "))
            knowledge_family_route.append("modeling_references")

    if isinstance(equipment_reference_resolution, dict):
        official_candidates = equipment_reference_resolution.get("official_source_candidates", [])
        pdf_lookup_plans = equipment_reference_resolution.get("pdf_lookup_plans", [])
        web_lookup_plans = equipment_reference_resolution.get("web_lookup_plans", [])
        unresolved_missing = equipment_reference_resolution.get("unresolved_missing_fields", [])
        review_required_fields = equipment_reference_resolution.get("review_required_fields", [])

        review_notes = []
        if isinstance(official_candidates, list) and official_candidates:
            knowledge_family_route.extend(["equipment_catalog", "vendor_documents"])
            review_notes.append("Structured equipment library should be used first before any PDF or web lookup.")

        if isinstance(pdf_lookup_plans, list) and pdf_lookup_plans:
            knowledge_family_route.append("vendor_documents")
            review_notes.append("Search the matched vendor PDF repository before attempting any web lookup.")
            if isinstance(unresolved_missing, list) and unresolved_missing:
                warnings.append("Use the vendor PDF repository for unresolved equipment specification fields after the library-first structured pass.")

        if isinstance(web_lookup_plans, list) and web_lookup_plans:
            for plan in web_lookup_plans:
                if not isinstance(plan, dict):
                    continue
                web_lookup_recommendations.append(
                    {
                        "lookup_mode": str(plan.get("lookup_mode", "official_source_only")).strip() or "official_source_only",
                        "allowed_domains": list(plan.get("allowed_domains", [])) if isinstance(plan.get("allowed_domains", []), list) else [],
                        "allowed_urls": list(plan.get("allowed_urls", [])) if isinstance(plan.get("allowed_urls", []), list) else [],
                        "search_terms": list(plan.get("search_terms", [])) if isinstance(plan.get("search_terms", []), list) else [],
                        "missing_fields": list(plan.get("missing_fields", [])) if isinstance(plan.get("missing_fields", []), list) else [],
                    }
                )
            if isinstance(unresolved_missing, list) and unresolved_missing:
                warnings.append("Use official-source-only vendor web lookup for equipment specification fields that remain unresolved after the library and PDF passes.")

        if isinstance(review_required_fields, list) and review_required_fields:
            warnings.append("Low-confidence vendor evidence should be confirmed during the applicant interview before final output.")
    else:
        review_notes = []

    for topic in suggested_query_topics:
        tokens = [token for token in topic.replace(",", " ").split() if token]
        suggested_queries.append(
            {
                "query_text": topic,
                "keywords": tokens,
            }
        )

    source_priority_summary: list[dict[str, Any]] = []
    for field_path in missing_fields:
        preferred_sources = preferred_sources_for_field(field_path)
        if preferred_sources:
            source_priority_summary.append(
                {
                    "field_path": field_path,
                    "preferred_sources": preferred_sources,
                    "planner_critical": "poi" in field_path.lower() or "voltage" in field_path.lower() or "generator" in field_path.lower() or "transformer" in field_path.lower() or "ups" in field_path.lower(),
                }
            )

    review_notes.extend(warnings)
    evidence_gap_flag = False

    if not snippets:
        review_notes.append("No evidence snippets were returned. Retrieval should broaden or shift corpus family.")
        evidence_gap_flag = True
    if warnings:
        evidence_gap_flag = True
    if isinstance(normalized_input, dict) and not normalized_input.get("facility"):
        review_notes.append("Normalized facility payload is sparse; retrieval specificity may be limited.")

    recommended_next_request = (
        "Request additional supporting documentation or engineer clarification for modeling-critical missing fields."
        if evidence_gap_flag or missing_fields
        else "Proceed with current grounded evidence bundle."
    )
    if web_lookup_recommendations:
        recommended_next_request = (
            "Use the structured library first, then the matched vendor PDF repository, then official-source-only vendor web lookup for any unresolved equipment spec fields, and send all candidates through validation before canonical acceptance."
        )

    return {
        "agent_role": "retrieval_planning",
        "review_notes": review_notes,
        "suggested_query_topics": suggested_query_topics,
        "suggested_queries": suggested_queries,
        "knowledge_family_route": sorted(set(knowledge_family_route)),
        "web_lookup_recommendations": web_lookup_recommendations,
        "source_priority_summary": source_priority_summary,
        "query_plan": {
            "missing_fields": missing_fields,
            "suggested_queries": suggested_queries,
            "knowledge_families": sorted(set(knowledge_family_route)),
            "library_first": True,
            "pdf_repository_lookup": bool(isinstance(equipment_reference_resolution, dict) and equipment_reference_resolution.get("pdf_lookup_plans")),
            "official_source_only_web_lookup": bool(web_lookup_recommendations),
        },
        "query_count": len(queries) if isinstance(queries, list) else 0,
        "snippet_count": len(snippets) if isinstance(snippets, list) else 0,
        "missing_field_count": len(missing_fields),
        "evidence_gap_flag": evidence_gap_flag,
        "recommended_next_request": recommended_next_request,
        "rationale": "Improved retrieval suggestions were derived from current missing fields, structured equipment library coverage, vendor PDF repository availability, and official-source-only guardrails for unresolved vendor specifications.",
        "confidence": "MODERATE" if missing_fields or web_lookup_recommendations else "HIGH",
    }


def _build_translation_support_output(inputs: dict[str, Any]) -> dict[str, Any]:
    output_parameters = inputs.get("output_parameters", [])
    assumptions = inputs.get("assumptions", [])

    low_confidence_parameters: list[str] = []
    assumption_backed_parameters: list[str] = []
    missing_dependency_parameters: list[str] = []

    for parameter in output_parameters:
        if not isinstance(parameter, dict):
            continue

        parameter_path = str(parameter.get("parameter_path", "")).strip()
        if not parameter_path:
            continue

        confidence_tag = str(parameter.get("confidence_tag", "")).strip().upper()
        if confidence_tag in {"LOW", "UNRESOLVED"}:
            low_confidence_parameters.append(parameter_path)

        provenance_type = str(parameter.get("provenance_type", "")).strip().lower()
        if provenance_type == "assumption":
            assumption_backed_parameters.append(parameter_path)

        confidence_factors = parameter.get("confidence_factors", {})
        if isinstance(confidence_factors, dict) and confidence_factors.get("missing_dependency"):
            missing_dependency_parameters.append(parameter_path)

    review_notes: list[str] = []
    if low_confidence_parameters:
        review_notes.append("Planner review is recommended for low-confidence parameters.")
    if missing_dependency_parameters:
        review_notes.append("Some parameters remain constrained by missing upstream dependencies.")

    assumption_summary = (
        f"{len(assumptions)} active assumptions inform the current translation output."
        if isinstance(assumptions, list) and assumptions
        else "No active assumptions were recorded for the current translation output."
    )
    missing_info_summary = (
        "Additional evidence is recommended for parameters that remain low-confidence or assumption-backed."
        if low_confidence_parameters or assumption_backed_parameters or missing_dependency_parameters
        else "Current translation inputs provide acceptable coverage for the generated planner-facing notes."
    )

    return {
        "agent_role": "translation_support",
        "review_notes": review_notes,
        "low_confidence_parameters": low_confidence_parameters,
        "assumption_backed_parameters": assumption_backed_parameters,
        "missing_dependency_parameters": missing_dependency_parameters,
        "parameter_explanation": "Deterministic parameter values remain unchanged. This advisory output only adds bounded review context.",
        "planner_note": "Review low-confidence and assumption-backed parameters before external publication.",
        "review_note": "This agent does not modify deterministic parameter values." if review_notes else "No additional bounded review note is required for the current translation output.",
        "assumption_summary": assumption_summary,
        "missing_info_summary": missing_info_summary,
        "confidence_explanation": (
            "Confidence remains constrained by upstream evidence gaps."
            if low_confidence_parameters or missing_dependency_parameters
            else "Confidence is supported by current deterministic translation inputs."
        ),
        "rationale": "Translation support output was derived from deterministic translation metadata and confidence tags.",
        "confidence": "MODERATE" if review_notes else "HIGH",
    }



def _build_document_interpretation_output(inputs: dict[str, Any]) -> dict[str, Any]:
    raw_text = str(inputs.get("raw_text", "")).strip()
    field_path = str(inputs.get("field_path", "")).strip()
    region_id = str(inputs.get("region_id", "")).strip()
    source_anchor = inputs.get("source_anchor")
    artifact_kind = str(inputs.get("artifact_kind", "engineering_document")).strip() or "engineering_document"

    candidate_interpretations: list[dict[str, Any]] = []
    review_notes: list[str] = []

    if raw_text:
        numeric = _to_float(raw_text)
        if numeric is not None:
            candidate_interpretations.append(
                {
                    "kind": "numeric_value",
                    "value": numeric,
                    "reason": "A numeric token was detected in the provided document fragment.",
                }
            )
        candidate_interpretations.append(
            {
                "kind": "text_fragment",
                "value": raw_text,
                "reason": "The literal fragment may contain equipment labels, ratings, or topology cues.",
            }
        )
    else:
        review_notes.append("No document fragment text was supplied for bounded interpretation.")

    if field_path:
        review_notes.append(f"Interpretation remains advisory for '{field_path}' until deterministic extraction and validation confirm it.")
    if artifact_kind:
        review_notes.append(f"Source artifact kind: {artifact_kind}.")

    confidence = "MODERATE" if raw_text else "LOW"
    return {
        "agent_role": "document_interpretation",
        "candidate_text": raw_text,
        "candidate_label": field_path,
        "candidate_value": raw_text,
        "candidate_interpretations": candidate_interpretations,
        "source_anchor": source_anchor,
        "interpretation_notes": review_notes,
        "review_notes": review_notes,
        "region_id": region_id,
        "rationale": "The agent summarizes plausible interpretations from ambiguous document evidence without accepting them into canonical state.",
        "confidence": confidence,
    }


def _build_evidence_resolution_output(inputs: dict[str, Any]) -> dict[str, Any]:
    validation_report = inputs.get("validation_report", {}) if isinstance(inputs.get("validation_report"), dict) else {}
    equipment_reference_resolution = inputs.get("equipment_reference_resolution", {}) if isinstance(inputs.get("equipment_reference_resolution"), dict) else {}
    missing_fields = _coerce_missing_fields(validation_report)
    unresolved = [
        str(item).strip()
        for item in equipment_reference_resolution.get("unresolved_missing_fields", [])
        if isinstance(item, str) and str(item).strip()
    ]
    review_required = [
        str(item).strip()
        for item in equipment_reference_resolution.get("review_required_fields", [])
        if isinstance(item, str) and str(item).strip()
    ]
    prioritized_targets = [value for value in missing_fields if value]
    if prioritized_targets:
        all_targets = []
        for value in prioritized_targets:
            if value not in all_targets:
                all_targets.append(value)
    else:
        all_targets = []
        for value in [*unresolved, *review_required]:
            if value not in all_targets:
                all_targets.append(value)

    source_priority_summary = []
    if all_targets:
        source_priority_summary.append("Search the structured knowledge library first for planner-field-aligned evidence.")
    if unresolved:
        source_priority_summary.append("Use matched vendor PDFs for unresolved model-specific equipment fields before web lookup.")
    if equipment_reference_resolution.get("web_lookup_required"):
        source_priority_summary.append("Use official-source-only web lookup for residual unresolved equipment specifications.")

    suggested_queries = []
    for field_path in all_targets[:8]:
        topic = field_path.split(".")[-1].replace("_", " ")
        suggested_queries.append({
            "query_text": f"{field_path} engineering specification",
            "keywords": [token for token in topic.split() if token],
            "target_field": field_path,
        })

    findings = []
    for field_path in all_targets[:8]:
        route = "knowledge_library"
        if field_path in unresolved:
            route = "vendor_pdf_repository"
        if equipment_reference_resolution.get("web_lookup_required") and field_path in unresolved:
            route = "official_source_web"
        findings.append({
            "field_path": field_path,
            "preferred_route": route,
            "needs_confirmation": field_path in review_required,
        })

    review_notes = []
    if not all_targets:
        review_notes.append("No active evidence gaps were supplied to the evidence-resolution agent.")
    else:
        review_notes.append("Evidence routing remains advisory; retrieved candidates still require deterministic validation and field resolution.")

    return {
        "agent_role": "evidence_resolution",
        "evidence_findings": findings,
        "source_priority_summary": source_priority_summary,
        "suggested_queries": suggested_queries,
        "knowledge_family_route": ["equipment_catalog", "vendor_documents", "modeling_references"] if all_targets else ["modeling_references"],
        "web_lookup_recommendations": list(equipment_reference_resolution.get("web_lookup_plans", [])) if isinstance(equipment_reference_resolution.get("web_lookup_plans", []), list) else [],
        "evidence_gap_flag": bool(all_targets),
        "recommended_next_request": (
            "Resolve outstanding evidence gaps through the library-first route, then vendor PDFs, then official-source-only web lookup."
            if all_targets
            else "Proceed with the current evidence bundle."
        ),
        "review_notes": review_notes,
        "rationale": "The agent synthesizes missing and weak evidence paths into a bounded retrieval strategy without accepting any candidate value as truth.",
        "confidence": "MODERATE" if all_targets else "HIGH",
    }


def _build_adjudication_support_output(inputs: dict[str, Any]) -> dict[str, Any]:
    summary = inputs.get("field_resolution_summary", {}) if isinstance(inputs.get("field_resolution_summary"), dict) else {}
    backlog = [item for item in inputs.get("backlog", []) if isinstance(item, dict)] if isinstance(inputs.get("backlog"), list) else []
    planner_review_queue = [item for item in inputs.get("planner_review_queue", []) if isinstance(item, dict)] if isinstance(inputs.get("planner_review_queue"), list) else []
    high_conflicts = [item for item in inputs.get("high_materiality_conflicts", []) if isinstance(item, dict)] if isinstance(inputs.get("high_materiality_conflicts"), list) else []
    adjudication_targets = [item for item in inputs.get("adjudication_targets", []) if isinstance(item, dict)] if isinstance(inputs.get("adjudication_targets"), list) else []

    def _field_brief(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "field_id": str(item.get("field_id", "")).strip(),
            "field_path": str(item.get("field_path", "")).strip(),
            "label": str(item.get("label", "")).strip(),
            "status": str(item.get("accepted_status", item.get("status", ""))).strip(),
            "unresolved_reason": str(item.get("unresolved_reason", "")).strip(),
            "planner_attention_tier": str(item.get("planner_attention_tier", "")).strip(),
            "confidence_band": str(item.get("confidence_band", "")).strip(),
        }

    def _value_text(value: Any) -> str:
        if isinstance(value, float):
            return str(int(value)) if value.is_integer() else str(round(value, 6)).rstrip('0').rstrip('.')
        if isinstance(value, (list, dict)):
            return json.dumps(value, sort_keys=True)
        return str(value)

    priority_conflicts = [_field_brief(item) for item in high_conflicts[:8]]
    priority_applicant_confirmations = [_field_brief(item) for item in backlog if bool(item.get("needs_applicant_confirmation", False))][:10]
    priority_planner_review_fields = [_field_brief(item) for item in planner_review_queue[:10]]

    hierarchy_rank = {
        "applicant_direct_document": 100,
        "applicant_inferred_document": 90,
        "applicant_confirmed_answer": 80,
        "manufacturer_model_specific_spec": 70,
        "manufacturer_family_spec": 60,
        "official_interconnection_source": 50,
        "vendor_pdf": 40,
        "official_website": 30,
        "secondary_web": 20,
        "llm_uncited": 10,
    }
    specificity_rank = {
        "exact_instance_match": 100,
        "exact_model_match": 90,
        "direct_field_match": 80,
        "family_match": 60,
        "category_match": 40,
        "context_inferred": 20,
    }

    def _quality_text(value: str) -> str:
        return value.replace("_", " ").strip() if value else "unspecified evidence quality"

    def _compare_quality(winner_value: str, runner_value: str, mapping: dict[str, int], higher_label: str, equal_label: str) -> str:
        winner_rank = mapping.get(winner_value, 0)
        runner_rank = mapping.get(runner_value, 0)
        if winner_rank > runner_rank:
            return f"Accepted candidate had {higher_label} ({_quality_text(winner_value)}) than the runner-up ({_quality_text(runner_value or 'unspecified')})."
        if winner_rank == runner_rank and winner_rank > 0:
            return f"Accepted candidate and runner-up carried comparable {equal_label} ({_quality_text(winner_value)}); deterministic scoring and corroboration broke the tie."
        return f"Accepted candidate path retained the strongest available {equal_label} in the current evidence set."

    per_field_adjudication: list[dict[str, Any]] = []
    stronger_candidate_reasoning: list[str] = []
    hidden_conflict_flags: list[str] = []
    review_notes = []
    ask_applicant_recommendation = False
    downgrade_recommendation = False

    for item in adjudication_targets[:10]:
        field_id = str(item.get("field_id", "")).strip()
        field_path = str(item.get("field_path", "")).strip()
        label = str(item.get("label", "")).strip() or field_id or field_path or "Unknown Field"
        accepted_value = _value_text(item.get("accepted_value"))
        accepted_source = str(item.get("accepted_source_hierarchy", "")).strip() or "unspecified source hierarchy"
        alternatives = [alt for alt in item.get("alternatives", []) if isinstance(alt, dict)] if isinstance(item.get("alternatives"), list) else []
        top_alt = alternatives[0] if alternatives else {}
        top_alt_value = _value_text(top_alt.get("value")) if top_alt else ""
        top_alt_anchor = str(top_alt.get("source_anchor", "")).strip()
        winner_hierarchy = str(item.get("accepted_source_hierarchy", "")).strip()
        winner_specificity = str(item.get("accepted_specificity", "")).strip()
        runner_hierarchy = str(top_alt.get("source_hierarchy", "")).strip() if top_alt else ""
        runner_specificity = str(top_alt.get("specificity", "")).strip() if top_alt else ""
        contradiction = str(item.get("contradiction_summary", "")).strip()
        unresolved_reason = str(item.get("unresolved_reason", "")).strip()
        route_record = item.get("evidence_route_record", {}) if isinstance(item.get("evidence_route_record"), dict) else {}
        route_status = str(item.get("evidence_route_status", "")).strip() or str(route_record.get("route_status", "")).strip()
        route_query_sources = [str(v).strip() for v in item.get("evidence_route_query_sources", []) if str(v).strip()] if isinstance(item.get("evidence_route_query_sources"), list) else []
        route_preferred_corpora = [str(v).strip() for v in item.get("evidence_route_preferred_corpora", []) if str(v).strip()] if isinstance(item.get("evidence_route_preferred_corpora"), list) else []
        if not winner_hierarchy:
            winner_hierarchy = str(route_record.get("best_source_hierarchy", "")).strip()
        if not winner_specificity:
            winner_specificity = str(route_record.get("best_specificity", "")).strip()
        confidence_band = str(item.get("confidence_band", "")).strip() or "LOW"
        status = str(item.get("accepted_status", "")).strip() or "unresolved"
        needs_confirmation = bool(item.get("needs_applicant_confirmation", False))
        materiality = str(item.get("conflict_materiality", "")).strip().lower()
        acceptance_margin = item.get("acceptance_margin")
        decision_basis = str(item.get("decision_basis", "")).strip()
        why_bits = [str(bit).strip() for bit in item.get("why_accepted", []) if str(bit).strip()] if isinstance(item.get("why_accepted"), list) else []

        reason = f"{label} accepted {accepted_value} because {accepted_source} ranked strongest"
        if route_status:
            reason += f" after a {route_status.replace('_', ' ')} retrieval route"
        if why_bits:
            reason += f"; deterministic rationale: {' '.join(why_bits[:2])}"
        if top_alt_value:
            reason += f". Runner-up {top_alt_value} remained plausible"
            if top_alt_anchor:
                reason += f" from {top_alt_anchor}"
        reason += "."
        stronger_candidate_reasoning.append(reason)

        runner_up_summary = ""
        if top_alt_value:
            runner_up_summary = f"Runner-up candidate {top_alt_value} was retained for planner visibility"
            if top_alt_anchor:
                runner_up_summary += f" ({top_alt_anchor})"
            runner_up_summary += "."

        source_quality_comparison = _compare_quality(
            winner_hierarchy,
            runner_hierarchy,
            hierarchy_rank,
            "a stronger source-quality tier",
            "source-quality tier",
        )
        specificity_comparison = _compare_quality(
            winner_specificity,
            runner_specificity,
            specificity_rank,
            "a stronger specificity tier",
            "specificity tier",
        )
        evidence_route_rationale = (
            f"Accepted search path relied on {_quality_text(winner_hierarchy)} evidence with {_quality_text(winner_specificity)} support"
            if winner_hierarchy or winner_specificity
            else "Accepted search path relied on the strongest available evidence route in the current bundle"
        )
        if route_query_sources:
            evidence_route_rationale += f" via {', '.join(route_query_sources[:3])}"
        if route_preferred_corpora:
            evidence_route_rationale += f" across preferred corpora {', '.join(route_preferred_corpora[:3])}"
        if top_alt_value:
            evidence_route_rationale += f" instead of the runner-up route behind {top_alt_value}"
        evidence_route_rationale += "."
        why_search_path_was_trusted = " ".join(
            bit for bit in [evidence_route_rationale, source_quality_comparison, specificity_comparison] if bit
        ).strip()

        field_flags: list[str] = []
        if contradiction:
            field_flags.append(contradiction)
        if materiality == "high":
            field_flags.append("High-materiality conflict remains visible.")
        if status in {"conflicting", "review_required"} and confidence_band in {"LOW", "MODERATE"}:
            field_flags.append("Bounded adjudication recommends preserving manual review visibility.")
        if field_flags:
            hidden_conflict_flags.extend(f"{label}: {flag}" for flag in field_flags)

        ask_field = needs_confirmation or status == "conflicting" or bool(contradiction)
        downgrade_field = status == "review_required" or (materiality == "high") or (acceptance_margin is not None and float(acceptance_margin or 0.0) < 20.0)
        ask_applicant_recommendation = ask_applicant_recommendation or ask_field
        downgrade_recommendation = downgrade_recommendation or downgrade_field

        per_field_adjudication.append({
            "field_id": field_id,
            "field_path": field_path,
            "label": label,
            "stronger_candidate_reasoning": reason,
            "runner_up_summary": runner_up_summary,
            "hidden_conflict_flags": field_flags,
            "ask_applicant_recommendation": ask_field,
            "downgrade_recommendation": downgrade_field,
            "evidence_route_rationale": evidence_route_rationale,
            "source_quality_comparison": source_quality_comparison,
            "specificity_comparison": specificity_comparison,
            "why_search_path_was_trusted": why_search_path_was_trusted,
            "decision_basis": decision_basis,
            "confidence_band": confidence_band,
            "evidence_route_status": route_status,
            "accepted_status": status,
            "recommended_interview_target": field_path if ask_field and field_path else "",
        })

    if priority_conflicts:
        review_notes.append("High-materiality conflicts remain and should not be silently collapsed in planner output.")
    if priority_applicant_confirmations:
        review_notes.append("Target applicant follow-up should focus on high-impact unresolved or conflicting fields only.")
    if per_field_adjudication:
        review_notes.append("Per-field adjudication notes were generated to explain why the best-supported candidate won and why the runner-up lost.")
    if not review_notes:
        review_notes.append("No high-priority adjudication escalation was identified from the supplied field-resolution snapshot.")

    resolved_count = int(summary.get("resolved_count", 0) or 0)
    review_count = int(summary.get("planner_review_count", 0) or 0)
    conflicting_count = int(summary.get("conflicting_count", 0) or 0)
    missing_count = int(summary.get("missing_count", 0) or 0)
    adjudication_summary = (
        f"Resolved fields: {resolved_count}; planner review: {review_count}; conflicts: {conflicting_count}; missing: {missing_count}."
    )

    recommended_targets = [item.get("field_path", "") for item in priority_applicant_confirmations if item.get("field_path")]
    recommended_targets.extend(
        item.get("recommended_interview_target", "")
        for item in per_field_adjudication
        if item.get("recommended_interview_target")
    )
    recommended_targets = list(dict.fromkeys(target for target in recommended_targets if target))

    return {
        "agent_role": "adjudication_support",
        "adjudication_summary": adjudication_summary,
        "priority_conflicts": priority_conflicts,
        "priority_applicant_confirmations": priority_applicant_confirmations,
        "priority_planner_review_fields": priority_planner_review_fields,
        "recommended_interview_targets": recommended_targets,
        "per_field_adjudication": per_field_adjudication,
        "stronger_candidate_reasoning": stronger_candidate_reasoning,
        "hidden_conflict_flags": hidden_conflict_flags,
        "ask_applicant_recommendation": ask_applicant_recommendation,
        "downgrade_recommendation": downgrade_recommendation,
        "runner_up_summary": per_field_adjudication[0].get("runner_up_summary", "") if per_field_adjudication else "",
        "review_notes": review_notes,
        "rationale": "The agent reviews deterministic resolution output to highlight where uncertainty remains materially important for interview or planner review.",
        "confidence": "MODERATE" if (priority_conflicts or priority_applicant_confirmations or priority_planner_review_fields or per_field_adjudication) else "HIGH",
    }


def _build_packet_review_output(inputs: dict[str, Any]) -> dict[str, Any]:
    summary = inputs.get("field_resolution_summary", {}) if isinstance(inputs.get("field_resolution_summary"), dict) else {}
    translation_support = inputs.get("translation_support", {}) if isinstance(inputs.get("translation_support"), dict) else {}
    translation_governance_alerts = inputs.get("translation_governance_alerts", {}) if isinstance(inputs.get("translation_governance_alerts"), dict) else {}
    scenario_governance_alerts = inputs.get("scenario_governance_alerts", {}) if isinstance(inputs.get("scenario_governance_alerts"), dict) else {}
    downstream_review_gating = inputs.get("downstream_review_gating", {}) if isinstance(inputs.get("downstream_review_gating"), dict) else {}
    planner_action_queue_summary = inputs.get("planner_action_queue_summary", {}) if isinstance(inputs.get("planner_action_queue_summary"), dict) else {}
    planner_packet_excerpt = str(inputs.get("planner_packet_excerpt", "")).strip()

    warnings = []
    if int(summary.get("planner_review_count", 0) or 0) > 0:
        warnings.append("Planner packet includes fields that still require planner review.")
    if int(summary.get("high_materiality_conflict_count", 0) or 0) > 0:
        warnings.append("High-materiality conflicts remain visible and should be reviewed before study assumptions are finalized.")
    translation_notes = translation_support.get("review_notes", [])
    if isinstance(translation_notes, list) and translation_notes:
        warnings.append("Translation support identified additional planner-facing review context.")
    if planner_packet_excerpt and len(planner_packet_excerpt) < 120:
        warnings.append("Planner packet excerpt was short; export review is based on limited visible packet text.")
    if bool(translation_governance_alerts.get("has_governance_attention", False)) or bool(downstream_review_gating.get("translation_has_governance_attention", False)):
        warnings.append("Translation outputs were governance-gated and should remain review-tagged until upstream issues are resolved.")
    if int(downstream_review_gating.get("scenario_needs_review_variant_count", 0) or 0) > 0 or bool(scenario_governance_alerts.get("has_governance_attention", False)):
        warnings.append("Scenario confidence was reduced by unresolved governance issues affecting downstream planner outputs.")

    reviewer_focus = []
    if int(summary.get("applicant_confirmation_needed_count", 0) or 0) > 0:
        reviewer_focus.append("Applicant confirmations still needed for some planner-critical fields.")
    if int(summary.get("missing_count", 0) or 0) > 0:
        reviewer_focus.append("Missing fields should remain visible in the open-items and backlog sections.")
    if int(summary.get("conflicting_count", 0) or 0) > 0:
        reviewer_focus.append("Check conflict alternatives and runner-up evidence before external use.")
    if int(downstream_review_gating.get("translation_high_priority_manual_review_count", 0) or 0) > 0:
        reviewer_focus.append("Review governance-driven confidence reductions in translated parameters before treating downstream values as settled.")
    if int(downstream_review_gating.get("scenario_needs_review_variant_count", 0) or 0) > 0:
        reviewer_focus.append("Treat low-confidence scenario variants as provisional until their driving manual-review items are resolved.")

    packet_readiness = "READY_WITH_WARNINGS" if warnings else "READY"
    trust_summary = (
        "The planner packet preserves accepted values, unresolved items, governance-gated downstream outputs, and review-required uncertainty instead of presenting flat certainty."
    )
    downstream_confidence_impact_summary = (
        "Downstream translation and scenario confidence was reduced by shared review-priority governance."
        if bool(translation_governance_alerts.get("has_governance_attention", False)) or int(downstream_review_gating.get("scenario_needs_review_variant_count", 0) or 0) > 0
        else "No downstream governance-driven confidence reduction was detected in translation or scenario generation."
    )

    return {
        "agent_role": "packet_review",
        "packet_review_notes": warnings,
        "trust_summary": trust_summary,
        "planner_warnings": warnings,
        "reviewer_focus": reviewer_focus,
        "packet_readiness": packet_readiness,
        "downstream_confidence_impact_summary": downstream_confidence_impact_summary,
        "planner_action_queue_summary": dict(planner_action_queue_summary),
        "review_notes": warnings,
        "rationale": "The packet-review agent adds a bounded trust-summary layer over deterministic export content without altering export values.",
        "confidence": "MODERATE" if warnings else "HIGH",
    }

def _build_intake_clarification_output(inputs: dict[str, Any], task_name: str = "question_explanation") -> dict[str, Any]:
    raw_answer = inputs.get("raw_answer")
    field_path = str(inputs.get("field_path", "")).strip()
    question_text = str(inputs.get("question_text", "")).strip()
    reason = str(inputs.get("reason", "")).strip()
    allowed_values = _trim_string_list(inputs.get("allowed_values", []))

    if task_name == "interview_oversight":
        question_records = inputs.get("question_records", [])
        if not isinstance(question_records, list):
            question_records = []
        recommended_missing_fields = [
            str(value).strip()
            for value in inputs.get("recommended_missing_fields", [])
            if isinstance(value, str) and str(value).strip()
        ]
        recommended_confirmations = [
            str(value).strip()
            for value in inputs.get("recommended_confirmations", [])
            if isinstance(value, str) and str(value).strip()
        ]
        question_sequence = [
            str(item.get("question_id", "")).strip()
            for item in question_records
            if isinstance(item, dict) and str(item.get("question_id", "")).strip()
        ]
        return {
            "agent_role": "intake_clarification",
            "review_notes": ["Interview oversight remains advisory and cannot persist canonical truth."],
            "recommended_missing_fields": recommended_missing_fields,
            "recommended_confirmations": recommended_confirmations,
            "question_sequence": question_sequence,
            "sufficiency_assessment": "SUFFICIENT" if not recommended_missing_fields else "NEEDS_INTERVIEW",
            "interview_readiness": "READY" if question_records else "NO_OPEN_QUESTIONS",
            "should_finalize_interview": not question_records,
            "rationale": "The interview should focus on unresolved gaps and low-confidence confirmations before final validation and export.",
            "confidence": "MODERATE" if question_records else "HIGH",
        }

    if task_name in {"missing_field_selection", "confirmation_planning", "sufficiency_review"}:
        question_records = inputs.get("question_records", [])
        if not isinstance(question_records, list):
            question_records = []
        candidate_field_paths = [
            str(item.get("field_path", "")).strip()
            for item in question_records
            if isinstance(item, dict) and str(item.get("field_path", "")).strip()
        ]
        return {
            "agent_role": "intake_clarification",
            "review_notes": ["Question planning remains advisory and does not satisfy validation by itself."],
            "recommended_missing_fields": candidate_field_paths,
            "recommended_confirmations": candidate_field_paths,
            "question_sequence": [
                str(item.get("question_id", "")).strip()
                for item in question_records
                if isinstance(item, dict) and str(item.get("question_id", "")).strip()
            ],
            "sufficiency_assessment": "SUFFICIENT" if not candidate_field_paths else "NEEDS_INTERVIEW",
            "interview_readiness": "READY" if candidate_field_paths else "NO_OPEN_QUESTIONS",
            "should_finalize_interview": not candidate_field_paths,
            "rationale": "Suggested interview ordering is based on unresolved field paths only.",
            "confidence": "MODERATE",
        }

    review_notes: list[str] = []
    clarification_prompt = ""
    candidate_structured_answer = None
    confidence = "LOW"
    needs_human_reask = True

    if raw_answer is None or (isinstance(raw_answer, str) and not raw_answer.strip()):
        review_notes.append("The supplied answer is blank or missing.")
        if question_text:
            clarification_prompt = (
                f"Please clarify your answer for '{field_path}' using a concrete engineering value."
                if field_path
                else "Please clarify your answer using a concrete engineering value."
            )
        else:
            clarification_prompt = (
                f"Please provide a direct answer for '{field_path}'." if field_path else "Please provide a direct answer."
            )
    else:
        raw_answer_text = str(raw_answer).strip()
        candidate_structured_answer = _infer_candidate_answer(field_path, raw_answer_text)
        if candidate_structured_answer is None:
            review_notes.append("The supplied answer may need clarification before deterministic validation.")
            clarification_prompt = (
                f"Please clarify your answer for '{field_path}' using a concrete engineering value."
                if field_path
                else "Please clarify your answer using a concrete engineering value."
            )
            if allowed_values:
                clarification_prompt += f" Allowed values include: {', '.join(allowed_values)}."
        else:
            review_notes.append("A bounded candidate answer was inferred and must be validated before acceptance.")
            clarification_prompt = (
                f"Please confirm the interpreted answer for '{field_path}'."
                if field_path
                else "Please confirm the interpreted answer."
            )
            confidence = "MODERATE"
            needs_human_reask = False

    explained_question = question_text or (
        f"Please provide the value required for '{field_path}'." if field_path else "Please provide the required value."
    )
    clarified_question_text = explained_question

    if reason:
        review_notes.append(reason)

    if allowed_values and field_path and not raw_answer:
        clarification_prompt = (
            f"Please answer '{field_path}' using one of these allowed values: {', '.join(allowed_values)}."
        )

    return {
        "agent_role": "intake_clarification",
        "review_notes": review_notes,
        "field_path": field_path,
        "clarified_question_text": clarified_question_text,
        "explained_question": explained_question,
        "clarification_prompt": clarification_prompt,
        "candidate_structured_answer": candidate_structured_answer,
        "needs_human_reask": needs_human_reask,
        "suggested_next_field_path": field_path,
        "rationale": "The response stays advisory and must still pass schema validation, dependency checks, and canonical acceptance.",
        "confidence": confidence,
    }


def _build_ocr_ambiguity_output(inputs: dict[str, Any]) -> dict[str, Any]:
    region_id = str(inputs.get("region_id", "")).strip()
    page_number = inputs.get("page_number")
    raw_text = str(inputs.get("raw_text", "")).strip()
    source_anchor = inputs.get("source_anchor")

    review_notes: list[str] = []
    if not raw_text:
        review_notes.append("OCR region text is empty or unreadable.")
    else:
        review_notes.append("OCR region appears ambiguous and should be reviewed before deterministic acceptance.")

    return {
        "agent_role": "ocr_ambiguity",
        "review_notes": review_notes,
        "region_id": region_id,
        "page_number": page_number,
        "candidate_text": raw_text,
        "candidate_label": "",
        "candidate_value": "",
        "source_anchor": source_anchor,
        "rationale": "The OCR interpretation remains advisory and must flow back through extraction and validation.",
        "confidence": "LOW" if not raw_text else "MODERATE",
    }


class ExtractionReviewAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        return _build_extraction_review_output(request.inputs)


class RetrievalPlanningAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        return _build_retrieval_planning_output(request.inputs)


class TranslationSupportAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        return _build_translation_support_output(request.inputs)


class DocumentInterpretationAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        return _build_document_interpretation_output(request.inputs)


class EvidenceResolutionAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        return _build_evidence_resolution_output(request.inputs)


class AdjudicationSupportAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        return _build_adjudication_support_output(request.inputs)


class PacketReviewAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        return _build_packet_review_output(request.inputs)


class IntakeClarificationAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        return _build_intake_clarification_output(request.inputs, request.task_name)


class OcrAmbiguityAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        return _build_ocr_ambiguity_output(request.inputs)


_AGENT_IMPLEMENTATIONS: dict[str, BaseBoundedAgent] = {
    "document_interpretation_agent": DocumentInterpretationAgent(get_agent_definition("document_interpretation_agent")),
    "evidence_resolution_agent": EvidenceResolutionAgent(get_agent_definition("evidence_resolution_agent")),
    "adjudication_support_agent": AdjudicationSupportAgent(get_agent_definition("adjudication_support_agent")),
    "applicant_interview_agent": IntakeClarificationAgent(get_agent_definition("applicant_interview_agent")),
    "planner_support_agent": PacketReviewAgent(get_agent_definition("planner_support_agent")),
}


class PlannerSupportAgent(BaseBoundedAgent):
    def propose(self, request: AgentRequest) -> dict[str, Any]:
        if request.task_name == "planner_packet_review":
            return _build_packet_review_output(request.inputs)
        return _build_translation_support_output(request.inputs)


_AGENT_IMPLEMENTATIONS["planner_support_agent"] = PlannerSupportAgent(get_agent_definition("planner_support_agent"))


def _normalized_request(request: AgentRequest) -> AgentRequest:
    family_agent_id = resolve_agent_id(request.agent_id)
    if family_agent_id == request.agent_id:
        return request
    return AgentRequest(
        agent_id=family_agent_id,
        stage_name=request.stage_name,
        task_name=request.task_name,
        inputs=dict(request.inputs),
        metadata=dict(request.metadata),
        trigger_reason=request.trigger_reason,
        associated_field_paths=list(request.associated_field_paths),
        evidence_anchors=list(request.evidence_anchors),
        suggested_output_fields=list(request.suggested_output_fields),
        requested_capabilities=list(request.requested_capabilities),
    )


def _bounded_provider(request: AgentRequest) -> dict[str, Any]:
    if request.agent_id == "ocr_ambiguity_agent":
        return _build_ocr_ambiguity_output(request.inputs)
    if request.agent_id == "extraction_review_agent":
        return _build_extraction_review_output(request.inputs)
    if request.agent_id == "retrieval_planning_agent":
        return _build_retrieval_planning_output(request.inputs)
    if request.agent_id == "translation_support_agent":
        return _build_translation_support_output(request.inputs)
    if request.agent_id == "packet_review_agent":
        return _build_packet_review_output(request.inputs)
    if request.agent_id == "intake_clarification_agent":
        return _build_intake_clarification_output(request.inputs, request.task_name)

    family_agent_id = resolve_agent_id(request.agent_id)
    implementation = _AGENT_IMPLEMENTATIONS.get(family_agent_id)
    if implementation is not None:
        return implementation.propose(_normalized_request(request))
    return {
        "agent_role": "unknown",
        "review_notes": [f"No bounded provider is defined for agent '{request.agent_id}'."],
        "rationale": "No provider was available for the requested agent.",
        "confidence": "LOW",
    }


def _should_use_runtime() -> bool:
    model_config = getattr(CONFIG, "model", None)
    if model_config is not None and not bool(getattr(model_config, "allow_model_assistance", False)):
        return False

    llm_runtime = getattr(CONFIG, "llm_runtime", None)
    if llm_runtime is None:
        return False

    enabled = bool(getattr(llm_runtime, "enabled", False))
    model_path = str(getattr(llm_runtime, "model_path", "") or "").strip()
    return enabled and bool(model_path)


def _build_runtime_schema(agent_id: str) -> dict[str, Any]:
    agent_family_id = resolve_agent_id(agent_id)

    common_properties = {
        "review_notes": {"type": "array"},
        "rationale": {"type": "string"},
        "confidence": {"type": "string"},
    }

    document_interpretation_properties = {
        **common_properties,
        "candidate_text": {"type": "string"},
        "candidate_label": {"type": "string"},
        "candidate_value": {},
        "candidate_interpretations": {"type": "array"},
        "source_anchor": {},
        "interpretation_notes": {"type": "array"},
        "candidate_focus_areas": {"type": "array"},
        "recommended_candidate": {"type": ["number", "null"]},
        "candidate_rankings": {"type": "array"},
        "review_flag": {"type": "boolean"},
        "region_id": {"type": "string"},
        "page_number": {"type": "number"},
    }

    evidence_resolution_properties = {
        **common_properties,
        "query_plan": {"type": "object"},
        "suggested_queries": {"type": "array"},
        "suggested_query_topics": {"type": "array"},
        "knowledge_family_route": {"type": "array"},
        "lookup_constraints": {"type": "object"},
        "web_lookup_recommendations": {"type": "array"},
        "web_lookup_required": {"type": "boolean"},
        "evidence_gap_flag": {"type": "boolean"},
        "recommended_next_request": {"type": "string"},
        "stop_reason": {"type": "string"},
        "evidence_findings": {"type": "array"},
        "source_priority_summary": {"type": "array"},
    }

    applicant_interview_properties = {
        **common_properties,
        "field_path": {"type": "string"},
        "clarified_question_text": {"type": "string"},
        "explained_question": {"type": "string"},
        "clarification_prompt": {"type": "string"},
        "candidate_structured_answer": {},
        "needs_human_reask": {"type": "boolean"},
        "suggested_next_field_path": {"type": "string"},
        "recommended_missing_fields": {"type": "array"},
        "recommended_confirmations": {"type": "array"},
        "question_sequence": {"type": "array"},
        "sufficiency_assessment": {"type": "string"},
        "interview_readiness": {"type": "string"},
        "should_finalize_interview": {"type": "boolean"},
    }

    planner_support_properties = {
        **common_properties,
        "low_confidence_parameters": {"type": "array"},
        "assumption_backed_parameters": {"type": "array"},
        "missing_dependency_parameters": {"type": "array"},
        "parameter_explanation": {"type": "string"},
        "planner_note": {"type": "string"},
        "review_note": {"type": "string"},
        "assumption_summary": {"type": "string"},
        "missing_info_summary": {"type": "string"},
        "confidence_explanation": {"type": "string"},
        "packet_review_notes": {"type": "array"},
        "trust_summary": {"type": "string"},
        "planner_warnings": {"type": "array"},
        "reviewer_focus": {"type": "array"},
        "packet_readiness": {"type": "string"},
    }

    if agent_family_id == "document_interpretation_agent":
        return {"type": "object", "properties": document_interpretation_properties}

    if agent_family_id == "evidence_resolution_agent":
        return {"type": "object", "properties": evidence_resolution_properties}

    if agent_family_id == "adjudication_support_agent":
        return {
            "type": "object",
            "properties": {
                **common_properties,
                "adjudication_summary": {"type": "string"},
                "priority_conflicts": {"type": "array"},
                "priority_applicant_confirmations": {"type": "array"},
                "priority_planner_review_fields": {"type": "array"},
                "recommended_interview_targets": {"type": "array"},
                "per_field_adjudication": {"type": "array"},
                "stronger_candidate_reasoning": {"type": "array"},
                "hidden_conflict_flags": {"type": "array"},
                "ask_applicant_recommendation": {"type": "boolean"},
                "downgrade_recommendation": {"type": "boolean"},
                "runner_up_summary": {"type": "string"},
                "evidence_route_rationale": {"type": "string"},
                "source_quality_comparison": {"type": "string"},
                "specificity_comparison": {"type": "string"},
                "why_search_path_was_trusted": {"type": "string"},
            },
        }

    if agent_family_id == "applicant_interview_agent":
        return {"type": "object", "properties": applicant_interview_properties}

    if agent_family_id == "planner_support_agent":
        return {"type": "object", "properties": planner_support_properties}

    return {"type": "object", "properties": common_properties}


def _build_runtime_prompts(
    request: AgentRequest,
    max_prompt_chars: int,
) -> tuple[str, str]:
    agent = get_agent_definition(request.agent_id)
    agent_family_id = get_agent_family_id(request.agent_id)

    system_prompt = (
        "You are a bounded engineering support agent inside GridSenpAI. "
        f"Your role is: {agent.role_summary} "
        "You may return structured advisory output only. "
        "You must not override deterministic outputs, canonical state, field records, "
        "validation reports, or export values."
    )

    compact_inputs = _compact_agent_inputs(request.inputs)
    raw_text = json.dumps(_json_safe(compact_inputs), sort_keys=True, ensure_ascii=False, default=str)
    user_prompt = (
        f"Agent: {agent.display_name}\n"
        f"Stage: {request.stage_name}\n"
        f"Task: {request.task_name}\n"
        f"Trigger: {request.trigger_reason or 'not_provided'}\n"
        f"Associated fields: {', '.join(request.associated_field_paths) or 'none'}\n"
        f"Requested output fields: {', '.join(request.suggested_output_fields) or 'bounded_default'}\n"
        "Return concise structured advisory output only.\n"
        "Do not recommend direct deterministic overrides.\n"
        f"Inputs:\n{_truncate_text(raw_text, max_prompt_chars)}"
    )

    return system_prompt, user_prompt


def _run_single_runtime_assistance(
    *,
    context: Any,
    run_id: str,
    request: AgentRequest,
    max_prompt_chars: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    system_prompt, user_prompt = _build_runtime_prompts(
        request=request,
        max_prompt_chars=max_prompt_chars,
    )

    prompt_char_count = len(system_prompt) + len(user_prompt)
    if prompt_char_count > max_prompt_chars + 2000:
        skipped = sanitize_agent_payload(
            {
                "review_notes": [
                    f"Runtime assistance skipped because bounded prompt length ({prompt_char_count}) exceeded the configured budget ({max_prompt_chars})."
                ],
                "rationale": "Oversized advisory packet was blocked before LLM invocation; deterministic governance remains authoritative.",
                "confidence": "LOW",
            },
            get_agent_definition(request.agent_id).forbidden_fields,
        )
        return skipped, {
            "status": "SKIPPED_PROMPT_BUDGET_EXCEEDED",
            "prompt_char_count": prompt_char_count,
            "max_prompt_chars": max_prompt_chars,
            "service": "agent_runtime_service",
        }

    runtime_request = LLMTaskRequest(
        task_name=request.task_name,
        prompt_template_id=f"{request.agent_id}.{request.stage_name}.{request.task_name}.v1",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_schema=_build_runtime_schema(request.agent_id),
        json_mode=True,
        metadata={
            "agent_id": request.agent_id,
            "agent_family_id": get_agent_family_id(request.agent_id),
            "stage_name": request.stage_name,
            "task_name": request.task_name,
            "service": "agent_runtime_service",
            "trigger_reason": request.trigger_reason,
            "requested_capabilities": list(request.requested_capabilities),
            "associated_field_paths": list(request.associated_field_paths),
            "chunk_id": request.metadata.get("chunk_id"),
            "chunk_domain": request.metadata.get("chunk_domain"),
        },
    )

    runtime_result = run_llm_task(
        run_id=run_id,
        request=runtime_request,
        context=context,
    )

    runtime_payload = runtime_result.to_dict()
    parsed_json = runtime_payload.get("parsed_json")
    forbidden_fields = get_agent_definition(request.agent_id).forbidden_fields

    if isinstance(parsed_json, dict):
        return sanitize_agent_payload(parsed_json, forbidden_fields), runtime_payload

    fallback = sanitize_agent_payload(
        {
            "review_notes": [
                "Runtime assistance did not return usable JSON. Falling back to deterministic bounded provider."
            ]
        },
        forbidden_fields,
    )
    return fallback, runtime_payload


def _run_chunked_runtime_assistance(
    *,
    context: Any,
    run_id: str,
    request: AgentRequest,
    max_prompt_chars: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    chunks = build_advisory_chunks(
        agent_id=request.agent_id,
        agent_family_id=get_agent_family_id(request.agent_id),
        stage_name=request.stage_name,
        task_name=request.task_name,
        inputs=request.inputs,
        max_prompt_chars=max_prompt_chars,
        max_evidence_chars=_agent_max_evidence_chars(),
    )
    chunk_outputs: list[dict[str, Any]] = []
    failed_chunk_count = 0
    policy_blocked_chunks = 0
    largest_chunk_chars = 0
    total_after_chunking = 0

    for chunk in chunks:
        chunk_request = AgentRequest(
            agent_id=request.agent_id,
            stage_name=request.stage_name,
            task_name=request.task_name,
            inputs={"advisory_chunk": chunk.to_dict()},
            metadata={
                **dict(request.metadata),
                "chunk_id": chunk.chunk_id,
                "chunk_domain": chunk.domain,
                "chunk_lineage": chunk.lineage,
            },
            trigger_reason=request.trigger_reason,
            associated_field_paths=list(chunk.field_paths or request.associated_field_paths),
            evidence_anchors=list(request.evidence_anchors),
            suggested_output_fields=list(request.suggested_output_fields),
            requested_capabilities=list(request.requested_capabilities),
        )
        system_prompt, user_prompt = _build_runtime_prompts(chunk_request, max_prompt_chars)
        chunk_prompt_chars = len(system_prompt) + len(user_prompt)
        largest_chunk_chars = max(largest_chunk_chars, chunk_prompt_chars)
        total_after_chunking += chunk_prompt_chars
        if chunk_prompt_chars > max_prompt_chars + 2000:
            failed_chunk_count += 1
            policy_blocked_chunks += 1
            chunk_outputs.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "domain": chunk.domain,
                    "field_paths": list(chunk.field_paths),
                    "status": "SKIPPED_PROMPT_BUDGET_EXCEEDED",
                    "estimated_chars": chunk_prompt_chars,
                    "max_prompt_chars": max_prompt_chars,
                    "output": {},
                }
            )
            continue
        try:
            output, payload = _run_single_runtime_assistance(
                context=context,
                run_id=run_id,
                request=chunk_request,
                max_prompt_chars=max_prompt_chars,
            )
            status = str(payload.get("status") or "COMPLETED")
            if status.upper().startswith("SKIPPED") or status.upper() == "ERROR":
                failed_chunk_count += 1
            chunk_outputs.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "domain": chunk.domain,
                    "field_paths": list(chunk.field_paths),
                    "status": status,
                    "estimated_chars": chunk_prompt_chars,
                    "max_prompt_chars": max_prompt_chars,
                    "output_keys": sorted(output.keys()),
                    "output": output,
                    "runtime_payload": payload,
                }
            )
        except Exception as exc:
            failed_chunk_count += 1
            chunk_outputs.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "domain": chunk.domain,
                    "field_paths": list(chunk.field_paths),
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "estimated_chars": chunk_prompt_chars,
                    "max_prompt_chars": max_prompt_chars,
                    "output": {},
                }
            )

    fallback = sanitize_agent_payload(_bounded_provider(request), get_agent_definition(request.agent_id).forbidden_fields)
    merged = merge_chunk_outputs(chunk_outputs, fallback=fallback)
    merged.setdefault("review_notes", [])
    if isinstance(merged["review_notes"], list):
        merged["review_notes"].append(
            f"Runtime advisory assistance used {len(chunks)} bounded chunk(s); {failed_chunk_count} chunk(s) failed or were skipped."
        )
    merged["agent_chunking"] = {
        "chunking_enabled": True,
        "chunk_count": len(chunks),
        "failed_chunk_count": failed_chunk_count,
        "policy_blocked_chunks": policy_blocked_chunks,
        "largest_chunk_chars": largest_chunk_chars,
        "total_prompt_chars_after_chunking": total_after_chunking,
        "max_prompt_chars": max_prompt_chars,
        "domains": sorted({chunk.domain for chunk in chunks}),
        "deterministic_output_continued": True,
    }
    return merged, {
        "status": "CHUNKED_RUNTIME_COMPLETED" if failed_chunk_count < len(chunks) else "CHUNKED_RUNTIME_DEGRADED",
        "service": "agent_runtime_service",
        "chunking_enabled": True,
        "chunk_count": len(chunks),
        "failed_chunk_count": failed_chunk_count,
        "policy_blocked_chunks": policy_blocked_chunks,
        "max_prompt_chars": max_prompt_chars,
        "largest_chunk_chars": largest_chunk_chars,
        "total_prompt_chars_after_chunking": total_after_chunking,
        "chunks": [
            {key: value for key, value in item.items() if key not in {"output", "runtime_payload"}}
            for item in chunk_outputs
        ],
    }


def _run_runtime_assistance(
    *,
    context: Any,
    run_id: str,
    request: AgentRequest,
    max_prompt_chars: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    system_prompt, user_prompt = _build_runtime_prompts(
        request=request,
        max_prompt_chars=max_prompt_chars,
    )
    prompt_char_count = len(system_prompt) + len(user_prompt)
    if _chunking_enabled_for_request(request) and prompt_char_count > max_prompt_chars:
        return _run_chunked_runtime_assistance(
            context=context,
            run_id=run_id,
            request=request,
            max_prompt_chars=max_prompt_chars,
        )
    return _run_single_runtime_assistance(
        context=context,
        run_id=run_id,
        request=request,
        max_prompt_chars=max_prompt_chars,
    )


def _make_blocked_decision(
    *,
    run_id: str,
    request: AgentRequest,
    policy: AgentPolicyDecision,
    forbidden_fields: set[str],
) -> AgentDecision:
    return AgentDecision(
        run_id=run_id,
        agent_id=request.agent_id,
        stage_name=request.stage_name,
        task_name=request.task_name,
        status=policy.status,
        provider_mode=policy.provider_mode,
        agent_family_id=get_agent_family_id(request.agent_id),
        requested_agent_id=request.agent_id,
        structured_output=sanitize_agent_payload(
            {
                "review_notes": [policy.reason],
                "rationale": "The request was blocked by agent policy or configuration before any advisory output was accepted.",
                "confidence": "LOW",
            },
            forbidden_fields,
        ),
        runtime_payload={},
        used_runtime=False,
        used_fallback=False,
    )


def _make_allowed_decision(
    *,
    context: Any,
    run_id: str,
    request: AgentRequest,
    policy: AgentPolicyDecision,
) -> AgentDecision:
    agent = get_agent_definition(request.agent_id)

    if _should_use_runtime():
        try:
            structured_output, runtime_payload = _run_runtime_assistance(
                context=context,
                run_id=run_id,
                request=request,
                max_prompt_chars=policy.max_prompt_chars,
            )
            return AgentDecision(
                run_id=run_id,
                agent_id=request.agent_id,
                stage_name=request.stage_name,
                task_name=request.task_name,
                status="COMPLETED",
                provider_mode="llama_cpp_local",
                agent_family_id=get_agent_family_id(request.agent_id),
                requested_agent_id=request.agent_id,
                structured_output=structured_output,
                runtime_payload=runtime_payload,
                used_runtime=True,
                used_fallback=False,
            )
        except Exception as exc:
            runtime_payload = {
                "status": "error",
                "errors": [str(exc)],
                "service": "llm_runtime_service",
            }
            structured_output = sanitize_agent_payload(_bounded_provider(request), agent.forbidden_fields)
            structured_output.setdefault("review_notes", [])
            structured_output["review_notes"].append(
                "Runtime assistance failed. Deterministic bounded fallback was used."
            )
            return AgentDecision(
                run_id=run_id,
                agent_id=request.agent_id,
                stage_name=request.stage_name,
                task_name=request.task_name,
                status="COMPLETED",
                provider_mode="bounded_local_fallback",
                agent_family_id=get_agent_family_id(request.agent_id),
                requested_agent_id=request.agent_id,
                structured_output=structured_output,
                runtime_payload=runtime_payload,
                used_runtime=False,
                used_fallback=True,
            )

    return AgentDecision(
        run_id=run_id,
        agent_id=request.agent_id,
        stage_name=request.stage_name,
        task_name=request.task_name,
        status="COMPLETED",
        provider_mode="bounded_local",
        agent_family_id=get_agent_family_id(request.agent_id),
        requested_agent_id=request.agent_id,
        structured_output=sanitize_agent_payload(_bounded_provider(request), agent.forbidden_fields),
        runtime_payload={},
        used_runtime=False,
        used_fallback=False,
    )



def run_agent(
    *,
    context: Any,
    request: AgentRequest,
) -> dict[str, Any]:
    run_id = _require_run_id(context)
    run_dir = _optional_run_dir(context)
    normalized_request = _normalized_request(request)

    # Policy is evaluated against the canonical family agent so legacy/advisory
    # aliases inherit the correct stage/task contract and prompt budget. The
    # runtime/audit payloads intentionally preserve the caller's requested
    # agent_id so existing service contracts and diagnostics remain stable.
    policy = evaluate_agent_request_policy(
        context=context,
        request=normalized_request,
    )

    prompt_payload = _build_prompt_payload(
        request=request,
        max_prompt_chars=policy.max_prompt_chars,
    )

    if policy.allowed:
        decision = _make_allowed_decision(
            context=context,
            run_id=run_id,
            request=request,
            policy=policy,
        )
    else:
        decision = _make_blocked_decision(
            run_id=run_id,
            request=request,
            policy=policy,
            forbidden_fields=get_agent_definition(request.agent_id).forbidden_fields,
        )

    decision.audit_path = write_agent_audit(
        run_id=run_id,
        run_dir=run_dir,
        request=request,
        policy=policy,
        prompt_payload=prompt_payload,
        prompt_input_preview={
            "associated_field_paths": list(request.associated_field_paths),
            "suggested_output_fields": list(request.suggested_output_fields),
            "requested_capabilities": list(request.requested_capabilities),
            "trigger_reason": request.trigger_reason,
        },
        decision=decision,
    )

    response = AgentResponse(
        run_id=run_id,
        agent_id=request.agent_id,
        agent_family_id=get_agent_family_id(request.agent_id),
        requested_agent_id=request.agent_id,
        stage_name=request.stage_name,
        task_name=request.task_name,
        status=decision.status,
        policy={
            **policy.to_dict(),
            "provider_mode": decision.provider_mode,
        },
        audit_path=decision.audit_path,
        structured_output=decision.structured_output,
        runtime_payload=decision.runtime_payload,
    )
    return response.to_dict()


__all__ = [
    "build_agent_registry",
    "get_agent_definition",
    "evaluate_agent_policy",
    "evaluate_agent_request_policy",
    "sanitize_agent_payload",
    "run_agent",
]