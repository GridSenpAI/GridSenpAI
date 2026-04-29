from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from services.authorization_service.service import AuthorizationError
from services.export_service.service import run_service
from shared.security.models import Actor
from shared.security.permissions import Role


@dataclass
class DummyContext:
    run_id: str
    run_dir: Path
    actor: Actor | None = None
    audit_logger: Any | None = None


def _build_context(
    tmp_path: Path,
    *,
    actor: Actor | None,
    run_id: str = "run_export_auth_001",
) -> DummyContext:
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return DummyContext(
        run_id=run_id,
        run_dir=run_dir,
        actor=actor,
        audit_logger=None,
    )


def _build_minimal_canonical_state_result(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "canonical_state": {
            "run_id": run_id,
            "artifacts": [],
            "entities": [],
            "evidence_snippets": [],
            "normalized_input": {
                "facility": {
                    "project_name": "Test Project",
                    "poi_voltage_kv": 138.0,
                    "frequency_hz": 60.0,
                    "load_schedule": {
                        "phase_1_mw": 25.0,
                    },
                    "ups": {
                        "topology": "2N",
                        "count": 2,
                    },
                    "generators": {
                        "present": True,
                        "count": 4,
                    },
                    "transformers": {
                        "count": 2,
                        "ratings_mva": [50.0, 50.0],
                    },
                },
                "source_summary": {
                    "artifact_count": 1,
                    "parsed_document_count": 1,
                    "ocr_document_count": 0,
                    "extraction_candidate_count": 3,
                },
            },
            "field_records": [],
            "field_resolution": {
                "ledger": [
                    {
                        "field_id": "generator_rated_kw_per_unit",
                        "field_path": "facility.generators.rated_kw_per_unit",
                        "label": "Generator rated kW per unit",
                        "accepted_status": "review_required",
                        "confidence_band": "MODERATE",
                        "planner_critical": True,
                        "needs_applicant_confirmation": True,
                        "adjudication_notes": ["Exact-model manufacturer evidence outranked weaker contextual support."],
                        "evidence_route_record": {
                            "agent_contributors": ["evidence_resolution_agent", "retrieval_planning_agent"],
                            "best_source_hierarchy": "manufacturer_model_specific_spec",
                            "best_specificity": "exact_model_match",
                        },
                    }
                ]
            },
            "stage_status": {
                "canonical_state": "CANONICAL_STATE_BUILT",
                "validation": "VALIDATED",
                "translation": "TRANSLATED",
                "scenarios": "SCENARIOS_GENERATED",
            },
            "calibration_datasets": [],
            "calibration_records": [],
            "assumption_registry": [],
            "validation_runs": [],
            "reconciliation_records": [],
            "change_log": [],
        },
    }


def _build_minimal_validation_result(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "VALIDATED",
        "canonical_state": {},
        "summary": {
            "validation_run_count": 1,
            "calibration_record_count": 2,
            "reconciliation_record_count": 1,
        },
        "validation_report": {
            "missing_fields": [],
            "conflicts": [],
            "warnings": [],
            "engineering_validation": {
                "status": "PASS",
                "review_flag_count": 0,
                "summary": {},
            },
            "calibration_summary": {
                "status": "CALIBRATION_COMPARISON_COMPLETE",
                "summary": {
                    "dataset_count": 1,
                    "calibration_record_count": 2,
                },
            },
            "reconciliation_summary": {
                "comparison_run_id": f"{run_id}::calibration_compare",
                "compared_at": "2026-04-08T00:00:00+00:00",
                "open_reconciliation_count": 1,
                "closed_reconciliation_count": 1,
                "review_required_count": 1,
                "conflict_count": 0,
                "change_log_count": 1,
                "severity_counts": {
                    "error": 0,
                    "warning": 1,
                    "info": 1,
                },
                "recommended_actions": [
                    "Keep the governed value provisional and request engineering review of the observed deviation."
                ],
            },
        },
    }


def _build_minimal_translation_result(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "TRANSLATED",
        "translated_at": "2026-03-16T00:00:00+00:00",
        "model_outputs": {},
        "output_parameters": [],
        "assumptions": [],
        "confidence_summary": {},
        "schema_validation": {},
        "translation_support": {
            "review_notes": ["Low-confidence translation note."],
            "planner_note": "Planner review advised.",
            "missing_info_summary": "More evidence recommended.",
            "low_confidence_parameters": ["zip_model.constant_power_fraction"],
            "assumption_backed_parameters": [],
            "missing_dependency_parameters": [],
        },
        "governance_alerts": {
            "has_governance_attention": True,
            "planner_review_count": 1,
            "high_priority_manual_review_count": 2,
            "manual_review_queue_summary": {
                "total_count": 2,
                "conflict_count": 1,
                "interview_dependency_count": 1,
            },
        },
    }


def _build_minimal_scenario_result(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "SCENARIOS_GENERATED",
        "generated_at": "2026-03-16T00:00:00+00:00",
        "scenarios": {
            "Typical": {"label": "Typical"},
            "Conservative": {"label": "Conservative"},
        },
        "scenario_variants": [
            {"label": "Typical", "confidence": "LOW", "metadata": {"manual_review_queue_summary": {"total_count": 2}}},
            {"label": "Conservative", "confidence": "MODERATE", "metadata": {"manual_review_queue_summary": {"total_count": 2}}},
        ],
        "scenario_families": {
            "baseline": ["Typical"],
            "core_bounds": ["Conservative"],
        },
        "governance_alerts": {
            "has_governance_attention": True,
            "manual_review_queue_summary": {
                "total_count": 2,
                "conflict_count": 1,
                "interview_dependency_count": 1,
            },
        },
    }


def _build_minimal_ingestion_result() -> dict[str, Any]:
    return {
        "status": "ARTIFACTS_INGESTED",
        "artifact_count": 1,
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "file_name": "facility_one_line.pdf",
            }
        ],
        "intake_session": {
            "session_id": "intake_001",
            "session_path": "/tmp/intake_001.json",
            "status": "COMPLETE",
            "required_artifact_count": 1,
            "uploaded_artifact_count": 1,
            "missing_required_count": 0,
            "requirements": [
                {
                    "requirement_id": "req_001",
                    "label": "One-line diagram",
                    "required": True,
                    "state": "PROVIDED",
                }
            ],
        },
    }


def _write_agent_audit_file(run_dir: Path) -> None:
    agent_audit_dir = run_dir / "agent_audit"
    agent_audit_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_dir.name,
        "created_at": "2026-04-08T00:00:00+00:00",
        "agent_id": "adjudication_support_agent",
        "stage_name": "canonical_state",
        "task_name": "candidate_comparison",
        "status": "COMPLETED",
        "provider_mode": "llama_cpp_local",
        "policy": {"allowed": True},
        "request": {"associated_field_paths": ["facility.generators.rated_kw_per_unit"]},
        "prompt_payload": {},
        "response_payload": {"stronger_candidate_reasoning": "Exact-model manufacturer evidence outranked weaker contextual support."},
        "associated_field_paths": ["facility.generators.rated_kw_per_unit"],
        "trigger_reason": "Planner-critical conflict required adjudication support.",
    }
    (agent_audit_dir / "intake_clarification_agent_question_explanation_001.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def test_export_service_allows_engineer_and_writes_expected_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRIDSENPAI_AUDIT_MODE", "1")
    monkeypatch.setenv("GRIDSENPAI_DEBUG_MODE", "1")
    monkeypatch.setenv("GRIDSENPAI_EXPORT_PLANNER_PACKET_MD", "1")
    monkeypatch.setenv("GRIDSENPAI_EXPORT_PLANNER_PACKET_DOCX", "1")
    monkeypatch.setenv("GRIDSENPAI_EXPORT_TLDR_DOCX", "1")
    actor = Actor(
        actor_id="engineer_001",
        role=Role.ENGINEER,
        display_name="Engineer User",
        email="engineer@example.com",
    )
    context = _build_context(tmp_path, actor=actor)
    run_id = context.run_id
    _write_agent_audit_file(context.run_dir)

    result = run_service(
        context=context,
        canonical_state_result=_build_minimal_canonical_state_result(run_id),
        validation_result=_build_minimal_validation_result(run_id),
        translation_result=_build_minimal_translation_result(run_id),
        scenario_result=_build_minimal_scenario_result(run_id),
        ingestion_result=_build_minimal_ingestion_result(),
    )

    exports_dir = context.run_dir / "exports"

    assert result["status"] in {"EXPORTED", "EXPORTED_PROVISIONAL", "EXPORTED_BLOCKED"}
    assert exports_dir.exists()

    assert (exports_dir / "canonical_facility_state.json").exists()
    assert (exports_dir / "translated_parameters.json").exists()
    assert (exports_dir / "scenario_set.json").exists()
    assert (exports_dir / "planner_packet.md").exists()
    assert (exports_dir / "audit" / "packet_review.json").exists()
    assert (exports_dir / "debug" / "agent_orchestration_trace.json").exists()
    assert (exports_dir / "debug" / "field_agent_consumption_audit.json").exists()
    assert (exports_dir / "audit" / "manual_review_queue.json").exists()
    assert (exports_dir / "audit" / "planner_action_queue.json").exists()
    assert (exports_dir / "audit" / "escalation_registry.json").exists()
    assert (exports_dir / "audit" / "stage_transition_decisions.json").exists()
    assert (exports_dir / "audit" / "field_governance_registry.json").exists()
    assert (exports_dir / "audit" / "governed_release_decision.json").exists()

    packet_review = json.loads((exports_dir / "audit" / "packet_review.json").read_text(encoding="utf-8"))
    assert packet_review["packet_readiness"] in {"READY_WITH_WARNINGS", "REVIEW_REQUIRED", "READY"}
    assert packet_review["recommended_action_count"] >= 1
    assert packet_review["planner_action_queue_summary"]["total_count"] >= 1
    assert "downstream translation and scenario confidence" in packet_review["downstream_confidence_impact_summary"].lower()

    planner_packet_text = (exports_dir / "planner_packet.md").read_text(encoding="utf-8")
    assert "## Packet Review" in planner_packet_text
    assert "Recommended planner actions" in planner_packet_text
    assert "Downstream confidence impact" in planner_packet_text
    assert "low-confidence scenario variants" in planner_packet_text
    assert not (exports_dir / "planner_packet.txt").exists()
    assert not (exports_dir / "planner_packet.html").exists()
    assert (exports_dir / "planner_tldr_summary.json").exists()
    assert (exports_dir / "planner_tldr_summary.md").exists()
    assert (exports_dir / "planner_tldr_summary.docx").exists()
    assert (exports_dir / "run_manifest.json").exists()

    export_manifest = result.get("export_manifest", {})
    assert export_manifest.get("status") in {"EXPORTED", "EXPORTED_PROVISIONAL", "EXPORTED_BLOCKED"}
    assert export_manifest.get("run_id") == run_id
    assert export_manifest.get("exports", {}).get("planner_tldr_docx")

    agent_audit_summary = result.get("agent_audit_summary", {})
    assert agent_audit_summary.get("available") is True
    assert agent_audit_summary.get("audit_file_count") == 1
    assert agent_audit_summary.get("runtime_count") == 1
    assert "adjudication_support_agent" in agent_audit_summary.get("agent_ids", [])

    run_manifest = json.loads((exports_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["summary"]["agent_audit_file_count"] == 1
    assert run_manifest["summary"]["open_reconciliation_count"] == 1
    assert run_manifest["summary"]["agent_stage_trace_count"] >= 1
    assert run_manifest["summary"]["invoked_agent_count"] >= 1
    assert run_manifest["summary"]["field_agent_audit_count"] >= 1
    assert run_manifest["summary"]["field_agent_accepted_into_ledger_count"] >= 1
    assert run_manifest["summary"]["manual_review_queue_count"] >= 1
    assert run_manifest["summary"]["manual_review_interview_dependency_count"] >= 1
    assert run_manifest["summary"]["planner_action_queue_count"] >= 1
    assert run_manifest["summary"]["escalation_registry_field_count"] >= 1
    assert run_manifest["summary"]["stage_transition_field_count"] >= 1
    assert run_manifest["summary"]["field_governance_registry_field_count"] >= 1
    assert run_manifest["summary"]["governed_release_blocking_field_count"] >= 1
    assert run_manifest["replay"]["replay_ready"] is True

    orchestration_trace = json.loads((exports_dir / "debug" / "agent_orchestration_trace.json").read_text(encoding="utf-8"))
    assert orchestration_trace["summary"]["invoked_agent_count"] >= 1
    assert orchestration_trace["stage_trace"][0]["stage_name"] == "canonical_state"
    assert orchestration_trace["stage_trace"][0]["agents"][0]["agent_id"] == "adjudication_support_agent"
    assert orchestration_trace["stage_trace"][0]["agents"][0]["deterministic_disposition"] == "applied_as_advisory_support"

    field_agent_consumption_audit = json.loads((exports_dir / "debug" / "field_agent_consumption_audit.json").read_text(encoding="utf-8"))
    assert field_agent_consumption_audit["summary"]["field_count"] >= 1
    assert field_agent_consumption_audit["summary"]["accepted_into_ledger_count"] >= 1
    first_field = field_agent_consumption_audit["fields"][0]
    assert first_field["field_id"] == "generator_rated_kw_per_unit"
    assert first_field["agents"][0]["deterministic_disposition"] == "accepted_into_field_resolution_ledger"

    manual_review_queue = json.loads((exports_dir / "audit" / "manual_review_queue.json").read_text(encoding="utf-8"))
    planner_action_queue = json.loads((exports_dir / "audit" / "planner_action_queue.json").read_text(encoding="utf-8"))
    escalation_registry = json.loads((exports_dir / "audit" / "escalation_registry.json").read_text(encoding="utf-8"))
    stage_transition_decisions = json.loads((exports_dir / "audit" / "stage_transition_decisions.json").read_text(encoding="utf-8"))
    field_governance_registry = json.loads((exports_dir / "audit" / "field_governance_registry.json").read_text(encoding="utf-8"))
    governed_release_decision = json.loads((exports_dir / "audit" / "governed_release_decision.json").read_text(encoding="utf-8"))
    planner_trust_dashboard = json.loads((exports_dir / "audit" / "planner_trust_dashboard.json").read_text(encoding="utf-8"))
    planner_tldr_summary = json.loads((exports_dir / "planner_tldr_summary.json").read_text(encoding="utf-8"))
    assert manual_review_queue["summary"]["total_count"] >= 1
    assert manual_review_queue["summary"]["interview_dependency_count"] >= 1
    interview_item = manual_review_queue["groups"]["interview_dependency"][0]
    assert interview_item["field_id"] == "generator_rated_kw_per_unit"
    assert planner_action_queue["summary"]["total_count"] >= 1
    assert planner_action_queue["summary"]["field_linked_count"] >= 1
    assert planner_action_queue["summary"]["next_stage_counts"]
    assert planner_action_queue["actions"][0]["title"]
    assert planner_action_queue["actions"][0]["next_best_stage"]
    assert planner_action_queue["actions"][0]["action_scope"] in {"field", "run"}
    assert escalation_registry["summary"]["field_count"] >= 1
    assert escalation_registry["summary"]["unresolved_field_count"] >= 1
    assert escalation_registry["fields"][0]["current_handling_stage"]
    assert escalation_registry["fields"][0]["next_escalation_target"]
    assert stage_transition_decisions["summary"]["field_count"] >= 1
    assert stage_transition_decisions["fields"][0]["transition_decision"]
    assert field_governance_registry["summary"]["field_count"] >= 1
    assert field_governance_registry["fields"][0]["current_handling_stage"]
    assert governed_release_decision["summary"]["release_state"]
    assert governed_release_decision["summary"]["blocking_field_count"] >= 1
    assert planner_trust_dashboard["summary"]["release_state"]
    assert isinstance(planner_trust_dashboard["summary"].get("trust_posture_counts", {}), dict)
    assert planner_trust_dashboard["high_attention_fields"]
    assert planner_tldr_summary["summary"]["winner_count"] >= 1
    assert planner_tldr_summary["winner_fields"]
    assert planner_tldr_summary["manual_inspection_fields"]

    planner_packet = (exports_dir / "planner_packet.md").read_text(encoding="utf-8")
    assert "## Reconciliation Summary" in planner_packet
    assert "## Agent Audit Summary" in planner_packet
    assert "## Agent Orchestration Trace" in planner_packet
    assert "## Field-Level Agent Consumption Audit" in planner_packet
    assert "## Manual Review Queue" in planner_packet
    assert "## Planner Action Queue" in planner_packet
    assert "## Escalation Registry" in planner_packet
    assert "## Stage Transition Decisions" in planner_packet
    assert "## Unified Field Governance Registry" in planner_packet
    assert "## Governed Release Decision" in planner_packet
    assert "## Planner Trust Dashboard" in planner_packet
    assert "## Planner Review Guide" in planner_packet
    assert "## Field Resolution Appendix" in planner_packet
    assert "High-attention fields:" in planner_packet
    assert "Next best stage:" in planner_packet
    assert "Open reconciliations: 1" in planner_packet
    assert "Agents invoked: adjudication_support_agent" in planner_packet
    assert "Stage canonical_state:" in planner_packet
    assert "Generator rated kW per unit" in planner_packet


def test_export_service_handles_missing_agent_audit_directory(tmp_path: Path) -> None:
    actor = Actor(
        actor_id="engineer_002",
        role=Role.ENGINEER,
        display_name="Engineer User",
        email="engineer2@example.com",
    )
    context = _build_context(tmp_path, actor=actor)
    run_id = context.run_id

    result = run_service(
        context=context,
        canonical_state_result=_build_minimal_canonical_state_result(run_id),
        validation_result=_build_minimal_validation_result(run_id),
        translation_result=_build_minimal_translation_result(run_id),
        scenario_result=_build_minimal_scenario_result(run_id),
        ingestion_result=_build_minimal_ingestion_result(),
    )

    agent_audit_summary = result["agent_audit_summary"]
    assert agent_audit_summary["available"] is False
    assert agent_audit_summary["audit_file_count"] == 0
    assert agent_audit_summary["replay_ready"] is False

    run_manifest = json.loads(
        (context.run_dir / "exports" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert run_manifest["summary"]["agent_audit_file_count"] == 0
    assert run_manifest["replay"]["replay_ready"] is False


def test_export_service_denies_read_only_actor(tmp_path: Path) -> None:
    actor = Actor(
        actor_id="readonly_001",
        role=Role.READ_ONLY,
        display_name="Read Only User",
        email="readonly@example.com",
    )
    context = _build_context(tmp_path, actor=actor)
    run_id = context.run_id

    with pytest.raises(AuthorizationError):
        run_service(
            context=context,
            canonical_state_result=_build_minimal_canonical_state_result(run_id),
            validation_result=_build_minimal_validation_result(run_id),
            translation_result=_build_minimal_translation_result(run_id),
            scenario_result=_build_minimal_scenario_result(run_id),
            ingestion_result=_build_minimal_ingestion_result(),
        )


def test_export_service_requires_authenticated_actor(tmp_path: Path) -> None:
    context = _build_context(tmp_path, actor=None)
    run_id = context.run_id

    with pytest.raises(RuntimeError, match="authenticated actor"):
        run_service(
            context=context,
            canonical_state_result=_build_minimal_canonical_state_result(run_id),
            validation_result=_build_minimal_validation_result(run_id),
            translation_result=_build_minimal_translation_result(run_id),
            scenario_result=_build_minimal_scenario_result(run_id),
            ingestion_result=_build_minimal_ingestion_result(),
        )