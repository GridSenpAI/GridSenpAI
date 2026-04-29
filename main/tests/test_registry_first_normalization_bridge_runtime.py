from __future__ import annotations

from types import SimpleNamespace

from services.normalization_service.service import normalize_inputs
from shared.planner_candidate_ledger import (
    build_registry_candidate_ledger,
    build_registry_extraction_worklist,
)
from shared.planner_registry import planner_registry_fields


def test_registry_extraction_worklist_tracks_master_registry() -> None:
    worklist = build_registry_extraction_worklist(include_optional=True)
    assert len(worklist) == len(planner_registry_fields())
    assert all(item["field_id"] for item in worklist)
    assert any(item["field_id"] == "point_of_interconnection_voltage_kv" for item in worklist)


def test_candidate_ledger_backfills_every_registry_field_and_buckets_candidates() -> None:
    contract = build_registry_candidate_ledger(
        schema_field_candidates=[
            {
                "field_path": "facility.poi_voltage_kv",
                "value": "138 kV",
                "confidence": 0.92,
                "source_role": "application_request_form",
                "source_document": "load_request.pdf",
                "page_number": 1,
                "evidence_snippet": "Nominal service voltage: 138 kV",
            }
        ],
        normalized_input={
            "planner_field_values": {"point_of_interconnection_voltage_kv": 138.0},
            "planner_field_sources": {
                "point_of_interconnection_voltage_kv": {
                    "source_type": "schema_field_candidate",
                    "source_name": "load_request.pdf",
                    "confidence": "HIGH",
                }
            },
        },
    )
    rows = contract["planner_candidate_ledger"]
    summary = contract["planner_candidate_ledger_summary"]
    assert summary["registry_field_count"] == len(planner_registry_fields())
    poi = next(row for row in rows if row["field_id"] == "point_of_interconnection_voltage_kv")
    assert poi["candidate_count"] == 1
    assert poi["accepted_value"] == 138.0
    assert poi["status"] == "ACCEPTED_BY_NORMALIZATION"


def test_normalization_result_carries_registry_first_bridge_artifacts() -> None:
    context = SimpleNamespace(
        run_id="registry-bridge-test",
        config=SimpleNamespace(schema_version_input="test"),
    )
    result = normalize_inputs(
        context=context,
        extraction_result={
            "schema_field_candidates": [
                {
                    "field_path": "facility.poi_voltage_kv",
                    "value": "138",
                    "confidence": 0.9,
                    "source_role": "application_request_form",
                    "source_document": "request.pdf",
                    "evidence_snippet": "Nominal service voltage: 138 kV",
                }
            ],
            "entities": [],
            "topology_cues": [],
            "canonical_state": {},
        },
    )
    normalized = result["normalized_input"]
    assert normalized["planner_extraction_worklist_summary"]["registry_field_count"] == len(planner_registry_fields())
    assert normalized["planner_candidate_ledger_summary"]["registry_field_count"] == len(planner_registry_fields())
    assert result["validation_report"]["planner_candidate_ledger_summary"]["registry_first_bridge"] is True
