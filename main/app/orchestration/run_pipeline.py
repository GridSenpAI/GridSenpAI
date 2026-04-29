from __future__ import annotations

import argparse
import inspect
import json
import logging
import time
import sys
import traceback
from types import SimpleNamespace
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Protocol, cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import CONFIG, apply_llm_runtime_overrides
from shared.confidence_utils import normalize_confidence_score
from shared.knowledge_routes import knowledge_route_status
from shared.planner_registry import pipeline_requested_field_paths
from shared.gap_resolution_utils import resolve_gap_resolution_stage_inputs
from shared.runtime_stage_contract import (
    GAP_RESOLUTION_INTERVIEW_STAGE,
    GAP_RESOLUTION_RETRIEVAL_STAGE,
    gap_resolution_substage_order,
    public_stage_order,
    replay_contract_summary,
)
from shared.canonical_state_contract import (
    annotate_final_canonical_state_result,
    build_working_canonical_state_result,
)
from shared.governed_summary import build_governed_run_summary, summarize_runtime_observability
from shared.project_identity import resolve_project_identity
from shared.adjudication_result import build_adjudication_result_from_canonical
from shared.planner_field_ledger import planner_field_contract_from_canonical
from shared.planner_interview_closure import apply_interview_answers_to_planner_contract
from shared.ledger_adjudication import (
    apply_ledger_adjudication_to_contract,
    build_ledger_adjudication_artifact,
)
from shared.planner_field_governance import build_planner_field_governance
from shared.phase6_redesign_contract import build_phase6_redesign_runtime_contract
from shared.security.run_access_registry import RunAccessRegistry
from shared.security.models import Actor
from services.audit_logging_service.service import initialize_audit_logger
from services.llm_runtime_service.service import initialize_runtime
from services.llm_runtime_service.models import LLMRuntimeConfig
from services.interview_service.service import run_service as default_interview_service
from services.canonical_state_service.service import run_service as default_canonical_state_service
from services.document_parser_service.service import run_service as default_document_parser_service
from services.extraction_service.domain import ExtractionDomainCoordinator
from services.extraction_service.models import ExtractionCandidate
from services.extraction_service.service import run_service as default_extraction_service
from services.canonical_state_service.service import merge_extraction_candidates
from services.interview_service.serialization import (
    serialize_interview_questions,
    serialize_resolved_entities,
)
from services.layout_analysis_service.service import run_service as default_layout_analysis_service
from services.retrieval_service.service import run_service as default_retrieval_service
from services.replay_service.service import initialize_replay_manager
from services.run_diff_service.service import compare_run_states
from services.run_governance_service.service import initialize_run_governance
from services.validation_service.service import run_service as default_validation_service
from services.ocr_service.service import run_service as default_ocr_service
from services.agent_runtime_service.service import run_agent
from services.agent_runtime_service.models import AgentRequest
from shared.types import (
    CanonicalFacilityState,
    CanonicalStateStageResult,
    ExportStageResult,
    ExtractionStageResult,
    IngestionStageResult,
    InterviewStageResult,
    NormalizationStageResult,
    RetrievalStageResult,
    ScenarioStageResult,
    TranslationStageResult,
    ValidationStageResult,
    build_empty_canonical_state,
)

LOGGER = logging.getLogger("gridsenpai.pipeline")


RUNTIME_ARCHITECTURE = CONFIG.runtime_architecture

PUBLIC_PIPELINE_STAGE_ORDER = public_stage_order()

GAP_RESOLUTION_SUBSTAGE_ORDER = gap_resolution_substage_order()

INTERVIEW_WAITING_STATUSES = {"WAITING_FOR_INTERVIEW", "IN_PROGRESS"}
INTERVIEW_RESOLVED_STATUSES = {
    "INTERVIEW_NOT_REQUIRED",
    "INTERVIEW_ANSWERS_SUBMITTED",
    "INTERVIEW_SKIPPED_BY_USER",
    "INTERVIEW_DEFERRED_BY_USER",
    "INTERVIEW_APPLIED_TO_LEDGER",
    "INTERVIEWS_INGESTED",
    "COMPLETE",
    "SKIPPED_BY_USER",
}


def _interview_workflow_state(interview_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(interview_result, dict):
        return {
            "state": "INTERVIEW_NOT_RUN",
            "ready_for_downstream": False,
            "requires_user_action": False,
            "question_count": 0,
            "remaining_question_count": 0,
            "state_reason": "Interview stage has not returned a structured result.",
        }

    explicit = interview_result.get("workflow_state")
    if isinstance(explicit, dict):
        state = str(explicit.get("state") or explicit.get("stage_status") or interview_result.get("status", "")).strip().upper()
        question_count = _safe_int(explicit.get("question_count", explicit.get("remaining_question_count", 0)))
        remaining_question_count = _safe_int(explicit.get("remaining_question_count", question_count))
        requires_user_action = bool(explicit.get("requires_user_action", False))
        ready_for_downstream = bool(explicit.get("ready_for_downstream", False))
        if state in INTERVIEW_WAITING_STATUSES and remaining_question_count > 0:
            requires_user_action = True
            ready_for_downstream = False
        return {
            **explicit,
            "state": state or "INTERVIEW_UNKNOWN",
            "ready_for_downstream": ready_for_downstream,
            "requires_user_action": requires_user_action,
            "question_count": question_count,
            "remaining_question_count": remaining_question_count,
            "state_reason": str(explicit.get("state_reason", "")).strip(),
        }

    status = str(interview_result.get("status", "")).strip().upper()
    session = interview_result.get("interview_session")
    session = session if isinstance(session, dict) else {}
    session_status = str(session.get("status", "")).strip().upper()
    questions = interview_result.get("questions", [])
    clarifications = interview_result.get("clarifications", [])
    question_count = len(questions) if isinstance(questions, list) else 0
    clarification_count = len(clarifications) if isinstance(clarifications, list) else 0
    state = status or session_status or "INTERVIEW_UNKNOWN"
    requires_user_action = (state in INTERVIEW_WAITING_STATUSES or session_status in INTERVIEW_WAITING_STATUSES) and (question_count > 0 or clarification_count > 0)
    ready_for_downstream = state in INTERVIEW_RESOLVED_STATUSES and not requires_user_action
    if question_count > 0 and state not in INTERVIEW_RESOLVED_STATUSES:
        requires_user_action = True
        ready_for_downstream = False
        state = "WAITING_FOR_INTERVIEW"

    return {
        "state": state,
        "ready_for_downstream": ready_for_downstream,
        "requires_user_action": requires_user_action,
        "question_count": question_count,
        "remaining_question_count": question_count,
        "clarification_count": clarification_count,
        "state_reason": "Derived from legacy interview result shape.",
    }


def _interview_requires_user_action(interview_result: dict[str, Any] | None) -> bool:
    state = _interview_workflow_state(interview_result)
    return bool(state.get("requires_user_action")) or (
        str(state.get("state", "")).strip().upper() == "WAITING_FOR_INTERVIEW"
        and _safe_int(state.get("remaining_question_count", 0)) > 0
    )


def _interview_allows_draft_outputs(interview_result: dict[str, Any] | None) -> bool:
    state = _interview_workflow_state(interview_result)
    state_name = str(state.get("state", "")).strip().upper()
    return state_name in {"INTERVIEW_SKIPPED_BY_USER", "INTERVIEW_DEFERRED_BY_USER", "SKIPPED_BY_USER", "DEFERRED_BY_USER"} and not bool(state.get("requires_user_action", False))


def _translation_is_ledger_first(translation_result: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
    payload = translation_result if isinstance(translation_result, dict) else {}
    contract = payload.get("translation_source_contract") if isinstance(payload.get("translation_source_contract"), dict) else {}
    if not contract:
        contract = payload.get("ledger_first_translation_contract") if isinstance(payload.get("ledger_first_translation_contract"), dict) else {}
    primary_source = str(contract.get("primary_source", "")).strip()
    fallback_used = contract.get("legacy_translation_fallback_used")
    passed = primary_source == "planner_field_ledger" and fallback_used is False
    return passed, {
        "primary_source": primary_source,
        "legacy_translation_fallback_used": fallback_used,
        "planner_ledger_row_count": contract.get("planner_ledger_row_count", 0),
        "fallback_rows_used": contract.get("fallback_rows_used", 0),
        "status": payload.get("status", "UNKNOWN"),
    }


def _scenario_is_ledger_native(scenario_result: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
    payload = scenario_result if isinstance(scenario_result, dict) else {}
    contract = payload.get("scenario_input_contract") if isinstance(payload.get("scenario_input_contract"), dict) else {}
    baseline_source = str(contract.get("baseline_output_source", "")).strip()
    passed = baseline_source == "ledger_native_model_outputs"
    return passed, {
        "baseline_output_source": baseline_source,
        "contract_version": contract.get("contract_version"),
        "blocked_parameter_count": contract.get("blocked_parameter_count", 0),
        "status": payload.get("status", "UNKNOWN"),
    }


def _adjudication_is_closed(planner_ledger_adjudication: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
    payload = planner_ledger_adjudication if isinstance(planner_ledger_adjudication, dict) else {}
    ledger_status = str(payload.get("status", "")).strip().upper()
    field_resolution_status = str(payload.get("field_resolution_adjudication_status", "")).strip().upper()
    decision_count = _safe_int(payload.get("decision_count", 0))
    closed = (
        ledger_status in {"LEDGER_ADJUDICATION_COMPLETED", "LEDGER_ADJUDICATION_SKIPPED_NO_FIELDS"}
        or (
            ledger_status == "LEDGER_ADJUDICATION_READY_OR_SKIPPED"
            and field_resolution_status in {"ADJUDICATION_SKIPPED_NO_CONFLICTS", "NO_ADJUDICATION_REQUIRED"}
        )
    )
    return closed, {
        "status": ledger_status,
        "field_resolution_adjudication_status": field_resolution_status,
        "decision_count": decision_count,
        "planner_critical_failed_count": payload.get("planner_critical_failed_count", 0),
        "release_effect": payload.get("release_effect"),
    }


def _build_pre_export_gate(
    *,
    run_id: str,
    interview_result: dict[str, Any] | None,
    translation_result: dict[str, Any] | None,
    scenario_result: dict[str, Any] | None,
    planner_ledger_adjudication: dict[str, Any] | None = None,
) -> dict[str, Any]:
    interview_state = _interview_workflow_state(interview_result)
    interview_ready = bool(interview_state.get("ready_for_downstream", False)) and not _interview_requires_user_action(interview_result)
    interview_state_name = str(interview_state.get("state", "")).strip().upper()
    draft_only_allowed = interview_state_name in {"INTERVIEW_SKIPPED_BY_USER", "INTERVIEW_DEFERRED_BY_USER"}
    translation_ready, translation_evidence = _translation_is_ledger_first(translation_result)
    scenario_ready, scenario_evidence = _scenario_is_ledger_native(scenario_result)
    adjudication_ready, adjudication_evidence = _adjudication_is_closed(planner_ledger_adjudication)
    gates = [
        {
            "gate": "interview_resolved_for_downstream",
            "status": "PASS" if interview_ready else "FAIL",
            "requirement": "Applicant interview must be not-required, answered, skipped, or deferred before planner-facing export.",
            "evidence": make_serializable(interview_state),
        },
        {
            "gate": "adjudication_closed",
            "status": "PASS" if adjudication_ready else "FAIL",
            "requirement": "Adjudication must be completed, deterministically skipped because no conflicts exist, or explicitly closed before planner-facing export.",
            "evidence": make_serializable(adjudication_evidence),
        },
        {
            "gate": "ledger_first_translation",
            "status": "PASS" if translation_ready else "FAIL",
            "requirement": "Translation must use final planner ledger rows as the primary source without legacy fallback.",
            "evidence": make_serializable(translation_evidence),
        },
        {
            "gate": "ledger_native_scenario_inputs",
            "status": "PASS" if scenario_ready else "FAIL",
            "requirement": "Scenario generation must consume ledger-native model outputs before export.",
            "evidence": make_serializable(scenario_evidence),
        },
    ]
    failed = [gate for gate in gates if gate.get("status") != "PASS"]
    return {
        "contract_version": "pre_export_gate_v1",
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "status": "PRE_EXPORT_GATE_PASS" if not failed else "PRE_EXPORT_GATE_FAIL",
        "ready_for_final_export": not failed,
        "draft_only_allowed": bool(draft_only_allowed),
        "export_mode": "FINAL_EXPORT_READY" if not failed else "DRAFT_EXPORT_ONLY" if draft_only_allowed else "BLOCKED_DIAGNOSTIC_ONLY",
        "failed_gate_count": len(failed),
        "failed_gates": [str(gate.get("gate", "")) for gate in failed],
        "gates": gates,
    }


def _build_blocked_export_result(*, run_id: str, pre_export_gate: dict[str, Any]) -> dict[str, Any]:
    interview_ready = all(
        gate.get("gate") != "interview_resolved_for_downstream" or gate.get("status") == "PASS"
        for gate in pre_export_gate.get("gates", [])
        if isinstance(gate, dict)
    )
    return {
        "run_id": run_id,
        "status": "EXPORT_BLOCKED_PRECONTRACT",
        "export_mode": str(pre_export_gate.get("export_mode") or "BLOCKED_DIAGNOSTIC_ONLY"),
        "exported_at": utc_now_iso(),
        "pre_export_gate": make_serializable(pre_export_gate),
        "warnings": [
            "Final planner export was blocked before artifact generation because required pre-export gates failed."
        ],
        "export_manifest": {
            "run_id": run_id,
            "status": "EXPORT_BLOCKED_PRECONTRACT",
            "summary": {
                "final_export_ready": False,
                "planner_packet_ready": False,
                "interview_ready_for_final_output": interview_ready,
                "pre_export_gate_status": pre_export_gate.get("status"),
                "blocked_export_reason": "PRE_EXPORT_GATE_FAIL",
                "blocked_export_failed_gates": list(pre_export_gate.get("failed_gates", [])) if isinstance(pre_export_gate.get("failed_gates", []), list) else [],
            },
            "exports": {},
        },
    }


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


@dataclass(slots=True)
class RunConfig:
    project_name: str = "GridSenpAI"
    project_id: str = ""
    project_number: str = ""
    applicant: str = ""
    schema_version_input: str = "0.1.0"
    schema_version_output: str = "0.1.0"
    prompt_template_version: str = "configured-at-runtime"
    model_version: str = "configured-at-runtime"
    retrieval_config: dict[str, Any] | None = None
    ocr_enabled: bool = field(default_factory=lambda: CONFIG.ocr.enabled)
    ocr_lang: str = field(default_factory=lambda: CONFIG.ocr.lang)
    ocr_render_scale: float = field(default_factory=lambda: CONFIG.ocr.render_scale)
    ocr_text_detection_model_name: str = field(default_factory=lambda: CONFIG.ocr.text_detection_model_name)
    ocr_text_recognition_model_name: str = field(default_factory=lambda: CONFIG.ocr.text_recognition_model_name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunContext:
    run_id: str
    project_root: Path
    input_dir: Path
    output_dir: Path
    run_dir: Path
    config: RunConfig

    actor: "Actor | None" = None
    run_access_registry: "RunAccessRegistry | None" = None

    parent_run_id: str | None = None
    execution_mode: str = "STANDARD"
    replay_source_run_id: str | None = None
    replay_stage_boundary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        actor_payload = None
        if self.actor is not None:
            actor_payload = {
                "actor_id": self.actor.actor_id,
                "role": self.actor.role.value,
                "display_name": self.actor.display_name,
                "email": self.actor.email,
            }

        run_access_payload = None
        if self.run_access_registry is not None:
            run_access_payload = {
                "registered_run_ids": sorted(
                    list(getattr(self.run_access_registry, "_runs", {}).keys())
                )
            }

        return {
            "run_id": str(self.run_id),
            "project_root": str(self.project_root),
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "run_dir": str(self.run_dir),
            "config": self.config.to_dict(),
            "actor": actor_payload,
            "run_access_registry": run_access_payload,
            "parent_run_id": self.parent_run_id,
            "execution_mode": self.execution_mode,
            "replay_source_run_id": self.replay_source_run_id,
            "replay_stage_boundary": self.replay_stage_boundary,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False, default=str)


LARGE_ARTIFACT_LIST_CAPS = {
    "candidates": 25,
    "candidate_options": 25,
    "evidence": 20,
    "evidence_records": 50,
    "source_snippets": 25,
    "supporting_snippets": 25,
    "review_flags": 200,
    "validation_impacts": 200,
    "manual_review_queue": 200,
    "planner_action_queue": 200,
    "decisions": 150,
    "planner_field_ledger": 1200,
}
LARGE_ARTIFACT_STRING_CAPS = {
    "evidence_snippet": 750,
    "text": 1200,
    "raw_text": 1200,
    "content": 1200,
    "prompt": 1200,
    "response": 1200,
}


def _compact_large_artifact_payload(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 10:
        return "[truncated:max_depth]"
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for child_key, child_value in value.items():
            compacted[str(child_key)] = _compact_large_artifact_payload(child_value, key=str(child_key), depth=depth + 1)
        return compacted
    if isinstance(value, list):
        cap = LARGE_ARTIFACT_LIST_CAPS.get(key)
        if cap is None:
            cap = 300 if depth >= 5 else len(value)
        visible = value[:cap]
        compacted_list = [_compact_large_artifact_payload(item, key=key, depth=depth + 1) for item in visible]
        if len(value) > cap:
            compacted_list.append({
                "_truncated": True,
                "original_count": len(value),
                "retained_count": cap,
                "reason": "runtime artifact compaction; full in-memory state was preserved during execution",
            })
        return compacted_list
    if isinstance(value, str):
        cap = LARGE_ARTIFACT_STRING_CAPS.get(key, 4000 if depth >= 4 else 12000)
        if len(value) > cap:
            return value[:cap] + f"...[truncated {len(value) - cap} chars]"
    return value


def safe_write_compact_json(path: Path, payload: Any) -> None:
    safe_write_json(path, _compact_large_artifact_payload(payload))


def safe_print_json(payload: Any) -> None:
    serialized = json.dumps(make_serializable(payload), indent=2, ensure_ascii=False, default=str)
    stdout = sys.stdout
    encoding = getattr(stdout, "encoding", None) or "utf-8"
    try:
        stdout.write(serialized)
        stdout.write("\n")
        return
    except UnicodeEncodeError:
        pass

    buffer = getattr(stdout, "buffer", None)
    encoded = serialized.encode(encoding, errors="replace") + b"\n"
    if buffer is not None:
        buffer.write(encoded)
        buffer.flush()
        return

    stdout.write(serialized.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    stdout.write("\n")


def safe_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def list_artifact_files(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    allowed_suffixes = {
        ".pdf",
        ".doc",
        ".docx",
        ".txt",
        ".json",
        ".csv",
        ".png",
        ".jpg",
        ".jpeg",
    }

    return [
        path
        for path in sorted(input_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in allowed_suffixes
    ]


def build_run_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"run_{timestamp}"


def normalize_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def make_serializable(payload: Any) -> Any:
    if isinstance(payload, Path):
        return str(payload)
    if isinstance(payload, dict):
        return {str(key): make_serializable(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [make_serializable(item) for item in payload]
    if isinstance(payload, tuple):
        return [make_serializable(item) for item in payload]
    return payload


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_field_records(canonical_state: dict[str, Any]) -> list[dict[str, Any]]:
    records = canonical_state.get("field_records", [])
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _field_records_by_path(canonical_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}

    for record in _coerce_field_records(canonical_state):
        field_path = record.get("field_path")
        if not isinstance(field_path, str) or not field_path.strip():
            continue
        normalized = field_path.strip()
        lookup.setdefault(normalized, []).append(record)

    return lookup


def _review_flag_categories_by_path(canonical_state: dict[str, Any]) -> dict[str, set[str]]:
    review_flags = canonical_state.get("review_flags", [])
    if not isinstance(review_flags, list):
        return {}

    lookup: dict[str, set[str]] = {}

    for item in review_flags:
        if not isinstance(item, dict):
            continue

        field_path = item.get("field_path")
        category = item.get("category")

        if not isinstance(field_path, str) or not field_path.strip():
            continue
        if not isinstance(category, str) or not category.strip():
            continue

        normalized = field_path.strip()
        lookup.setdefault(normalized, set()).add(category.strip().upper())

    return lookup


def _has_conflict_for_field(canonical_state: dict[str, Any], field_path: str) -> bool:
    conflict_records = canonical_state.get("conflict_records", [])
    if not isinstance(conflict_records, list):
        return False

    for item in conflict_records:
        if not isinstance(item, dict):
            continue
        candidate_path = item.get("field_path")
        if isinstance(candidate_path, str) and candidate_path.strip() == field_path:
            return True

    return False


def _resolve_export_field_value(
    canonical_state: dict[str, Any],
    field_path: str,
    fallback_value: Any = "Unknown",
) -> Any:
    records_by_path = _field_records_by_path(canonical_state)
    review_flags_by_path = _review_flag_categories_by_path(canonical_state)

    records = records_by_path.get(field_path, [])
    categories = review_flags_by_path.get(field_path, set())

    if _has_conflict_for_field(canonical_state, field_path):
        return "CONFLICTING"

    if "CONFLICTING_FIELD" in categories or "MULTI_PROJECT_SCOPE_CONFLICT" in categories:
        return "CONFLICTING"

    if not records:
        return fallback_value

    primary = None
    for record in records:
        if record.get("is_primary") is True:
            primary = record
            break

    if primary is None:
        primary = records[0]

    status = str(primary.get("status", "")).strip().lower()
    value = primary.get("value")

    if status in {"validated", "interview_confirmed"}:
        return value if value is not None else fallback_value

    if status == "conflicting":
        return "CONFLICTING"

    if status in {"review_required", "provisional_extracted", "missing", "superseded"}:
        return "REVIEW REQUIRED"

    return value if value is not None else fallback_value


def build_runtime_contract_summary() -> dict[str, Any]:
    knowledge_status = knowledge_route_status()
    configured_canonical_families = list(RUNTIME_ARCHITECTURE.canonical_knowledge_families)
    configured_legacy_fallbacks = list(RUNTIME_ARCHITECTURE.legacy_knowledge_fallbacks)
    contract = replay_contract_summary()
    active_runtime_sources = knowledge_status.get("active_runtime_sources", {})
    legacy_compatibility = knowledge_status.get("legacy_compatibility", {})

    contract["bounded_assist"] = {
        "active_runtime": contract.get("active_bounded_assist_backend", ""),
        "legacy_compatibility_layers": {
            layer_name: "inactive_on_active_runtime_path"
            for layer_name in contract.get("inactive_compatibility_layers", [])
        },
    }
    contract["knowledge_families"] = configured_canonical_families
    contract["knowledge_runtime_status"] = {
        family_name: active_runtime_sources.get(family_name, {})
        for family_name in configured_canonical_families
    }
    contract["knowledge_legacy_compatibility"] = {
        family_name: legacy_compatibility.get(family_name, {})
        for family_name in configured_legacy_fallbacks
    }
    return contract


def build_intake_summary(ingestion_result: dict[str, Any] | None) -> dict[str, Any]:
    payload = ingestion_result if isinstance(ingestion_result, dict) else {}
    intake_session = payload.get("intake_session", {})
    if not isinstance(intake_session, dict):
        intake_session = {}

    requirements = intake_session.get("requirements", [])
    if not isinstance(requirements, list):
        requirements = []

    required_requirements = [
        requirement
        for requirement in requirements
        if isinstance(requirement, dict) and bool(requirement.get("required", False))
    ]

    missing_required = [
        requirement
        for requirement in required_requirements
        if str(requirement.get("state", "")).strip().upper() == "MISSING"
    ]

    discovered_artifacts = payload.get("artifacts") or payload.get("artifacts_discovered") or []
    if not isinstance(discovered_artifacts, list):
        discovered_artifacts = []

    return {
        "session_id": str(intake_session.get("session_id", "")).strip(),
        "session_path": str(intake_session.get("session_path", "")).strip(),
        "status": str(intake_session.get("status", "NOT_STARTED")).strip() or "NOT_STARTED",
        "artifact_count": _safe_int(payload.get("artifact_count", len(discovered_artifacts)), len(discovered_artifacts)),
        "required_artifact_count": _safe_int(
            intake_session.get("required_artifact_count", len(required_requirements)),
            len(required_requirements),
        ),
        "uploaded_artifact_count": _safe_int(intake_session.get("uploaded_artifact_count", 0), 0),
        "missing_required_count": _safe_int(intake_session.get("missing_required_count", len(missing_required)), len(missing_required)),
        "missing_required_requirement_ids": [
            str(requirement.get("requirement_id", "")).strip()
            for requirement in missing_required
            if str(requirement.get("requirement_id", "")).strip()
        ],
        "missing_required_labels": [
            str(requirement.get("label", "")).strip()
            for requirement in missing_required
            if str(requirement.get("label", "")).strip()
        ],
        "complete": _safe_int(intake_session.get("missing_required_count", len(missing_required)), len(missing_required)) == 0
        and bool(intake_session),
    }


def _rebase_run_id_in_payload(payload: Any, source_run_id: str | None, target_run_id: str) -> Any:
    if source_run_id is None or source_run_id == target_run_id:
        return deepcopy(payload)

    if isinstance(payload, dict):
        rebased: dict[str, Any] = {}
        for key, value in payload.items():
            if key == "run_id" and value == source_run_id:
                rebased[key] = target_run_id
            else:
                rebased[key] = _rebase_run_id_in_payload(value, source_run_id, target_run_id)
        return rebased

    if isinstance(payload, list):
        return [_rebase_run_id_in_payload(item, source_run_id, target_run_id) for item in payload]

    if isinstance(payload, tuple):
        return [_rebase_run_id_in_payload(item, source_run_id, target_run_id) for item in payload]

    return deepcopy(payload)


class SupportsToDict(Protocol):
    def to_dict(self) -> dict[str, Any]:
        ...


class ServiceResolver:
    FUNCTION_CANDIDATES: dict[str, list[str]] = {
        "ingestion": [
            "run_service",
            "run",
            "execute",
            "ingest_artifacts",
            "ingest",
        ],
        "extraction": [
            "run_service",
            "run",
            "execute",
            "extract_entities",
            "extract",
        ],
        "retrieval": [
            "run_service",
            "run",
            "execute",
            "retrieve_evidence",
            "retrieve",
        ],
        "interview": [
            "run_service",
            "run",
            "execute",
            "ingest_interviews",
            "interview",
        ],
        "normalization": [
            "run_service",
            "run",
            "execute",
            "normalize_inputs",
            "normalize",
        ],
        "canonical_state": [
            "run_service",
            "run",
            "execute",
            "build_canonical_state",
        ],
        "validation": [
            "run_service",
            "run",
            "execute",
            "validate_canonical_state",
        ],
        "translation": [
            "run_service",
            "run",
            "execute",
            "translate_parameters",
            "translate",
        ],
        "scenarios": [
            "run_service",
            "run",
            "execute",
            "generate_scenarios",
            "generate",
        ],
        "export": [
            "run_service",
            "run",
            "execute",
            "build_export_packet",
            "export_packet",
            "export",
        ],
    }

    MODULES: dict[str, str] = {
        "ingestion": "services.ingestion_service.service",
        "extraction": "services.extraction_service.service",
        "retrieval": "services.retrieval_service.service",
        "interview": "services.interview_service.service",
        "normalization": "services.normalization_service.service",
        "canonical_state": "services.canonical_state_service.service",
        "validation": "services.validation_service.service",
        "translation": "services.translation_service.service",
        "scenarios": "services.scenario_service.service",
        "export": "services.export_service.service",
    }

    def resolve(self, stage_name: str) -> Callable[..., dict[str, Any]] | None:
        module_name = self.MODULES[stage_name]
        function_candidates = self.FUNCTION_CANDIDATES[stage_name]

        try:
            module = import_module(module_name)
        except Exception as exc:
            LOGGER.debug("Could not import module for stage '%s': %s", stage_name, exc)
            return None

        for function_name in function_candidates:
            candidate = getattr(module, function_name, None)
            if callable(candidate):
                LOGGER.info(
                    "Resolved custom implementation for stage '%s': %s.%s",
                    stage_name,
                    module_name,
                    function_name,
                )
                return cast(Callable[..., dict[str, Any]], candidate)

        LOGGER.debug(
            "No compatible callable found in module '%s' for stage '%s'.",
            module_name,
            stage_name,
        )
        return None



def _coerce_extraction_confidence(value: Any) -> float:
    return normalize_confidence_score(value, band=str(value or ""), default=0.0)


def _string_key_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        if isinstance(raw_key, str):
            key = raw_key
        elif isinstance(raw_key, bytes):
            key = raw_key.decode("utf-8", errors="replace")
        else:
            key = str(raw_key)
        if key:
            normalized[key] = raw_value
    return normalized


def _candidate_evidence_dict(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("evidence")
    if isinstance(evidence, dict):
        return _string_key_dict(evidence)
    if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
        return _string_key_dict(evidence[0])
    return {}


def _schema_candidate_to_extraction_candidate(candidate: dict[str, Any]) -> ExtractionCandidate | None:
    if not isinstance(candidate, dict):
        return None
    field_path = str(candidate.get("field_path", "")).strip()
    if not field_path:
        return None
    value = candidate.get("value")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    source_artifact_id = str(
        candidate.get("artifact_id") or candidate.get("source_artifact_id") or ""
    ).strip()
    return ExtractionCandidate(
        field_path=field_path,
        value=value,
        confidence=_coerce_extraction_confidence(candidate.get("confidence")),
        source_artifact_id=source_artifact_id,
        method=str(candidate.get("method") or candidate.get("source_method") or "schema_extraction").strip(),
        evidence=_candidate_evidence_dict(candidate),
        metadata=_string_key_dict(candidate.get("metadata")),
    )


def _derive_unresolved_requested_fields_from_canonical(
    *,
    requested_field_paths: list[str],
    canonical_state: dict[str, Any],
) -> list[str]:
    unresolved: list[str] = []
    for field_path in requested_field_paths:
        normalized_path = str(field_path).strip()
        if not normalized_path:
            continue
        entry = canonical_state.get(normalized_path)
        if not isinstance(entry, dict):
            unresolved.append(normalized_path)
            continue
        value = entry.get("value")
        status = str(entry.get("status", "")).strip().lower()
        if value is None or (isinstance(value, str) and not value.strip()) or status in {"missing", "unresolved"}:
            unresolved.append(normalized_path)
    return unresolved


def default_ingestion(context: RunContext) -> dict[str, Any]:
    artifacts = list_artifact_files(context.input_dir)

    artifact_records: list[dict[str, Any]] = []
    for index, artifact_path in enumerate(artifacts, start=1):
        artifact_records.append(
            {
                "artifact_id": f"artifact_{index:03d}",
                "file_name": artifact_path.name,
                "file_path": str(artifact_path),
                "file_suffix": artifact_path.suffix.lower(),
                "size_bytes": artifact_path.stat().st_size,
                "ingested_at": utc_now_iso(),
                "index_status": "PENDING",
                "classification": "UNCLASSIFIED",
            }
        )

    return {
        "run_id": context.run_id,
        "status": "ARTIFACTS_INGESTED",
        "ingested_at": utc_now_iso(),
        "artifacts_discovered": artifact_records,
        "artifacts": artifact_records,
        "artifact_count": len(artifact_records),
        "warnings": [],
        "errors": [],
    }


def default_extraction(
    context: RunContext,
    ingestion_result: dict[str, Any],
    document_parser_result: dict[str, Any] | None = None,
    layout_analysis_result: dict[str, Any] | None = None,
    ocr_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ingestion_artifacts = ingestion_result.get("artifacts") or ingestion_result.get(
        "artifacts_discovered",
        [],
    )
    if not isinstance(ingestion_artifacts, list):
        ingestion_artifacts = []

    requested_field_paths = pipeline_requested_field_paths()

    rich_extraction_result = default_extraction_service(
        context=context,
        ingestion_result=ingestion_result,
        document_parser_result=document_parser_result,
        layout_analysis_result=layout_analysis_result,
        ocr_result=ocr_result,
    )

    extraction_domain = ExtractionDomainCoordinator()
    extraction_candidates = [
        candidate
        for candidate in (
            _schema_candidate_to_extraction_candidate(item)
            for item in rich_extraction_result.get("schema_field_candidates", [])
        )
        if candidate is not None
    ]
    canonical_state = merge_extraction_candidates(
        candidates=extraction_candidates,
        canonical_state={},
    )
    unresolved_fields = _derive_unresolved_requested_fields_from_canonical(
        requested_field_paths=requested_field_paths,
        canonical_state=canonical_state,
    )

    observations = extraction_domain.collect_entity_observations(ingestion_artifacts)
    resolved_entities = serialize_resolved_entities(extraction_domain.resolve_entities(observations))

    llm_assistance = rich_extraction_result.get("llm_assistance", {})
    llm_task_policy = {}
    if isinstance(llm_assistance, dict):
        llm_task_policy = {
            "extraction_review": {
                "status": str(llm_assistance.get("status", "NOT_RUN")).strip() or "NOT_RUN",
                "agent_id": str(llm_assistance.get("agent_id", "")).strip() or None,
                "policy": llm_assistance.get("policy", {}),
            }
        }

    warnings = rich_extraction_result.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []

    return {
        "run_id": context.run_id,
        "status": str(rich_extraction_result.get("status", "EXTRACTED")).strip() or "EXTRACTED",
        "extracted_at": rich_extraction_result.get("extracted_at", utc_now_iso()),
        "candidate_entities": rich_extraction_result.get("candidate_entities", []),
        "entities": rich_extraction_result.get("entities", []),
        "schema_field_candidates": rich_extraction_result.get("schema_field_candidates", []),
        "resolved_entities": resolved_entities,
        "canonical_state": canonical_state or {},
        "unresolved_fields": unresolved_fields or [],
        "interview_questions": [],
        "ready_for_interview": False,
        "pre_gap_resolution_unresolved_fields": unresolved_fields or [],
        "llm_task_policy": llm_task_policy or {
            "allowed": [],
            "blocked": [],
            "notes": "No LLM tasks registered.",
        },
        "topology_cues": rich_extraction_result.get("topology_cues", []),
        "source_anchors": rich_extraction_result.get("source_anchors", []),
        "document_parser_result": rich_extraction_result.get("document_parser_result"),
        "layout_analysis_result": rich_extraction_result.get("layout_analysis_result"),
        "ocr_result": rich_extraction_result.get("ocr_result"),
        "warnings": warnings,
        "errors": rich_extraction_result.get("errors", []),
    }


def default_retrieval(
    context: RunContext,
    normalization_result: dict[str, Any] | None = None,
    extraction_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return default_retrieval_service(
        context=context,
        normalization_result=normalization_result,
        extraction_result=extraction_result,
    )


def default_interview(
    context: RunContext,
    extraction_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    working_canonical_state_result = build_working_canonical_state_result(
        run_id=context.run_id,
        extraction_result=extraction_result,
        normalization_result=normalization_result,
    )
    return default_interview_service(
        context=context,
        extraction_result=extraction_result,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
        canonical_state_result=working_canonical_state_result,
    )


def default_normalization(
    context: RunContext,
    extraction_result: dict[str, Any],
    interview_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_state = extraction_result.get("canonical_state", {})
    retrieval_result = retrieval_result or {}

    confirmed_interview_count = 0
    clarification_count = 0

    if isinstance(interview_result, dict):
        confirmed = interview_result.get("answers_confirmed", [])
        clarifications = interview_result.get("clarifications", [])

        if isinstance(confirmed, list):
            confirmed_interview_count = len(confirmed)

        if isinstance(clarifications, list):
            clarification_count = len(clarifications)

    followup_questions: list[dict[str, Any]] = []
    unresolved_fields = extraction_result.get("unresolved_fields", [])

    facility = {
        "project_name": context.config.project_name,
        "poi_voltage_kv": None,
        "frequency_hz": 60,
        "load_schedule": {
            "phase_1_mw": None,
            "phase_2_mw": None,
            "phase_3_mw": None,
        },
        "ups": {
            "topology": None,
            "count": None,
        },
        "generators": {
            "present": None,
            "count": None,
        },
        "transformers": {
            "count": None,
            "ratings_mva": [],
        },
    }

    if "facility.poi_voltage_kv" in canonical_state:
        facility["poi_voltage_kv"] = canonical_state["facility.poi_voltage_kv"].get("value")

    if "facility.load_schedule.phase_1_mw" in canonical_state:
        facility["load_schedule"]["phase_1_mw"] = canonical_state[
            "facility.load_schedule.phase_1_mw"
        ].get("value")

    if "facility.load_schedule.phase_2_mw" in canonical_state:
        facility["load_schedule"]["phase_2_mw"] = canonical_state[
            "facility.load_schedule.phase_2_mw"
        ].get("value")

    if "facility.load_schedule.phase_3_mw" in canonical_state:
        facility["load_schedule"]["phase_3_mw"] = canonical_state[
            "facility.load_schedule.phase_3_mw"
        ].get("value")

    if "facility.ups.topology" in canonical_state:
        facility["ups"]["topology"] = canonical_state["facility.ups.topology"].get("value")

    if "facility.ups.count" in canonical_state:
        facility["ups"]["count"] = canonical_state["facility.ups.count"].get("value")

    if "facility.generators.count" in canonical_state:
        generator_count = canonical_state["facility.generators.count"].get("value")
        facility["generators"]["count"] = generator_count
        facility["generators"]["present"] = (
            generator_count is not None and generator_count > 0
        )

    if "facility.transformers.count" in canonical_state:
        facility["transformers"]["count"] = canonical_state[
            "facility.transformers.count"
        ].get("value")

    if "facility.transformers.ratings_mva" in canonical_state:
        transformer_rating = canonical_state["facility.transformers.ratings_mva"].get("value")
        if transformer_rating is not None:
            facility["transformers"]["ratings_mva"] = [transformer_rating]

    normalized_input = {
        "run_id": context.run_id,
        "schema_version": context.config.schema_version_input,
        "facility": facility,
        "source_summary": {
            "canonical_field_count": len(canonical_state),
            "entity_count": len(
                extraction_result.get("entities")
                or extraction_result.get("candidate_entities")
                or []
            ),
            "topology_cue_count": len(extraction_result.get("topology_cues", [])),
            "evidence_snippet_count": len(retrieval_result.get("snippets", [])),
            "confirmed_interview_count": confirmed_interview_count,
            "clarification_count": clarification_count,
        },
    }

    validation_report = {
        "run_id": context.run_id,
        "schema_valid": True,
        "schema_path": "planner_required_fields.normalization_runtime",
        "errors": [],
        "warnings": [],
        "missing_fields": unresolved_fields,
        "conflicts": [],
        "interview_summary": {
            "confirmed_field_paths": [
                item.get("field_path")
                for item in (interview_result or {}).get("answers_confirmed", [])
                if isinstance(item, dict) and isinstance(item.get("field_path"), str)
            ],
        },
    }

    return {
        "run_id": context.run_id,
        "status": "NORMALIZED",
        "normalized_at": utc_now_iso(),
        "normalized_input": normalized_input,
        "validation_report": validation_report,
        "followup_questions": followup_questions,
        "pre_gap_resolution_unresolved_fields": unresolved_fields,
        "warnings": [],
        "errors": [],
    }


def _can_run_translation_support_agent(context: Any | None) -> bool:
    if context is None:
        return False
    run_id = getattr(context, "run_id", None)
    return isinstance(run_id, str) and bool(run_id.strip())


def _build_translation_support_fallback(*, output_parameters: list[dict[str, Any]], assumptions: list[dict[str, Any]]) -> dict[str, Any]:
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
        if str(parameter.get("provenance_type", "")).strip().lower() == "assumption":
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
        "agent_id": "translation_support_agent",
        "agent_status": "NOT_RUN",
        "agent_audit_path": "",
        "agent_policy": {},
    }


def _append_unique_note(existing: str, note: str) -> str:
    base = str(existing or "").strip()
    candidate = str(note or "").strip()
    if not candidate:
        return base
    if not base:
        return candidate
    base_parts = [part.strip() for part in base.split(" ") if part.strip()]
    if candidate in base or candidate in base_parts:
        return base
    return f"{base} {candidate}".strip()


def _apply_translation_support_to_fallback(
    *,
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    translation_support: dict[str, Any],
) -> None:
    low_confidence_parameters = set(translation_support.get("low_confidence_parameters", []) if isinstance(translation_support.get("low_confidence_parameters", []), list) else [])
    assumption_backed_parameters = set(translation_support.get("assumption_backed_parameters", []) if isinstance(translation_support.get("assumption_backed_parameters", []), list) else [])
    missing_dependency_parameters = set(translation_support.get("missing_dependency_parameters", []) if isinstance(translation_support.get("missing_dependency_parameters", []), list) else [])

    global_planner_note = str(translation_support.get("planner_note", "")).strip()
    global_review_note = str(translation_support.get("review_note", "")).strip()
    global_confidence_explanation = str(translation_support.get("confidence_explanation", "")).strip()

    for parameter in output_parameters:
        if not isinstance(parameter, dict):
            continue
        parameter_path = str(parameter.get("parameter_path", "")).strip()
        if not parameter_path:
            continue
        if parameter_path in low_confidence_parameters:
            parameter["review_note"] = _append_unique_note(str(parameter.get("review_note", "")), "Translation Support Agent flagged this parameter as low-confidence.")
        if parameter_path in assumption_backed_parameters:
            parameter["planner_note"] = _append_unique_note(str(parameter.get("planner_note", "")), "This parameter is supported by an explicit assumption record.")
        if parameter_path in missing_dependency_parameters:
            parameter["confidence_explanation"] = _append_unique_note(str(parameter.get("confidence_explanation", "")), "Confidence is reduced because one or more dependency fields remain unresolved.")
        if global_planner_note:
            parameter["planner_note"] = _append_unique_note(str(parameter.get("planner_note", "")), global_planner_note)
        if global_review_note:
            parameter["review_note"] = _append_unique_note(str(parameter.get("review_note", "")), global_review_note)
        if global_confidence_explanation:
            parameter["confidence_explanation"] = _append_unique_note(str(parameter.get("confidence_explanation", "")), global_confidence_explanation)

    for assumption in assumptions:
        if not isinstance(assumption, dict):
            continue
        parameter_path = str(assumption.get("parameter_path", "")).strip()
        if not parameter_path:
            continue
        assumption["planner_note"] = _append_unique_note(
            str(assumption.get("planner_note", "")),
            "Translation Support Agent confirmed this assumption remains planner-visible.",
        )
        if str(translation_support.get("assumption_summary", "")).strip():
            assumption["planner_note"] = _append_unique_note(
                str(assumption.get("planner_note", "")),
                str(translation_support.get("assumption_summary", "")).strip(),
            )


def _run_translation_support_agent(
    *,
    context: Any,
    output_parameters: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    validation_report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    fallback_support = _build_translation_support_fallback(output_parameters=output_parameters, assumptions=assumptions)
    llm_assistance = {
        "agent_id": "translation_support_agent",
        "status": "NOT_RUN",
        "policy": {},
        "audit_path": "",
        "bounded_response": {
            "reason": "Deterministic translation support fallback was used without bounded agent review.",
            "deterministic_override_allowed": False,
        },
    }
    if not _can_run_translation_support_agent(context):
        _apply_translation_support_to_fallback(output_parameters=output_parameters, assumptions=assumptions, translation_support=fallback_support)
        return fallback_support, llm_assistance

    try:
        agent_result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="translation_support_agent",
                stage_name="translation",
                task_name="parameter_review",
                inputs={
                    "output_parameters": output_parameters,
                    "assumptions": assumptions,
                    "validation_report": validation_report if isinstance(validation_report, dict) else {},
                },
                metadata={"service": "run_pipeline.default_translation"},
                trigger_reason="planner_facing_translation_support_requested",
                associated_field_paths=[
                    str(parameter.get("parameter_path", "")).strip()
                    for parameter in output_parameters
                    if isinstance(parameter, dict) and str(parameter.get("parameter_path", "")).strip()
                ],
                suggested_output_fields=[
                    "parameter_explanation", "planner_note", "review_note", "assumption_summary",
                    "missing_info_summary", "confidence_explanation", "rationale", "confidence",
                    "review_notes", "low_confidence_parameters", "assumption_backed_parameters",
                    "missing_dependency_parameters",
                ],
            ),
        )
    except Exception as exc:
        llm_assistance["status"] = "ERROR"
        llm_assistance["agent_error"] = str(exc)
        llm_assistance["bounded_response"] = {
            "reason": f"Translation support agent failed: {exc}",
            "deterministic_override_allowed": False,
        }
        _apply_translation_support_to_fallback(output_parameters=output_parameters, assumptions=assumptions, translation_support=fallback_support)
        return fallback_support, llm_assistance

    structured_output = agent_result.get("structured_output", {}) if isinstance(agent_result, dict) else {}
    if not isinstance(structured_output, dict):
        structured_output = {}
    translation_support = dict(fallback_support)
    for key in [
        "review_notes", "low_confidence_parameters", "assumption_backed_parameters", "missing_dependency_parameters",
        "parameter_explanation", "planner_note", "review_note", "assumption_summary", "missing_info_summary",
        "confidence_explanation", "rationale", "confidence",
    ]:
        if key in structured_output:
            translation_support[key] = structured_output.get(key)
    translation_support["agent_id"] = str(agent_result.get("agent_id", "")).strip() or "translation_support_agent"
    translation_support["agent_status"] = str(agent_result.get("status", "")).strip()
    translation_support["agent_audit_path"] = str(agent_result.get("audit_path", "")).strip()
    translation_support["agent_policy"] = dict(agent_result.get("policy", {})) if isinstance(agent_result.get("policy", {}), dict) else {}
    _apply_translation_support_to_fallback(output_parameters=output_parameters, assumptions=assumptions, translation_support=translation_support)
    llm_assistance = {
        "agent_id": translation_support["agent_id"],
        "status": translation_support["agent_status"] or "FALLBACK",
        "policy": translation_support["agent_policy"],
        "audit_path": translation_support["agent_audit_path"],
        "bounded_response": {
            "reason": str(translation_support.get("review_note") or translation_support.get("rationale") or "Translation support review completed.").strip(),
            "deterministic_override_allowed": False,
        },
    }
    return translation_support, llm_assistance



def default_translation(
    context: RunContext,
    canonical_state_result: dict[str, Any] | None = None,
    validation_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_state = {}
    if isinstance(validation_result, dict):
        canonical_state = validation_result.get("canonical_state", {})
    if not canonical_state and isinstance(canonical_state_result, dict):
        canonical_state = canonical_state_result.get("canonical_state", {})
    if not canonical_state and isinstance(normalization_result, dict):
        canonical_state = {
            "normalized_input": normalization_result.get("normalized_input", {}),
            "validation_report": normalization_result.get("validation_report", {}),
        }

    snippets = []
    if isinstance(canonical_state, dict):
        snippets = canonical_state.get("evidence_snippets", [])
    if not snippets and isinstance(retrieval_result, dict):
        snippets = retrieval_result.get("snippets", [])

    assumption_id = "assumption_001"

    parameters = [
        {
            "parameter_path": "steady_state.p_mw",
            "value": 0.0,
            "units": "MW",
            "provenance_type": "assumption",
            "provenance_ref": assumption_id,
            "dependency_paths": ["facility.load_schedule.phase_1_mw"],
            "source_field_paths": ["facility.load_schedule.phase_1_mw"],
            "supporting_snippet_ids": [],
            "confidence_score": 0.10,
            "confidence_tag": "LOW",
            "confidence_factors": {
                "engineer_confirmed": False,
                "direct_evidence_count": 0,
                "derived_from_rule": False,
                "assumption_used": True,
                "conflict_present": False,
                "missing_dependency": True,
                "uses_default_rule": False,
            },
        },
        {
            "parameter_path": "steady_state.q_mvar",
            "value": 0.0,
            "units": "MVAR",
            "provenance_type": "rule",
            "provenance_ref": "RULE.AGGREGATION.DEFAULT_Q.v1",
            "dependency_paths": ["facility.load_schedule.phase_1_mw"],
            "source_field_paths": ["facility.load_schedule.phase_1_mw"],
            "supporting_snippet_ids": [],
            "confidence_score": 0.45,
            "confidence_tag": "LOW",
            "confidence_factors": {
                "engineer_confirmed": False,
                "direct_evidence_count": 0,
                "derived_from_rule": True,
                "assumption_used": True,
                "conflict_present": False,
                "missing_dependency": True,
                "uses_default_rule": True,
            },
        },
        {
            "parameter_path": "zip_model.constant_power_fraction",
            "value": 0.80,
            "units": "fraction",
            "provenance_type": "evidence",
            "provenance_ref": [snippets[0]["snippet_id"]] if snippets else [],
            "dependency_paths": ["facility.ups.topology"],
            "source_field_paths": ["facility.ups.topology"],
            "supporting_snippet_ids": [snippets[0]["snippet_id"]] if snippets else [],
            "confidence_score": 0.85,
            "confidence_tag": "HIGH",
            "confidence_factors": {
                "engineer_confirmed": False,
                "direct_evidence_count": 1 if snippets else 0,
                "derived_from_rule": False,
                "assumption_used": False,
                "conflict_present": False,
                "missing_dependency": False,
                "uses_default_rule": False,
            },
        },
        {
            "parameter_path": "ramping.max_ramp_up_mw_per_min",
            "value": 1.0,
            "units": "MW/min",
            "provenance_type": "evidence",
            "provenance_ref": [snippets[1]["snippet_id"]] if len(snippets) > 1 else [],
            "dependency_paths": ["facility.load_schedule.phase_1_mw"],
            "source_field_paths": ["facility.load_schedule.phase_1_mw"],
            "supporting_snippet_ids": [snippets[1]["snippet_id"]] if len(snippets) > 1 else [],
            "confidence_score": 0.60 if len(snippets) > 1 else 0.40,
            "confidence_tag": "MODERATE" if len(snippets) > 1 else "LOW",
            "confidence_factors": {
                "engineer_confirmed": False,
                "direct_evidence_count": 1 if len(snippets) > 1 else 0,
                "derived_from_rule": False,
                "assumption_used": False,
                "conflict_present": False,
                "missing_dependency": False,
                "uses_default_rule": False,
            },
        },
    ]

    confidence_summary = {
        "HIGH": 0,
        "MODERATE": 0,
        "LOW": 0,
        "UNRESOLVED": 0,
    }
    for parameter in parameters:
        confidence_summary[str(parameter["confidence_tag"])] += 1

    assumptions = [
        {
            "assumption_id": assumption_id,
            "parameter_path": "steady_state.p_mw",
            "nominal_value": 0.0,
            "bounds": {
                "min": 0.0,
                "max": 5.0,
            },
            "rationale": "Fallback assumption emitted because grounded facility buildout evidence was unavailable. Review required.",
            "created_by": "system",
        }
    ]

    output_schema = {
        "run_id": context.run_id,
        "schema_version": context.config.schema_version_output,
        "steady_state": {
            "p_mw": 0.0,
            "q_mvar": 0.0,
        },
        "zip_model": {
            "constant_power_fraction": 0.80,
            "constant_current_fraction": 0.10,
            "constant_impedance_fraction": 0.10,
        },
        "ramping": {
            "max_ramp_up_mw_per_min": 1.0,
            "max_ramp_down_mw_per_min": 1.0,
        },
    }

    translation_support, llm_assistance = _run_translation_support_agent(
        context=context,
        output_parameters=parameters,
        assumptions=assumptions,
        validation_report=validation_result.get("validation_report", {}) if isinstance(validation_result, dict) else {},
    )

    return {
        "run_id": context.run_id,
        "status": "TRANSLATED",
        "translated_at": utc_now_iso(),
        "model_outputs": output_schema,
        "output_parameters": parameters,
        "assumptions": assumptions,
        "confidence_summary": confidence_summary,
        "translation_support": translation_support,
        "schema_validation": {
            "schema_valid": True,
            "schema_path": "planner_required_fields.translation_runtime",
            "errors": [],
        },
        "llm_assistance": llm_assistance,
        "warnings": [
            "Translation fallback emitted review-required defaults because grounded translation evidence was unavailable.",
        ],
        "errors": [],
    }


def default_scenarios(
    context: RunContext,
    translation_result: dict[str, Any],
) -> dict[str, Any]:
    base_output = translation_result.get("model_outputs", {})
    output_parameters = translation_result.get("output_parameters", [])
    assumptions = translation_result.get("assumptions", [])
    confidence_summary = translation_result.get("confidence_summary", {})

    assumption_ids = {
        str(item.get("assumption_id"))
        for item in assumptions
        if isinstance(item, dict) and item.get("assumption_id") is not None
    }

    def _find_parameter(parameter_path: str) -> dict[str, Any] | None:
        for parameter in output_parameters:
            if (
                isinstance(parameter, dict)
                and str(parameter.get("parameter_path", "")).strip() == parameter_path
            ):
                return parameter
        return None

    def _deep_get(mapping: dict[str, Any], dotted_path: str) -> Any:
        current: Any = mapping
        for part in dotted_path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def _deep_set(mapping: dict[str, Any], dotted_path: str, value: Any) -> None:
        current = mapping
        parts = dotted_path.split(".")
        for part in parts[:-1]:
            next_value = current.get(part)
            if not isinstance(next_value, dict):
                next_value = {}
                current[part] = next_value
            current = next_value
        current[parts[-1]] = value

    def _build_change(parameter_path: str, new_value: Any, reason: str) -> dict[str, Any]:
        parameter = _find_parameter(parameter_path) or {}
        baseline_value = _deep_get(base_output, parameter_path)
        delta = None

        if isinstance(baseline_value, (int, float)) and isinstance(new_value, (int, float)):
            delta = float(new_value) - float(baseline_value)

        provenance_ref = parameter.get("provenance_ref")
        assumption_refs: list[str] = []
        if isinstance(provenance_ref, str) and provenance_ref in assumption_ids:
            assumption_refs.append(provenance_ref)
        if isinstance(provenance_ref, list):
            assumption_refs.extend(
                str(item)
                for item in provenance_ref
                if str(item) in assumption_ids
            )

        return {
            "parameter_path": parameter_path,
            "baseline_parameter_path": parameter_path,
            "baseline_value": baseline_value,
            "new_value": new_value,
            "delta": delta,
            "units": parameter.get("units"),
            "change_reason": reason,
            "dependency_paths": list(parameter.get("dependency_paths", [])),
            "source_field_paths": list(parameter.get("source_field_paths", [])),
            "supporting_snippet_ids": list(parameter.get("supporting_snippet_ids", [])),
            "assumption_ids": assumption_refs,
        }

    def _variant(
        label: str,
        description: str,
        changes: list[tuple[str, Any, str]],
        confidence: str,
        scenario_method: str,
    ) -> dict[str, Any]:
        outputs = deepcopy(base_output)
        changed_parameters: list[dict[str, Any]] = []

        for parameter_path, new_value, reason in changes:
            _deep_set(outputs, parameter_path, new_value)
            changed_parameters.append(_build_change(parameter_path, new_value, reason))

        metadata = {
            "source_confidence_summary": dict(confidence_summary),
            "parameter_count": len(output_parameters),
            "changed_parameter_count": len(changed_parameters),
            "assumption_heavy_change_count": sum(
                1 for item in changed_parameters if item["assumption_ids"]
            ),
            "scenario_method": scenario_method,
        }

        return {
            "label": label,
            "description": description,
            "outputs": outputs,
            "confidence": confidence,
            "metadata": metadata,
            "changed_parameters": changed_parameters,
        }

    typical = _variant(
        label="Typical",
        description="Best estimate based on currently governed evidence and assumptions.",
        changes=[],
        confidence="LOW",
        scenario_method="baseline_copy",
    )

    conservative = _variant(
        label="Conservative",
        description="Risk-sensitive bounded case with more conservative ramping assumptions.",
        changes=[
            (
                "ramping.max_ramp_up_mw_per_min",
                0.5,
                "Applied conservative downward ramp bound.",
            ),
            (
                "ramping.max_ramp_down_mw_per_min",
                0.5,
                "Applied conservative downward ramp bound.",
            ),
        ],
        confidence="LOW",
        scenario_method="bounded_adjustment",
    )

    best_case = _variant(
        label="Best-case",
        description="Optimistic but bounded case for governed scenario exploration.",
        changes=[
            (
                "ramping.max_ramp_up_mw_per_min",
                1.5,
                "Applied optimistic upward ramp bound.",
            ),
            (
                "ramping.max_ramp_down_mw_per_min",
                1.5,
                "Applied optimistic upward ramp bound.",
            ),
        ],
        confidence="LOW",
        scenario_method="bounded_adjustment",
    )

    scenarios = {
        "Typical": typical,
        "Conservative": conservative,
        "Best-case": best_case,
    }
    scenario_variants = [typical, conservative, best_case]

    return {
        "run_id": context.run_id,
        "status": "SCENARIOS_GENERATED",
        "generated_at": utc_now_iso(),
        "scenario_variants": scenario_variants,
        "scenarios": scenarios,
        "warnings": [],
        "errors": [],
    }


def default_export(
    context: RunContext,
    canonical_state_result: dict[str, Any],
    validation_result: dict[str, Any],
    translation_result: dict[str, Any],
    scenario_result: dict[str, Any],
    ingestion_result: dict[str, Any] | None = None,
    extraction_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
    retrieval_result: dict[str, Any] | None = None,
    interview_result: dict[str, Any] | None = None,
    gap_resolution_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ = extraction_result
    _ = normalization_result

    retrieval_result, interview_result = resolve_gap_resolution_stage_inputs(
        retrieval_result=retrieval_result,
        interview_result=interview_result,
        gap_resolution_result=gap_resolution_result,
    )

    exports_dir = context.run_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    canonical_state = validation_result.get("canonical_state") or canonical_state_result.get("canonical_state", {})
    validation_report = validation_result.get("validation_report", {})
    scenarios = scenario_result.get("scenarios", {})
    translated_outputs = translation_result.get("model_outputs", {})
    intake_summary = build_intake_summary(ingestion_result)

    canonical_state_path = exports_dir / "canonical_facility_state.json"
    translated_parameters_path = exports_dir / "translated_parameters.json"
    scenario_path = exports_dir / "scenario_set.json"
    planner_packet_path = exports_dir / "planner_packet.md"
    manifest_path = exports_dir / "run_manifest.json"

    safe_write_json(canonical_state_path, make_serializable(canonical_state))
    safe_write_json(translated_parameters_path, make_serializable(translation_result))
    safe_write_json(scenario_path, make_serializable(scenario_result))

    report_lines = [
        "# GridSenpAI Planner Packet",
        "",
        f"**Run ID:** {context.run_id}",
        f"**Generated:** {utc_now_iso()}",
        "",
        "## Summary",
        f"- Artifacts ingested: {intake_summary['artifact_count']}",
        f"- Intake complete: {'Yes' if intake_summary['complete'] else 'No'}",
        f"- Missing required artifact categories: {intake_summary['missing_required_count']}",
        f"- Entities extracted: {len((canonical_state or {}).get('entities', []))}",
        f"- Evidence snippets: {len((canonical_state or {}).get('evidence_snippets', []))}",
        f"- Output parameters: {len(translation_result.get('output_parameters', []))}",
        f"- Scenarios generated: {len(scenarios)}",
        "",
        "## Intake Status",
        f"- Intake session status: {intake_summary['status']}",
        f"- Intake session path: {intake_summary['session_path'] or 'N/A'}",
        f"- Required artifact categories: {intake_summary['required_artifact_count']}",
        f"- Uploaded required artifact matches: {intake_summary['uploaded_artifact_count']}",
    ]

    missing_labels = intake_summary.get("missing_required_labels", [])
    if missing_labels:
        report_lines.append("- Missing required categories: " + ", ".join(missing_labels))
    else:
        report_lines.append("- Missing required categories: None")

    report_lines.extend(
        [
            "",
            "## Validation",
            f"- Status: {validation_result.get('status', 'UNKNOWN')}",
            f"- Errors: {len(validation_report.get('errors', []))}",
            f"- Warnings: {len(validation_report.get('warnings', []))}",
            f"- Missing fields: {len(validation_report.get('missing_fields', []))}",
            f"- Conflicts: {len(validation_report.get('conflicts', []))}",
            "",
            "## Supporting Evidence Snippets",
        ]
    )

    evidence_snippets = (canonical_state or {}).get("evidence_snippets", [])
    if evidence_snippets:
        for snippet in evidence_snippets:
            snippet_id = str(snippet.get("snippet_id", "unknown"))
            text = str(snippet.get("text", "")).strip()
            source_ref = str(snippet.get("source_ref", "")).strip()
            report_lines.append(f"- `{snippet_id}` | {source_ref} | {text}")
    else:
        report_lines.append("- None available.")

    report_lines.extend(
        [
            "",
            "## Translated Output Keys",
        ]
    )

    for top_level_key in translated_outputs.keys():
        report_lines.append(f"- {top_level_key}")

    safe_write_text(planner_packet_path, "\n".join(report_lines))

    manifest = {
        "run_id": context.run_id,
        "generated_at": utc_now_iso(),
        "status": "EXPORTED",
        "intake_summary": intake_summary,
        "exports": {
            "canonical_facility_state_json": str(canonical_state_path),
            "translated_parameters_json": str(translated_parameters_path),
            "scenario_set_json": str(scenario_path),
            "planner_packet_md": str(planner_packet_path),
        },
    }
    safe_write_json(manifest_path, manifest)

    return {
        "run_id": context.run_id,
        "status": "EXPORTED",
        "intake_summary": intake_summary,
        "export_manifest": manifest,
        "exported_at": utc_now_iso(),
        "warnings": [],
        "errors": [],
    }


def _summarize_validation_substages(validation_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validation_report = validation_result.get("validation_report", {})
    if not isinstance(validation_report, dict):
        validation_report = {}

    canonical_state = validation_result.get("canonical_state", {})
    if not isinstance(canonical_state, dict):
        canonical_state = {}

    engineering_validation = validation_report.get("engineering_validation", {})
    if not isinstance(engineering_validation, dict):
        engineering_validation = {}

    calibration_summary = validation_report.get("calibration_summary", {})
    if not isinstance(calibration_summary, dict):
        calibration_summary = {}

    calibration_datasets = canonical_state.get("calibration_datasets", [])
    if not isinstance(calibration_datasets, list):
        calibration_datasets = []

    calibration_records = canonical_state.get("calibration_records", [])
    if not isinstance(calibration_records, list):
        calibration_records = []

    reconciliation_records = canonical_state.get("reconciliation_records", [])
    if not isinstance(reconciliation_records, list):
        reconciliation_records = []

    dataset_ids = [
        str(item.get("dataset_id", "")).strip()
        for item in calibration_datasets
        if isinstance(item, dict) and str(item.get("dataset_id", "")).strip()
    ]

    engineering_summary = engineering_validation.get("summary", {})
    if not isinstance(engineering_summary, dict):
        engineering_summary = {}

    calibration_summary_details = calibration_summary.get("summary", {})
    if not isinstance(calibration_summary_details, dict):
        calibration_summary_details = {}

    return {
        "engineering_validation": {
            "status": str(engineering_validation.get("status", "NOT_RUN")).strip() or "NOT_RUN",
            "summary": engineering_summary,
            "review_flag_count": int(engineering_validation.get("review_flag_count", 0) or 0),
            "error_count": int(engineering_validation.get("error_count", 0) or 0),
            "warning_count": int(engineering_validation.get("warning_count", 0) or 0),
            "info_count": int(engineering_validation.get("info_count", 0) or 0),
        },
        "calibration_dataset": {
            "status": "CALIBRATION_DATASETS_READY" if calibration_datasets else "NO_CALIBRATION_DATASETS",
            "summary": {
                "dataset_count": len(calibration_datasets),
                "dataset_ids": dataset_ids,
            },
            "calibration_datasets": calibration_datasets,
        },
        "calibration_comparison": {
            "status": str(calibration_summary.get("status", "NOT_RUN")).strip() or "NOT_RUN",
            "summary": calibration_summary_details,
            "calibration_record_count": len(calibration_records),
            "reconciliation_record_count": len(reconciliation_records),
            "calibration_records": calibration_records,
            "reconciliation_records": reconciliation_records,
        },
    }


class GridSenpAIPipeline:
    STAGE_CONTRACTS: dict[str, type[Any]] = {
        "ingestion": IngestionStageResult,
        "extraction": ExtractionStageResult,
        "retrieval": RetrievalStageResult,
        "interview": InterviewStageResult,
        "normalization": NormalizationStageResult,
        "canonical_state": CanonicalStateStageResult,
        "validation": ValidationStageResult,
        "translation": TranslationStageResult,
        "scenarios": ScenarioStageResult,
        "export": ExportStageResult,
    }

    def __init__(self, context: RunContext) -> None:
        from shared.security.permissions import Role
        from shared.security.run_access_registry import RunAccessRegistry

        self.context = context

        if self.context.actor is None:
            self.context.actor = Actor(
                actor_id="local_cli_engineer",
                role=Role.ENGINEER,
                display_name="Local CLI Engineer",
                email=None,
            )

        if self.context.run_access_registry is None:
            run_access_registry = RunAccessRegistry()
            run_access_registry.register_run(self.context.run_id, self.context.actor)
            self.context.run_access_registry = run_access_registry

        self.service_resolver = ServiceResolver()
        self.canonical_state: CanonicalFacilityState = build_empty_canonical_state(
            context.run_id
        )
        self.run_governance = initialize_run_governance(context)
        self.audit_logger = initialize_audit_logger(context)
        self.replay_manager = None
        self.stage_execution_metrics: dict[str, dict[str, Any]] = {}
        self.substage_execution_metrics: dict[str, dict[str, dict[str, Any]]] = {}

        if (
            self.context.execution_mode == "REPLAY"
            and self.context.replay_source_run_id
            and self.context.replay_stage_boundary
        ):
            self.replay_manager = initialize_replay_manager(
                context=self.context,
                replay_source_run_id=self.context.replay_source_run_id,
                replay_stage_boundary=self.context.replay_stage_boundary,
            )

    def _canonical_state_path(self) -> Path:
        return self.context.run_dir / "state" / "canonical_facility_state.json"

    def _pipeline_summary_path(self) -> Path:
        return self.context.run_dir / "pipeline_summary.json"

    def _persist_stage_output(self, stage_name: str, payload: dict[str, Any]) -> None:
        stage_dir = self.context.run_dir / "stages"
        stage_dir.mkdir(parents=True, exist_ok=True)
        writer = safe_write_compact_json if stage_name in {"validation", "canonical_state"} else safe_write_json
        writer(stage_dir / f"{stage_name}.json", make_serializable(payload))

    def _persist_substage_output(
        self,
        stage_name: str,
        substage_name: str,
        payload: dict[str, Any],
    ) -> None:
        stage_dir = self.context.run_dir / "stages"
        stage_dir.mkdir(parents=True, exist_ok=True)
        writer = safe_write_compact_json if stage_name in {"validation", "canonical_state", "export"} else safe_write_json
        writer(
            stage_dir / f"{stage_name}__{substage_name}.json",
            make_serializable(payload),
        )

    def _persist_canonical_state_payload(self, canonical_state: dict[str, Any]) -> None:
        canonical_dir = self.context.run_dir / "state"
        canonical_dir.mkdir(parents=True, exist_ok=True)
        safe_write_compact_json(
            canonical_dir / "canonical_facility_state.json",
            make_serializable(canonical_state),
        )
        self.canonical_state = CanonicalFacilityState.from_dict(canonical_state)

    def _snapshot_current_state(self, label: str) -> None:
        self.run_governance.snapshot_canonical_state(
            label=label,
            canonical_state=self.canonical_state.to_dict(),
        )

    def _coerce_stage_result(self, stage_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        contract_cls = self.STAGE_CONTRACTS.get(stage_name)
        if contract_cls is None:
            return payload

        if not is_dataclass(contract_cls):
            return payload

        allowed_field_names = {field.name for field in fields(contract_cls)}
        filtered_payload = {
            key: value for key, value in payload.items() if key in allowed_field_names
        }

        try:
            contract = cast(SupportsToDict, contract_cls(**filtered_payload))
        except TypeError as exc:
            raise TypeError(
                f"Stage '{stage_name}' returned payload that does not match "
                f"contract '{contract_cls.__name__}': {exc}"
            ) from exc

        merged_payload = dict(payload)
        merged_payload.update(contract.to_dict())
        return merged_payload

    def _normalize_stage_output(self, raw_result: Any, stage_name: str) -> dict[str, Any]:
        if isinstance(raw_result, dict):
            return raw_result

        to_dict_method = getattr(raw_result, "to_dict", None)
        if callable(to_dict_method):
            result = to_dict_method()
            if not isinstance(result, dict):
                raise TypeError(
                    f"Stage '{stage_name}' to_dict() returned "
                    f"{type(result).__name__}, expected dict."
                )
            return result

        if is_dataclass(raw_result) and not isinstance(raw_result, type):
            result = asdict(raw_result)
            if not isinstance(result, dict):
                raise TypeError(
                    f"Stage '{stage_name}' dataclass serialization returned "
                    f"{type(result).__name__}, expected dict."
                )
            return result

        raise TypeError(
            f"Stage '{stage_name}' returned {type(raw_result).__name__}, expected dict "
            "or dataclass-like object with to_dict()."
        )

    def _invoke_callable(self, callable_to_use: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
        signature = inspect.signature(callable_to_use)
        parameters = signature.parameters

        accepts_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        if accepts_var_kwargs:
            return callable_to_use(**kwargs)

        allowed_kwargs = {
            name: value
            for name, value in kwargs.items()
            if name in parameters
        }
        return callable_to_use(**allowed_kwargs)

    def _run_stage(
        self,
        stage_name: str,
        default_callable: Callable[..., dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        LOGGER.info("Starting stage: %s", stage_name)
        stage_started_at = utc_now_iso()
        stage_started_perf = time.perf_counter()
        self.audit_logger.log_stage_start(
            stage_name=stage_name,
            metadata={
                "execution_mode": self.context.execution_mode,
            },
        )

        custom_callable = self.service_resolver.resolve(stage_name)
        callable_to_use = custom_callable or default_callable

        try:
            raw_result = self._invoke_callable(callable_to_use, kwargs)
            result = self._normalize_stage_output(raw_result, stage_name)
            result = self._coerce_stage_result(stage_name, result)
        except Exception as exc:
            traceback_text = traceback.format_exc()
            LOGGER.error("Stage '%s' failed: %s", stage_name, exc)
            LOGGER.debug(traceback_text)
            self.audit_logger.log_stage_failure(
                stage_name=stage_name,
                error=str(exc),
                traceback_text=traceback_text,
                metadata={
                    "execution_mode": self.context.execution_mode,
                },
            )
            raise

        duration_ms = max(0, int((time.perf_counter() - stage_started_perf) * 1000))
        self.stage_execution_metrics[stage_name] = {
            "status": str(result.get("status", "COMPLETED")),
            "mode": "executed",
            "started_at": stage_started_at,
            "completed_at": utc_now_iso(),
            "duration_ms": duration_ms,
            "warning_count": len(result.get("warnings", [])) if isinstance(result.get("warnings"), list) else 0,
            "error_count": len(result.get("errors", [])) if isinstance(result.get("errors"), list) else 0,
        }

        self._persist_stage_output(stage_name, result)
        self.audit_logger.log_stage_complete(
            stage_name=stage_name,
            status=str(result.get("status", "COMPLETED")),
            metadata={
                "warning_count": len(result.get("warnings", [])) if isinstance(result.get("warnings"), list) else 0,
                "error_count": len(result.get("errors", [])) if isinstance(result.get("errors"), list) else 0,
            },
        )
        LOGGER.info("Completed stage: %s", stage_name)
        return result

    def _run_internal_substage(
        self,
        stage_name: str,
        substage_name: str,
        callable_to_use: Callable[..., Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        qualified_name = f"{stage_name}::{substage_name}"
        LOGGER.info("Starting internal substage: %s", qualified_name)
        substage_started_at = utc_now_iso()
        substage_started_perf = time.perf_counter()
        self.audit_logger.log_substage_start(
            stage_name=stage_name,
            substage_name=substage_name,
            metadata={
                "qualified_name": qualified_name,
            },
        )

        try:
            raw_result = self._invoke_callable(callable_to_use, kwargs)
            result = self._normalize_stage_output(raw_result, qualified_name)
        except Exception as exc:
            traceback_text = traceback.format_exc()
            LOGGER.error("Internal substage '%s' failed: %s", qualified_name, exc)
            LOGGER.debug(traceback_text)
            self.audit_logger.log_substage_failure(
                stage_name=stage_name,
                substage_name=substage_name,
                error=str(exc),
                traceback_text=traceback_text,
                metadata={
                    "qualified_name": qualified_name,
                },
            )
            raise

        duration_ms = max(0, int((time.perf_counter() - substage_started_perf) * 1000))
        self.substage_execution_metrics.setdefault(stage_name, {})[substage_name] = {
            "status": str(result.get("status", "COMPLETED")),
            "mode": "executed",
            "started_at": substage_started_at,
            "completed_at": utc_now_iso(),
            "duration_ms": duration_ms,
            "warning_count": len(result.get("warnings", [])) if isinstance(result.get("warnings"), list) else 0,
            "error_count": len(result.get("errors", [])) if isinstance(result.get("errors"), list) else 0,
        }

        self._persist_substage_output(stage_name, substage_name, result)
        self.audit_logger.log_substage_complete(
            stage_name=stage_name,
            substage_name=substage_name,
            status=str(result.get("status", "COMPLETED")),
            metadata={
                "qualified_name": qualified_name,
                "warning_count": len(result.get("warnings", [])) if isinstance(result.get("warnings"), list) else 0,
                "error_count": len(result.get("errors", [])) if isinstance(result.get("errors"), list) else 0,
            },
        )
        LOGGER.info("Completed internal substage: %s", qualified_name)
        return result

    def _reuse_or_run_gap_resolution_substage(
        self,
        qualified_substage_name: str,
        substage_name: str,
        callable_to_use: Callable[..., Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self.replay_manager and self.replay_manager.should_reuse_gap_resolution_substage(qualified_substage_name):
            LOGGER.info("Reusing replay gap-resolution substage output: %s", qualified_substage_name)
            persisted_result = self.replay_manager.get_reused_gap_resolution_substage_output(qualified_substage_name)
            rebased_result = _rebase_run_id_in_payload(
                persisted_result,
                self.context.replay_source_run_id,
                self.context.run_id,
            )
            self._persist_substage_output("gap_resolution", substage_name, rebased_result)
            self.substage_execution_metrics.setdefault("gap_resolution", {})[substage_name] = {
                "status": str(rebased_result.get("status", "REUSED")),
                "mode": "reused",
                "started_at": utc_now_iso(),
                "completed_at": utc_now_iso(),
                "duration_ms": 0,
                "warning_count": len(rebased_result.get("warnings", [])) if isinstance(rebased_result.get("warnings"), list) else 0,
                "error_count": len(rebased_result.get("errors", [])) if isinstance(rebased_result.get("errors"), list) else 0,
            }
            return rebased_result

        return self._run_internal_substage(
            "gap_resolution",
            substage_name,
            callable_to_use,
            **kwargs,
        )

    def _run_extraction_subpipeline(
        self,
        ingestion_result: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        document_parser_result = self._run_internal_substage(
            "extraction",
            "document_parser",
            default_document_parser_service,
            context=self.context,
            ingestion_result=ingestion_result,
        )

        layout_analysis_result = self._run_internal_substage(
            "extraction",
            "layout_analysis",
            default_layout_analysis_service,
            context=self.context,
            document_parser_result=document_parser_result,
        )

        ocr_result = self._run_internal_substage(
            "extraction",
            "ocr",
            default_ocr_service,
            context=self.context,
            document_parser_result=document_parser_result,
            layout_analysis_result=layout_analysis_result,
        )

        return document_parser_result, layout_analysis_result, ocr_result

    def _persist_validation_substages(self, validation_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        substages = _summarize_validation_substages(validation_result)

        for substage_name, payload in substages.items():
            self._persist_substage_output("validation", substage_name, payload)

        return substages

    def _build_gap_resolution_stage_result(
        self,
        interview_result: dict[str, Any],
        retrieval_result: dict[str, Any],
    ) -> dict[str, Any]:
        interview_warnings = interview_result.get("warnings", [])
        retrieval_warnings = retrieval_result.get("warnings", [])

        warnings: list[str] = []
        if isinstance(interview_warnings, list):
            warnings.extend(str(item) for item in interview_warnings if str(item).strip())
        if isinstance(retrieval_warnings, list):
            warnings.extend(str(item) for item in retrieval_warnings if str(item).strip())

        interview_workflow_state = _interview_workflow_state(interview_result)
        waiting_for_interview = _interview_requires_user_action(interview_result)
        status = "GAP_RESOLUTION_WAITING_FOR_INTERVIEW" if waiting_for_interview else "GAP_RESOLUTION_COMPLETE"
        if waiting_for_interview:
            warnings.append(
                "Gap resolution paused: applicant interview questions are waiting for answer, skip, or defer action."
            )

        return {
            "run_id": self.context.run_id,
            "status": status,
            "resolved_at": utc_now_iso(),
            "interview": make_serializable(interview_result),
            "retrieval": make_serializable(retrieval_result),
            "warnings": warnings,
            "workflow_state": {
                "interview": make_serializable(interview_workflow_state),
                "ready_for_downstream": not waiting_for_interview,
                "requires_user_action": waiting_for_interview,
            },
            "summary": {
                "interview_status": str(interview_result.get("status", "NOT_RUN")),
                "interview_workflow_state": str(interview_workflow_state.get("state", "INTERVIEW_UNKNOWN")),
                "interview_requires_user_action": waiting_for_interview,
                "interview_remaining_question_count": _safe_int(interview_workflow_state.get("remaining_question_count", 0)),
                "retrieval_status": str(retrieval_result.get("status", "NOT_RUN")),
                "clarification_count": len(interview_result.get("clarifications", [])) if isinstance(interview_result.get("clarifications"), list) else 0,
                "retrieval_snippet_count": len(retrieval_result.get("snippets", [])) if isinstance(retrieval_result.get("snippets"), list) else 0,
            },
        }

    def _reuse_or_run_stage(
        self,
        stage_name: str,
        default_callable: Callable[..., dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self.replay_manager and self.replay_manager.should_reuse_stage(stage_name):
            LOGGER.info("Reusing replay stage output: %s", stage_name)
            persisted_result = self.replay_manager.get_reused_stage_output(stage_name)
            self._persist_stage_output(stage_name, persisted_result)

            rebased_result = _rebase_run_id_in_payload(
                persisted_result,
                self.context.replay_source_run_id,
                self.context.run_id,
            )

            if stage_name in {"canonical_state", "validation"}:
                canonical_state_payload = rebased_result.get("canonical_state", {})
                if isinstance(canonical_state_payload, dict) and canonical_state_payload:
                    self._persist_canonical_state_payload(canonical_state_payload)

            self.stage_execution_metrics[stage_name] = {
                "status": str(rebased_result.get("status", "REUSED")),
                "mode": "reused",
                "started_at": utc_now_iso(),
                "completed_at": utc_now_iso(),
                "duration_ms": 0,
                "warning_count": len(rebased_result.get("warnings", [])) if isinstance(rebased_result.get("warnings"), list) else 0,
                "error_count": len(rebased_result.get("errors", [])) if isinstance(rebased_result.get("errors"), list) else 0,
            }

            self.audit_logger.log_stage_reused(
                stage_name=stage_name,
                metadata={
                    "replay_source_run_id": self.context.replay_source_run_id,
                    "replay_stage_boundary": self.context.replay_stage_boundary,
                    "status": str(rebased_result.get("status", "REUSED")),
                },
            )
            return rebased_result

        return self._run_stage(stage_name, default_callable, **kwargs)

    def _build_stage_timing_summary(self) -> dict[str, Any]:
        stages = {name: dict(payload) for name, payload in self.stage_execution_metrics.items()}
        substages = {stage: {sub: dict(payload) for sub, payload in payloads.items()} for stage, payloads in self.substage_execution_metrics.items()}
        total_stage_duration_ms = sum(int(payload.get("duration_ms", 0) or 0) for payload in stages.values())
        return {
            "total_stage_duration_ms": total_stage_duration_ms,
            "stages": stages,
            "substages": substages,
        }

    def _build_run_observability_summary(
        self,
        *,
        extraction_result: dict[str, Any] | None,
        retrieval_result: dict[str, Any] | None,
        interview_result: dict[str, Any] | None,
        canonical_state: dict[str, Any] | None,
        validation_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        runtime_observability = summarize_runtime_observability(
            extraction_result,
            retrieval_result,
            interview_result,
            canonical_state,
            validation_result,
        )
        return {
            "stage_timing": self._build_stage_timing_summary(),
            "runtime_metrics": runtime_observability,
        }

    def run(self) -> dict[str, Any]:
        LOGGER.info("Beginning pipeline run: %s", self.context.run_id)

        # --- AUTHORIZATION ENFORCEMENT ---
        if self.context.actor is None:
            raise RuntimeError("Pipeline execution requires an authenticated actor.")

        from services.authorization_service.service import AuthorizationService
        from shared.security.models import AuthorizationRequest
        from shared.security.permissions import Permission

        auth_service = AuthorizationService(
            audit_service=self.audit_logger,
            run_access_registry=getattr(self.context, "run_access_registry", None),
        )

        auth_service.require(
            AuthorizationRequest(
                actor=self.context.actor,
                permission=Permission.EXECUTE_PIPELINE,
                resource_type="pipeline_run",
                resource_id=self.context.run_id,
            )
        )
        # --- END AUTHORIZATION ENFORCEMENT ---

        self.context.run_dir.mkdir(parents=True, exist_ok=True)

        safe_write_json(
            self.context.run_dir / "run_context.json",
            make_serializable(self.context.to_dict()),
        )

        self.audit_logger.log_pipeline_start(
            metadata={
                "execution_mode": self.context.execution_mode,
                "parent_run_id": self.context.parent_run_id,
                "replay_source_run_id": self.context.replay_source_run_id,
                "replay_stage_boundary": self.context.replay_stage_boundary,
                "input_dir": str(self.context.input_dir),
                "output_dir": str(self.context.output_dir),
                "actor_id": self.context.actor.actor_id,
                "actor_role": self.context.actor.role.value,
            }
        )

        if self.replay_manager:
            self.replay_manager.persist_plan()
            source_state = self.replay_manager.source_canonical_state()
            if source_state:
                rebased_source_state = _rebase_run_id_in_payload(
                    source_state,
                    self.context.replay_source_run_id,
                    self.context.run_id,
                )
                if isinstance(rebased_source_state, dict):
                    self._persist_canonical_state_payload(rebased_source_state)
                else:
                    self._persist_canonical_state_payload(self.canonical_state.to_dict())
                self._snapshot_current_state("replay_initialized")
            else:
                self._persist_canonical_state_payload(self.canonical_state.to_dict())
                self._snapshot_current_state("replay_initialized")
        else:
            self._persist_canonical_state_payload(self.canonical_state.to_dict())
            self._snapshot_current_state("initial")

        ingestion_result = self._reuse_or_run_stage(
            "ingestion",
            default_ingestion,
            context=self.context,
        )

        document_parser_result: dict[str, Any] | None = None
        layout_analysis_result: dict[str, Any] | None = None
        ocr_result: dict[str, Any] | None = None

        extraction_is_reused = bool(
            self.replay_manager and self.replay_manager.should_reuse_stage("extraction")
        )

        if not extraction_is_reused:
            (
                document_parser_result,
                layout_analysis_result,
                ocr_result,
            ) = self._run_extraction_subpipeline(ingestion_result)

        extraction_result = self._reuse_or_run_stage(
            "extraction",
            default_extraction,
            context=self.context,
            ingestion_result=ingestion_result,
            document_parser_result=document_parser_result,
            layout_analysis_result=layout_analysis_result,
            ocr_result=ocr_result,
        )

        normalization_result = self._reuse_or_run_stage(
            "normalization",
            default_normalization,
            context=self.context,
            extraction_result=extraction_result,
            interview_result=None,
            retrieval_result=None,
        )

        project_identity = resolve_project_identity(
            run_id=self.context.run_id,
            replay_source_run_id=self.context.replay_source_run_id,
            parent_run_id=self.context.parent_run_id,
            existing_project_name=self.context.config.project_name,
            normalization_result=normalization_result,
            extraction_result=extraction_result,
        )
        if project_identity.get("project_name"):
            self.context.config.project_name = str(project_identity.get("project_name"))
        if project_identity.get("project_id"):
            self.context.config.project_id = str(project_identity.get("project_id"))
        if project_identity.get("project_number"):
            self.context.config.project_number = str(project_identity.get("project_number"))
        if project_identity.get("applicant"):
            self.context.config.applicant = str(project_identity.get("applicant"))
        self.run_governance.update_project_identity(project_identity)
        safe_write_json(
            self.context.run_dir / "project_identity.json",
            make_serializable(project_identity),
        )
        safe_write_json(
            self.context.run_dir / "run_context.json",
            make_serializable(self.context.to_dict()),
        )

        retrieval_result = self._reuse_or_run_gap_resolution_substage(
            GAP_RESOLUTION_RETRIEVAL_STAGE,
            "retrieval",
            default_retrieval,
            context=self.context,
            normalization_result=normalization_result,
            extraction_result=extraction_result,
        )

        interview_result = self._reuse_or_run_gap_resolution_substage(
            GAP_RESOLUTION_INTERVIEW_STAGE,
            "interview",
            default_interview,
            context=self.context,
            extraction_result=extraction_result,
            normalization_result=normalization_result,
            retrieval_result=retrieval_result,
        )

        gap_resolution_result = self._build_gap_resolution_stage_result(
            interview_result=interview_result,
            retrieval_result=retrieval_result,
        )
        self._persist_stage_output("gap_resolution", gap_resolution_result)

        if _interview_requires_user_action(interview_result):
            interview_workflow_state = _interview_workflow_state(interview_result)
            pipeline_summary = {
                "run_id": self.context.run_id,
                "completed_at": utc_now_iso(),
                "status": "PIPELINE_WAITING_FOR_INTERVIEW",
                "execution_mode": self.context.execution_mode,
                "parent_run_id": self.context.parent_run_id,
                "replay_source_run_id": self.context.replay_source_run_id,
                "replay_stage_boundary": self.context.replay_stage_boundary,
                "project_identity": make_serializable(project_identity),
                "public_stage_order": list(PUBLIC_PIPELINE_STAGE_ORDER),
                "gap_resolution_substage_order": list(GAP_RESOLUTION_SUBSTAGE_ORDER),
                "runtime_contract": build_runtime_contract_summary(),
                "stage_status": {
                    "ingestion": ingestion_result.get("status"),
                    "extraction": extraction_result.get("status"),
                    "normalization": normalization_result.get("status"),
                    "gap_resolution": gap_resolution_result.get("status"),
                    "validation": "SKIPPED_WAITING_FOR_INTERVIEW",
                    "canonical_state": "SKIPPED_WAITING_FOR_INTERVIEW",
                    "canonical_state::adjudication": "SKIPPED_WAITING_FOR_INTERVIEW",
                    "translation": "SKIPPED_WAITING_FOR_INTERVIEW",
                    "scenarios": "SKIPPED_WAITING_FOR_INTERVIEW",
                    "export": "SKIPPED_WAITING_FOR_INTERVIEW",
                },
                "gap_resolution_substages": {
                    substage_name: payload.get("status")
                    for substage_name, payload in {
                        GAP_RESOLUTION_RETRIEVAL_STAGE: retrieval_result,
                        GAP_RESOLUTION_INTERVIEW_STAGE: interview_result,
                    }.items()
                },
                "interview_workflow_state": make_serializable(interview_workflow_state),
                "next_action": "APPLICANT_INTERVIEW_REQUIRED",
                "planner_readiness": "NOT_READY",
                "governed_run_summary": build_governed_run_summary(
                    canonical_state=extraction_result.get("canonical_state", {}),
                    validation_result={},
                    retrieval_result=retrieval_result,
                    interview_result=interview_result,
                    gap_resolution_result=gap_resolution_result,
                    translation_result={},
                    scenario_result={},
                    export_result=None,
                    extraction_result=extraction_result,
                ),
                "observability_summary": self._build_run_observability_summary(
                    extraction_result=extraction_result,
                    retrieval_result=retrieval_result,
                    interview_result=interview_result,
                    canonical_state=extraction_result.get("canonical_state", {}),
                    validation_result={},
                ),
                "canonical_state_path": str(self._canonical_state_path()),
                "run_governance": self.run_governance.finalize(
                    status="PIPELINE_WAITING_FOR_INTERVIEW",
                    canonical_state_path=self._canonical_state_path(),
                    pipeline_summary_path=self._pipeline_summary_path(),
                    export_manifest_path=None,
                    notes=[
                        "Pipeline paused before validation/canonicalization/translation/scenarios/export because applicant interview action is required."
                    ],
                ),
            }

            safe_write_json(
                self._pipeline_summary_path(),
                make_serializable(pipeline_summary),
            )

            self.audit_logger.log_pipeline_complete(
                metadata={
                    "pipeline_summary_path": str(self._pipeline_summary_path()),
                    "canonical_state_path": str(self._canonical_state_path()),
                    "status": "PIPELINE_WAITING_FOR_INTERVIEW",
                    "project_identity": make_serializable(project_identity),
                    "next_action": "APPLICANT_INTERVIEW_REQUIRED",
                }
            )

            LOGGER.info("Pipeline paused waiting for applicant interview: %s", self.context.run_id)
            return pipeline_summary

        validation_result = self._reuse_or_run_stage(
            "validation",
            default_validation_service,
            context=self.context,
            ingestion_result=ingestion_result,
            extraction_result=extraction_result,
            interview_result=interview_result,
            normalization_result=normalization_result,
            retrieval_result=retrieval_result,
            gap_resolution_result=gap_resolution_result,
        )

        validation_substages = self._persist_validation_substages(validation_result)
        validation_status = str(validation_result.get("status", "")).strip().upper()

        if validation_status == "VALIDATION_FAILED":
            LOGGER.error(
                "Validation failed. Downstream modeling stages will not execute final outputs for run %s.",
                self.context.run_id,
            )
            draft_export_result: dict[str, Any] | None = None
            draft_canonical_state_result: dict[str, Any] | None = None
            draft_translation_result: dict[str, Any] | None = None
            draft_scenario_result: dict[str, Any] | None = None
            if _interview_allows_draft_outputs(interview_result):
                LOGGER.info(
                    "Validation failed after applicant interview skip/defer; generating draft/blocked planner-facing artifacts for run %s.",
                    self.context.run_id,
                )
                draft_canonical_state = validation_result.get("canonical_state", {})
                draft_canonical_state_result = {
                    "run_id": self.context.run_id,
                    "status": "DRAFT_CANONICAL_STATE_FROM_FAILED_VALIDATION",
                    "canonical_state": draft_canonical_state if isinstance(draft_canonical_state, dict) else {},
                }
                draft_translation_result = {
                    "run_id": self.context.run_id,
                    "status": "SKIPPED_DRAFT_VALIDATION_FAILED",
                    "output_parameters": [],
                    "model_outputs": {},
                    "assumptions": [
                        "Draft planner artifacts were generated after applicant interview skip/defer and validation failure; translated model parameters are not final-ready."
                    ],
                    "confidence_summary": {},
                    "schema_validation": {"status": "SKIPPED_DRAFT_VALIDATION_FAILED"},
                    "translation_source_contract": {
                        "primary_source": "validation_failed_draft",
                        "legacy_translation_fallback_used": False,
                        "planner_ledger_row_count": 0,
                    },
                }
                draft_scenario_result = {
                    "run_id": self.context.run_id,
                    "status": "SKIPPED_DRAFT_VALIDATION_FAILED",
                    "scenarios": {},
                    "scenario_variants": [],
                    "scenario_families": {},
                    "scenario_input_contract": {
                        "baseline_output_source": "validation_failed_draft",
                    },
                }
                try:
                    draft_export_result = self._run_stage(
                        "export",
                        default_export,
                        context=self.context,
                        canonical_state_result=draft_canonical_state_result,
                        validation_result=validation_result,
                        translation_result=draft_translation_result,
                        scenario_result=draft_scenario_result,
                        ingestion_result=ingestion_result,
                        extraction_result=extraction_result,
                        normalization_result=normalization_result,
                        retrieval_result=retrieval_result,
                        interview_result=interview_result,
                        gap_resolution_result=gap_resolution_result,
                    )
                    if isinstance(draft_export_result, dict):
                        draft_export_result["export_mode"] = "DRAFT_BLOCKED_VALIDATION_FAILED"
                        draft_export_result["draft_only_reason"] = "Applicant interview was skipped/deferred and validation failed; planner-facing outputs are draft/blocked and not final-ready."
                        manifest = draft_export_result.get("export_manifest", {})
                        if isinstance(manifest, dict):
                            manifest["export_mode"] = "DRAFT_BLOCKED_VALIDATION_FAILED"
                            manifest["draft_only_reason"] = draft_export_result["draft_only_reason"]
                            summary = manifest.get("summary", {})
                            if isinstance(summary, dict):
                                summary["final_export_ready"] = False
                                summary["planner_packet_ready"] = True
                                summary["planner_packet_readiness"] = "DRAFT_BLOCKED_VALIDATION_FAILED"
                                summary["interview_ready_for_final_output"] = False
                except Exception as exc:
                    LOGGER.exception("Draft export after validation failure failed for run %s.", self.context.run_id)
                    draft_export_result = {
                        "run_id": self.context.run_id,
                        "status": "DRAFT_EXPORT_FAILED",
                        "errors": [str(exc)],
                    }

            pipeline_summary = {
                "run_id": self.context.run_id,
                "completed_at": utc_now_iso(),
                "status": "VALIDATION_FAILED",
                "execution_mode": self.context.execution_mode,
                "parent_run_id": self.context.parent_run_id,
                "replay_source_run_id": self.context.replay_source_run_id,
                "replay_stage_boundary": self.context.replay_stage_boundary,
                "project_identity": make_serializable(project_identity),
                "public_stage_order": list(PUBLIC_PIPELINE_STAGE_ORDER),
                "gap_resolution_substage_order": list(GAP_RESOLUTION_SUBSTAGE_ORDER),
                "runtime_contract": build_runtime_contract_summary(),
                "stage_status": {
                    "ingestion": ingestion_result.get("status"),
                    "extraction": extraction_result.get("status"),
                    "normalization": normalization_result.get("status"),
                    "gap_resolution": gap_resolution_result.get("status"),
                    "validation": validation_status,
                    "canonical_state": "SKIPPED_DUE_TO_VALIDATION_FAILURE",
                },
                "gap_resolution_substages": {
                    substage_name: payload.get("status")
                    for substage_name, payload in {
                        GAP_RESOLUTION_RETRIEVAL_STAGE: retrieval_result,
                        GAP_RESOLUTION_INTERVIEW_STAGE: interview_result,
                    }.items()
                },
                "validation_substages": {
                    substage_name: payload.get("status")
                    for substage_name, payload in validation_substages.items()
                },
                "validation_details": {
                    "engineering_validation": validation_substages.get("engineering_validation", {}).get("summary", {}),
                    "calibration_dataset": validation_substages.get("calibration_dataset", {}).get("summary", {}),
                    "calibration_comparison": validation_substages.get("calibration_comparison", {}).get("summary", {}),
                },
                "draft_export_after_interview_skip": make_serializable(draft_export_result) if draft_export_result else None,
                "draft_outputs_generated": bool(draft_export_result and draft_export_result.get("status") not in {"DRAFT_EXPORT_FAILED"}),
                "governed_run_summary": build_governed_run_summary(
                    canonical_state=validation_result.get("canonical_state", {}),
                    validation_result=validation_result,
                    retrieval_result=retrieval_result,
                    interview_result=interview_result,
                    gap_resolution_result=gap_resolution_result,
                    translation_result={},
                    scenario_result={},
                    export_result=None,
                    extraction_result=extraction_result,
                ),
                "observability_summary": self._build_run_observability_summary(
                    extraction_result=extraction_result,
                    retrieval_result=retrieval_result,
                    interview_result=interview_result,
                    canonical_state=validation_result.get("canonical_state", {}),
                    validation_result=validation_result,
                ),
                "canonical_state_path": str(self._canonical_state_path()),
                "run_governance": self.run_governance.finalize(
                    status="VALIDATION_FAILED",
                    canonical_state_path=self._canonical_state_path(),
                    pipeline_summary_path=self._pipeline_summary_path(),
                    export_manifest_path=(self.context.run_dir / "exports" / "run_manifest.json") if draft_export_result else None,
                ),
            }

            safe_write_json(
                self._pipeline_summary_path(),
                make_serializable(pipeline_summary),
            )

            self.audit_logger.log_pipeline_complete(
                metadata={
                    "pipeline_summary_path": str(self._pipeline_summary_path()),
                    "canonical_state_path": str(self._canonical_state_path()),
                    "status": "VALIDATION_FAILED",
                }
            )

            LOGGER.error("Pipeline halted due to validation failure: %s", self.context.run_id)
            return pipeline_summary

        canonical_state_result = self._reuse_or_run_stage(
            "canonical_state",
            default_canonical_state_service,
            context=self.context,
            validation_result=validation_result,
            gap_resolution_result=gap_resolution_result,
        )

        canonical_state_result = annotate_final_canonical_state_result(canonical_state_result)
        canonical_state_result_payload = canonical_state_result if isinstance(canonical_state_result, dict) else {}
        canonical_state_payload = canonical_state_result_payload.get("canonical_state", {})
        if isinstance(canonical_state_payload, dict) and canonical_state_payload:
            self._persist_canonical_state_payload(canonical_state_payload)
            self._snapshot_current_state("after_canonical_state")

        adjudication_result = build_adjudication_result_from_canonical(
            run_id=self.context.run_id,
            canonical_state_result=canonical_state_result_payload,
        )
        self._persist_substage_output("canonical_state", "adjudication", adjudication_result)
        safe_write_json(
            self.context.run_dir / "adjudication_result.json",
            make_serializable(adjudication_result),
        )

        planner_field_contract = planner_field_contract_from_canonical(canonical_state_result_payload)
        planner_field_contract = apply_interview_answers_to_planner_contract(
            planner_field_contract,
            interview_result=interview_result,
            gap_resolution_result=gap_resolution_result,
        )
        planner_interview_closure = (
            planner_field_contract.get("planner_interview_closure", {})
            if isinstance(planner_field_contract.get("planner_interview_closure"), dict)
            else {}
        )
        safe_write_json(
            self.context.run_dir / "planner_interview_closure.json",
            make_serializable(planner_interview_closure),
        )

        planner_ledger_adjudication = build_ledger_adjudication_artifact(
            run_id=self.context.run_id,
            planner_field_contract=planner_field_contract,
            adjudication_result=adjudication_result,
        )
        planner_field_contract = apply_ledger_adjudication_to_contract(
            planner_field_contract,
            planner_ledger_adjudication,
        )
        planner_field_contract["planner_field_governance"] = build_planner_field_governance(
            planner_field_contract.get("planner_field_ledger", [])
            if isinstance(planner_field_contract.get("planner_field_ledger"), list)
            else []
        )
        planner_ledger_adjudication = (
            planner_field_contract.get("planner_ledger_adjudication", planner_ledger_adjudication)
            if isinstance(planner_field_contract, dict)
            else planner_ledger_adjudication
        )
        self._persist_substage_output("canonical_state", "planner_interview_closure", planner_interview_closure)
        self._persist_substage_output("canonical_state", "planner_ledger_adjudication", planner_ledger_adjudication)
        safe_write_json(
            self.context.run_dir / "planner_ledger_adjudication.json",
            make_serializable(planner_ledger_adjudication),
        )

        if isinstance(canonical_state_payload, dict):
            canonical_state_payload["planner_field_contract"] = planner_field_contract
            canonical_state_payload["planner_field_ledger"] = planner_field_contract.get("planner_field_ledger", [])
            canonical_state_payload["planner_field_ledger_summary"] = planner_field_contract.get("planner_field_ledger_summary", {})
            canonical_state_payload["planner_field_governance"] = planner_field_contract.get("planner_field_governance", {})
            canonical_state_payload["planner_interview_closure"] = planner_interview_closure
            canonical_state_payload["planner_ledger_adjudication"] = planner_ledger_adjudication
            if isinstance(canonical_state_result_payload, dict):
                canonical_state_result_payload["canonical_state"] = canonical_state_payload
                canonical_state_result_payload["planner_field_contract"] = planner_field_contract
                canonical_state_result_payload["planner_field_ledger"] = planner_field_contract.get("planner_field_ledger", [])
                canonical_state_result_payload["planner_field_ledger_summary"] = planner_field_contract.get("planner_field_ledger_summary", {})
                canonical_state_result_payload["planner_field_governance"] = planner_field_contract.get("planner_field_governance", {})
                canonical_state_result_payload["planner_interview_closure"] = planner_interview_closure
                canonical_state_result_payload["planner_ledger_adjudication"] = planner_ledger_adjudication
            self._persist_canonical_state_payload(canonical_state_payload)
        self._persist_substage_output("canonical_state", "planner_field_ledger", planner_field_contract)
        safe_write_json(
            self.context.run_dir / "planner_field_ledger.json",
            make_serializable(planner_field_contract.get("planner_field_ledger", [])),
        )
        safe_write_json(
            self.context.run_dir / "planner_field_ledger_summary.json",
            make_serializable(planner_field_contract.get("planner_field_ledger_summary", {})),
        )

        translation_result = self._reuse_or_run_stage(
            "translation",
            default_translation,
            context=self.context,
            canonical_state_result=canonical_state_result,
            validation_result=validation_result,
            normalization_result=normalization_result,
            retrieval_result=retrieval_result,
            gap_resolution_result=gap_resolution_result,
        )

        scenario_result = self._reuse_or_run_stage(
            "scenarios",
            default_scenarios,
            context=self.context,
            translation_result=translation_result,
        )

        pre_export_gate = _build_pre_export_gate(
            run_id=self.context.run_id,
            interview_result=interview_result,
            translation_result=translation_result,
            scenario_result=scenario_result,
            planner_ledger_adjudication=planner_ledger_adjudication,
        )
        self._persist_substage_output("export", "pre_export_gate", pre_export_gate)
        safe_write_json(
            self.context.run_dir / "pre_export_gate.json",
            make_serializable(pre_export_gate),
        )

        if bool(pre_export_gate.get("ready_for_final_export", False)) or bool(pre_export_gate.get("draft_only_allowed", False)):
            export_result = self._reuse_or_run_stage(
                "export",
                default_export,
                context=self.context,
                canonical_state_result=canonical_state_result,
                validation_result=validation_result,
                translation_result=translation_result,
                scenario_result=scenario_result,
                ingestion_result=ingestion_result,
                extraction_result=extraction_result,
                normalization_result=normalization_result,
                retrieval_result=retrieval_result,
                interview_result=interview_result,
                gap_resolution_result=gap_resolution_result,
            )
            if bool(pre_export_gate.get("draft_only_allowed", False)) and isinstance(export_result, dict):
                export_result["export_mode"] = "DRAFT_EXPORT_ONLY"
                export_result["draft_only_reason"] = "Applicant interview was skipped or deferred; planner-facing outputs are provisional and not final-ready."
                manifest = export_result.get("export_manifest", {})
                if isinstance(manifest, dict):
                    manifest["export_mode"] = "DRAFT_EXPORT_ONLY"
                    manifest["draft_only_reason"] = export_result["draft_only_reason"]
                    summary = manifest.get("summary", {})
                    if isinstance(summary, dict):
                        summary["final_export_ready"] = False
                        summary["interview_ready_for_final_output"] = False
                        summary["planner_packet_ready"] = True
                        summary["planner_packet_readiness"] = "DRAFT_BLOCKED_INTERVIEW_SKIPPED"
        else:
            export_result = _build_blocked_export_result(
                run_id=self.context.run_id,
                pre_export_gate=pre_export_gate,
            )
            self._persist_stage_output("export", export_result)
            (self.context.run_dir / "exports").mkdir(parents=True, exist_ok=True)
            safe_write_json(
                self.context.run_dir / "exports" / "blocked_export_manifest.json",
                make_serializable(export_result.get("export_manifest", {})),
            )

        phase6_redesign_runtime_contract = build_phase6_redesign_runtime_contract(
            run_id=self.context.run_id,
            canonical_state_result=canonical_state_result_payload,
            normalization_result=normalization_result,
            interview_result=interview_result,
            translation_result=translation_result,
            scenario_result=scenario_result,
            export_result=export_result,
            adjudication_result=adjudication_result,
            planner_field_contract=planner_field_contract,
            planner_interview_closure=planner_interview_closure,
            planner_ledger_adjudication=planner_ledger_adjudication,
        )
        safe_write_json(
            self.context.run_dir / "phase6_redesign_runtime_contract.json",
            make_serializable(phase6_redesign_runtime_contract),
        )

        self._snapshot_current_state("final")

        replay_summary = None
        if self.replay_manager:
            replay_summary = {
                "source_run_id": self.context.replay_source_run_id,
                "requested_stage_boundary": self.context.replay_stage_boundary,
                "resume_from_stage": self.replay_manager.plan["resume_from_stage"],
                "reused_stages": list(self.replay_manager.plan["reused_stages"]),
                "rerun_stages": list(self.replay_manager.plan["rerun_stages"]),
                "reused_gap_resolution_substages": list(self.replay_manager.plan.get("reused_gap_resolution_substages", [])),
            }
            self.replay_manager.mark_completed()

        extraction_substages = {
            "document_parser": (
                document_parser_result.get("status")
                if isinstance(document_parser_result, dict)
                else ("REUSED_WITH_EXTRACTION" if extraction_is_reused else None)
            ),
            "layout_analysis": (
                layout_analysis_result.get("status")
                if isinstance(layout_analysis_result, dict)
                else ("REUSED_WITH_EXTRACTION" if extraction_is_reused else None)
            ),
            "ocr": (
                ocr_result.get("status")
                if isinstance(ocr_result, dict)
                else ("REUSED_WITH_EXTRACTION" if extraction_is_reused else None)
            ),
        }

        intake_summary = build_intake_summary(ingestion_result)

        export_manifest_summary = export_result.get("export_manifest", {}).get("summary", {}) if isinstance(export_result.get("export_manifest", {}), dict) and isinstance(export_result.get("export_manifest", {}).get("summary", {}), dict) else {}
        interview_ready_for_final_output = bool(export_manifest_summary.get("interview_ready_for_final_output", False))
        final_export_ready = bool(export_manifest_summary.get("final_export_ready", False))
        planner_packet_ready = bool(export_manifest_summary.get("planner_packet_ready", False))
        if export_result.get("status") == "EXPORT_BLOCKED_PRECONTRACT":
            pipeline_status = "PIPELINE_COMPLETED_BLOCKED"
            governance_status = "EXPORT_BLOCKED_PRECONTRACT"
        elif final_export_ready and export_result.get("status") == "EXPORTED":
            pipeline_status = "SUCCESS_FINAL"
            governance_status = "SUCCESS_FINAL"
        elif planner_packet_ready:
            pipeline_status = "SUCCESS_PROVISIONAL"
            governance_status = "SUCCESS_PROVISIONAL"
        elif not interview_ready_for_final_output:
            pipeline_status = "BLOCKED_PENDING_INTERVIEW"
            governance_status = "BLOCKED_PENDING_INTERVIEW"
        else:
            pipeline_status = "BLOCKED_REVIEW_REQUIRED"
            governance_status = "BLOCKED_REVIEW_REQUIRED"

        if pipeline_status == "SUCCESS_FINAL":
            planner_readiness_state = "FINAL_EXPORT_READY"
        elif pipeline_status == "SUCCESS_PROVISIONAL":
            planner_readiness_state = "DRAFT_EXPORT_READY"
        elif pipeline_status == "BLOCKED_PENDING_INTERVIEW":
            planner_readiness_state = "WAITING_OR_BLOCKED_ON_INTERVIEW"
        else:
            planner_readiness_state = "FINAL_EXPORT_BLOCKED"

        export_manifest_path = (
            self.context.run_dir / "exports" / "blocked_export_manifest.json"
            if export_result.get("status") == "EXPORT_BLOCKED_PRECONTRACT"
            else self.context.run_dir / "exports" / "run_manifest.json"
        )

        pipeline_summary = {
            "run_id": self.context.run_id,
            "completed_at": utc_now_iso(),
            "status": pipeline_status,
            "planner_readiness_state": planner_readiness_state,
            "technical_completion_state": "PIPELINE_COMPLETED",
            "execution_mode": self.context.execution_mode,
            "parent_run_id": self.context.parent_run_id,
            "replay_source_run_id": self.context.replay_source_run_id,
            "replay_stage_boundary": self.context.replay_stage_boundary,
            "replay_summary": replay_summary,
            "intake_summary": intake_summary,
            "public_stage_order": list(PUBLIC_PIPELINE_STAGE_ORDER),
            "gap_resolution_substage_order": list(GAP_RESOLUTION_SUBSTAGE_ORDER),
            "runtime_contract": build_runtime_contract_summary(),
            "stage_status": {
                "ingestion": ingestion_result.get("status"),
                "extraction": extraction_result.get("status"),
                "normalization": normalization_result.get("status"),
                "gap_resolution": gap_resolution_result.get("status"),
                "validation": validation_result.get("status"),
                "canonical_state": canonical_state_result_payload.get("status"),
                "canonical_state::adjudication": adjudication_result.get("status"),
                "canonical_state::planner_interview_closure": planner_interview_closure.get("contract_version") if isinstance(planner_interview_closure, dict) else None,
                "canonical_state::planner_ledger_adjudication": planner_ledger_adjudication.get("status") if isinstance(planner_ledger_adjudication, dict) else None,
                "phase6_redesign_runtime_contract": phase6_redesign_runtime_contract.get("status") if isinstance(phase6_redesign_runtime_contract, dict) else None,
                "export::pre_export_gate": pre_export_gate.get("status") if isinstance(pre_export_gate, dict) else None,
                "translation": translation_result.get("status"),
                "scenarios": scenario_result.get("status"),
                "export": export_result.get("status"),
            },
            "gap_resolution_substages": {
                substage_name: payload.get("status")
                for substage_name, payload in {
                    GAP_RESOLUTION_RETRIEVAL_STAGE: retrieval_result,
                    GAP_RESOLUTION_INTERVIEW_STAGE: interview_result,
                }.items()
            },
            "validation_substages": {
                substage_name: payload.get("status")
                for substage_name, payload in validation_substages.items()
            },
            "validation_details": {
                "engineering_validation": validation_substages.get("engineering_validation", {}).get("summary", {}),
                "calibration_dataset": validation_substages.get("calibration_dataset", {}).get("summary", {}),
                "calibration_comparison": validation_substages.get("calibration_comparison", {}).get("summary", {}),
            },
            "extraction_substages": extraction_substages,
            "governed_run_summary": build_governed_run_summary(
                canonical_state=canonical_state_payload,
                validation_result=validation_result,
                retrieval_result=retrieval_result,
                interview_result=interview_result,
                gap_resolution_result=gap_resolution_result,
                translation_result=translation_result,
                scenario_result=scenario_result,
                export_result=export_result,
                extraction_result=extraction_result,
            ),
            "observability_summary": self._build_run_observability_summary(
                extraction_result=extraction_result,
                retrieval_result=retrieval_result,
                interview_result=interview_result,
                canonical_state=canonical_state_payload,
                validation_result=validation_result,
            ),
            "canonical_state_path": str(self._canonical_state_path()),
            "adjudication_result": adjudication_result,
            "planner_interview_closure": planner_interview_closure,
            "planner_ledger_adjudication": planner_ledger_adjudication,
            "phase6_redesign_runtime_contract": phase6_redesign_runtime_contract,
            "pre_export_gate": pre_export_gate,
            "export_manifest": export_result.get("export_manifest"),
            "run_governance": self.run_governance.finalize(
                status=governance_status,
                canonical_state_path=self._canonical_state_path(),
                pipeline_summary_path=self._pipeline_summary_path(),
                export_manifest_path=export_manifest_path,
            ),
        }

        safe_write_json(
            self._pipeline_summary_path(),
            make_serializable(pipeline_summary),
        )

        self.audit_logger.log_pipeline_complete(
            metadata={
                "pipeline_summary_path": str(self._pipeline_summary_path()),
                "canonical_state_path": str(self._canonical_state_path()),
                "status": pipeline_summary.get("status"),
            }
        )

        LOGGER.info("Pipeline run completed with status %s: %s", pipeline_status, self.context.run_id)
        return pipeline_summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the GridSenpAI pipeline.")
    parser.add_argument(
        "--input-dir",
        default=str(PROJECT_ROOT / "sample_data"),
        help="Directory containing input artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "runs"),
        help="Directory where run outputs should be written.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional explicit run ID. If omitted, one is generated automatically.",
    )
    parser.add_argument(
        "--parent-run-id",
        default=None,
        help="Optional parent run ID for lineage tracking.",
    )
    parser.add_argument(
        "--replay-run-id",
        default=None,
        help="Optional source run ID to replay from.",
    )
    parser.add_argument(
        "--replay-stage-boundary",
        default=None,
        help=(
            "Optional replay boundary stage. Reuse all stage outputs through this stage "
            "and rerun downstream stages."
        ),
    )
    parser.add_argument(
        "--diff-baseline-run-id",
        default=None,
        help="Optional baseline run ID for run diff mode.",
    )
    parser.add_argument(
        "--diff-candidate-run-id",
        default=None,
        help="Optional candidate run ID for run diff mode.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity.",
    )
    parser.add_argument(
        "--llm-provider",
        default=None,
        choices=["llama_cpp", "ibm_watsonx"],
        help="Optional local LLM runtime provider override.",
    )
    parser.add_argument(
        "--llm-model-path",
        default=None,
        help="Optional GGUF model path override. Supports Qwen, IBM Granite, and other llama.cpp-compatible GGUF models.",
    )
    parser.add_argument(
        "--llm-model-alias",
        default=None,
        help="Optional model alias override used in diagnostics and run provenance.",
    )
    parser.add_argument(
        "--llm-n-ctx",
        default=None,
        type=int,
        help="Optional local runtime context window override.",
    )
    parser.add_argument(
        "--llm-n-batch",
        default=None,
        type=int,
        help="Optional local runtime batch size override.",
    )
    parser.add_argument(
        "--llm-disable-runtime",
        action="store_true",
        help="Disable configured LLM runtime and run deterministic-only bounded flows.",
    )
    parser.add_argument("--watsonx-url", default=None, help="IBM watsonx base URL, for example https://us-south.ml.cloud.ibm.com")
    parser.add_argument("--watsonx-api-key", default=None, help="IBM watsonx IAM API key used to obtain a bearer token.")
    parser.add_argument("--watsonx-project-id", default=None, help="IBM watsonx project ID for chat inference.")
    parser.add_argument("--watsonx-space-id", default=None, help="IBM watsonx space ID for chat inference when project_id is not used.")
    parser.add_argument("--watsonx-model-id", default=None, help="IBM Granite model ID, for example ibm/granite-3-3-8b-instruct.")
    parser.add_argument("--watsonx-api-version", default=None, help="IBM watsonx API version string for /ml/v1/text/chat.")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    is_replay = bool(args.replay_run_id or args.replay_stage_boundary)
    is_diff = bool(args.diff_baseline_run_id or args.diff_candidate_run_id)

    if is_replay and is_diff:
        raise ValueError("Replay mode and diff mode cannot be used together.")

    if is_replay and not args.replay_run_id:
        raise ValueError("--replay-run-id is required when using replay mode.")

    if is_replay and not args.replay_stage_boundary:
        raise ValueError("--replay-stage-boundary is required when using replay mode.")

    if is_diff and not args.diff_baseline_run_id:
        raise ValueError("--diff-baseline-run-id is required when using diff mode.")

    if is_diff and not args.diff_candidate_run_id:
        raise ValueError("--diff-candidate-run-id is required when using diff mode.")




def apply_cli_llm_overrides(args: argparse.Namespace) -> None:
    requested_model_path = str(args.llm_model_path).strip() if getattr(args, "llm_model_path", None) else None
    requested_alias = str(args.llm_model_alias).strip() if getattr(args, "llm_model_alias", None) else None
    requested_provider = str(args.llm_provider).strip() if getattr(args, "llm_provider", None) else None
    disable_runtime = bool(getattr(args, "llm_disable_runtime", False))

    requested_watsonx_url = str(args.watsonx_url).strip() if getattr(args, "watsonx_url", None) else None
    requested_watsonx_api_key = str(args.watsonx_api_key).strip() if getattr(args, "watsonx_api_key", None) else None
    requested_watsonx_project_id = str(args.watsonx_project_id).strip() if getattr(args, "watsonx_project_id", None) else None
    requested_watsonx_space_id = str(args.watsonx_space_id).strip() if getattr(args, "watsonx_space_id", None) else None
    requested_watsonx_model_id = str(args.watsonx_model_id).strip() if getattr(args, "watsonx_model_id", None) else None
    requested_watsonx_api_version = str(args.watsonx_api_version).strip() if getattr(args, "watsonx_api_version", None) else None

    if not any([requested_model_path, requested_alias, requested_provider, getattr(args, "llm_n_ctx", None) is not None, getattr(args, "llm_n_batch", None) is not None, requested_watsonx_url, requested_watsonx_api_key, requested_watsonx_project_id, requested_watsonx_space_id, requested_watsonx_model_id, requested_watsonx_api_version, disable_runtime]):
        return

    enable_runtime = None
    if disable_runtime:
        enable_runtime = False
    elif requested_model_path or requested_provider or requested_alias:
        enable_runtime = True

    apply_llm_runtime_overrides(
        enabled=enable_runtime,
        provider=requested_provider,
        model_path=requested_model_path,
        model_alias=requested_alias,
        n_ctx=getattr(args, "llm_n_ctx", None),
        n_batch=getattr(args, "llm_n_batch", None),
        watsonx_url=requested_watsonx_url,
        watsonx_api_key=requested_watsonx_api_key,
        watsonx_project_id=requested_watsonx_project_id,
        watsonx_space_id=requested_watsonx_space_id,
        watsonx_model_id=requested_watsonx_model_id,
        watsonx_api_version=requested_watsonx_api_version,
    )

def build_run_config() -> RunConfig:
    return RunConfig(
        project_name=CONFIG.project_name,
        schema_version_input=CONFIG.schemas.input_schema_version,
        schema_version_output=CONFIG.schemas.output_schema_version,
        prompt_template_version=CONFIG.model.prompt_template_version,
        model_version=CONFIG.model.model_version,
        retrieval_config=CONFIG.retrieval.to_dict(),
        ocr_enabled=CONFIG.ocr.enabled,
        ocr_lang=CONFIG.ocr.lang,
        ocr_render_scale=CONFIG.ocr.render_scale,
        ocr_text_detection_model_name=CONFIG.ocr.text_detection_model_name,
        ocr_text_recognition_model_name=CONFIG.ocr.text_recognition_model_name,
    )


def build_run_context(
    args: argparse.Namespace,
) -> RunContext:
    from shared.security.models import Actor
    from shared.security.permissions import Role
    from shared.security.run_access_registry import RunAccessRegistry

    run_id = str(args.run_id).strip() if args.run_id else build_run_id()

    project_root = normalize_path(CONFIG.paths.project_root)
    input_dir = normalize_path(args.input_dir)
    output_dir = normalize_path(args.output_dir)
    run_dir = output_dir / run_id

    project_root.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    config = build_run_config()

    replay_source_run_id = (
        str(args.replay_run_id).strip()
        if args.replay_run_id is not None and str(args.replay_run_id).strip()
        else None
    )
    replay_stage_boundary = (
        str(args.replay_stage_boundary).strip()
        if args.replay_stage_boundary is not None and str(args.replay_stage_boundary).strip()
        else None
    )
    parent_run_id = (
        str(args.parent_run_id).strip()
        if args.parent_run_id is not None and str(args.parent_run_id).strip()
        else None
    )

    if replay_source_run_id is not None and parent_run_id is None:
        parent_run_id = replay_source_run_id

    execution_mode = (
        "REPLAY"
        if replay_source_run_id is not None and replay_stage_boundary is not None
        else "STANDARD"
    )

    actor = Actor(
        actor_id="local_cli_engineer",
        role=Role.ENGINEER,
        display_name="Local CLI Engineer",
        email=None,
    )

    run_access_registry = RunAccessRegistry()
    run_access_registry.register_run(run_id, actor)

    return RunContext(
        run_id=run_id,
        project_root=project_root,
        input_dir=input_dir,
        output_dir=output_dir,
        run_dir=run_dir,
        config=config,
        actor=actor,
        run_access_registry=run_access_registry,
        parent_run_id=parent_run_id,
        execution_mode=execution_mode,
        replay_source_run_id=replay_source_run_id,
        replay_stage_boundary=replay_stage_boundary,
    )

def run_from_args(args: argparse.Namespace) -> dict[str, Any]:
    validate_args(args)

    if args.diff_baseline_run_id and args.diff_candidate_run_id:
        return compare_run_states(
            output_dir=normalize_path(args.output_dir),
            baseline_run_id=str(args.diff_baseline_run_id).strip(),
            candidate_run_id=str(args.diff_candidate_run_id).strip(),
            write_artifact=True,
        )

    context = build_run_context(args)
    pipeline = GridSenpAIPipeline(context)
    return pipeline.run()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(getattr(logging, args.log_level.upper(), logging.INFO))
    apply_cli_llm_overrides(args)

    if CONFIG.llm_runtime.enabled and (CONFIG.llm_runtime.model_path or str(CONFIG.llm_runtime.provider or "").strip() == "ibm_watsonx"):

        runtime_config = LLMRuntimeConfig(
            provider=CONFIG.llm_runtime.provider,
            model_path=CONFIG.llm_runtime.model_path,
            model_alias=CONFIG.llm_runtime.model_alias,
            n_ctx=CONFIG.llm_runtime.n_ctx,
            n_threads=CONFIG.llm_runtime.n_threads,
            n_batch=CONFIG.llm_runtime.n_batch,
            n_gpu_layers=CONFIG.llm_runtime.n_gpu_layers,
            temperature=CONFIG.llm_runtime.temperature,
            top_p=CONFIG.llm_runtime.top_p,
            max_tokens=CONFIG.llm_runtime.max_tokens,
            watsonx_url=CONFIG.llm_runtime.watsonx_url,
            watsonx_api_key=CONFIG.llm_runtime.watsonx_api_key,
            watsonx_project_id=CONFIG.llm_runtime.watsonx_project_id,
            watsonx_space_id=CONFIG.llm_runtime.watsonx_space_id,
            watsonx_model_id=CONFIG.llm_runtime.watsonx_model_id,
            watsonx_api_version=CONFIG.llm_runtime.watsonx_api_version,
            watsonx_iam_url=CONFIG.llm_runtime.watsonx_iam_url,
            watsonx_time_limit_ms=CONFIG.llm_runtime.watsonx_time_limit_ms,
        )

        initialize_runtime(runtime_config)

    try:
        summary = run_from_args(args)
    except Exception as exc:
        output_dir = normalize_path(args.output_dir)
        run_id = args.run_id or "unknown_run"
        run_dir = output_dir / run_id

        LOGGER.error("Pipeline failed: %s", exc)
        safe_write_json(
            run_dir / "pipeline_summary.json",
            {
                "run_id": run_id,
                "completed_at": utc_now_iso(),
                "status": "FAILED",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        return 1

    safe_print_json(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())