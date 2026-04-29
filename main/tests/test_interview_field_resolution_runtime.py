from __future__ import annotations

from services.interview_service.service import _build_questions_from_registry_resolution_backlog


def test_interview_uses_field_resolution_backlog_when_present() -> None:
    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "backlog": [
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "label": "POI nominal voltage kV",
                        "accepted_status": "review_required",
                        "requiredness": "required",
                        "planner_critical": True,
                        "packet_section": "interconnection_topology",
                        "packet_section_label": "Interconnection Topology",
                        "resolution_priority": 1,
                        "preferred_sources": ["applicant one-line diagram"],
                    }
                ]
            }
        }
    }
    questions = _build_questions_from_registry_resolution_backlog(canonical_state_result, set())
    assert questions
    assert questions[0]["source"] == "planner_registry_resolution_backlog"
    assert questions[0]["metadata"]["planner_registry_backed"] is True


def test_interview_backlog_questions_prioritize_high_materiality_and_preserve_governance_context() -> None:
    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "backlog": [
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "label": "POI nominal voltage kV",
                        "accepted_status": "review_required",
                        "accepted_value": 138.0,
                        "accepted_confidence": 0.62,
                        "confidence_band": "MODERATE",
                        "requiredness": "required",
                        "planner_critical": True,
                        "packet_section": "interconnection_topology",
                        "packet_section_label": "Interconnection Topology",
                        "resolution_priority": 4,
                        "preferred_sources": ["applicant one-line diagram"],
                        "alternatives": [{"value": 69.0}],
                        "source_anchors": ["one_line_drawing_page_12_table_3"],
                        "source_ref": ["artifact_one_line"],
                        "supporting_sources": [
                            {"source_ref": ["artifact_vendor_pdf"], "value": 138.0},
                        ],
                        "candidate_summary": {
                            "candidate_count": 3,
                            "distinct_value_count": 2,
                            "supporting_source_count": 2,
                        },
                        "conflict_materiality": "high",
                        "planner_attention_tier": "critical",
                        "needs_applicant_confirmation": True,
                        "planner_review_flag": True,
                        "acceptance_margin": 0.08,
                        "why_accepted": ["Matches the one-line schedule."],
                        "contradiction_summary": "Applicant schedule and vendor spec disagree on POI voltage.",
                        "unresolved_reason": "Material voltage disagreement changes interconnection assumptions",
                    },
                    {
                        "field_id": "generator_unit_count",
                        "field_path": "facility.generators.count",
                        "label": "Generator unit count",
                        "accepted_status": "missing",
                        "requiredness": "required",
                        "planner_critical": True,
                        "resolution_priority": 2,
                    },
                ],
            },
            "field_resolution_overview": {
                "planner_review_queue": [
                    {"field_path": "facility.poi_voltage_kv", "planner_review_flag": True},
                ],
                "high_materiality_conflicts": [
                    {"field_path": "facility.poi_voltage_kv", "conflict_materiality": "high"},
                ],
            },
            "field_records": [
                {
                    "field_path": "facility.poi_voltage_kv",
                    "value": 138.0,
                    "status": "review_required",
                }
            ],
            "validation_report": {},
        }
    }

    questions = _build_questions_from_registry_resolution_backlog(canonical_state_result, set())
    assert questions
    assert questions[0]["field_path"] == "facility.poi_voltage_kv"
    assert questions[0]["question_category"] == "conflicting"
    assert "Runner-up value found" in questions[0]["question"]
    assert questions[0]["metadata"]["conflict_materiality"] == "high"
    assert questions[0]["metadata"]["candidate_summary"]["candidate_count"] == 3
    assert questions[0]["metadata"]["source_anchors"] == ["one_line_drawing_page_12_table_3"]
    assert set(questions[0]["related_artifact_ids"]) == {"artifact_one_line", "artifact_vendor_pdf"}
    assert "Material voltage disagreement changes interconnection assumptions" in questions[0]["reason"]
    assert questions[0]["metadata"]["governance_summary"]["high_materiality_conflict_count"] >= 1
