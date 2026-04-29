from shared.field_value_policies import context_adjustment, candidate_is_rejected_for_field, normalization_authority_score
from shared.master_field_policy import field_policy_export, source_role_authority_score
from services.field_resolution_service.adjudication_packets import build_adjudication_packet_plan


def test_master_field_policy_exists_for_registry_fields() -> None:
    policy = field_policy_export("point_of_interconnection_voltage_kv")
    assert policy["field_id"] == "point_of_interconnection_voltage_kv"
    assert policy["expected_unit"] == "kV"
    assert policy["policy_family"] == "interconnection"
    assert "interview" in policy["preferred_source_roles"]
    assert policy["preferred_source_roles"]["interview"] >= policy["preferred_source_roles"].get("application_request_form", 0)


def test_policy_scoring_rejects_internal_voltage_for_poi() -> None:
    candidate = {
        "field_path": "facility.poi_voltage_kv",
        "value": "13.8 kV",
        "unit": "kV",
        "method": "table_row",
        "confidence": "HIGH",
        "metadata": {"source_role": "equipment_schedule", "source_excerpt": "Campus medium voltage distribution main switchgear voltage 13.8 kV"},
    }
    adjustment, notes, rejected = context_adjustment("facility.poi_voltage_kv", candidate)
    assert rejected is True
    assert adjustment < 0
    assert any("rejected field-intent" in note.lower() for note in notes)
    assert candidate_is_rejected_for_field("facility.poi_voltage_kv", candidate)


def test_source_role_authority_is_field_specific() -> None:
    poi_form = source_role_authority_score("facility.poi_voltage_kv", "application_request_form")
    poi_oem = source_role_authority_score("facility.poi_voltage_kv", "oem_reference")
    generator_schedule = source_role_authority_score("facility.generators.count", "equipment_schedule")
    generator_drawing = source_role_authority_score("facility.generators.count", "drawing")
    assert poi_form > poi_oem
    assert generator_schedule > generator_drawing


def test_normalization_authority_prefers_explicit_schedule_count_over_drawing_count() -> None:
    schedule = {
        "field_path": "facility.generators.count",
        "value": 60,
        "confidence": "HIGH",
        "method": "table_row",
        "metadata": {"source_role": "equipment_schedule", "source_excerpt": "Campus quantity: 60 generator units total"},
    }
    drawing = {
        "field_path": "facility.generators.count",
        "value": 64,
        "confidence": "HIGH",
        "method": "drawing_label_count",
        "metadata": {"source_role": "drawing", "source_excerpt": "Repeated drawing labels / typical symbols counted on sheet"},
    }
    assert normalization_authority_score("facility.generators.count", schedule) > normalization_authority_score("facility.generators.count", drawing)


def test_adjudication_packet_includes_field_policy_contract() -> None:
    ledger = [
        {
            "field_id": "point_of_interconnection_voltage_kv",
            "field_path": "facility.poi_voltage_kv",
            "label": "POI nominal voltage kV",
            "accepted_status": "conflicting",
            "accepted_value": 13.8,
            "accepted_confidence": 0.42,
            "planner_critical": True,
            "candidates": [
                {
                    "candidate_id": "doc-1",
                    "value": 138,
                    "unit": "kV",
                    "confidence": 0.9,
                    "metadata": {"source_role": "application_request_form", "source_excerpt": "Nominal service voltage: 138 kV"},
                }
            ],
        }
    ]
    plan = build_adjudication_packet_plan(ledger=ledger, summary={}, max_input_chars=4000)
    assert plan.packets
    field = plan.packets[0]["adjudication_targets"][0]
    assert field["field_policy"]["policy_family"] == "interconnection"
    assert "preferred_source_roles" in field["field_policy"]
    assert field["expected_unit"] == "kV"
