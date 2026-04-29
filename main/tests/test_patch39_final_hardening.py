from __future__ import annotations

from shared.ledger_adjudication import build_ledger_adjudication_artifact, apply_ledger_adjudication_to_contract
from shared.phase6_redesign_contract import build_phase6_redesign_runtime_contract
from shared.planner_field_governance import build_planner_field_governance
from shared.planner_field_ledger import build_planner_field_ledger


def test_deterministic_adjudication_accepts_corroborated_same_value() -> None:
    row = {
        "field_path": "facility.poi_voltage_kv",
        "field_id": "point_of_interconnection_voltage_kv",
        "field_label": "POI voltage",
        "status": "BLOCKED_BY_CONFLICT",
        "accepted_value": 138.0,
        "confidence_score": 0.70,
        "planner_critical": True,
        "requiredness": "required",
        "candidate_count": 2,
        "candidate_options": [
            {"candidate_id": "form", "value": 138.0, "normalized_value": 138.0, "confidence_score": 0.72, "source_role": "application_request_form", "source_document": "request.pdf", "unit": "kV"},
            {"candidate_id": "summary", "value": 138.0, "normalized_value": 138.0, "confidence_score": 0.70, "source_role": "project_summary", "source_document": "summary.pdf", "unit": "kV"},
        ],
    }
    contract = {"planner_field_ledger": [dict(row)], "planner_field_governance": build_planner_field_governance([row])}
    artifact = build_ledger_adjudication_artifact(
        run_id="r1",
        planner_field_contract=contract,
        adjudication_result={"status": "ADJUDICATION_PACKETS_READY"},
    )
    assert artifact["status"] != "LEDGER_ADJUDICATION_REQUIRED_BUT_FAILED_CRITICAL"
    decision = artifact["decisions"][0]
    assert decision["adjudication_decision_status"] == "ADJUDICATION_COMPLETED"
    assert decision["adjudicated_value"] == 138.0
    assert "corroborated" in decision["adjudicated_rationale"].lower()
    applied = apply_ledger_adjudication_to_contract(contract, artifact)
    assert applied["planner_field_ledger"][0]["status"] in {"ACCEPTED", "ACCEPTED_WITH_CONFLICT_NOTE", "PROVISIONAL"}
    assert applied["planner_field_ledger"][0]["accepted_value"] == 138.0


def test_boolean_presence_rows_export_boolean_not_token_soup() -> None:
    ledger = build_planner_field_ledger([
        {
            "field_id": "equipment_schedule_present",
            "field_path": "facility.equipment_schedule",
            "label": "Equipment schedule present",
            "accepted_status": "accepted",
            "accepted_value": {"equipment_ids": ["Project", "The", "Campus"], "rows": [{"tokens": ["bad", "token", "soup"]}]},
            "accepted_confidence": 0.8,
            "confidence_band": "HIGH",
            "candidates": [
                {
                    "candidate_id": "equipment",
                    "value": {"equipment_ids": ["Project", "The"]},
                    "confidence": 0.8,
                    "source_role": "equipment_schedule",
                    "source_document": "equipment.pdf",
                    "evidence_snippet": "Major equipment schedule table detected.",
                }
            ],
            "field_release_profile": {"release_state": "READY", "export_readiness_tier": "ready"},
        }
    ])
    row = next(item for item in ledger if item["field_id"] == "equipment_schedule_present")
    assert row["accepted_value"] == True  # noqa: E712
    assert row["source_document"] == "equipment.pdf"


def test_titleblock_revision_date_cannot_satisfy_milestone_date() -> None:
    ledger = build_planner_field_ledger([
        {
            "field_id": "requested_in_service_date",
            "field_path": "facility.energization.initial_energization_date",
            "label": "Requested in-service date",
            "accepted_status": "accepted",
            "accepted_value": "04/2026",
            "accepted_confidence": 0.9,
            "confidence_band": "HIGH",
            "candidates": [
                {
                    "candidate_id": "titleblock",
                    "value": "04/2026",
                    "confidence": 0.9,
                    "source_role": "drawing",
                    "source_document": "one_line.pdf",
                    "source_section": "REV DATE DESCRIPTION BY CK title block",
                    "evidence_snippet": "REV DATE DESCRIPTION BY CK 2 04/2026 ISSUED FOR INTERCONNECTION REVIEW",
                }
            ],
            "field_release_profile": {"release_state": "READY", "export_readiness_tier": "ready"},
        }
    ])
    row = next(item for item in ledger if item["field_id"] == "requested_in_service_date")
    assert row["status"] == "UNRESOLVED"
    assert "title-block" in row["unresolved_reason"]


def test_governance_excludes_future_and_not_applicable_from_action_queues() -> None:
    rows = [
        {"field_id": "optional", "field_path": "optional", "status": "NOT_APPLICABLE", "accepted_value": "UNRESOLVED", "planner_critical": False, "requiredness": "optional"},
        {"field_id": "future", "field_path": "future", "status": "FUTURE_STUDY_REQUIRED", "accepted_value": "UNRESOLVED", "planner_critical": True, "requiredness": "conditional_required"},
    ]
    governance = build_planner_field_governance(rows)
    assert governance["applicant_followup_count"] == 0
    assert governance["adjudication_required_count"] == 0
    assert governance["manual_review_count"] == 0


def test_phase6_contract_uses_exported_translation_contract_when_stage_payload_is_thin() -> None:
    contract = build_phase6_redesign_runtime_contract(
        run_id="r1",
        canonical_state_result={"canonical_state": {"source_candidate_inputs": {"candidate_governance_source": "planner_candidate_ledger", "planner_candidate_ledger": [{"x": 1}]}}},
        normalization_result={"planner_candidate_ledger": [{"x": 1}]},
        interview_result={"pre_interview_planner_field_ledger_question_count": 0},
        translation_result={},
        scenario_result={"scenario_input_contract": {"baseline_output_source": "ledger_native_model_outputs"}},
        export_result={"export_manifest": {"x": 1}, "translation_source_contract": {"primary_source": "planner_field_ledger", "legacy_translation_fallback_used": False}},
        adjudication_result={"status": "ADJUDICATION_COMPLETED"},
        planner_field_contract={"planner_field_ledger": [{"field_id": "x", "status": "ACCEPTED", "source_document": "doc.pdf"}]},
        planner_interview_closure={"contract_version": "planner_interview_closure_v1"},
        planner_ledger_adjudication={"contract_version": "planner_ledger_adjudication_v1"},
    )
    gate = next(item for item in contract["gates"] if item["gate"] == "ledger_first_translation")
    assert gate["status"] == "PASS"
