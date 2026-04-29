from __future__ import annotations

from services.export_service.service import _build_planner_packet


def test_export_includes_field_resolution_sections() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "doc-1",
                "field_path": "facility.poi_voltage_kv",
                "value": 138.0,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.9,
                "evidence_strength": "STRONG",
                "metadata": {"artifact_name": "one_line.pdf", "page_number": 2, "section_label": "POI"},
                "is_primary": True,
            },
            {
                "field_record_id": "web-1",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 115.0,
                "source_stage": "retrieval",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.55,
                "evidence_strength": "WEAK",
                "metadata": {"artifact_name": "site.html", "source_method": "official_website"},
            },
        ]
    }
    packet = _build_planner_packet(
        run_id="run-export-field-resolution",
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
    assert "## Field Resolution Ledger" in packet
    assert "## Applicant Confirmation Backlog" in packet
    assert "alternative:" in packet
