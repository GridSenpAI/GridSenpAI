from services.field_resolution_service.service import build_field_resolution_result


def test_field_resolution_assigns_value_kind_and_attention_tier_for_direct_document_fact():
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "r1",
                "field_path": "interconnection.point_of_interconnection_voltage_kv",
                "value": 138.0,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "source_ref": ["poi_one_line.pdf"],
                "confidence_score": 0.97,
                "evidence_strength": "STRONG",
                "metadata": {"field_id": "point_of_interconnection_voltage_kv", "specificity": "direct_field_match", "source_anchor": "poi_one_line.pdf:p2"},
            }
        ]
    }
    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "point_of_interconnection_voltage_kv")
    assert entry["accepted_value_kind"] == "direct_document_fact"
    assert entry["planner_attention_tier"] in {"critical_resolved", "information"}
