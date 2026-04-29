def _normalized_path(value: str) -> str:
    return value.replace("\\", "/")

from shared.runtime_stage_contract import replay_contract_summary


def test_runtime_contract_reports_canonical_schema_alignment_and_legacy_manifest() -> None:
    summary = replay_contract_summary()
    alignment = summary["derived_schema_alignment"]
    manifest = summary["legacy_artifact_manifest"]

    assert alignment["canonical_schema_aligned"] is True
    assert alignment["canonical_schema_field_count"] >= 524
    assert _normalized_path(alignment["canonical_schema_path"]).endswith("shared/schemas/gridsenpai_canonical_facility_model.json")
    assert manifest["planner_registry_backed"] is True
    assert "shared/schemas/master_QA_intake_schema.json" in manifest["candidate_repo_files_to_deprecate_after_migration"]
