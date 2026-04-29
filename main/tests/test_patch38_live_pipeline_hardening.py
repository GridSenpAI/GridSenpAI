from __future__ import annotations

from services.extraction_service.utils import scan_project_primary_package_candidates
from services.field_resolution_service.service import build_field_resolution_result
from shared.ledger_adjudication import build_ledger_adjudication_artifact, apply_ledger_adjudication_to_contract
from shared.planner_field_ledger import build_planner_field_ledger, planner_field_ledger_summary
from shared.planner_registry import registry_field_id_for_path


def test_phase_aliases_do_not_collapse_initial_phase_to_peak_demand() -> None:
    assert registry_field_id_for_path("facility.load_schedule.phase_1_mw") == "peak_demand_mw"
    assert registry_field_id_for_path("facility.load_schedule.phase_2_mw") == "buildout_phases_summary"
    assert registry_field_id_for_path("facility.load_schedule.phase_3_mw") == "buildout_phases_summary"
    assert registry_field_id_for_path("facility.load_schedule.maximum_coincident_demand_mw") == "peak_demand_mw"


def test_project_primary_phase_rows_and_peak_demand_are_bound_separately() -> None:
    artifact = {"artifact_id": "a1", "artifact_type": "pdf", "file_name": "generic_large_load_request_form.pdf"}
    text = """
    Large Load Request Form
    Project name Atlas Compute Campus
    Project number ABC-123
    Applicant / owner Atlas Digital LLC
    Nominal service voltage 230 kV
    Maximum coincident demand at POI 240 MW
    Phase 1 / 2 / 3 demand 80 MW / 160 MW / 240 MW
    Requested initial in-service 2030-01-15
    Ultimate commercial operation 2031-05-30
    """
    candidates, _ = scan_project_primary_package_candidates(
        artifact,
        {},
        [{"text": text, "anchor_id": "a1_p1", "page_number": 1}],
        0,
    )
    by_path = {candidate["field_path"]: candidate for candidate in candidates}
    assert by_path["peak_demand_mw"]["value"] == 240.0
    assert by_path["facility.load_schedule.phase_1_mw"]["value"] == 80.0
    assert by_path["facility.load_schedule.phase_2_mw"]["value"] == 160.0
    assert by_path["facility.load_schedule.phase_3_mw"]["value"] == 240.0
    assert by_path["nominal_poi_voltage_kv"]["value"] == 230.0


def test_direct_application_fact_can_clear_planner_critical_threshold_relief() -> None:
    result = build_field_resolution_result(
        {
            "field_records": [
                {
                    "field_record_id": "req-poi",
                    "field_path": "point_of_interconnection_voltage_kv",
                    "value": 138,
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "confidence_score": 0.78,
                    "evidence_strength": "STRONG",
                    "source_ref": ["request_form.pdf"],
                    "metadata": {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "source_method": "table_extract",
                        "source_role": "application_request_form",
                        "source_document": "request_form.pdf",
                        "specificity": "direct_field_match",
                    },
                }
            ]
        }
    )
    entry = next(item for item in result["ledger"] if item["field_id"] == "point_of_interconnection_voltage_kv")
    assert entry["accepted_value"] == 138
    assert entry["accepted_status"] == "resolved"
    assert entry["field_release_profile"]["release_state"] == "READY"
    assert entry["acceptance_policy_result"]["direct_document_threshold_relief"] is True


def test_deterministic_adjudication_uses_compact_candidate_options_on_packets_ready() -> None:
    contract = {
        "planner_field_governance": {
            "adjudication_plan": [
                {
                    "field_path": "point_of_interconnection_voltage_kv",
                    "field_id": "point_of_interconnection_voltage_kv",
                    "field_label": "POI voltage",
                    "planner_critical": True,
                    "status": "BLOCKED_BY_CONFLICT",
                    "accepted_value": 138,
                    "confidence_score": 0.82,
                    "source_reference": "request_form.pdf, page 1",
                    "candidate_options": [
                        {"candidate_id": "a", "value": 138, "confidence_score": 0.82, "source_role": "application_request_form", "source_document": "request_form.pdf"},
                        {"candidate_id": "b", "value": 13.8, "confidence_score": 0.6, "source_role": "drawing", "source_document": "one_line.pdf"},
                    ],
                }
            ]
        },
        "planner_field_ledger": [
            {
                "field_path": "point_of_interconnection_voltage_kv",
                "field_id": "point_of_interconnection_voltage_kv",
                "field_label": "POI voltage",
                "planner_critical": True,
                "status": "BLOCKED_BY_CONFLICT",
                "accepted_value": "UNRESOLVED",
                "candidate_options": [
                    {"candidate_id": "a", "value": 138, "confidence_score": 0.82, "source_role": "application_request_form", "source_document": "request_form.pdf"},
                    {"candidate_id": "b", "value": 13.8, "confidence_score": 0.6, "source_role": "drawing", "source_document": "one_line.pdf"},
                ],
            }
        ],
    }
    artifact = build_ledger_adjudication_artifact(
        run_id="x",
        planner_field_contract=contract,
        adjudication_result={"status": "ADJUDICATION_PACKETS_READY"},
    )
    updated = apply_ledger_adjudication_to_contract(contract, artifact)
    row = updated["planner_field_ledger"][0]
    assert row["accepted_value"] == 138
    assert row["status"] in {"ACCEPTED", "ACCEPTED_WITH_CONFLICT_NOTE", "PROVISIONAL"}


def test_registry_backfill_classifies_later_stage_missing_fields_without_overblocking() -> None:
    rows = build_planner_field_ledger([])
    summary = planner_field_ledger_summary(rows)
    assert summary["status_counts"].get("FUTURE_STUDY_REQUIRED", 0) > 0
    assert summary["status_counts"].get("NOT_APPLICABLE", 0) > 0
    assert summary["status_counts"].get("UNRESOLVED", 0) < len(rows)
