from __future__ import annotations

from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_builds_accepted_and_alternative_candidates() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "doc-1",
                "field_path": "facility.generators.ratings",
                "value": 3000,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.82,
                "evidence_strength": "STRONG",
                "source_ref": ["one_line"],
                "metadata": {
                    "page_number": 12,
                    "section_label": "Generator Schedule",
                    "artifact_name": "one_line.pdf",
                    "source_method": "table_deterministic",
                    "specificity": "direct_field_match",
                    "unit": "kW",
                },
                "is_primary": True,
            },
            {
                "field_record_id": "vendor-1",
                "field_path": "generator_rated_kw_per_unit",
                "value": 3125,
                "source_stage": "retrieval",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.78,
                "evidence_strength": "MODERATE",
                "source_ref": ["cummins datasheet"],
                "metadata": {
                    "artifact_name": "cummins_xyz.pdf",
                    "source_method": "manufacturer_model_specific_spec",
                    "specificity": "exact_model_match",
                    "unit": "kW",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    ledger = result["ledger"]
    generator_entry = next(item for item in ledger if item["field_id"] == "generator_rated_kw_per_unit")

    assert generator_entry["accepted_value"] == 3000
    assert generator_entry["accepted_status"] in {"conflicting", "review_required", "resolved"}
    assert generator_entry["alternatives"]
    assert generator_entry["why_accepted"]
    assert result["backlog_count"] > 0


def test_field_resolution_backlog_prioritizes_planner_critical_missing() -> None:
    canonical_state = {"field_records": []}
    result = build_field_resolution_result(canonical_state)
    assert result["backlog_count"] > 0
    first = result["backlog"][0]
    assert first["planner_critical"] is True or first["requiredness"] != "optional"



def test_field_resolution_prefers_promoted_and_executed_official_interconnection_evidence() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "poi-promo",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 138,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.83,
                "evidence_strength": "STRONG",
                "source_ref": ["pjm_study.pdf"],
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "artifact_name": "pjm_study.pdf",
                    "page_number": 4,
                    "section_label": "Facilities Study",
                    "source_method": "interconnection_study.poi_voltage",
                    "specificity": "direct_field_match",
                    "unit": "kV",
                    "is_applicant_document_direct": True,
                },
            },
            {
                "field_record_id": "poi-official-web",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 138,
                "source_stage": "retrieval",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.76,
                "evidence_strength": "STRONG",
                "source_ref": ["https://www.pjm.com/planning/services-requests/interconnection-queues"] ,
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "source_method": "official_web_execution",
                    "source_priority": "official_web_executed",
                    "source_kind": "official_web",
                    "document_type": "official_web_reference",
                    "source_url": "https://www.pjm.com/planning/services-requests/interconnection-queues",
                    "source_hierarchy": "official_interconnection_source",
                    "specificity": "direct_field_match",
                    "unit": "kV",
                    "is_official_source": True,
                },
            },
            {
                "field_record_id": "poi-vendor-wrong",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 34.5,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.90,
                "evidence_strength": "MODERATE",
                "source_ref": ["vendor_transformer.pdf"],
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "source_method": "vendor_pdf",
                    "specificity": "exact_model_match",
                    "unit": "kV",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "point_of_interconnection_voltage_kv")

    assert entry["accepted_value"] == 138
    assert any("executed official web retrieval" in reason.lower() for reason in entry["why_accepted"])
    assert any("interconnection-study promotion" in reason.lower() for reason in entry["why_accepted"])
    assert entry["accepted_source_hierarchy"] in {"applicant_direct_document", "official_interconnection_source"}
