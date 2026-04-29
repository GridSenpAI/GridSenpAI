from __future__ import annotations

from dataclasses import dataclass, field, replace
import os

from services.agent_models.models import AgentDefinition
from shared.runtime_stage_contract import GAP_RESOLUTION_INTERVIEW_STAGE, GAP_RESOLUTION_RETRIEVAL_STAGE


DISALLOWED_OVERRIDE_FIELDS: set[str] = {
    "entities",
    "topology_cues",
    "snippets",
    "output_parameters",
    "model_outputs",
    "canonical_state",
    "validation_report",
    "assumptions",
    "field_records",
    "conflict_records",
    "review_flags",
    "validated_updates",
    "translation_outputs",
    "scenario_outputs",
    "structured_answers",
}

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _agent_prompt_budget(agent_id: str) -> int:
    default = _env_int("GRIDSENPAI_AGENT_MAX_PROMPT_CHARS", 24000)
    env_by_agent = {
        "document_interpretation_agent": "GRIDSENPAI_DOCUMENT_AGENT_MAX_PROMPT_CHARS",
        "evidence_resolution_agent": "GRIDSENPAI_EVIDENCE_AGENT_MAX_PROMPT_CHARS",
        "adjudication_support_agent": "GRIDSENPAI_ADJUDICATION_AGENT_MAX_PROMPT_CHARS",
        "applicant_interview_agent": "GRIDSENPAI_INTERVIEW_AGENT_MAX_PROMPT_CHARS",
        "planner_support_agent": "GRIDSENPAI_PLANNER_AGENT_MAX_PROMPT_CHARS",
    }
    return _env_int(env_by_agent.get(agent_id, "GRIDSENPAI_AGENT_MAX_PROMPT_CHARS"), default)


DEFAULT_MAX_PROMPT_CHARS = _env_int("GRIDSENPAI_AGENT_MAX_PROMPT_CHARS", 24000)
DEFAULT_MAX_RESPONSE_CHARS = _env_int("GRIDSENPAI_AGENT_MAX_RESPONSE_CHARS", 2500)

CANONICAL_AGENT_FAMILIES: tuple[str, ...] = (
    "document_interpretation_agent",
    "evidence_resolution_agent",
    "adjudication_support_agent",
    "applicant_interview_agent",
    "planner_support_agent",
)

LEGACY_AGENT_ALIASES: dict[str, str] = {
    "ocr_ambiguity_agent": "document_interpretation_agent",
    "extraction_review_agent": "document_interpretation_agent",
    "retrieval_planning_agent": "evidence_resolution_agent",
    "intake_clarification_agent": "applicant_interview_agent",
    "translation_support_agent": "planner_support_agent",
    "packet_review_agent": "planner_support_agent",
}


@dataclass(slots=True)
class AgentRegistry:
    _definitions: dict[str, AgentDefinition] = field(default_factory=dict)

    def register(self, definition: AgentDefinition) -> None:
        self._definitions[definition.agent_id] = definition

    def get(self, agent_id: str) -> AgentDefinition:
        resolved_agent_id = resolve_agent_id(agent_id)
        try:
            return self._definitions[resolved_agent_id]
        except KeyError as exc:
            raise ValueError(f"Unknown agent_id '{agent_id}'.") from exc

    def as_dict(self) -> dict[str, AgentDefinition]:
        return dict(self._definitions)


def resolve_agent_id(agent_id: str) -> str:
    normalized = str(agent_id or "").strip()
    if not normalized:
        raise ValueError("agent_id must be a non-empty string.")
    return LEGACY_AGENT_ALIASES.get(normalized, normalized)


def get_agent_family_id(agent_id: str) -> str:
    return resolve_agent_id(agent_id)


def _merge_allowed_stage_tasks(*maps: dict[str, set[str]]) -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {}
    for mapping in maps:
        for stage_name, task_names in mapping.items():
            merged.setdefault(stage_name, set()).update(task_names)
    return merged


def _merge_sets(*values: set[str]) -> set[str]:
    merged: set[str] = set()
    for value in values:
        merged.update(value)
    return merged


def _build_definition_map() -> dict[str, AgentDefinition]:
    document_interpretation_tasks = _merge_allowed_stage_tasks(
        {"ocr": {"ocr_clarification"}, "extraction": {"ocr_clarification"}},
        {"extraction": {"entity_review"}},
        {
            "ocr": {"document_interpretation", "ocr_clarification"},
            "extraction": {"document_interpretation", "entity_review", "drawing_context_review"},
        },
    )
    evidence_resolution_tasks = _merge_allowed_stage_tasks(
        {GAP_RESOLUTION_RETRIEVAL_STAGE: {"query_review"}},
        {GAP_RESOLUTION_RETRIEVAL_STAGE: {"evidence_resolution", "query_review", "source_synthesis"}},
    )
    applicant_interview_tasks = _merge_allowed_stage_tasks(
        {
            GAP_RESOLUTION_INTERVIEW_STAGE: {
                "question_explanation",
                "answer_interpretation",
                "clarification_generation",
                "missing_field_selection",
                "sufficiency_review",
                "confirmation_planning",
                "interview_oversight",
            },
            "intake": {"question_explanation", "answer_interpretation", "clarification_generation"},
        },
    )
    planner_support_tasks = _merge_allowed_stage_tasks(
        {"translation": {"parameter_review"}},
        {"export": {"planner_packet_review"}},
    )
    return {
        "document_interpretation_agent": AgentDefinition(
            agent_id="document_interpretation_agent",
            display_name="Document Interpretation Agent",
            role_summary=(
                "Interprets messy engineering-document fragments, ambiguous OCR labels, and uncertain extraction candidates "
                "to propose bounded candidate interpretations without becoming canonical truth."
            ),
            allowed_stage_tasks=document_interpretation_tasks,
            allowed_task_types=_merge_sets({"ocr_clarification"}, {"entity_review"}, {"document_interpretation", "drawing_context_review"}),
            provider_mode="bounded_local",
            max_prompt_chars=_agent_prompt_budget("document_interpretation_agent"),
            max_response_chars=DEFAULT_MAX_RESPONSE_CHARS,
            forbidden_fields=set(DISALLOWED_OVERRIDE_FIELDS),
            advisory_text_only=False,
            structured_candidate_fields_allowed={
                "candidate_text",
                "candidate_label",
                "candidate_value",
                "candidate_interpretations",
                "source_anchor",
                "interpretation_notes",
                "review_notes",
                "recommended_candidate",
                "candidate_rankings",
                "review_flag",
                "candidate_focus_areas",
                "rationale",
                "confidence",
            },
            may_rank_candidates=True,
            allowed_stages={"ocr", "extraction"},
        ),
        "evidence_resolution_agent": AgentDefinition(
            agent_id="evidence_resolution_agent",
            display_name="Evidence Resolution Agent",
            role_summary=(
                "Synthesizes evidence gaps across the structured library, vendor PDF repository, and official-source web "
                "lookup routes to recommend the next bounded evidence-acquisition step without accepting values as truth."
            ),
            allowed_stage_tasks=evidence_resolution_tasks,
            allowed_task_types={"evidence_resolution", "query_review", "source_synthesis"},
            provider_mode="bounded_local",
            max_prompt_chars=_agent_prompt_budget("evidence_resolution_agent"),
            max_response_chars=DEFAULT_MAX_RESPONSE_CHARS,
            forbidden_fields=set(DISALLOWED_OVERRIDE_FIELDS),
            advisory_text_only=False,
            structured_candidate_fields_allowed={
                "query_plan",
                "suggested_queries",
                "suggested_query_topics",
                "knowledge_family_route",
                "lookup_constraints",
                "web_lookup_recommendations",
                "web_lookup_required",
                "evidence_gap_flag",
                "recommended_next_request",
                "stop_reason",
                "evidence_findings",
                "source_priority_summary",
                "review_notes",
                "rationale",
                "confidence",
            },
            may_propose_retrieval_queries=True,
            may_rank_candidates=True,
            may_suggest_followup_questions=True,
            allowed_stages={GAP_RESOLUTION_RETRIEVAL_STAGE},
        ),
        "adjudication_support_agent": AgentDefinition(
            agent_id="adjudication_support_agent",
            display_name="Adjudication Support Agent",
            role_summary=(
                "Reviews field-resolution outcomes, highlights hidden conflicts or weak acceptance decisions, and recommends "
                "which fields should be routed to applicant confirmation or planner review while leaving deterministic governance authoritative."
            ),
            allowed_stage_tasks={"canonical_state": {"field_resolution_review"}, "validation": {"field_resolution_review"}},
            allowed_task_types={"field_resolution_review"},
            provider_mode="bounded_local",
            max_prompt_chars=_agent_prompt_budget("adjudication_support_agent"),
            max_response_chars=DEFAULT_MAX_RESPONSE_CHARS,
            forbidden_fields=set(DISALLOWED_OVERRIDE_FIELDS),
            advisory_text_only=False,
            structured_candidate_fields_allowed={
                "adjudication_summary",
                "priority_conflicts",
                "priority_applicant_confirmations",
                "priority_planner_review_fields",
                "recommended_interview_targets",
                "per_field_adjudication",
                "stronger_candidate_reasoning",
                "hidden_conflict_flags",
                "ask_applicant_recommendation",
                "downgrade_recommendation",
                "runner_up_summary",
                "evidence_route_rationale",
                "source_quality_comparison",
                "specificity_comparison",
                "why_search_path_was_trusted",
                "review_notes",
                "rationale",
                "confidence",
            },
            may_rank_candidates=True,
            allowed_stages={"canonical_state", "validation"},
        ),
        "applicant_interview_agent": AgentDefinition(
            agent_id="applicant_interview_agent",
            display_name="Applicant Interview Agent",
            role_summary=(
                "Oversees the governed applicant interview after evidence processing by explaining questions, interpreting "
                "ambiguous answers, proposing targeted clarification prompts, ranking the next missing or low-confidence fields "
                "to ask about, and assessing whether the interview is sufficiently complete for deterministic validation."
            ),
            allowed_stage_tasks=applicant_interview_tasks,
            allowed_task_types={
                "question_explanation",
                "answer_interpretation",
                "clarification_generation",
                "missing_field_selection",
                "sufficiency_review",
                "confirmation_planning",
                "interview_oversight",
            },
            provider_mode="bounded_local",
            max_prompt_chars=_agent_prompt_budget("applicant_interview_agent"),
            max_response_chars=DEFAULT_MAX_RESPONSE_CHARS,
            forbidden_fields=set(DISALLOWED_OVERRIDE_FIELDS),
            advisory_text_only=False,
            structured_candidate_fields_allowed={
                "clarified_question_text",
                "explained_question",
                "candidate_structured_answer",
                "clarification_prompt",
                "needs_human_reask",
                "suggested_next_field_path",
                "recommended_missing_fields",
                "recommended_confirmations",
                "question_sequence",
                "sufficiency_assessment",
                "interview_readiness",
                "should_finalize_interview",
                "rationale",
                "confidence",
            },
            may_suggest_followup_questions=True,
            allowed_stages={GAP_RESOLUTION_INTERVIEW_STAGE, "intake"},
        ),
        "planner_support_agent": AgentDefinition(
            agent_id="planner_support_agent",
            display_name="Planner Support Agent",
            role_summary=(
                "Supports planner-facing rationale, review-note phrasing, and bounded packet trust summaries around deterministic "
                "translation and export outputs without changing any governed value."
            ),
            allowed_stage_tasks=planner_support_tasks,
            allowed_task_types={"parameter_review", "planner_packet_review"},
            provider_mode="bounded_local",
            max_prompt_chars=_agent_prompt_budget("planner_support_agent"),
            max_response_chars=DEFAULT_MAX_RESPONSE_CHARS,
            forbidden_fields=set(DISALLOWED_OVERRIDE_FIELDS),
            advisory_text_only=False,
            structured_candidate_fields_allowed={
                "parameter_explanation",
                "planner_note",
                "review_note",
                "assumption_summary",
                "missing_info_summary",
                "confidence_explanation",
                "packet_review_notes",
                "trust_summary",
                "planner_warnings",
                "reviewer_focus",
                "packet_readiness",
                "review_notes",
                "rationale",
                "confidence",
            },
            allowed_stages={"translation", "export"},
        ),
    }


def build_agent_registry() -> dict[str, AgentDefinition]:
    return _build_definition_map()


def build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for definition in _build_definition_map().values():
        registry.register(definition)
    return registry


_AGENT_REGISTRY = build_registry()


def get_agent_definition(agent_id: str) -> AgentDefinition:
    return _AGENT_REGISTRY.get(agent_id)


def get_registry() -> AgentRegistry:
    return _AGENT_REGISTRY


def get_legacy_agent_aliases() -> dict[str, str]:
    return dict(LEGACY_AGENT_ALIASES)


def get_agent_policy_matrix(agent_id: str) -> dict[str, object]:
    from services.agent_policy_service.matrix import export_policy_matrix

    return export_policy_matrix(get_agent_definition(agent_id))


def get_all_agent_policy_matrices() -> dict[str, dict[str, object]]:
    from services.agent_policy_service.matrix import export_policy_matrix

    registry = get_registry()
    return {agent_id: export_policy_matrix(definition) for agent_id, definition in registry.as_dict().items()}
