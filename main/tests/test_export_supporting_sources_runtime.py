from __future__ import annotations

from services.export_service.service import _build_planner_packet


def test_export_field_resolution_includes_supporting_sources_and_stream_counts() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "generator_rated_kw_per_unit",
                    "label": "Generator rated kW per unit",
                    "accepted_status": "review_required",
                    "accepted_value": 3125,
                    "confidence_band": "MODERATE",
                    "accepted_source_hierarchy": "manufacturer_model_specific_spec",
                    "accepted_specificity": "exact_model_match",
                    "candidate_evidence_appendix": [
                        {
                            "value": 3125,
                            "source_stream": "vendor_pdf",
                            "source_anchor": "vendor/cummins_xyz_datasheet.pdf",
                            "source_hierarchy": "manufacturer_model_specific_spec",
                            "specificity": "exact_model_match",
                            "consistency_notes": [],
                        }
                    ],
                    "supporting_sources": [
                        {
                            "source_stream": "official_web",
                            "source_type": "official_web_lookup_plan",
                            "source_ref": "https://www.cummins.com/generators/xyz",
                            "target_fields": ["generator_rated_kw_per_unit"],
                        }
                    ],
                    "source_stream_counts": {"vendor_pdf": 1, "official_web": 1},
                    "why_accepted": ["Model-specific vendor evidence ranked highest."],
                    "source_anchors": ["vendor/cummins_xyz_datasheet.pdf"],
                    "alternatives": [],
                    "decision_basis": "accepted_from_governed_adjudication",
                    "applicant_answer_state": "none",
                    "planner_critical": True,
                }
            ],
            "backlog": [],
        },
        "field_records": [],
    }
    packet = _build_planner_packet(
        run_id="run-export-supporting-sources",
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
    assert "source_streams: official_web=1, vendor_pdf=1" in packet
    assert "supporting_source: official_web / official_web_lookup_plan" in packet
