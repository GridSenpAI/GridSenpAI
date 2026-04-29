from services.equipment_reference_resolution_service.planner_guidance import (
    canonical_input_schema_fields,
    planner_document_field_map,
    target_fields_for_families,
)


def test_registry_backed_family_fields_include_identity_and_specs() -> None:
    fields = canonical_input_schema_fields()
    generator_fields = fields["generators"]
    transformer_fields = fields["transformers"]

    assert "generator_unit_count" in generator_fields
    assert "generator_manufacturer" in generator_fields
    assert "generator_model" in generator_fields
    assert "generator_rated_kw_per_unit" in generator_fields

    assert "interconnection_transformer_unit_count" in transformer_fields
    assert "interconnection_transformer_manufacturer" in transformer_fields
    assert "interconnection_transformer_model" in transformer_fields


def test_planner_document_map_returns_family_buckets() -> None:
    document_map = planner_document_field_map()
    assert set(document_map.keys()) >= {"generators", "ups", "transformers", "switchgear", "relays", "cooling_systems"}


def test_target_fields_for_families_prefers_registry_vendor_resolvable_fields() -> None:
    result = target_fields_for_families(
        families=["generators"],
        requested_missing_fields=["generator_model", "generator_unit_count", "load_customer_name"],
        family_record_fields={"generators": ["generator_nameplate_summary"]},
    )

    assert result["families"] == ["generators"]
    assert "generator_model" in result["vendor_resolvable_requested_fields"]
    assert "generator_unit_count" in result["vendor_resolvable_requested_fields"]
    assert "load_customer_name" in result["out_of_scope_requested_fields"]
    assert "generator_nameplate_summary" in result["target_fields"]
    assert result["sources"]["planner_documents"] == "shared/schemas/planner_required_fields.json#planner_documents"
