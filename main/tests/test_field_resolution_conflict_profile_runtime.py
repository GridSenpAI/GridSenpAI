from __future__ import annotations

from services.export_service.service import _build_planner_packet
from services.field_resolution_service.service import build_field_resolution_result
from services.interview_service.service import _build_questions_from_registry_resolution_backlog


def test_field_resolution_emits_runner_up_and_conflict_profiles_for_material_conflict() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "official-138",
                "field_path": "interconnection.point_of_interconnection_voltage_kv",
                "value": 138,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.91,
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
            {
                "field_record_id": "legacy-115-b",
                "field_path": "interconnection.point_of_interconnection_voltage_kv",
                "value": 115,
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.76,
                "evidence_strength": "MODERATE",
                "source_ref": ["normalized_legacy_poi"],
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "source_method": "normalized_schedule_alignment",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "point_of_interconnection_voltage_kv")

    assert entry["accepted_value"] == 138
    assert entry["runner_up_profile"]["value"] == 115
    assert entry["runner_up_profile"]["group_independent_source_count"] >= 1
    assert entry["conflict_profile"]["has_runner_up_conflict"] is True
    assert entry["conflict_profile"]["conflict_materiality"] in {"medium", "high"}
    assert "Runner-up value 115" in entry["conflict_profile"]["summary_text"]


def test_interview_reason_includes_runner_up_conflict_profile_summary() -> None:
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
                        },
                        "dominance_profile": {
                            "dominance_level": "narrow",
                            "winner_group_independent_source_count": 1,
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
    assert "Runner-up support" in questions[0]["question"]
    assert "Runner-up conflict profile" in questions[0]["reason"]


def test_export_packet_surfaces_runner_up_support_and_conflict_profile() -> None:
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
                    "decision_basis": "accepted_from_governed_adjudication",
                    "why_accepted": ["Official interconnection source ranked highest."],
                    "source_anchors": ["official_interconnection.pdf:p2"],
                    "alternatives": [{"value": 115, "source_anchor": "legacy_one_line.pdf:p9", "not_accepted_reason": "Source hierarchy ranked below the accepted candidate."}],
                    "runner_up_profile": {
                        "value": 115,
                        "source_hierarchy": "applicant_direct_document",
                        "specificity": "direct_field_match",
                        "group_independent_source_count": 2,
                    },
                    "conflict_profile": {
                        "summary_text": "Runner-up value 115 remains plausible; numeric delta 16.7%; materiality=medium; group source delta=-1",
                    },
                    "planner_review_flag": True,
                    "needs_applicant_confirmation": True,
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
    assert "  - conflict_profile: Runner-up value 115 remains plausible; numeric delta 16.7%; materiality=medium; group source delta=-1" in payload
    assert "    - runner_up_support: applicant_direct_document; direct_field_match; 2 independent source trace(s)" in payload
