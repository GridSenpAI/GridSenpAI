from __future__ import annotations

from shared.planner_field_ledger import build_planner_field_ledger, planner_field_ledger_summary
from shared.planner_registry import planner_registry_fields


def test_planner_field_ledger_backfills_every_master_registry_field() -> None:
    fields = planner_registry_fields()
    rows = build_planner_field_ledger([])
    assert len(rows) == len(fields)
    assert {row["field_id"] for row in rows} == {field["field_id"] for field in fields}
    assert all(row["accepted_value"] == "UNRESOLVED" for row in rows)
    assert all(row["source_document"] == "No direct source found" for row in rows)
    assert all(row["registry_backfilled"] is True for row in rows)
    summary = planner_field_ledger_summary(rows)
    assert summary["field_count"] == len(fields)


def test_planner_field_ledger_preserves_resolved_registry_row_and_backfills_rest() -> None:
    rows = build_planner_field_ledger([
        {
            "field_path": "facility.poi_voltage_kv",
            "field_id": "point_of_interconnection_voltage_kv",
            "label": "POI voltage",
            "accepted_status": "resolved",
            "accepted_value": 138,
            "accepted_confidence": 0.94,
            "accepted_unit": "kV",
            "accepted_candidate_id": "candidate-poi-1",
            "candidates": [
                {
                    "candidate_id": "candidate-poi-1",
                    "value": 138,
                    "unit": "kV",
                    "metadata": {
                        "source_document": "01_large_load_request_form.pdf",
                        "page_number": 1,
                        "section_label": "Electrical Characteristics",
                        "source_role": "application_request_form",
                        "evidence_snippet": "Nominal service voltage: 138 kV",
                    },
                }
            ],
        }
    ])
    fields = planner_registry_fields()
    assert len(rows) == len(fields)
    poi_rows = [row for row in rows if row["field_id"] == "point_of_interconnection_voltage_kv"]
    assert len(poi_rows) == 1
    poi = poi_rows[0]
    assert poi["accepted_value"] == "138"
    assert poi["confidence_score"] == 0.94
    assert poi["source_document"] == "01_large_load_request_form.pdf"
    assert poi["source_page"] == "1"
    assert poi["registry_backfilled"] is False
