from __future__ import annotations

from typing import Iterable

from services.agent_models.models import AgentDefinition, AgentRequest

CAPABILITY_ADVISORY_TEXT = "advisory_text"
CAPABILITY_STRUCTURED_CANDIDATES = "structured_candidate_fields"
CAPABILITY_FOLLOWUP_QUESTIONS = "followup_questions"
CAPABILITY_CANDIDATE_RANKING = "candidate_ranking"
CAPABILITY_RETRIEVAL_QUERY_PROPOSALS = "retrieval_query_proposals"
CAPABILITY_CONFIDENCE = "confidence"
CAPABILITY_RATIONALE = "rationale"

KNOWN_REQUEST_CAPABILITIES: set[str] = {
    CAPABILITY_ADVISORY_TEXT,
    CAPABILITY_STRUCTURED_CANDIDATES,
    CAPABILITY_FOLLOWUP_QUESTIONS,
    CAPABILITY_CANDIDATE_RANKING,
    CAPABILITY_RETRIEVAL_QUERY_PROPOSALS,
    CAPABILITY_CONFIDENCE,
    CAPABILITY_RATIONALE,
}


def normalize_requested_capabilities(values: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    if values is None:
        return normalized
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip().lower()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def infer_requested_capabilities(request: AgentRequest) -> list[str]:
    normalized = normalize_requested_capabilities(request.requested_capabilities)
    if normalized:
        return normalized

    inferred: list[str] = []
    if request.suggested_output_fields:
        inferred.append(CAPABILITY_STRUCTURED_CANDIDATES)
    for field_name in request.suggested_output_fields:
        lowered = str(field_name).strip().lower()
        if lowered in {"clarification_prompt", "suggested_next_field_path", "recommended_next_request"}:
            inferred.append(CAPABILITY_FOLLOWUP_QUESTIONS)
        if lowered in {"candidate_rankings", "recommended_candidate"}:
            inferred.append(CAPABILITY_CANDIDATE_RANKING)
        if lowered in {"suggested_queries", "query_plan", "knowledge_family_route"}:
            inferred.append(CAPABILITY_RETRIEVAL_QUERY_PROPOSALS)
        if lowered == "confidence":
            inferred.append(CAPABILITY_CONFIDENCE)
        if lowered == "rationale":
            inferred.append(CAPABILITY_RATIONALE)
    if not inferred:
        inferred.append(CAPABILITY_ADVISORY_TEXT)
    return normalize_requested_capabilities(inferred)


def allowed_capabilities_for(definition: AgentDefinition) -> set[str]:
    allowed: set[str] = {CAPABILITY_ADVISORY_TEXT}
    if definition.structured_candidate_fields_allowed:
        allowed.add(CAPABILITY_STRUCTURED_CANDIDATES)
    if definition.may_suggest_followup_questions:
        allowed.add(CAPABILITY_FOLLOWUP_QUESTIONS)
    if definition.may_rank_candidates:
        allowed.add(CAPABILITY_CANDIDATE_RANKING)
    if definition.may_propose_retrieval_queries:
        allowed.add(CAPABILITY_RETRIEVAL_QUERY_PROPOSALS)
    if definition.may_emit_confidence:
        allowed.add(CAPABILITY_CONFIDENCE)
    if definition.may_emit_rationale:
        allowed.add(CAPABILITY_RATIONALE)
    return allowed


def export_policy_matrix(definition: AgentDefinition) -> dict[str, object]:
    return {
        "agent_id": definition.agent_id,
        "display_name": definition.display_name,
        "allowed_stages": sorted(definition.allowed_stages),
        "allowed_task_types": sorted(definition.allowed_task_types),
        "allowed_stage_tasks": {
            stage_name: sorted(task_names)
            for stage_name, task_names in definition.allowed_stage_tasks.items()
        },
        "max_prompt_chars": definition.max_prompt_chars,
        "max_response_chars": definition.max_response_chars,
        "forbidden_fields": sorted(definition.forbidden_fields),
        "structured_candidate_fields_allowed": sorted(definition.structured_candidate_fields_allowed),
        "allowed_capabilities": sorted(allowed_capabilities_for(definition)),
        "advisory_text_only": definition.advisory_text_only,
    }
