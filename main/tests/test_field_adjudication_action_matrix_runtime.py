from __future__ import annotations

import os
import pytest

from services.export_service.service import _build_planner_packet
from services.field_resolution_service.service import build_field_resolution_result
from services.interview_service.service import _build_questions_from_registry_resolution_backlog

requires_audit_mode = pytest.mark.skipif(os.getenv("GRIDSENPAI_AUDIT_MODE", "0") != "1", reason="Audit-mode planner packet sections are disabled in current environment.")

def test_field_resolution_emits_adjudication_trace_with_runner_up_loss_and_next_action() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "official-138",
                "field_path": "interconnection.point_of_interconnection_voltage_kv",
                "value": 138,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.9,
                "evidence_strength": "STRONG",
                "source_ref": ["official_interconnection.pdf"],
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "source_method": "official_interconnection_source",
                    "specificity": "direct_field_match",
                },
            },
            {
                "field_record_id": "legacy-115-a",
                "field_path": "interconnection.point_of_interconnection_voltage_kv",
                "value": 115,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.82,
                "evidence_strength": "STRONG",
                "source_ref": ["legacy_one_line.pdf"],
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "source_method": "table_extract",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "point_of_interconnection_voltage_kv")

    trace = entry["adjudication_trace"]
    assert trace["winner_summary"]
    assert any("official interconnection source" in part.lower() for part in trace["winner_reason_chain"])
    assert "Runner-up 115" in trace["runner_up_summary"]
    assert trace["next_action"]["action"] in {"ask_applicant_now", "planner_review_before_use"}
    assert trace["release_summary"]


def test_interview_reason_carries_adjudication_trace() -> None:
    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "backlog": [
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "interconnection.point_of_interconnection_voltage_kv",
                        "label": "POI Service Voltage",
                        "accepted_status": "review_required",
                        "status": "review_required",
                        "accepted_value": 138,
                        "alternatives": [{"value": 115}],
                        "why_accepted": ["Official interconnection source ranked highest."],
                        "runner_up_profile": {
                            "value": 115,
                            "not_accepted_reason": "Source hierarchy ranked below the accepted candidate.",
                        },
                        "conflict_profile": {
                            "summary_text": "Runner-up value 115 remains plausible; materiality=medium; group source delta=-1",
                            "conflict_materiality": "medium",
                            "requires_applicant_decision": True,
                        },
                        "applicant_question_profile": {
                            "question_category": "confirmation",
                            "question_strategy": "confirm_provisional_value",
                            "interview_priority_score": 455,
                        },
                        "adjudication_trace": {
                            "planner_narrative": "POI Service Voltage accepted 138 with status review_required and confidence MODERATE. Official interconnection source ranked highest. Runner-up 115 lost because Source hierarchy ranked below the accepted candidate.",
                        },
                        "resolution_priority": 1,
                        "requiredness": "required",
                        "planner_critical": True,
                    }
                ]
            }
        }
    }
    questions = _build_questions_from_registry_resolution_backlog(canonical_state_result, set())
    assert questions
    assert "Adjudication trace:" in questions[0]["reason"]
    assert "Runner-up 115 lost because" in questions[0]["reason"]


@requires_audit_mode
def test_export_packet_includes_field_adjudication_action_matrix() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "field_path": "interconnection.point_of_interconnection_voltage_kv",
                    "label": "POI Service Voltage",
                    "packet_section": "site_and_interconnection_context",
                    "packet_section_label": "Site & Interconnection Context",
                    "requiredness": "required",
                    "planner_critical": True,
                    "accepted_status": "review_required",
                    "accepted_value": 138,
                    "accepted_confidence": 0.83,
                    "confidence_band": "MODERATE",
                    "planner_review_flag": True,
                    "needs_applicant_confirmation": True,
                    "field_release_profile": {
                        "release_state": "BLOCKED",
                    },
                    "adjudication_trace": {
                        "winner_summary": "Official interconnection source ranked highest.",
                        "runner_up_summary": "Runner-up 115 lost because Source hierarchy ranked below the accepted candidate.",
                        "release_summary": "Field is not safe for modeled downstream use until the governing blocker is resolved.",
                        "next_action": {
                            "action": "ask_applicant_now",
                            "owner": "applicant",
                        },
                    },
                }
            ],
            "summary": {"accepted_field_index_count": 1},
        },
        "entities": [],
        "field_records": [],
    }
    payload = _build_planner_packet(
        run_id="run-1",
        canonical_state=canonical_state,
        validation_result={"validation_report": {}},
        translation_result={"output_parameters": [], "model_outputs": {}, "assumptions": [], "confidence_summary": {}},
        scenario_result={"scenarios": {}},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "## Field Adjudication Action Matrix" in payload
    assert "POI Service Voltage: BLOCKED -> ask_applicant_now (applicant)" in payload
    assert "  - winner: Official interconnection source ranked highest." in payload
    assert "  - runner_up: Runner-up 115 lost because Source hierarchy ranked below the accepted candidate." in payload
