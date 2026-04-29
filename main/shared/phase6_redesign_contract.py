from __future__ import annotations

"""Runtime contract audit for the Phase 6 ledger-first redesign.

This module is intentionally lightweight and deterministic.  It does not decide
pipeline success.  It records whether the active run used the redesign contracts
that GridSenpAI now depends on: registry-complete planner ledger, candidate-ledger
bridge, pre-interview ledger questions, interview/adjudication closure, and
ledger-native translation/scenario/export handoff.
"""

from datetime import datetime, timezone
from typing import Any

from shared.planner_registry import pipeline_requested_field_paths


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _status(pass_condition: bool, *, required: bool = True) -> str:
    if pass_condition:
        return "PASS"
    return "FAIL" if required else "WARN"


def _gate(name: str, passed: bool, *, required: bool = True, evidence: dict[str, Any] | None = None, requirement: str = "") -> dict[str, Any]:
    return {
        "gate": name,
        "status": _status(passed, required=required),
        "required": required,
        "requirement": requirement,
        "evidence": evidence or {},
    }


def _canonical_payload(canonical_state_result: dict[str, Any] | None) -> dict[str, Any]:
    payload = _as_dict(canonical_state_result)
    canonical = _as_dict(payload.get("canonical_state"))
    return canonical or payload


def _ledger_rows(planner_field_contract: dict[str, Any] | None, canonical_state_result: dict[str, Any] | None) -> list[Any]:
    contract = _as_dict(planner_field_contract)
    rows = _as_list(contract.get("planner_field_ledger"))
    if rows:
        return rows
    canonical = _canonical_payload(canonical_state_result)
    return _as_list(canonical.get("planner_field_ledger"))


def _candidate_ledger(normalization_result: dict[str, Any] | None, canonical_state_result: dict[str, Any] | None) -> list[Any]:
    normalization = _as_dict(normalization_result)
    rows = _as_list(normalization.get("planner_candidate_ledger"))
    if rows:
        return rows
    canonical = _canonical_payload(canonical_state_result)
    rows = _as_list(canonical.get("planner_candidate_ledger"))
    if rows:
        return rows
    source_inputs = _as_dict(canonical.get("source_candidate_inputs"))
    return _as_list(source_inputs.get("planner_candidate_ledger"))


def _candidate_source_inputs(canonical_state_result: dict[str, Any] | None) -> dict[str, Any]:
    canonical = _canonical_payload(canonical_state_result)
    return _as_dict(canonical.get("source_candidate_inputs"))


def build_phase6_redesign_runtime_contract(
    *,
    run_id: str,
    canonical_state_result: dict[str, Any] | None,
    normalization_result: dict[str, Any] | None,
    interview_result: dict[str, Any] | None,
    translation_result: dict[str, Any] | None,
    scenario_result: dict[str, Any] | None,
    export_result: dict[str, Any] | None,
    adjudication_result: dict[str, Any] | None,
    planner_field_contract: dict[str, Any] | None,
    planner_interview_closure: dict[str, Any] | None,
    planner_ledger_adjudication: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build an auditable runtime contract for the ledger-first redesign."""

    registry_count = len(pipeline_requested_field_paths())
    rows = _ledger_rows(planner_field_contract, canonical_state_result)
    candidate_rows = _candidate_ledger(normalization_result, canonical_state_result)
    source_inputs = _candidate_source_inputs(canonical_state_result)
    interview = _as_dict(interview_result)
    translation = _as_dict(translation_result)
    scenarios = _as_dict(scenario_result)
    export = _as_dict(export_result)
    adjudication = _as_dict(adjudication_result)
    ledger_adjudication = _as_dict(planner_ledger_adjudication)
    interview_closure = _as_dict(planner_interview_closure)
    translation_contract = _as_dict(translation.get("translation_source_contract")) or _as_dict(translation.get("ledger_first_translation_contract"))
    if not translation_contract:
        export_translation_contract = _as_dict(export.get("translation_source_contract")) or _as_dict(export.get("ledger_first_translation_contract"))
        translation_contract = export_translation_contract
    ledger_native_translation = _as_dict(translation.get("ledger_native_translation"))
    scenario_input_contract = _as_dict(scenarios.get("scenario_input_contract"))
    export_manifest = _as_dict(export.get("export_manifest"))

    ledger_row_count = len([row for row in rows if isinstance(row, dict)])
    candidate_row_count = len([row for row in candidate_rows if isinstance(row, dict)])
    accepted_or_provisional_rows = [
        row for row in rows
        if isinstance(row, dict)
        and _clean(row.get("status")).upper() in {
            "ACCEPTED",
            "ACCEPTED_WITH_CONFLICT_NOTE",
            "INTERVIEW_CONFIRMED",
            "INTERVIEW_SUPPLIED",
            "INTERVIEW_CONFLICT_CONFIRMED",
            "PROVISIONAL",
        }
    ]
    sourced_rows = [
        row for row in accepted_or_provisional_rows
        if _clean(row.get("source_document")) or _clean(row.get("source_reference")) or _clean(row.get("source_anchor"))
    ]

    gates = [
        _gate(
            "registry_complete_planner_ledger",
            registry_count > 0 and ledger_row_count >= registry_count,
            requirement="Final planner field ledger must include every master registry field.",
            evidence={"registry_field_count": registry_count, "planner_ledger_row_count": ledger_row_count},
        ),
        _gate(
            "candidate_ledger_primary_source_available",
            candidate_row_count > 0 and _clean(source_inputs.get("candidate_governance_source")) == "planner_candidate_ledger",
            requirement="Canonical/field resolution must receive planner_candidate_ledger as a governed input.",
            evidence={
                "candidate_row_count": candidate_row_count,
                "source_candidate_inputs_keys": sorted(source_inputs.keys()),
                "candidate_governance_source": source_inputs.get("candidate_governance_source"),
            },
        ),
        _gate(
            "pre_interview_working_ledger",
            bool(_clean(_as_dict(interview.get("pre_interview_planner_field_contract")).get("contract_version")))
            or "pre_interview_planner_field_ledger_question_count" in interview,
            requirement="Interview must build/record a pre-interview planner ledger contract before final canonical state exists.",
            evidence={
                "contract_version": _as_dict(interview.get("pre_interview_planner_field_contract")).get("contract_version"),
                "question_count": interview.get("pre_interview_planner_field_ledger_question_count"),
            },
        ),
        _gate(
            "interview_closure_recorded",
            _clean(interview_closure.get("contract_version")) == "planner_interview_closure_v1",
            requirement="Applicant answers must close into the planner field ledger contract.",
            evidence={"contract_version": interview_closure.get("contract_version"), "applied_answer_count": interview_closure.get("applied_answer_count")},
        ),
        _gate(
            "adjudication_contract_recorded",
            _clean(ledger_adjudication.get("contract_version")) == "planner_ledger_adjudication_v1",
            requirement="Compact adjudication/deterministic fallback must close at the planner-ledger layer.",
            evidence={
                "contract_version": ledger_adjudication.get("contract_version"),
                "status": ledger_adjudication.get("status"),
                "field_resolution_adjudication_status": ledger_adjudication.get("field_resolution_adjudication_status"),
                "decision_count": ledger_adjudication.get("decision_count"),
            },
        ),
        _gate(
            "adjudication_prompt_contract_bounded",
            _clean(adjudication.get("status")) != "PROMPT_TOO_LARGE",
            requirement="Adjudication may not silently fail because of oversized prompts.",
            evidence={"status": adjudication.get("status"), "packet_count": adjudication.get("packet_count"), "blocked_packet_count": adjudication.get("blocked_packet_count")},
        ),
        _gate(
            "ledger_first_translation",
            _clean(translation_contract.get("primary_source")) == "planner_field_ledger"
            and translation_contract.get("legacy_translation_fallback_used") is False,
            requirement="Translation must use final planner ledger rows as the primary source, with legacy only as fallback/diagnostic.",
            evidence=translation_contract,
        ),
        _gate(
            "ledger_native_scenario_inputs",
            _clean(scenario_input_contract.get("baseline_output_source")) == "ledger_native_model_outputs",
            requirement="Scenarios must consume ledger-native model outputs first.",
            evidence=scenario_input_contract,
        ),
        _gate(
            "export_carries_ledger_contracts",
            bool(export_manifest),
            requirement="Export must carry final ledger/adjudication/translation contracts into planner-facing artifacts.",
            evidence={"export_status": export.get("status"), "manifest_keys": sorted(export_manifest.keys())[:25]},
        ),
        _gate(
            "resolved_rows_are_sourced",
            len(accepted_or_provisional_rows) == len(sourced_rows),
            required=False,
            requirement="Every accepted/provisional row should carry source location, except interview-only/future-study rows explicitly marked elsewhere.",
            evidence={"accepted_or_provisional_count": len(accepted_or_provisional_rows), "sourced_count": len(sourced_rows)},
        ),
    ]

    failed_required = [gate for gate in gates if gate["required"] and gate["status"] != "PASS"]
    warnings = [gate for gate in gates if not gate["required"] and gate["status"] != "PASS"]
    status = "PHASE6_REDESIGN_RUNTIME_CONTRACT_PASS" if not failed_required else "PHASE6_REDESIGN_RUNTIME_CONTRACT_FAIL"

    return {
        "contract_version": "phase6_redesign_runtime_contract_v1",
        "run_id": run_id,
        "created_at": _utc_now_iso(),
        "status": status,
        "required_gate_count": len([gate for gate in gates if gate["required"]]),
        "required_gate_pass_count": len([gate for gate in gates if gate["required"] and gate["status"] == "PASS"]),
        "required_gate_fail_count": len(failed_required),
        "warning_count": len(warnings),
        "final_flow": [
            "planner_required_fields.json",
            "extraction_worklist",
            "planner_candidate_ledger",
            "pre_interview_planner_ledger",
            "planner_interview_closure",
            "planner_ledger_adjudication",
            "final_planner_field_ledger",
            "ledger_first_translation",
            "ledger_native_scenarios",
            "ledger_driven_export",
        ],
        "gates": gates,
    }
