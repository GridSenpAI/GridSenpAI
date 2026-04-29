from __future__ import annotations

from services.extraction_service.utils import scan_project_primary_package_candidates
from shared.ledger_adjudication import build_ledger_adjudication_artifact, apply_ledger_adjudication_to_contract
from shared.ledger_native_translation import build_ledger_first_translation_inputs
from shared.planner_candidate_bridge import attach_candidate_ledger_to_canonical_state
from shared.planner_field_governance import build_planner_field_governance
from shared.planner_field_ledger import build_planner_field_ledger, planner_field_ledger_summary


def test_candidate_bridge_marks_candidate_ledger_as_governed_primary_source() -> None:
    state: dict[str, object] = {}
    result = attach_candidate_ledger_to_canonical_state(
        state,
        normalization_result={
            "normalized_input": {
                "planner_candidate_ledger": [{"field_id": "project_name", "field_path": "project_name"}],
                "planner_candidate_ledger_summary": {"field_count_with_candidates": 1},
            }
        },
    )

    source_inputs = result["source_candidate_inputs"]
    assert result["candidate_governance_source"] == "planner_candidate_ledger"
    assert source_inputs["candidate_governance_source"] == "planner_candidate_ledger"
    assert source_inputs["planner_candidate_ledger"] == source_inputs["planner_candidate_rows"]


def test_compact_adjudication_plan_preserves_candidates_for_deterministic_fallback() -> None:
    field_resolution_ledger = [
        {
            "field_id": "point_of_interconnection_voltage_kv",
            "field_path": "point_of_interconnection_voltage_kv",
            "label": "POI voltage",
            "requiredness": "required",
            "planner_critical": True,
            "accepted_value": 138,
            "accepted_status": "review_required",
            "accepted_confidence": 0.91,
            "confidence_band": "HIGH",
            "accepted_candidate_id": "poi-138",
            "field_release_profile": {"release_state": "BLOCKED", "export_readiness_tier": "blocked"},
            "candidates": [
                {
                    "candidate_id": "poi-138",
                    "value": 138,
                    "normalized_value": 138,
                    "unit": "kV",
                    "confidence": 0.91,
                    "score": 0.91,
                    "source_role": "load_request_form",
                    "source_document": "request.pdf",
                    "source_page": "1",
                    "evidence_snippet": "Nominal service voltage 138 kV",
                },
                {
                    "candidate_id": "campus-13-8",
                    "value": 13.8,
                    "normalized_value": 13.8,
                    "unit": "kV",
                    "confidence": 0.70,
                    "score": 0.70,
                    "source_role": "drawing",
                    "source_document": "one_line.pdf",
                    "source_page": "1",
                },
            ],
            "candidate_summary": {"candidate_count": 2},
            "conflict_materiality": "medium",
            "conflict_profile": {"summary": "Runner-up value differs", "conflict_materiality": "medium"},
            "planner_review_flag": True,
            "needs_applicant_confirmation": True,
        }
    ]
    rows = build_planner_field_ledger(field_resolution_ledger)
    contract = {
        "planner_field_ledger": rows,
        "planner_field_ledger_summary": planner_field_ledger_summary(rows),
        "planner_field_governance": build_planner_field_governance(rows),
    }

    plan = contract["planner_field_governance"]["adjudication_plan"]
    assert plan
    assert plan[0]["candidate_options"]

    adjudication = build_ledger_adjudication_artifact(
        run_id="run-test",
        planner_field_contract=contract,
        adjudication_result={"status": "ADJUDICATION_PACKETS_READY"},
    )
    closed = apply_ledger_adjudication_to_contract(contract, adjudication)
    row = next(item for item in closed["planner_field_ledger"] if item["field_id"] == "point_of_interconnection_voltage_kv")

    assert row["accepted_value"] in {138, "138"}
    assert row["adjudication_method"] == "deterministic"
    assert row["status"] in {"ACCEPTED", "ACCEPTED_WITH_CONFLICT_NOTE", "PROVISIONAL"}
    assert closed["planner_field_ledger_summary"]["ledger_adjudication_applied_value_count"] == 1


def test_project_primary_scanner_binds_phase_rows_without_sample_specific_values() -> None:
    artifact = {"artifact_id": "generic", "file_name": "large_load_request_form.pdf", "classification": "form"}
    text = """
    Large Load Request Form
    Project name Solar Ridge Campus
    Project number SR-2026-1
    Applicant / owner Example Load LLC
    Nominal service voltage 345 kV
    Nominal campus medium voltage 34.5 kV
    Maximum coincident demand at POI 250 MW
    Phase 1 / 2 / 3 demand 50 MW / 150 MW / 250 MW
    Critical IT load at ultimate build-out 180 MW
    Campus quantity 40 units total generator
    UPS modules 120 modules total
    three main power transformers
    """

    candidates, _ = scan_project_primary_package_candidates(
        artifact,
        {},
        [{"text": text, "anchor_id": "generic_page_1", "page_number": 1}],
        0,
    )
    values = {candidate["field_path"]: candidate["value"] for candidate in candidates}

    assert values["project_name"] == "Solar Ridge Campus"
    assert values["nominal_poi_voltage_kv"] == 345.0
    assert values["peak_demand_mw"] == 250.0
    assert values["facility.load_schedule.phase_1_mw"] == 50.0
    assert values["facility.load_schedule.phase_2_mw"] == 150.0
    assert values["facility.load_schedule.phase_3_mw"] == 250.0
    assert values["interconnection_transformer_unit_count"] == 3


def test_ledger_first_translation_prefers_peak_demand_registry_aliases() -> None:
    contract = build_ledger_first_translation_inputs(
        {
            "planner_field_contract": {
                "planner_field_ledger": [
                    {
                        "field_id": "peak_demand_mw",
                        "field_path": "peak_demand_mw",
                        "accepted_value": "250",
                        "normalized_value": "250",
                        "status": "ACCEPTED",
                        "release_state": "READY",
                        "translation_use_policy": "use_accepted_value",
                        "confidence_band": "HIGH",
                        "confidence_score": 0.95,
                    },
                    {
                        "field_id": "net_power_factor_at_poi",
                        "field_path": "net_power_factor_at_poi",
                        "accepted_value": "0.98",
                        "normalized_value": "0.98",
                        "status": "ACCEPTED",
                        "release_state": "READY",
                        "translation_use_policy": "use_accepted_value",
                        "confidence_band": "HIGH",
                        "confidence_score": 0.90,
                    },
                ]
            }
        }
    )

    assert contract["used_ledger_native_primary"] is True
    assert contract["model_outputs"]["steady_state"]["p_mw"] == 250.0
    assert contract["model_outputs"]["steady_state"]["power_factor"] == 0.98
