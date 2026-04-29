def _normalized_path(value: str) -> str:
    return value.replace("\\", "/")

import json
from pathlib import Path

from shared.planner_registry import (
    build_canonical_schema_from_registry,
    planner_legacy_artifact_manifest,
    planner_schema_alignment_summary,
)


def test_derived_canonical_schema_aligns_with_planner_required_fields() -> None:
    canonical_schema = build_canonical_schema_from_registry()
    summary = planner_schema_alignment_summary()

    assert canonical_schema["schema_name"] == "gridsenpai_canonical_facility_model"
    assert canonical_schema["authoritative_source_contract"]["contract_name"] == "planner_required_fields"
    assert canonical_schema["authoritative_source_contract"]["registry_field_count"] >= 524
    assert summary["canonical_schema_aligned"] is True
    assert _normalized_path(summary["canonical_schema_path"]).endswith("shared/schemas/gridsenpai_canonical_facility_model.json")


def test_derived_canonical_schema_is_full_drop_in_json_document() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    canonical_schema_path = repo_root / "shared" / "schemas" / "gridsenpai_canonical_facility_model.json"
    payload = json.loads(canonical_schema_path.read_text())

    assert payload["schema_name"] == "gridsenpai_canonical_facility_model"
    assert "canonical_layers" in payload
    assert "planner_packet_contract" in payload
    assert "planner_field_groups" in payload
    assert "packet_sections" in payload
    assert "field_families" in payload


def test_legacy_artifact_manifest_separates_deprecation_candidates_from_supported_derived_artifacts() -> None:
    manifest = planner_legacy_artifact_manifest()

    assert "shared/schemas/master_QA_intake_schema.json" in manifest["candidate_repo_files_to_deprecate_after_migration"]
    assert "shared/schemas/planner_documents_required.json" in manifest["candidate_repo_files_to_deprecate_after_migration"]
    assert "shared/schemas/gridsenpai_inputs_schema.json" in manifest["still_supported_derived_or_runtime_artifacts"]
    assert "shared/schemas/gridsenpai_outputs_schema.json" in manifest["still_supported_derived_or_runtime_artifacts"]
    assert "shared/schemas/gridsenpai_canonical_facility_model.json" in manifest["still_supported_derived_or_runtime_artifacts"]
