from services.export_service.service import _build_planner_packet


def test_export_packet_includes_planner_decision_highlights_and_review_actions() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "generator_rated_kw_per_unit",
                    "field_path": "facility.generators.rated_kw_per_unit",
                    "label": "Generator rated kW per unit",
                    "accepted_status": "review_required",
                    "accepted_value": 3125,
                    "confidence_band": "MODERATE",
                    "planner_critical": True,
                    "decision_basis": "accepted_with_validation_contradiction",
                    "why_accepted": ["Exact model sheet matched installed unit count."],
                    "source_anchors": ["cummins_xyz.pdf:p2"],
                    "contradiction_summary": "Applicant stated 3000 kW prime while manufacturer sheet shows 3125 kW standby.",
                    "alternatives": [
                        {
                            "value": 3000,
                            "source_anchor": "one_line.pdf:p12",
                            "not_accepted_reason": "Applicant statement conflicts with stronger model-specific evidence.",
                        }
                    ],
                    "needs_applicant_confirmation": True,
                    "unresolved_reason": "Prime versus standby rating still needs applicant confirmation.",
                }
            ],
            "summary": {
                "accepted_field_index_count": 1,
                "applicant_confirmation_needed_count": 1,
                "planner_review_count": 1,
            },
            "backlog": [
                {
                    "field_id": "generator_rated_kw_per_unit",
                    "label": "Generator rated kW per unit",
                    "needs_applicant_confirmation": True,
                    "unresolved_reason": "Prime versus standby rating still needs applicant confirmation.",
                }
            ],
        },
        "planner_packet_field_rows": {
            "generator_and_backup_systems": [
                {
                    "field_id": "generator_rated_kw_per_unit",
                    "label": "Generator rated kW per unit",
                    "packet_section_label": "Generator & Backup Systems",
                    "status": "review_required",
                    "value": 3125,
                    "confidence_band": "MODERATE",
                    "planner_critical": True,
                    "accepted_value_kind": "manufacturer_model_specific_fact",
                    "planner_attention_tier": "critical_review_required",
                    "decision_basis": "accepted_with_validation_contradiction",
                    "why_accepted": ["Exact model sheet matched installed unit count."],
                    "source_anchors": ["cummins_xyz.pdf:p2"],
                    "contradiction_summary": "Applicant stated 3000 kW prime while manufacturer sheet shows 3125 kW standby.",
                    "alternatives": [
                        {
                            "value": 3000,
                            "source_anchor": "one_line.pdf:p12",
                            "not_accepted_reason": "Applicant statement conflicts with stronger model-specific evidence.",
                        }
                    ],
                }
            ]
        },
        "entities": [],
        "field_records": [],
    }
    validation_result = {
        "validation_report": {
            "engineering_validation": {
                "errors": [
                    {
                        "code": "GENERATOR_RATING_STANDBY_PRIME_CONFLICT",
                        "field_path": "facility.generators.rated_kw_per_unit",
                        "message": "Prime and standby rating sources materially disagree.",
                    }
                ],
                "warnings": [],
            }
        }
    }
    translation_result = {
        "output_parameters": [],
        "model_outputs": {},
        "assumptions": [],
        "confidence_summary": {},
        "scenario_driver_context": {
            "redundancy_architecture": "N+1",
            "generator_unit_count": 6,
        },
    }
    scenario_result = {
        "scenarios": {},
        "scenario_variants": [
            {
                "label": "Redundancy Degraded",
                "confidence": "LOW",
                "metadata": {
                    "scenario_family": "redundancy",
                    "review_required_change_count": 2,
                },
            }
        ],
    }
    packet = _build_planner_packet(
        run_id="run-export-hardened",
        canonical_state=canonical_state,
        validation_result=validation_result,
        translation_result=translation_result,
        scenario_result=scenario_result,
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "## Planner Decision Highlights" in packet
    assert "Generator rated kW per unit (Generator System): accepted=3125 [review_required; MODERATE]" in packet
    assert "decision_basis: accepted_with_validation_contradiction" in packet
    assert "why: Exact model sheet matched installed unit count." in packet
    assert "contradiction: Applicant stated 3000 kW prime while manufacturer sheet shows 3125 kW standby." in packet
    assert "runner_up: 3000 (one_line.pdf:p12)" in packet
    assert "## Modeling-Critical Review Actions" in packet
    assert "planner_critical_open=" in packet
    assert "applicant_confirmations_needed=1; scenarios_needing_review=1; engineering_errors=1; engineering_warnings=0" in packet
    assert "Planner review: Generator rated kW per unit (Generator System)" in packet
    assert "Applicant confirm: Generator rated kW per unit :: Prime versus standby rating still needs applicant confirmation." in packet
    assert "Scenario review: Redundancy Degraded family=redundancy; review_required_changes=2" in packet


def test_export_packet_includes_adjudication_support_reasoning_for_runner_up_conflicts() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "generator_rated_kw_per_unit",
                    "field_path": "facility.generators.rated_kw_per_unit",
                    "label": "Generator rated kW per unit",
                    "accepted_status": "review_required",
                    "accepted_value": 3125,
                    "confidence_band": "MODERATE",
                    "planner_critical": True,
                    "decision_basis": "accepted_with_applicant_contradiction",
                    "why_accepted": ["Exact model sheet matched installed unit count."],
                    "source_anchors": ["cummins_xyz.pdf:p2"],
                    "contradiction_summary": "Prime versus standby rating conflict remains.",
                    "alternatives": [{"value": 3000, "source_anchor": "one_line.pdf:p12"}],
                    "stronger_candidate_reasoning": "Generator rated kW per unit accepted 3125 because manufacturer_model_specific_spec ranked strongest.",
                    "runner_up_summary": "Runner-up candidate 3000 was retained for planner visibility (one_line.pdf:p12).",
                    "hidden_conflict_flags": ["Prime versus standby rating conflict remains."],
                    "ask_applicant_recommendation": True,
                    "downgrade_recommendation": True,
                    "evidence_route_rationale": "Accepted search path relied on manufacturer model specific spec evidence with exact model match support instead of the runner-up route behind 3000.",
                    "source_quality_comparison": "Accepted candidate had a stronger source-quality tier (manufacturer model specific spec) than the runner-up (applicant direct document).",
                    "specificity_comparison": "Accepted candidate had a stronger specificity tier (exact model match) than the runner-up (direct field match).",
                    "why_search_path_was_trusted": "Accepted search path relied on manufacturer model specific spec evidence with exact model match support instead of the runner-up route behind 3000. Accepted candidate had a stronger source-quality tier (manufacturer model specific spec) than the runner-up (applicant direct document). Accepted candidate had a stronger specificity tier (exact model match) than the runner-up (direct field match).",
                }
            ],
            "summary": {
                "accepted_field_index_count": 1,
                "applicant_confirmation_needed_count": 1,
                "planner_review_count": 1,
            },
            "backlog": [],
        },
        "planner_packet_field_rows": {},
        "entities": [],
        "field_records": [],
    }
    packet = _build_planner_packet(
        run_id="run-export-adjudication",
        canonical_state=canonical_state,
        validation_result={"validation_report": {"engineering_validation": {"errors": [], "warnings": []}}},
        translation_result={"output_parameters": [], "model_outputs": {}, "assumptions": [], "confidence_summary": {}},
        scenario_result={"scenarios": {}, "scenario_variants": []},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )

    assert "adjudication: Generator rated kW per unit accepted 3125 because manufacturer_model_specific_spec ranked strongest." in packet
    assert "runner_up_summary: Runner-up candidate 3000 was retained for planner visibility (one_line.pdf:p12)." in packet
    assert "evidence_route_rationale: Accepted search path relied on manufacturer model specific spec evidence with exact model match support instead of the runner-up route behind 3000." in packet
    assert "source_quality_comparison: Accepted candidate had a stronger source-quality tier (manufacturer model specific spec) than the runner-up (applicant direct document)." in packet
    assert "specificity_comparison: Accepted candidate had a stronger specificity tier (exact model match) than the runner-up (direct field match)." in packet
    assert "why_search_path_was_trusted: Accepted search path relied on manufacturer model specific spec evidence with exact model match support instead of the runner-up route behind 3000. Accepted candidate had a stronger source-quality tier (manufacturer model specific spec) than the runner-up (applicant direct document). Accepted candidate had a stronger specificity tier (exact model match) than the runner-up (direct field match)." in packet
    assert "adjudication_recommendation: ask_applicant" in packet



def test_export_packet_includes_master_planner_field_model_status() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "facility.project_name",
                    "field_path": "facility.project_name",
                    "label": "Project Name",
                    "accepted_status": "resolved",
                    "accepted_value": "Alpha Campus",
                    "confidence_band": "HIGH",
                    "planner_critical": True,
                    "field_release_profile": {"release_state": "READY"},
                },
                {
                    "field_id": "facility.poi_voltage_kv",
                    "field_path": "facility.poi_voltage_kv",
                    "label": "POI nominal voltage kV",
                    "accepted_status": "review_required",
                    "accepted_value": 138.0,
                    "confidence_band": "MODERATE",
                    "planner_critical": True,
                    "needs_applicant_confirmation": True,
                    "field_release_profile": {"release_state": "PROVISIONAL"},
                },
                {
                    "field_id": "facility.substation.configuration",
                    "field_path": "facility.substation.configuration",
                    "label": "Substation configuration",
                    "accepted_status": "conflicting",
                    "planner_critical": True,
                    "field_release_profile": {"release_state": "BLOCKED"},
                },
            ],
            "summary": {
                "accepted_field_index_count": 3,
                "applicant_confirmation_needed_count": 1,
                "planner_review_count": 2,
            },
        },
        "planner_packet_field_rows": {
            "site_and_interconnection_context": [
                {
                    "field_id": "facility.project_name",
                    "label": "Project Name",
                    "packet_section_label": "Site & Interconnection Context",
                    "status": "resolved",
                    "value": "Alpha Campus",
                    "planner_critical": True,
                },
                {
                    "field_id": "facility.poi_voltage_kv",
                    "label": "POI nominal voltage kV",
                    "packet_section_label": "Site & Interconnection Context",
                    "status": "review_required",
                    "value": 138.0,
                    "planner_critical": True,
                    "planner_review_flag": True,
                    "needs_applicant_confirmation": True,
                },
            ],
            "topology_and_electrical_configuration": [
                {
                    "field_id": "facility.substation.configuration",
                    "label": "Substation configuration",
                    "packet_section_label": "Topology & Electrical Configuration",
                    "status": "conflicting",
                    "planner_critical": True,
                    "planner_review_flag": True,
                }
            ],
        },
        "entities": [],
        "field_records": [],
        "normalized_input": {"facility": {}, "source_summary": {}},
    }
    validation_result = {"validation_report": {}}
    packet = _build_planner_packet(
        run_id="run-master-field-model",
        canonical_state=canonical_state,
        validation_result=validation_result,
        translation_result={"output_parameters": [], "model_outputs": {}, "assumptions": [], "confidence_summary": {}},
        scenario_result={"scenarios": {}, "scenario_variants": []},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "## Master Planner-Field Model Status" in packet
    assert "- Authoritative target model: planner_required_fields" in packet
    assert "- Governed completion:" in packet
    assert "- Model-safe now: 1" in packet
    assert "- Provisional / review-required: 1" in packet
    assert "- Blocked: 1" in packet
    assert "- Applicant confirmations pending: 1" in packet
    assert "### Planner-Field Completion by Section" in packet
    assert "Site And Interconnection Context: resolved=2/2 (100.0%); model_safe=1; provisional=1; blocked=0" in packet
    assert "Topology And Electrical Configuration: resolved=1/1 (100.0%); model_safe=0; provisional=0; blocked=1" in packet
