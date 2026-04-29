from __future__ import annotations

from services.export_service.service import _build_planner_packet


def test_export_field_resolution_includes_contradiction_and_not_accepted_reason() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "generator_rated_kw_per_unit",
                    "label": "Generator rated kW per unit",
                    "accepted_status": "review_required",
                    "accepted_value": 3000,
                    "confidence_band": "MODERATE",
                    "accepted_source_hierarchy": "applicant_direct_document",
                    "accepted_specificity": "direct_field_match",
                    "decision_basis": "accepted_with_applicant_contradiction",
                    "applicant_answer_state": "applicant_conflicts_with_winner",
                    "contradiction_summary": "Applicant-confirmed value 3125 conflicts with the accepted value and requires review.",
                    "candidate_evidence_appendix": [
                        {
                            "value": 3000,
                            "source_anchor": "one_line.pdf / page 12 / Generator Schedule",
                            "source_hierarchy": "applicant_direct_document",
                            "specificity": "direct_field_match",
                            "consistency_notes": [],
                        }
                    ],
                    "why_accepted": ["Winner exceeded runner-up by 12.0 score points."],
                    "source_anchors": ["one_line.pdf / page 12 / Generator Schedule"],
                    "alternatives": [
                        {
                            "value": 3125,
                            "source_anchor": "engineer_input",
                            "source_hierarchy": "applicant_confirmed_answer",
                            "not_accepted_reason": "Score trailed accepted candidate by 12.0 points.",
                            "consistency_notes": [],
                        }
                    ],
                    "planner_critical": True,
                }
            ],
            "backlog": [],
        },
        "field_records": [],
    }
    packet = _build_planner_packet(
        run_id="run-export-contradiction",
        canonical_state=canonical_state,
        validation_result={"validation_report": {"missing_fields": [], "conflicts": [], "summary": {}}, "summary": {}},
        translation_result={"status": "ok", "output_parameters": []},
        scenario_result={},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "contradiction:" in packet
    assert "not accepted:" in packet
    assert "decision_basis=accepted_with_applicant_contradiction" in packet
    assert "applicant_state=applicant_conflicts_with_winner" in packet
