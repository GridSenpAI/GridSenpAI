from __future__ import annotations

from services.export_service.service import _build_planner_packet


def test_export_field_resolution_includes_anchors_and_hierarchy_for_alternatives() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "generator_rated_kw_per_unit",
                    "label": "Generator rated kW per unit",
                    "accepted_status": "review_required",
                    "accepted_value": 3125,
                    "confidence_band": "MODERATE",
                    "why_accepted": ["Source hierarchy favored manufacturer model specific spec."],
                    "source_anchors": ["cummins_xyz.pdf / page 2 / Ratings"],
                    "alternatives": [
                        {
                            "value": 3000,
                            "source_anchor": "one_line.pdf / page 12 / Generator Schedule",
                            "source_hierarchy": "applicant_direct_document",
                            "consistency_notes": ["Manufacturer differs from other evidence in this equipment family."],
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
        run_id="run-export-richer",
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
    assert "anchor:" in packet
    assert "applicant_direct_document" in packet
    assert "consistency:" in packet
