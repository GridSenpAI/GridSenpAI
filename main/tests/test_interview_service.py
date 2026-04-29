from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from services.interview_service.service import run_service


def _build_context(*, project_root: Path, input_dir: Path, run_id: str, project_name: str):
    run_dir = project_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        run_id=run_id,
        project_root=project_root,
        input_dir=input_dir,
        output_dir=run_dir / "outputs",
        run_dir=run_dir,
        config=SimpleNamespace(project_name=project_name),
    )


def test_interview_service_prefers_registry_question_wording_for_followups(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "facility.load_schedule.phase_1_mw",
                "reason": "Phase 1 MW missing.",
                "severity": "HIGH",
                "suggested_sources": ["Completed utility/ISO load information form"],
            },
        ]
    }

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_001",
        project_name="Test Project",
    )

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
    )

    assert result["status"] == "INTERVIEWS_INGESTED"
    assert result["questions"]

    question = result["questions"][0]
    assert question["field_path"] == "facility.load_schedule.phase_1_mw"
    assert question["question_id"] == "PEAK_DEMAND_MW"
    assert "question" in question
    assert question["question"]
    assert question["metadata"]["answer_type"] == "number"


def test_interview_service_persists_session_and_tracks_answered_inferred_and_missing_fields(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    interview_payload = {
        "answers": [
            {
                "question_id": "FACILITY_POI_VOLTAGE_KV",
                "field_path": "facility.poi_voltage_kv",
                "answer": "138",
            }
        ]
    }
    (input_dir / "facility_intake.json").write_text(
        json.dumps(interview_payload, indent=2),
        encoding="utf-8",
    )

    extraction_result = {
        "schema_field_candidates": [
            {
                "candidate_id": "cand_001",
                "field_path": "facility.transformers.count",
                "confidence_label": "HIGH",
                "confidence": 0.92,
                "source_method": "heuristic",
            },
            {
                "candidate_id": "cand_002",
                "field_path": "facility.ups.topology",
                "confidence_label": "LOW",
                "confidence": 0.41,
                "source_method": "heuristic",
            },
        ]
    }

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "facility.poi_voltage_kv",
                "reason": "POI voltage missing.",
                "severity": "HIGH",
                "suggested_sources": ["one-line diagram"],
            },
            {
                "question_id": "fq_002",
                "field_path": "facility.load_schedule.phase_1_mw",
                "reason": "Phase 1 MW missing.",
                "severity": "HIGH",
                "suggested_sources": ["load letter"],
            },
        ]
    }

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_001",
        project_name="Test Project",
    )

    result = run_service(
        context=context,
        extraction_result=extraction_result,
        normalization_result=normalization_result,
    )

    assert result["status"] == "INTERVIEWS_INGESTED"
    assert "interview_session" in result
    assert "field_tracking" in result
    assert "session_summary" in result

    field_tracking = result["field_tracking"]
    assert "facility.poi_voltage_kv" in field_tracking["answered"]
    assert "facility.transformers.count" in field_tracking["inferred"]
    assert "facility.load_schedule.phase_1_mw" in field_tracking["missing"]
    assert "facility.poi_voltage_kv" not in field_tracking["missing"]

    session = result["interview_session"]
    assert session["status"] == "IN_PROGRESS"
    assert session["summary"]["answers_confirmed_count"] == 1
    assert session["summary"]["missing_field_count"] == 2

    session_path = Path(session["session_path"])
    assert session_path.exists()


def test_interview_service_resumes_session_and_clears_answered_missing_field_from_open_questions(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    first_payload = {
        "answers": [
            {
                "question_id": "FACILITY_POI_VOLTAGE_KV",
                "field_path": "facility.poi_voltage_kv",
                "answer": "138",
            }
        ]
    }
    (input_dir / "facility_intake.json").write_text(
        json.dumps(first_payload, indent=2),
        encoding="utf-8",
    )

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "facility.poi_voltage_kv",
                "reason": "POI voltage missing.",
                "severity": "HIGH",
                "suggested_sources": ["one-line diagram"],
            },
            {
                "question_id": "fq_002",
                "field_path": "facility.load_schedule.phase_1_mw",
                "reason": "Phase 1 MW missing.",
                "severity": "HIGH",
                "suggested_sources": ["load letter"],
            },
        ]
    }

    first_context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_001",
        project_name="Test Project",
    )
    first_result = run_service(
        context=first_context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
    )

    first_session = first_result["interview_session"]
    assert first_session["status"] == "IN_PROGRESS"
    assert "facility.load_schedule.phase_1_mw" in first_session["field_tracking"]["missing"]

    second_payload = {
        "answers": [
            {
                "question_id": "FACILITY_POI_VOLTAGE_KV",
                "field_path": "facility.poi_voltage_kv",
                "answer": "138",
            },
            {
                "question_id": "REQUESTED_PEAK_DEMAND_MW",
                "field_path": "facility.load_schedule.phase_1_mw",
                "answer": "42",
            },
        ]
    }
    (input_dir / "facility_intake.json").write_text(
        json.dumps(second_payload, indent=2),
        encoding="utf-8",
    )

    second_context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_002",
        project_name="Test Project",
    )
    second_result = run_service(
        context=second_context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
    )

    second_session = second_result["interview_session"]
    assert second_session["status"] == "COMPLETE"
    assert second_session["field_tracking"]["missing"] == []
    assert second_session["summary"]["answers_confirmed_count"] == 2

    answered = set(second_session["field_tracking"]["answered"])
    assert answered == {
        "facility.poi_voltage_kv",
        "facility.load_schedule.phase_1_mw",
    }

def test_interview_service_records_agent_focus_summary_and_blockers(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "facility.poi_voltage_kv",
                "reason": "POI voltage conflict.",
                "severity": "HIGH",
                "suggested_sources": ["one-line diagram"],
            },
            {
                "question_id": "fq_002",
                "field_path": "facility.ups.topology",
                "reason": "UPS topology review required.",
                "severity": "HIGH",
                "suggested_sources": ["electrical single line"],
            },
        ]
    }

    canonical_state_result = {
        "canonical_state": {
            "planner_registry_resolution_backlog": [
                {
                    "field_id": "ups_topology",
                    "field_path": "facility.ups.topology",
                    "label": "UPS Topology",
                    "accepted_status": "review_required",
                    "needs_applicant_confirmation": True,
                    "planner_attention_tier": "HIGH",
                    "confidence_band": "MODERATE",
                }
            ]
        }
    }

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_003",
        project_name="Test Project",
    )

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
    )

    oversight = result["interview_oversight"]
    assert oversight["agent_id"] == "applicant_interview_agent"
    assert oversight["interview_focus_summary"]
    assert isinstance(oversight["blocker_field_paths"], list)

    session_summary = result["session_summary"]
    assert "blocker_field_count" in session_summary
    assert "interview_focus_summary" in session_summary
    assert "governed_release_state" in session_summary
    assert session_summary["question_count"] >= 1


def test_interview_service_uses_shared_manual_review_priority_for_question_order(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "facility.poi_voltage_kv",
                "reason": "POI voltage conflict.",
                "severity": "HIGH",
                "suggested_sources": ["one-line diagram"],
            },
            {
                "question_id": "fq_002",
                "field_path": "facility.ups.topology",
                "reason": "UPS topology review required.",
                "severity": "HIGH",
                "suggested_sources": ["electrical single line"],
            },
        ]
    }

    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "ledger": [
                    {
                        "field_id": "ups_topology",
                        "field_path": "facility.ups.topology",
                        "label": "UPS Topology",
                        "accepted_status": "review_required",
                        "needs_applicant_confirmation": True,
                        "planner_critical": True,
                        "confidence_band": "MODERATE",
                        "unresolved_reason": "Applicant must confirm UPS topology.",
                    },
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "label": "POI Voltage",
                        "accepted_status": "conflicting",
                        "planner_critical": True,
                        "confidence_band": "LOW",
                        "contradiction_summary": "Conflicting POI voltage evidence remains.",
                    },
                ]
            }
        }
    }

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_004",
        project_name="Test Project",
    )

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
    )

    questions = result["questions"]
    assert questions[0]["field_path"] == "facility.ups.topology"
    oversight = result["interview_oversight"]
    assert oversight["review_priority_counts"]["interview_dependency"] >= 1
    assert oversight["question_sequence"][0] == questions[0]["question_id"]
    assert result["session_summary"]["manual_review_interview_dependency_count"] >= 1
    assert oversight["planner_action_queue_summary"]["total_count"] >= 1
    assert oversight["planner_action_queue_summary"]["next_stage_counts"]["applicant_interview"] >= 1
    assert oversight["escalation_registry_summary"]["field_count"] >= 1
    assert oversight["stage_transition_summary"]["field_count"] >= 1
    assert oversight["field_governance_summary"]["field_count"] >= 1


def test_interview_service_applies_document_field_pack_question_suppression(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "Attachment_I_Interconnection_Study_Report.pdf").write_text("placeholder", encoding="utf-8")

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "facility.generators.count",
                "reason": "Generator count missing.",
                "severity": "HIGH",
                "suggested_sources": ["interconnection study"],
            },
            {
                "question_id": "fq_002",
                "field_path": "facility.relay_settings",
                "reason": "Relay settings summary missing.",
                "severity": "HIGH",
                "suggested_sources": ["interconnection study"],
            },
        ]
    }

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_003",
        project_name="Test Project",
    )

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
    )

    question_fields = {item["field_path"] for item in result["questions"]}
    assert "facility.generators.count" not in question_fields
    assert "facility.relay_settings" in question_fields
    assert "interconnection_study" in result["interview_session"]["field_tracking"]["document_field_pack"]["document_classes"]


def test_interview_service_triages_blocking_questions_ahead_of_informational(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "facility.poi_voltage_kv",
                "reason": "POI voltage conflict.",
                "severity": "HIGH",
                "suggested_sources": ["one-line diagram"],
            },
            {
                "question_id": "fq_002",
                "field_path": "facility.site_notes",
                "reason": "Site notes missing.",
                "severity": "LOW",
                "suggested_sources": ["facility narrative"],
            },
        ]
    }

    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "ledger": [
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "accepted_status": "conflicting",
                        "planner_critical": True,
                        "confidence_band": "LOW",
                        "conflict_materiality": "high",
                    },
                    {
                        "field_id": "site_notes",
                        "field_path": "facility.site_notes",
                        "accepted_status": "unresolved",
                        "planner_critical": False,
                        "confidence_band": "LOW",
                    },
                ]
            }
        }
    }

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_triage_001",
        project_name="Test Project",
    )

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
    )

    questions = result["questions"]
    assert questions[0]["field_path"] == "facility.poi_voltage_kv"
    assert questions[0]["triage_bucket"] == "planner_critical_blocking"
    assert any(item["triage_bucket"] == "informational" for item in questions)
    assert result["session_summary"]["planner_critical_blocking_question_count"] >= 1


def test_interview_service_suppresses_low_yield_confirmations_backed_by_high_confidence_resolution(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "facility.site_notes",
                "reason": "Please confirm the site notes.",
                "severity": "LOW",
                "suggested_sources": ["facility narrative"],
            },
            {
                "question_id": "fq_002",
                "field_path": "facility.poi_voltage_kv",
                "reason": "POI voltage conflict.",
                "severity": "HIGH",
                "suggested_sources": ["one-line diagram"],
            },
        ]
    }

    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "ledger": [
                    {
                        "field_id": "site_notes",
                        "field_path": "facility.site_notes",
                        "accepted_status": "resolved",
                        "planner_critical": False,
                        "confidence_band": "HIGH",
                        "accepted_confidence": 0.96,
                        "needs_applicant_confirmation": False,
                    },
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "accepted_status": "conflicting",
                        "planner_critical": True,
                        "confidence_band": "LOW",
                        "conflict_materiality": "high",
                    },
                ]
            }
        }
    }

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_triage_002",
        project_name="Test Project",
    )

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
    )

    question_fields = {item["field_path"] for item in result["questions"]}
    assert "facility.site_notes" not in question_fields
    assert "facility.poi_voltage_kv" in question_fields
    assert result["session_summary"]["suppressed_low_yield_question_count"] >= 1
    assert result["interview_oversight"]["suppressed_low_yield_questions"]


def test_interview_service_sequences_immediate_questions_before_deferred(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_info",
                "field_path": "facility.site_notes",
                "reason": "Helpful context note.",
                "severity": "LOW",
                "suggested_sources": ["site narrative"],
            },
            {
                "question_id": "fq_block",
                "field_path": "facility.poi_voltage_kv",
                "reason": "POI voltage conflict.",
                "severity": "HIGH",
                "suggested_sources": ["one-line diagram"],
            },
            {
                "question_id": "fq_confirm",
                "field_path": "facility.ups.topology",
                "reason": "UPS topology confirmation.",
                "severity": "HIGH",
                "suggested_sources": ["electrical single line"],
            },
        ]
    }

    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "ledger": [
                    {
                        "field_id": "site_notes",
                        "field_path": "facility.site_notes",
                        "label": "Site Notes",
                        "accepted_status": "missing",
                        "planner_critical": False,
                        "confidence_band": "LOW",
                        "unresolved_reason": "Optional narrative field remains blank.",
                    },
                    {
                        "field_id": "ups_topology",
                        "field_path": "facility.ups.topology",
                        "label": "UPS Topology",
                        "accepted_status": "review_required",
                        "needs_applicant_confirmation": True,
                        "planner_critical": True,
                        "confidence_band": "MODERATE",
                        "unresolved_reason": "Applicant must confirm UPS topology.",
                    },
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "label": "POI Voltage",
                        "accepted_status": "conflicting",
                        "planner_critical": True,
                        "confidence_band": "LOW",
                        "contradiction_summary": "Conflicting POI voltage evidence remains.",
                    },
                ]
            }
        }
    }

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_005",
        project_name="Test Project",
    )

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
    )

    questions = result["questions"]
    ordered_fields = [item["field_path"] for item in questions]
    assert ordered_fields[:2] == ["facility.ups.topology", "facility.poi_voltage_kv"]
    assert ordered_fields[-1] == "facility.site_notes"

    oversight = result["interview_oversight"]
    assert oversight["initial_focus_question_count"] == 2
    assert oversight["deferred_question_count"] >= 1


def test_interview_service_can_generate_questions_from_missing_fields_without_normalization_followups(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_missing_only",
        project_name="Test Project",
    )

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": [], "unresolved_fields": ["facility.poi_voltage_kv"]},
        normalization_result={"followup_questions": [], "validation_report": {"missing_fields": ["facility.poi_voltage_kv"]}},
        retrieval_result={"validation_report": {"missing_fields": ["facility.poi_voltage_kv"]}},
    )

    assert result["status"] == "INTERVIEWS_INGESTED"
    assert result["questions"]
    assert any(question.get("field_path") == "facility.poi_voltage_kv" for question in result["questions"])


def test_interview_service_prefers_registry_backlog_question_over_normalization_duplicate(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_dedupe",
        project_name="Test Project",
    )

    normalization_result = {
        "followup_questions": [
            {
                "question_id": "fq_001",
                "field_path": "generator_model",
                "reason": "Generator model is missing.",
                "severity": "HIGH",
                "planner_critical": True,
                "field_id": "generator_model",
            }
        ]
    }
    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "backlog": [
                    {
                        "field_id": "generator_model",
                        "field_path": "generator_model",
                        "label": "Generator model",
                        "accepted_status": "missing",
                        "requiredness": "required",
                        "planner_critical": True,
                        "resolution_priority": 1,
                    }
                ]
            },
            "validation_report": {},
        }
    }

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
    )

    questions = [item for item in result["questions"] if item.get("field_path") == "generator_model"]
    assert len(questions) == 1
    assert questions[0]["source"] == "planner_registry_resolution_backlog"



def test_interview_service_filters_broad_normalization_missing_fields_when_governed_release_is_ready(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_ready",
        project_name="Test Project",
    )

    normalization_result = {
        "followup_questions": [],
        "validation_report": {
            "missing_fields": [
                "generator_model",
                "generator_manufacturer",
                "facility.poi_voltage_kv",
            ]
        },
    }
    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {"backlog": []},
            "validation_report": {},
            "governed_truth_summary": {},
            "field_records": [],
            "review_flags": [],
        }
    }

    result = run_service(
        context=context,
        extraction_result={"schema_field_candidates": []},
        normalization_result=normalization_result,
        canonical_state_result=canonical_state_result,
    )

    assert result["questions"] == []
    assert result["session_summary"]["question_count"] == 0
