from shared.planner_field_ledger import (
    build_planner_field_ledger,
    planner_field_contract_from_canonical,
    planner_field_ledger_summary,
)


def test_contract_downgrades_resolved_field_without_source_to_provisional():
    rows = build_planner_field_ledger([
        {
            "field_id": "facility_poi_voltage_kv",
            "field_path": "facility.poi_voltage_kv",
            "label": "POI Voltage",
            "accepted_value": 138,
            "accepted_unit": "kV",
            "accepted_status": "resolved",
            "accepted_confidence": 0.94,
            "confidence_band": "HIGH",
            "planner_critical": True,
            "candidates": [{"candidate_id": "c1", "value": 138, "unit": "kV"}],
        }
    ])

    assert rows[0]["status"] == "PROVISIONAL"
    assert rows[0]["release_state"] == "PROVISIONAL"
    assert "lacks source location" in rows[0]["manual_review_reason"]


def test_contract_summary_blocks_release_for_critical_unresolved_fields():
    rows = build_planner_field_ledger([
        {
            "field_id": "dynamic_model_available",
            "field_path": "facility.dynamic_model_available",
            "label": "Dynamic Model Available",
            "accepted_value": None,
            "accepted_status": "missing",
            "confidence_band": "UNRESOLVED",
            "planner_critical": True,
            "requiredness": "required",
            "candidates": [],
            "unresolved_reason": "No direct source found",
        }
    ])
    summary = planner_field_ledger_summary(rows)

    assert summary["release_blocked"] is True
    assert summary["planner_critical_blocked_count"] >= 1
    assert summary["unresolved_or_blocked_count"] >= 1


def test_contract_can_be_built_from_canonical_state_result():
    contract = planner_field_contract_from_canonical({
        "canonical_state": {
            "field_resolution": {
                "ledger": [
                    {
                        "field_id": "facility_poi_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "label": "POI Voltage",
                        "accepted_value": 138,
                        "accepted_unit": "kV",
                        "accepted_status": "resolved",
                        "accepted_confidence": 0.94,
                        "confidence_band": "HIGH",
                        "planner_critical": True,
                        "accepted_candidate_id": "cand-1",
                        "candidates": [
                            {
                                "candidate_id": "cand-1",
                                "value": 138,
                                "unit": "kV",
                                "source_anchor": "request.pdf / page 1 / Electrical Characteristics",
                                "metadata": {"artifact_name": "request.pdf", "page_number": 1, "source_role": "application_request_form"},
                            }
                        ],
                    }
                ]
            }
        }
    })

    assert contract["contract_version"] == "planner_field_ledger_v2"
    assert contract["planner_field_ledger"][0]["field_path"] == "facility.poi_voltage_kv"
    assert contract["planner_field_ledger_summary"]["accepted_count"] == 1
    assert contract["source_index"][0]["source_document"] == "request.pdf"
