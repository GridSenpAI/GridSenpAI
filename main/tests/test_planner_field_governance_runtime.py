from shared.planner_field_governance import build_planner_field_governance
from shared.planner_field_ledger import planner_field_contract_from_canonical


def test_planner_field_governance_builds_followup_and_adjudication_plans():
    rows = [
        {
            "field_path": "facility.poi_voltage_kv",
            "field_id": "facility.poi_voltage_kv",
            "field_label": "POI voltage",
            "status": "BLOCKED_BY_CONFLICT",
            "accepted_value": "13.8",
            "confidence_score": 0.52,
            "source_document": "05_single_line_diagram.pdf",
            "source_page": "1",
            "candidate_count": 3,
            "planner_critical": True,
            "requiredness": "required",
            "conflict_summary": "138 kV application evidence conflicts with 13.8 kV internal distribution evidence.",
        },
        {
            "field_path": "facility.dynamic_model_available",
            "field_id": "facility.dynamic_model_available",
            "field_label": "Dynamic model available",
            "status": "UNRESOLVED",
            "accepted_value": "UNRESOLVED",
            "confidence_score": 0.0,
            "source_document": "No direct source found",
            "candidate_count": 0,
            "planner_critical": False,
            "requiredness": "conditional",
            "unresolved_reason": "No direct source found",
        },
    ]

    governance = build_planner_field_governance(rows)

    assert governance["release_state"] == "BLOCKED_PENDING_APPLICANT_OR_ENGINEERING_REVIEW"
    assert governance["applicant_followup_count"] == 2
    assert governance["adjudication_required_count"] >= 1
    assert governance["applicant_followup_plan"][0]["field_path"] == "facility.poi_voltage_kv"
    assert "Conflicting evidence" in governance["applicant_followup_plan"][0]["question"]


def test_planner_field_contract_includes_governance_from_master_ledger():
    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "ledger": [
                    {
                        "field_path": "facility.poi_voltage_kv",
                        "field_id": "facility.poi_voltage_kv",
                        "label": "POI voltage",
                        "accepted_status": "resolved",
                        "accepted_value": 138,
                        "accepted_confidence": 0.94,
                        "confidence_band": "HIGH",
                        "planner_critical": True,
                        "requiredness": "required",
                        "candidates": [
                            {
                                "candidate_id": "c1",
                                "value": 138,
                                "unit": "kV",
                                "metadata": {
                                    "source_document": "01_large_load_request_form.pdf",
                                    "page_number": "1",
                                    "section_label": "Electrical Characteristics",
                                    "source_role": "application_request_form",
                                    "evidence_snippet": "Nominal service voltage: 138 kV",
                                },
                            }
                        ],
                    }
                ]
            }
        }
    }

    contract = planner_field_contract_from_canonical(canonical_state_result)

    assert "planner_field_governance" in contract
    assert contract["planner_field_governance"]["field_count"] == contract["planner_field_ledger_summary"]["field_count"]
    assert contract["planner_field_governance"]["applicant_followup_count"] >= 0
