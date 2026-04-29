from shared.master_field_policy import (
    field_policy_export,
    master_policy_coverage_audit,
    registry_policy_manifest,
    source_role_authority_score,
)


def test_policy_coverage_audit_covers_every_registry_field_explicitly() -> None:
    audit = master_policy_coverage_audit()
    assert audit["registry_field_count"] == 524
    assert audit["policy_count"] == audit["registry_field_count"]
    assert audit["explicit_policy_count"] == audit["registry_field_count"]
    assert audit["fallback_policy_count"] == 0
    assert audit["fields_without_rejected_context_count"] == 0


def test_policy_export_contains_required_end_state_contract_fields() -> None:
    policy = field_policy_export("point_of_interconnection_voltage_kv")
    for key in (
        "field_id",
        "field_path",
        "field_label",
        "definition",
        "data_type",
        "expected_unit",
        "aliases",
        "accepted_contexts",
        "rejected_contexts",
        "preferred_source_roles",
        "conflict_behavior",
        "interview_priority",
        "export_criticality",
        "policy_source",
        "policy_coverage",
    ):
        assert key in policy
    assert policy["field_id"] == "point_of_interconnection_voltage_kv"
    assert policy["expected_unit"] == "kV"
    assert policy["policy_source"] == "registry_first_with_field_enrichment"
    assert policy["policy_coverage"]["coverage_level"] == "explicit"


def test_failure_family_policies_are_field_specific_not_only_heuristic() -> None:
    poi = field_policy_export("point_of_interconnection_voltage_kv")
    distribution = field_policy_export("distribution_voltage_levels")
    gen_count = field_policy_export("generator_unit_count")
    requested_date = field_policy_export("requested_in_service_date")
    revision_date = field_policy_export("one_line_revision_date")

    assert "nominal service voltage" in poi["accepted_contexts"]
    assert "generator terminal" in poi["rejected_contexts"]
    assert "point of interconnection" in distribution["rejected_contexts"]
    assert gen_count["conflict_behavior"]["candidate_strategy"] == "prefer_explicit_quantity_source_not_drawing_frequency"
    assert requested_date["conflict_behavior"]["drawing_dates_are_rejected"] is True
    assert revision_date["policy_family"] == "date"
    assert "requested in-service" in revision_date["rejected_contexts"]


def test_registry_source_preferences_drive_source_authority() -> None:
    assert source_role_authority_score("generator_unit_count", "equipment_schedule") > source_role_authority_score("generator_unit_count", "drawing")
    assert source_role_authority_score("requested_in_service_date", "application_request_form") > source_role_authority_score("requested_in_service_date", "drawing")
    assert source_role_authority_score("generator_model", "oem_reference") > source_role_authority_score("generator_model", "drawing")


def test_policy_manifest_is_registry_sized_and_serializable() -> None:
    manifest = registry_policy_manifest()
    assert len(manifest) == 524
    assert all(item["policy_coverage"]["coverage_level"] == "explicit" for item in manifest)
