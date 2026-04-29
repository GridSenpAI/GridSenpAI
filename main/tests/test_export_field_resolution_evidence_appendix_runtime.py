from __future__ import annotations

from services.export_service.service import _build_planner_packet


def test_export_field_resolution_includes_evidence_appendix() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "generator_rated_kw_per_unit",
                    "label": "Generator rated kW per unit",
                    "accepted_status": "review_required",
                    "accepted_value": 3125,
                    "confidence_band": "MODERATE",
                    "accepted_source_hierarchy": "applicant_confirmed_answer",
                    "accepted_specificity": "direct_field_match",
                    "candidate_evidence_appendix": [
                        {
                            "value": 3125,
                            "source_anchor": "facility_intake.json",
                            "source_hierarchy": "applicant_confirmed_answer",
                            "specificity": "direct_field_match",
                            "consistency_notes": ["Generator rating basis aligns with related generator operating basis evidence."],
                        },
                        {
                            "value": 3000,
                            "source_anchor": "one_line.pdf / page 12 / Generator Schedule",
                            "source_hierarchy": "applicant_direct_document",
                            "specificity": "direct_field_match",
                            "consistency_notes": [],
                        },
                    ],
                    "why_accepted": ["Applicant-confirmed interview evidence supports this value."],
                    "source_anchors": ["facility_intake.json"],
                    "alternatives": [],
                    "planner_critical": True,
                }
            ],
            "backlog": [],
        },
        "field_records": [],
    }
    packet = _build_planner_packet(
        run_id="run-export-evidence",
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
    assert "## Field Resolution Evidence Appendix" in packet
    assert "applicant_confirmed_answer" in packet
    assert "facility_intake.json" in packet
