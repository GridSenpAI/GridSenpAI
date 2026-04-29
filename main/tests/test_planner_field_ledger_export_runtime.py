from services.export_service.service import (
    _build_planner_field_ledger,
    _build_planner_tldr_markdown,
    _build_planner_tldr_summary,
)


def test_planner_field_ledger_rows_include_value_confidence_and_source_location():
    ledger = [
        {
            "field_id": "facility_poi_voltage_kv",
            "field_path": "facility.poi_voltage_kv",
            "label": "POI Voltage",
            "accepted_value": 138,
            "accepted_unit": "kV",
            "accepted_status": "resolved",
            "accepted_confidence": 0.94,
            "confidence_band": "HIGH",
            "accepted_candidate_id": "cand-1",
            "planner_critical": True,
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "value": 138,
                    "unit": "kV",
                    "source_stream": "extraction",
                    "source_hierarchy": "application_request_form",
                    "source_anchor": "01_large_load_request_form.pdf / page 1 / Electrical Characteristics table row Nominal service voltage",
                    "confidence_band": "HIGH",
                    "metadata": {
                        "artifact_name": "01_large_load_request_form.pdf",
                        "page_number": 1,
                        "table_label": "Electrical Characteristics",
                        "row_label": "Nominal service voltage",
                        "evidence_snippet": "Nominal service voltage: 138 kV",
                        "source_role": "application_request_form",
                    },
                }
            ],
            "candidate_summary": {"candidate_count": 2},
        }
    ]

    rows = _build_planner_field_ledger(ledger)

    assert len(rows) >= 1
    assert any(item["field_path"] == "facility.poi_voltage_kv" for item in rows)
    row = next(item for item in rows if item["field_path"] == "facility.poi_voltage_kv")
    assert row["field_path"] == "facility.poi_voltage_kv"
    assert row["accepted_value"] == "138"
    assert row["confidence_score"] == 0.94
    assert row["source_document"] == "01_large_load_request_form.pdf"
    assert row["source_page"] == "1"
    assert row["source_section"] == "Electrical Characteristics"
    assert row["status"] == "ACCEPTED"
    assert "138 kV" in row["evidence_snippet"]


def test_planner_tldr_is_ledger_first_and_lists_master_fields():
    ledger = [
        {
            "field_id": "facility_poi_voltage_kv",
            "field_path": "facility.poi_voltage_kv",
            "label": "POI Voltage",
            "accepted_value": 138,
            "accepted_unit": "kV",
            "accepted_status": "resolved",
            "accepted_confidence": 0.94,
            "confidence_band": "HIGH",
            "accepted_candidate_id": "cand-1",
            "planner_critical": True,
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "value": 138,
                    "unit": "kV",
                    "source_stream": "extraction",
                    "source_hierarchy": "application_request_form",
                    "source_anchor": "request.pdf / page 1 / Electrical Characteristics",
                    "metadata": {"artifact_name": "request.pdf", "page_number": 1},
                }
            ],
        },
        {
            "field_id": "dynamic_model_available",
            "field_path": "facility.dynamic_model_available",
            "label": "Dynamic Model Available",
            "accepted_value": None,
            "accepted_status": "missing",
            "accepted_confidence": None,
            "confidence_band": "UNRESOLVED",
            "planner_critical": True,
            "candidates": [],
            "unresolved_reason": "No direct source found",
        },
    ]

    summary = _build_planner_tldr_summary(ledger)
    markdown = _build_planner_tldr_markdown("run_test", summary)

    assert summary["planner_field_ledger_summary"]["field_count"] >= 2
    assert summary["planner_field_ledger_summary"]["registry_complete"] is True
    assert summary["planner_field_ledger_summary"]["accepted_count"] == 1
    assert "## Master planner field ledger" in markdown
    assert "`facility.poi_voltage_kv`" in markdown
    assert "accepted_value: 138" in markdown
    assert "source: request.pdf, page 1" in markdown
    assert "`facility.dynamic_model_available`" in markdown
    assert "accepted_value: UNRESOLVED" in markdown
