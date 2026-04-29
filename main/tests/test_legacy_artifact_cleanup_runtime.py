from __future__ import annotations

import inspect

from shared.planner_registry import planner_legacy_artifact_manifest
from shared.schemas import domain_registry


DELETED = {
    "shared/schemas/master_QA_intake_schema.json",
    "shared/schemas/planner_documents_required.json",
    "shared/schemas/master_extraction_blueprint.json",
}


def test_legacy_artifact_manifest_tracks_deleted_legacy_artifacts() -> None:
    manifest = planner_legacy_artifact_manifest()
    assert manifest.get("safe_to_delete_now", []) == []
    assert set(manifest.get("deleted_legacy_artifacts", [])) == DELETED
    assert DELETED.issubset(set(manifest.get("inactive_legacy_fallback_artifacts", [])))
    assert "shared/schemas/gridsenpai_inputs_schema.json" in manifest.get(
        "still_supported_derived_or_runtime_artifacts", []
    )


def test_domain_registry_no_longer_references_legacy_schema_files() -> None:
    source = inspect.getsource(domain_registry)
    assert "master_QA_intake_schema.json" not in source
    assert "planner_documents_required.json" not in source
    assert "master_extraction_blueprint.json" not in source

    extraction_fields = domain_registry.load_extraction_blueprint()
    intake_questions = domain_registry.load_intake_question_specs()
    planner_documents = domain_registry.load_planner_document_specs()

    assert extraction_fields
    assert intake_questions
    assert planner_documents
