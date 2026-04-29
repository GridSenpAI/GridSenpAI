from __future__ import annotations

from pathlib import Path

from shared.runtime_stage_contract import replay_contract_summary


DELETED = {
    "shared/schemas/master_QA_intake_schema.json",
    "shared/schemas/planner_documents_required.json",
    "shared/schemas/master_extraction_blueprint.json",
}


def test_runtime_contract_reports_deleted_legacy_artifacts() -> None:
    summary = replay_contract_summary()
    safe_delete = set(summary.get("legacy_artifacts_safe_to_delete_now", []))
    deleted = set(summary.get("deleted_legacy_artifacts", []))
    assert safe_delete == set()
    assert deleted == DELETED


def test_deleted_legacy_artifacts_are_absent_from_repo() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for rel_path in DELETED:
        assert not (repo_root / rel_path).exists()
