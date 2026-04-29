from services.export_service.service import _build_planner_packet


def test_export_packet_includes_governed_pipeline_consistency_section() -> None:
    canonical_state = {
        "normalized_input": {"facility": {"project_name": "GridSenpAI Test Project"}},
        "planner_packet_field_rows": {},
        "field_resolution": {"ledger": [], "summary": {"accepted_field_index_count": 4, "applicant_confirmation_needed_count": 1, "planner_review_count": 2}},
        "governed_truth_summary": {
            "accepted_planner_field_count": 4,
            "planner_review_count": 2,
            "applicant_confirmation_needed_count": 1,
            "high_materiality_conflict_count": 1,
            "review_required_count": 2,
            "conflicting_count": 1,
            "top_backlog_field_ids": ["generator_rated_kw_per_unit", "facility.telemetry.points_list"],
        },
        "entities": [],
        "field_records": [],
        "artifacts": [],
        "evidence_snippets": [],
    }
    packet = _build_planner_packet(
        run_id="run-governed-consistency",
        canonical_state=canonical_state,
        validation_result={"validation_report": {"engineering_validation": {"errors": [], "warnings": []}}},
        translation_result={"output_parameters": [], "model_outputs": {}, "assumptions": [], "confidence_summary": {}, "governance_alerts": {"planner_review_count": 2, "has_governance_attention": True}},
        scenario_result={"scenarios": {}, "scenario_variants": [], "governance_alerts": {"applicant_confirmation_needed_count": 1, "has_governance_attention": True}},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "## Governed Pipeline Consistency" in packet
    assert "accepted_planner_fields=4; planner_review=2; applicant_confirmation_needed=1; high_materiality_conflicts=1; review_required=2; conflicting=1" in packet
    assert "top_backlog_fields=generator_rated_kw_per_unit, facility.telemetry.points_list" in packet
