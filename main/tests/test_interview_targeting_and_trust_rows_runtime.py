from __future__ import annotations

import os
import pytest

from services.export_service.service import _build_planner_packet
from services.field_resolution_service.service import build_field_resolution_result
from services.interview_service.service import _build_questions_from_registry_resolution_backlog

requires_audit_mode = pytest.mark.skipif(os.getenv("GRIDSENPAI_AUDIT_MODE", "0") != "1", reason="Audit-mode planner packet sections are disabled in current environment.")

def test_field_resolution_emits_applicant_question_profile_and_trust_row() -> None:
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

    assert entry["applicant_question_profile"]["should_ask_now"] is True
    assert entry["applicant_question_profile"]["question_strategy"] in {"resolve_material_conflict", "confirm_provisional_value"}
    assert entry["planner_trust_row"]["trust_posture"] in {"contested", "provisional"}
    assert entry["planner_trust_row"]["planner_action"] in {"ask_applicant_now", "planner_review_before_use"}
    assert entry["field_release_profile"]["release_state"] == "BLOCKED"
    assert entry["field_release_profile"]["translation_use_policy"] == "hold_from_modeled_output"


def test_interview_questions_use_applicant_question_profile_priority_and_reasoning() -> None:
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
                            "source_hierarchy": "applicant_direct_document",
                            "source_anchor": "legacy_one_line.pdf:p9",
                            "group_independent_source_count": 2,
                        },
                        "conflict_profile": {
                            "summary_text": "Runner-up value 115 remains plausible; materiality=medium; group source delta=-1",
                            "conflict_materiality": "medium",
                            "requires_applicant_decision": True,
                        },
                        "dominance_profile": {
                            "dominance_level": "narrow",
                            "winner_group_independent_source_count": 1,
                        },
                        "applicant_question_profile": {
                            "question_category": "confirmation",
                            "question_strategy": "confirm_provisional_value",
                            "interview_priority_score": 455,
                            "selection_rationale": [
                                "Runner-up conflict is still material enough that the applicant should decide the final engineering value.",
                                "This field remains planner-critical and still carries review posture downstream.",
                            ],
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
    assert questions[0]["priority"] == 455
    assert questions[0]["question_category"] == "confirmation"
    assert "Please confirm whether the current best-supported value" in questions[0]["question"]
    assert "Interview targeting:" in questions[0]["reason"]


@requires_audit_mode
def test_export_packet_includes_planner_field_trust_rows() -> None:
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
                    "why_accepted": ["Official interconnection source ranked highest."],
                    "alternatives": [{"value": 115, "source_anchor": "legacy_one_line.pdf:p9", "not_accepted_reason": "Source hierarchy ranked below the accepted candidate."}],
                    "runner_up_profile": {
                        "value": 115,
                        "group_independent_source_count": 2,
                    },
                    "conflict_profile": {
                        "runner_up_plausibility": "credible_runner_up_conflict",
                    },
                    "planner_review_flag": True,
                    "needs_applicant_confirmation": True,
                    "planner_trust_row": {
                        "label": "POI Service Voltage",
                        "accepted_value": 138,
                        "status": "review_required",
                        "confidence_band": "MODERATE",
                        "trust_posture": "contested",
                        "planner_action": "ask_applicant_now",
                        "support_summary": "winner_sources=1; runner_up_sources=2; dominance=narrow",
                        "runner_up_value": 115,
                        "runner_up_plausibility": "credible_runner_up_conflict",
                    },
                    "field_release_profile": {
                        "release_state": "BLOCKED",
                        "export_readiness_tier": "blocked",
                        "translation_use_policy": "hold_from_modeled_output",
                        "scenario_use_policy": "hold_for_review_variant_only",
                        "planner_packet_use_policy": "show_as_provisional_with_blocker",
                        "reason_summary": "Field is not safe for modeled downstream use until the governing blocker is resolved.",
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
    assert "## Field Export Readiness Matrix" in payload
    assert "POI Service Voltage: BLOCKED [blocked]" in payload
    assert "  - translation_policy: hold_from_modeled_output" in payload
    assert "## Planner Field Trust Rows" in payload
    assert "POI Service Voltage: 138 [review_required; MODERATE; contested] -> ask_applicant_now" in payload
    assert "  - support: winner_sources=1; runner_up_sources=2; dominance=narrow" in payload
    assert "  - runner_up: 115" in payload
    assert "  - runner_up_posture: credible_runner_up_conflict" in payload
