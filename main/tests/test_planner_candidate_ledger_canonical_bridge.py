from __future__ import annotations

from shared.planner_candidate_bridge import (
    attach_candidate_ledger_to_canonical_state,
    candidate_ledger_records_for_lookup_keys,
)
from services.field_resolution_service.service import build_field_resolution_result


def _candidate_row() -> dict:
    return {
        "field_id": "facility.poi_voltage_kv",
        "field_path": "facility.poi_voltage_kv",
        "field_label": "POI voltage",
        "expected_unit": "kV",
        "policy_family": "poi_voltage",
        "candidate_count": 1,
        "candidates": [
            {
                "candidate_id": "cand-poi-138",
                "field_path": "facility.poi_voltage_kv",
                "value": 138,
                "normalized_value": 138,
                "confidence_score": 0.93,
                "confidence_label": "HIGH",
                "authority_score": 28,
                "authority_notes": ["application request form is authoritative for POI voltage"],
                "source_role": "application_request_form",
                "source_document": "01_large_load_request_form.pdf",
                "source_page": "1",
                "source_section": "Electrical Characteristics table / Nominal service voltage",
                "source_anchor_id": "anchor-poi-138",
                "method": "schema_extraction",
                "evidence_snippet": "Nominal service voltage: 138 kV",
                "rejected_by_field_policy": False,
            }
        ],
    }


def test_candidate_ledger_records_are_field_resolution_compatible() -> None:
    records = candidate_ledger_records_for_lookup_keys([_candidate_row()], ["facility.poi_voltage_kv"])

    assert len(records) == 1
    record = records[0]
    assert record["field_path"] == "facility.poi_voltage_kv"
    assert record["value"] == 138
    assert record["source_type"] == "planner_candidate_ledger"
    assert record["metadata"]["record_origin"] == "planner_candidate_ledger"
    assert record["metadata"]["source_document"] == "01_large_load_request_form.pdf"


def test_canonical_attachment_exposes_candidate_ledger_to_source_inputs() -> None:
    canonical_state = {"normalized_input": {}}
    normalization_result = {
        "normalized_input": {
            "planner_candidate_ledger": [_candidate_row()],
            "planner_candidate_ledger_summary": {"field_count_with_candidates": 1},
        }
    }

    attach_candidate_ledger_to_canonical_state(canonical_state, normalization_result=normalization_result)

    assert canonical_state["planner_candidate_ledger"][0]["field_path"] == "facility.poi_voltage_kv"
    assert canonical_state["source_candidate_inputs"]["planner_candidate_rows"][0]["field_path"] == "facility.poi_voltage_kv"


def test_field_resolution_consumes_planner_candidate_ledger_rows() -> None:
    canonical_state = {
        "field_records": [],
        "source_candidate_inputs": {"planner_candidate_rows": [_candidate_row()]},
    }

    result = build_field_resolution_result(canonical_state, None, include_optional=True)

    accepted = result.get("accepted_field_index", {})
    assert "facility.poi_voltage_kv" in accepted or "poi_voltage_kv" in accepted
    ledger_rows = result.get("ledger", [])
    poi_rows = [row for row in ledger_rows if row.get("field_path") == "facility.poi_voltage_kv"]
    assert poi_rows, "field resolution should create a ledger row from planner_candidate_ledger"
    assert poi_rows[0].get("candidates"), "planner candidate rows must be active candidates"
    assert any(
        candidate.get("source_type") == "planner_candidate_ledger"
        for candidate in poi_rows[0].get("candidates", [])
    )


def test_field_resolution_candidate_ledger_governs_legacy_competing_records() -> None:
    candidate_row = _candidate_row()
    legacy_record = {
        "field_record_id": "legacy-poi-13-8",
        "field_path": "facility.poi_voltage_kv",
        "value": 13.8,
        "source_stage": "normalization",
        "source_type": "normalized_input",
        "source_ref": ["legacy-normalized-voltage"],
        "confidence_score": 0.99,
        "metadata": {
            "field_id": "facility.poi_voltage_kv",
            "unit": "kV",
            "evidence_snippet": "Campus medium voltage distribution: 13.8 kV",
        },
    }
    canonical_state = {
        "field_records": [legacy_record],
        "source_candidate_inputs": {"planner_candidate_rows": [candidate_row]},
    }

    result = build_field_resolution_result(canonical_state, None, include_optional=True)

    poi_rows = [row for row in result.get("ledger", []) if row.get("field_path") == "facility.poi_voltage_kv"]
    assert poi_rows, "field resolution should include the POI voltage row"
    row = poi_rows[0]
    assert row.get("accepted_value") == 138
    assert row.get("candidates", [])[0].get("metadata", {}).get("record_origin") == "planner_candidate_ledger"
    assert row.get("candidates", [])[0].get("metadata", {}).get("planner_candidate_primary") is True
    assert any(
        candidate.get("metadata", {}).get("legacy_candidate_supplement") is True
        for candidate in row.get("candidates", [])[1:]
    )
