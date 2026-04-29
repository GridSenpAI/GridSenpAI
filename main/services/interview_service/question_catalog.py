from __future__ import annotations

from functools import lru_cache
from typing import Any

from shared.field_paths import normalize_field_path as canonical_normalize_field_path
from services.interview_service.models import InterviewQuestion
from shared.schemas.domain_registry import load_intake_question_specs


def normalize_field_path(field_path: Any) -> str:
    return canonical_normalize_field_path(field_path)


ALLOWED_ANSWER_TYPES: set[str] = {
    "string",
    "integer",
    "number",
    "boolean",
    "enum",
}

LEGACY_QUESTION_CATALOG: list[InterviewQuestion] = [
    InterviewQuestion(
        question_id="FACILITY_POI_VOLTAGE_KV",
        field_path="facility.poi_voltage_kv",
        prompt="What is the point of interconnection voltage in kV?",
        answer_type="number",
        help_text="Provide the nominal POI voltage used for interconnection planning.",
        examples=["138", "345", "69"],
    ),
    InterviewQuestion(
        question_id="FACILITY_FREQUENCY_HZ",
        field_path="facility.frequency_hz",
        prompt="What operating frequency does the facility use?",
        answer_type="enum",
        allowed_values=[50, 60],
        help_text="Most U.S. interconnections use 60 Hz.",
        examples=["60"],
    ),
    InterviewQuestion(
        question_id="FACILITY_INITIAL_ENERGIZATION_DATE",
        field_path="facility.energization.initial_energization_date",
        prompt="What is the planned initial energization date?",
        answer_type="string",
        help_text="Provide the best current energization date or month/year if a final date is not set.",
        examples=["2027-06-15", "June 2027"],
    ),
    InterviewQuestion(
        question_id="FACILITY_PHASE_1_MW",
        field_path="facility.load_schedule.phase_1_mw",
        prompt="What is the phase 1 buildout demand in MW?",
        answer_type="number",
        help_text="Provide the expected MW demand for the first buildout phase.",
        examples=["12.5", "20"],
    ),
    InterviewQuestion(
        question_id="FACILITY_PHASE_2_MW",
        field_path="facility.load_schedule.phase_2_mw",
        prompt="What is the phase 2 buildout demand in MW?",
        answer_type="number",
        required=False,
        help_text="Provide the expected MW demand for the second buildout phase if known.",
        examples=["24", "40"],
    ),
    InterviewQuestion(
        question_id="FACILITY_PHASE_3_MW",
        field_path="facility.load_schedule.phase_3_mw",
        prompt="What is the phase 3 buildout demand in MW?",
        answer_type="number",
        required=False,
        help_text="Provide the expected MW demand for the third buildout phase if known.",
        examples=["36", "60"],
    ),
    InterviewQuestion(
        question_id="FACILITY_RAMP_TO_FULL_BUILDOUT",
        field_path="facility.load_schedule.ramp_to_full_buildout_duration",
        prompt="Over what time period do you expect the facility to ramp from initial energization to full buildout?",
        answer_type="string",
        required=False,
        help_text="Provide the expected duration or milestone schedule, such as months or years.",
        examples=["18 months", "Phase 1 in 2027, full buildout by 2030"],
    ),
    InterviewQuestion(
        question_id="FACILITY_DEMAND_RESPONSE_CAPABILITY",
        field_path="facility.operational_flexibility.demand_response_capable",
        prompt="Can the facility participate in peak shaving, demand response, or price-responsive curtailment?",
        answer_type="boolean",
        required=False,
        help_text="Answer yes or no based on planned or supported operation.",
        examples=["yes", "no"],
    ),
    InterviewQuestion(
        question_id="FACILITY_UPS_TOPOLOGY",
        field_path="facility.ups.topology",
        prompt="What UPS topology is installed?",
        answer_type="enum",
        allowed_values=["2N", "N+1", "DOUBLE_CONVERSION", "ECO_MODE", "UNKNOWN"],
        help_text="Choose the topology that best matches the installed UPS design.",
        examples=["2N", "N+1", "DOUBLE_CONVERSION"],
    ),
    InterviewQuestion(
        question_id="FACILITY_UPS_COUNT",
        field_path="facility.ups.count",
        prompt="How many UPS systems or modules are installed?",
        answer_type="integer",
        help_text="Provide the count of UPS systems or modules relevant to the facility design.",
        examples=["2", "6"],
    ),
    InterviewQuestion(
        question_id="FACILITY_TRANSFORMER_COUNT",
        field_path="facility.transformers.count",
        prompt="How many main transformers are installed?",
        answer_type="integer",
        help_text="Provide the count of main facility transformers.",
        examples=["2", "3"],
    ),
    InterviewQuestion(
        question_id="FACILITY_MAJOR_INTERNAL_VOLTAGES",
        field_path="facility.electrical_configuration.internal_voltage_levels",
        prompt="What are the major internal facility voltage levels?",
        answer_type="string",
        required=False,
        help_text="List the main internal voltage levels used across the facility.",
        examples=["34.5 kV, 13.8 kV, 480 V", "34.5 kV to 415 V"],
    ),
    InterviewQuestion(
        question_id="FACILITY_LOAD_COMPOSITION",
        field_path="facility.load_composition.summary",
        prompt="What portion of the site load is approximately IT load versus cooling/mechanical versus other major categories?",
        answer_type="string",
        required=False,
        help_text="A rough engineering estimate is acceptable if exact percentages are not available.",
        examples=["70% IT, 20% cooling, 10% other"],
    ),
    InterviewQuestion(
        question_id="FACILITY_GENERATORS_PRESENT",
        field_path="facility.generators.present",
        prompt="Are backup generators present?",
        answer_type="boolean",
        help_text="Answer yes or no.",
        examples=["yes", "no"],
    ),
    InterviewQuestion(
        question_id="FACILITY_GENERATOR_COUNT",
        field_path="facility.generators.count",
        prompt="How many generators are installed?",
        answer_type="integer",
        required=False,
        help_text="Provide the total installed generator count if generators are present.",
        examples=["2", "6"],
    ),
    InterviewQuestion(
        question_id="FACILITY_GENERATOR_OPERATION_MODE",
        field_path="facility.generators.operation_mode",
        prompt="Are the generators capable of operating grid-parallel, islanded only, or both?",
        answer_type="enum",
        required=False,
        allowed_values=[
            "GRID_PARALLEL",
            "ISLANDED_ONLY",
            "GRID_PARALLEL_AND_ISLAND",
            "UNKNOWN",
        ],
        help_text="Select the mode that best describes how the generators can operate relative to the grid.",
        examples=["GRID_PARALLEL", "ISLANDED_ONLY", "GRID_PARALLEL_AND_ISLAND"],
    ),
    InterviewQuestion(
        question_id="FACILITY_BTM_RESOURCES",
        field_path="facility.behind_the_meter.resources_present",
        prompt="Is there any behind-the-meter generation or storage that planners should account for?",
        answer_type="boolean",
        required=False,
        help_text="Answer yes or no.",
        examples=["yes", "no"],
    ),
    InterviewQuestion(
        question_id="FACILITY_MAX_UP_RAMP",
        field_path="facility.dynamic_behavior.max_ramp_up_mw_per_min",
        prompt="What is the approximate maximum upward ramp rate in MW per minute under fast-changing operating conditions?",
        answer_type="number",
        required=False,
        help_text="Provide the best available engineering estimate of the maximum upward demand ramp.",
        examples=["1.0", "5.5"],
    ),
    InterviewQuestion(
        question_id="FACILITY_MAX_DOWN_RAMP",
        field_path="facility.dynamic_behavior.max_ramp_down_mw_per_min",
        prompt="What is the approximate maximum downward ramp rate in MW per minute under fast-changing operating conditions?",
        answer_type="number",
        required=False,
        help_text="Provide the best available engineering estimate of the maximum downward demand ramp.",
        examples=["1.0", "4.0"],
    ),
    InterviewQuestion(
        question_id="FACILITY_VOLTAGE_RIDE_THROUGH",
        field_path="facility.dynamic_behavior.voltage_ride_through_behavior",
        prompt="What are the facility's voltage disturbance ride-through expectations or settings?",
        answer_type="string",
        required=False,
        help_text="Describe any ride-through settings, trip thresholds, or expected behavior during voltage events.",
        examples=[
            "UPS-supported ride-through for short voltage depressions",
            "Trips below a defined undervoltage threshold",
        ],
    ),
    InterviewQuestion(
        question_id="FACILITY_FREQUENCY_RIDE_THROUGH",
        field_path="facility.dynamic_behavior.frequency_ride_through_behavior",
        prompt="What are the facility's frequency disturbance ride-through expectations or settings?",
        answer_type="string",
        required=False,
        help_text="Describe any trip thresholds, control behavior, or ride-through expectations during frequency events.",
        examples=[
            "Maintains load through short frequency deviations",
            "Trips below minimum operating frequency threshold",
        ],
    ),
    InterviewQuestion(
        question_id="FACILITY_POST_DISTURBANCE_RESTORATION",
        field_path="facility.dynamic_behavior.post_disturbance_restoration_behavior",
        prompt="After a disturbance or transfer event, how and over what time does the load return to pre-disturbance demand?",
        answer_type="string",
        required=False,
        help_text="Describe restoration sequence, delays, staged loading, or operator actions.",
        examples=[
            "Returns in stages over 10 minutes",
            "Automatic staged restoration after transfer",
        ],
    ),
    InterviewQuestion(
        question_id="FACILITY_MODEL_AVAILABILITY",
        field_path="facility.modeling.model_availability_status",
        prompt="Are dynamic, phasor-domain, or EMT models available or expected to be provided for this facility?",
        answer_type="string",
        required=False,
        help_text="Describe what model types are available now, expected later, or not yet developed.",
        examples=[
            "Positive-sequence dynamic model available",
            "EMT model under development",
            "No formal model available yet",
        ],
    ),
]


FIELD_PATH_TYPE_OVERRIDES: dict[str, str] = {
    "facility.poi_voltage_kv": "number",
    "facility.frequency_hz": "enum",
    "facility.energization.initial_energization_date": "string",
    "facility.load_schedule.phase_1_mw": "number",
    "facility.dynamic_behavior.max_ramp_up_mw_per_min": "number",
    "facility.dynamic_behavior.max_ramp_down_mw_per_min": "number",
    "facility.ups.topology": "enum",
    "facility.ups.count": "integer",
    "facility.generators.count": "integer",
    "facility.generators.operation_mode": "enum",
    "facility.electrical_configuration.internal_voltage_levels": "string",
    "facility.transformers.count": "integer",
}


def _normalize_answer_type(data_type: str) -> str:
    normalized = data_type.strip().lower()

    mapping = {
        "string": "string",
        "text": "string",
        "date": "string",
        "datetime": "string",
        "month_year": "string",
        "structured_text": "string",
        "structured_text_optional": "string",
        "document_reference": "string",
        "document_reference_optional": "string",
        "contact_optional": "string",
        "checklist_documents": "string",
        "integer": "integer",
        "int": "integer",
        "count": "integer",
        "number": "number",
        "float": "number",
        "decimal": "number",
        "float_mw": "number",
        "float_mvar": "number",
        "mw": "number",
        "mvar": "number",
        "kv": "number",
        "hz": "number",
        "boolean": "boolean",
        "bool": "boolean",
        "enum": "enum",
        "table_backup_power": "string",
        "table_motors": "string",
        "table_induction_starting": "string",
        "table_synchronous_starting_optional": "string",
    }

    return mapping.get(normalized, "string")


def _allowed_values_for_field_id(field_id: str, data_type: str, field_path: str | None = None) -> list[Any]:
    normalized_field_id = field_id.strip().lower()
    normalized_type = data_type.strip().lower()
    normalized_field_path = (field_path or "").strip()

    if normalized_field_id == "frequency_hz" or normalized_field_path == "facility.frequency_hz":
        return [50, 60]

    if normalized_field_id == "ups_topology" or normalized_field_path == "facility.ups.topology":
        return ["2N", "N+1", "DOUBLE_CONVERSION", "ECO_MODE", "UNKNOWN"]

    if normalized_field_id in {
        "generator_parallel_capable",
        "generator_operation_mode",
    } or normalized_field_path == "facility.generators.operation_mode":
        return [
            "GRID_PARALLEL",
            "ISLANDED_ONLY",
            "GRID_PARALLEL_AND_ISLAND",
            "UNKNOWN",
        ]

    if normalized_type in {"boolean", "bool"}:
        return [True, False]

    return []


def _build_examples(field_id: str, data_type: str) -> list[str]:
    normalized_field_id = field_id.strip().lower()
    normalized_type = data_type.strip().lower()

    examples_by_field: dict[str, list[str]] = {
        "project_name": ["North Campus Data Center"],
        "service_delivery_point_voltage_kv": ["138", "345"],
        "requested_peak_demand_mw": ["75", "150"],
        "desired_initial_energization_date": ["2027-06-15", "June 2027"],
        "ups_topology": ["2N", "N+1", "DOUBLE_CONVERSION"],
        "ups_unit_count": ["2", "6"],
        "generator_count": ["2", "6"],
        "transformer_count": ["2", "3"],
        "internal_voltage_levels": ["34.5 kV, 13.8 kV, 480 V"],
        "frequency_hz": ["60"],
    }

    if normalized_field_id in examples_by_field:
        return examples_by_field[normalized_field_id]

    if normalized_type in {"integer", "count"}:
        return ["1", "2"]

    if normalized_type in {"number", "float", "decimal", "float_mw", "float_mvar", "mw", "mvar", "kv", "hz"}:
        return ["1.0", "10.5"]

    if normalized_type in {"boolean", "bool"}:
        return ["yes", "no"]

    return []


def _build_help_text(group: str, purpose: str, field_id: str) -> str | None:
    parts = [part.strip() for part in [group, purpose] if isinstance(part, str) and part.strip()]
    if not parts:
        return f"Provide the best available engineering answer for '{field_id}'."
    return " | ".join(parts)


def _clone_question_with_alias_id(question: InterviewQuestion, alias_question_id: str) -> InterviewQuestion:
    return InterviewQuestion(
        question_id=alias_question_id,
        field_path=question.field_path,
        prompt=question.prompt,
        answer_type=question.answer_type,
        required=question.required,
        allowed_values=list(question.allowed_values),
        help_text=question.help_text,
        examples=list(question.examples),
        follow_up_on_missing=question.follow_up_on_missing,
        reason=question.reason,
        triggering_status=question.triggering_status,
        question_category=question.question_category,
        priority=question.priority,
        requires_confirmation=question.requires_confirmation,
        related_artifact_ids=list(question.related_artifact_ids),
        metadata=dict(question.metadata),
        agent_id=question.agent_id,
        agent_status=question.agent_status,
        agent_audit_path=question.agent_audit_path,
    )


@lru_cache(maxsize=1)
def _registry_question_catalog() -> tuple[InterviewQuestion, ...]:
    questions: list[InterviewQuestion] = []

    for spec in load_intake_question_specs():
        if not spec.field_path:
            continue

        answer_type = _normalize_answer_type(spec.data_type)
        answer_type = FIELD_PATH_TYPE_OVERRIDES.get(spec.field_path, answer_type)

        if answer_type not in ALLOWED_ANSWER_TYPES:
            answer_type = "string"

        allowed_values = _allowed_values_for_field_id(spec.field_id, spec.data_type, spec.field_path)
        if allowed_values and answer_type in {"string", "number"} and spec.field_path not in {
            "facility.poi_voltage_kv",
            "facility.load_schedule.phase_1_mw",
        }:
            answer_type = "enum"

        metadata = {
            "registry_backed": True,
            "field_id": spec.field_id,
            "required_for": list(spec.required_for),
            "used_in": list(spec.used_in),
        }
        questions.append(
            InterviewQuestion(
                question_id=spec.question_id or spec.field_id.upper(),
                field_path=spec.field_path,
                prompt=spec.question,
                answer_type=answer_type,
                required=bool(spec.required_for),
                allowed_values=allowed_values,
                help_text=_build_help_text(spec.group, spec.purpose, spec.field_id),
                examples=_build_examples(spec.field_id, spec.data_type),
                follow_up_on_missing=True,
                question_category=spec.group,
                metadata=metadata,
            )
        )

    return tuple(questions)


def _deduplicate_questions(questions: list[InterviewQuestion]) -> list[InterviewQuestion]:
    deduped: list[InterviewQuestion] = []
    seen_question_ids: set[str] = set()
    seen_field_paths: set[str] = set()

    for question in questions:
        if question.question_id in seen_question_ids:
            continue
        if question.field_path in seen_field_paths:
            seen_question_ids.add(question.question_id)
            continue

        seen_question_ids.add(question.question_id)
        seen_field_paths.add(question.field_path)
        deduped.append(question)

    return deduped


@lru_cache(maxsize=1)
def _question_catalog() -> tuple[InterviewQuestion, ...]:
    registry_questions = list(_registry_question_catalog())
    if registry_questions:
        return tuple(_deduplicate_questions(registry_questions))
    return tuple(_deduplicate_questions(list(LEGACY_QUESTION_CATALOG)))


@lru_cache(maxsize=1)
def _question_id_alias_map() -> dict[str, InterviewQuestion]:
    alias_map: dict[str, InterviewQuestion] = {}

    canonical_questions = list(_question_catalog())
    canonical_by_field_path = {
        question.field_path: question
        for question in canonical_questions
    }

    for question in canonical_questions:
        alias_map[question.question_id] = question

    for legacy_question in LEGACY_QUESTION_CATALOG:
        canonical_question = canonical_by_field_path.get(legacy_question.field_path)
        if canonical_question is not None:
            alias_map[legacy_question.question_id] = _clone_question_with_alias_id(
                canonical_question,
                legacy_question.question_id,
            )
        elif not canonical_questions:
            alias_map[legacy_question.question_id] = legacy_question

    for registry_question in _registry_question_catalog():
        canonical_question = canonical_by_field_path.get(registry_question.field_path)
        if canonical_question is not None:
            alias_map[registry_question.question_id] = canonical_question
        else:
            alias_map[registry_question.question_id] = registry_question

    return alias_map


def get_question_catalog() -> list[InterviewQuestion]:
    return list(_question_catalog())


def get_question_by_id(question_id: str) -> InterviewQuestion | None:
    normalized = question_id.strip()
    if not normalized:
        return None
    return _question_id_alias_map().get(normalized)


def get_question_by_field_path(field_path: str) -> InterviewQuestion | None:
    normalized = field_path.strip()
    for question in _question_catalog():
        if question.field_path == normalized:
            return question
    return None


def build_question_metadata(field_path: str) -> tuple[str, str]:
    normalized = normalize_field_path(field_path)
    question = get_question_by_field_path(normalized)
    if question is not None:
        return question.question_id, question.prompt
    slug = normalized.replace('.', '_').upper() or 'UNKNOWN_FIELD'
    prompt = f"Please provide a value for {normalized}."
    return f"AUTO_{slug}", prompt
