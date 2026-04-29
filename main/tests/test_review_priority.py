from shared.review_priority import build_escalation_registry, build_field_governance_core, build_planner_action_queue, build_stage_transition_decisions


def test_planner_action_queue_builds_field_linked_stage_aware_actions() -> None:
    manual_review_queue = {
        "summary": {
            "total_count": 3,
            "conflict_count": 1,
            "interview_dependency_count": 1,
            "evidence_weakness_count": 1,
            "deterministic_override_count": 0,
        },
        "groups": {
            "conflict": [
                {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "field_path": "facility.poi_voltage_kv",
                    "label": "POI Voltage",
                    "status": "conflicting",
                    "planner_critical": True,
                    "reason": "Official and vendor evidence still disagree.",
                }
            ],
            "interview_dependency": [
                {
                    "field_id": "ups_topology",
                    "field_path": "facility.ups.topology",
                    "label": "UPS Topology",
                    "status": "review_required",
                    "planner_critical": True,
                    "reason": "Applicant must confirm UPS topology.",
                }
            ],
            "evidence_weakness": [
                {
                    "field_id": "generator_model",
                    "field_path": "facility.generators.model",
                    "label": "Generator Model",
                    "status": "review_required",
                    "planner_critical": False,
                    "reason": "Only family-level evidence was found.",
                }
            ],
            "deterministic_override": [],
        },
    }
    interview_priority_plan = {
        "question_sequence": ["Q_UPS_TOPOLOGY"]
    }

    queue = build_planner_action_queue(
        manual_review_queue=manual_review_queue,
        interview_priority_plan=interview_priority_plan,
        translation_governance_alerts={"has_governance_attention": True},
        scenario_governance_alerts={"has_governance_attention": True},
    )

    assert queue["summary"]["field_linked_count"] >= 3
    assert queue["summary"]["next_stage_counts"]["applicant_interview"] >= 1
    assert queue["summary"]["next_stage_counts"]["evidence_resolution"] >= 1
    assert queue["summary"]["next_stage_counts"]["planner_review"] >= 1

    interview_action = next(item for item in queue["actions"] if item.get("field_path") == "facility.ups.topology")
    assert interview_action["next_best_stage"] == "applicant_interview"
    assert interview_action["action_scope"] == "field"
    assert interview_action["planner_critical"] is True

    conflict_action = next(item for item in queue["actions"] if item.get("field_path") == "facility.poi_voltage_kv")
    assert conflict_action["next_best_stage"] == "planner_review"
    assert conflict_action["priority"] == "CRITICAL"

    evidence_action = next(item for item in queue["actions"] if item.get("field_path") == "facility.generators.model")
    assert evidence_action["next_best_stage"] == "evidence_resolution"
    assert evidence_action["provisional_allowed"] is True

    run_action = next(item for item in queue["actions"] if item.get("action_scope") == "run")
    assert run_action["next_best_stage"] == "planner_review"



def test_escalation_registry_builds_authoritative_field_stage_registry() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "ups_topology",
                    "field_path": "facility.ups.topology",
                    "label": "UPS Topology",
                    "accepted_status": "review_required",
                    "planner_critical": True,
                    "unresolved_reason": "Applicant must confirm UPS topology.",
                },
                {
                    "field_id": "generator_model",
                    "field_path": "facility.generators.model",
                    "label": "Generator Model",
                    "accepted_status": "review_required",
                    "planner_critical": False,
                    "unresolved_reason": "Only family-level evidence was found.",
                },
            ]
        }
    }
    manual_review_queue = {
        "groups": {
            "interview_dependency": [{"field_id": "ups_topology", "field_path": "facility.ups.topology"}],
            "evidence_weakness": [{"field_id": "generator_model", "field_path": "facility.generators.model"}],
            "conflict": [],
            "deterministic_override": [],
        }
    }
    planner_action_queue = {
        "actions": [
            {
                "action_scope": "field",
                "field_id": "ups_topology",
                "field_path": "facility.ups.topology",
                "next_best_stage": "applicant_interview",
                "stage_owner": "applicant_interview",
                "stage_reason": "The field still needs applicant confirmation.",
                "escalation_trigger": "interview dependency",
            },
            {
                "action_scope": "field",
                "field_id": "generator_model",
                "field_path": "facility.generators.model",
                "next_best_stage": "evidence_resolution",
                "stage_owner": "evidence_resolution",
                "stage_reason": "Current support is too weak to trust.",
                "escalation_trigger": "evidence weakness",
            },
        ]
    }

    registry = build_escalation_registry(
        canonical_state=canonical_state,
        manual_review_queue=manual_review_queue,
        planner_action_queue=planner_action_queue,
    )

    assert registry["summary"]["field_count"] == 2
    assert registry["summary"]["unresolved_field_count"] == 2
    assert registry["summary"]["current_stage_counts"]["applicant_interview_pending"] == 1
    assert registry["summary"]["next_stage_counts"]["evidence_resolution"] == 1

    ups_entry = next(item for item in registry["fields"] if item["field_path"] == "facility.ups.topology")
    assert ups_entry["current_handling_stage"] == "applicant_interview_pending"
    assert ups_entry["next_escalation_target"] == "applicant_interview"
    assert ups_entry["authoritative_source"] == "shared_escalation_registry"



def test_field_governance_core_builds_unified_registry_and_transition_decisions() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "ups_topology",
                    "field_path": "facility.ups.topology",
                    "label": "UPS Topology",
                    "accepted_status": "review_required",
                    "planner_critical": True,
                    "confidence_band": "LOW",
                    "needs_applicant_confirmation": True,
                    "unresolved_reason": "Applicant must confirm UPS topology.",
                    "evidence_route_record": {"support_strength": "LOW", "weak_support_only": True},
                }
            ]
        }
    }
    audit = {
        "fields": [
            {
                "field_id": "ups_topology",
                "field_path": "facility.ups.topology",
                "linked_agent_ids": ["applicant_interview_agent"],
                "disposition_counts": {"accepted_into_interview_backlog": 1},
            }
        ]
    }

    core = build_field_governance_core(
        canonical_state=canonical_state,
        field_agent_consumption_audit=audit,
        translation_governance_alerts={"has_governance_attention": True},
        scenario_governance_alerts={"has_governance_attention": True},
    )

    assert core["manual_review_queue"]["summary"]["interview_dependency_count"] == 1
    assert core["planner_action_queue"]["summary"]["field_linked_count"] >= 1
    assert core["escalation_registry"]["summary"]["field_count"] == 1
    assert core["stage_transition_decisions"]["summary"]["field_count"] == 1
    assert core["field_governance_registry"]["summary"]["field_count"] == 1
    gov_field = core["field_governance_registry"]["fields"][0]
    assert gov_field["transition_decision"] == "escalate_to_applicant_interview"
    assert gov_field["current_handling_stage"] == "applicant_interview_pending"
    assert gov_field["field_release_state"] == "BLOCKED"


def test_field_governance_core_builds_governed_release_decision_with_blockers() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "poi_voltage",
                    "field_path": "facility.poi_voltage_kv",
                    "label": "POI Voltage",
                    "accepted_status": "conflicting",
                    "planner_critical": True,
                    "confidence_band": "LOW",
                    "unresolved_reason": "Official and vendor evidence still disagree.",
                    "field_release_profile": {"release_state": "BLOCKED", "export_readiness_tier": "blocked", "translation_use_policy": "hold_from_modeled_output", "scenario_use_policy": "hold_for_review_variant_only"},
                },
                {
                    "field_id": "generator_model",
                    "field_path": "facility.generators.model",
                    "label": "Generator Model",
                    "accepted_status": "review_required",
                    "planner_critical": False,
                    "confidence_band": "LOW",
                    "unresolved_reason": "Only family-level evidence was found.",
                    "field_release_profile": {"release_state": "PROVISIONAL", "export_readiness_tier": "provisional", "translation_use_policy": "use_with_provisional_tag", "scenario_use_policy": "use_with_review_variant"},
                    "evidence_route_record": {"support_strength": "LOW", "weak_support_only": True},
                },
            ]
        }
    }

    core = build_field_governance_core(
        canonical_state=canonical_state,
        translation_governance_alerts={"has_governance_attention": True},
        scenario_governance_alerts={"has_governance_attention": True},
    )

    release = core["governed_release_decision"]
    assert release["summary"]["release_state"] == "BLOCKED"
    assert release["summary"]["blocking_field_count"] == 1
    assert release["summary"]["planner_packet_state"] == "BLOCKED"
    assert release["summary"]["translation_state"] == "BLOCKED"
    assert release["summary"]["scenario_state"] == "BLOCKED"
    assert release["blockers"][0]["field_path"] == "facility.poi_voltage_kv"
    assert release["provisional_fields"][0]["field_path"] == "facility.generators.model"
