from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from services.export_service.service import run_service
from shared.planner_registry import summarize_registry_packet_coverage
from shared.security.models import Actor
from shared.security.permissions import Role


@dataclass
class DummyContext:
    run_id: str
    run_dir: Path
    actor: Actor | None = None
    audit_logger: Any | None = None


def _build_context(tmp_path: Path, *, actor: Actor | None, run_id: str = "run_registry_packet_001") -> DummyContext:
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return DummyContext(run_id=run_id, run_dir=run_dir, actor=actor, audit_logger=None)


def _build_canonical_state_result(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "canonical_state": {
            "run_id": run_id,
            "artifacts": [],
            "entities": [],
            "evidence_snippets": [],
            "normalized_input": {
                "facility": {
                    "project_name": "Registry Test Project",
                    "poi_voltage_kv": 345.0,
                    "frequency_hz": 60.0,
                    "load_schedule": {"phase_1_mw": 120.0},
                    "ups": {"topology": "2N", "count": 6},
                    "generators": {"present": True, "count": 24},
                    "transformers": {"count": 3, "ratings_mva": [75.0, 75.0, 75.0]},
                },
                "source_summary": {
                    "artifact_count": 2,
                    "parsed_document_count": 2,
                    "ocr_document_count": 1,
                    "extraction_candidate_count": 12,
                },
            },
            "field_records": [
                {
                    "field_record_id": "fr_project_name",
                    "field_path": "facility.project_name",
                    "value": "Registry Test Project",
                    "status": "validated",
                    "validation_status": "VALIDATED",
                    "review_status": "RESOLVED",
                    "conflict_status": "NO_CONFLICT",
                    "source_stage": "normalization",
                    "source_type": "document",
                    "source_ref": ["artifact_001"],
                    "metadata": {},
                    "is_primary": True,
                },
                {
                    "field_record_id": "fr_poi_voltage",
                    "field_path": "facility.poi_voltage_kv",
                    "value": 345.0,
                    "status": "validated",
                    "validation_status": "VALIDATED",
                    "review_status": "RESOLVED",
                    "conflict_status": "NO_CONFLICT",
                    "source_stage": "normalization",
                    "source_type": "document",
                    "source_ref": ["artifact_001"],
                    "metadata": {},
                    "is_primary": True,
                },
                {
                    "field_record_id": "fr_generator_count",
                    "field_path": "facility.generators.count",
                    "value": 24,
                    "status": "provisional_retrieved",
                    "validation_status": "PROVISIONAL_RETRIEVED",
                    "review_status": "PENDING_REVIEW",
                    "conflict_status": "NO_CONFLICT",
                    "source_stage": "retrieval",
                    "source_type": "vendor_pdf",
                    "source_ref": ["datasheet_001"],
                    "metadata": {},
                    "is_primary": True,
                },
                {
                    "field_record_id": "fr_transformer_count",
                    "field_path": "facility.transformers.count",
                    "value": 3,
                    "status": "conflicting",
                    "validation_status": "CONFLICTING",
                    "review_status": "PENDING_REVIEW",
                    "conflict_status": "CONFLICT_PRESENT",
                    "source_stage": "extraction",
                    "source_type": "document",
                    "source_ref": ["artifact_002"],
                    "metadata": {},
                    "is_primary": True,
                },
            ],
            "stage_status": {
                "canonical_state": "CANONICAL_STATE_BUILT",
                "validation": "VALIDATED",
                "translation": "TRANSLATED",
                "scenarios": "SCENARIOS_GENERATED",
            },
            "calibration_datasets": [],
            "calibration_records": [],
            "assumption_registry": [],
            "validation_runs": [],
            "reconciliation_records": [],
            "change_log": [],
        },
    }


def _build_validation_result(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "VALIDATED",
        "summary": {},
        "canonical_state": {},
        "validation_report": {
            "missing_fields": [
                {"field_path": "facility.ups.topology"},
                {"field_path": "facility.generators.ratings"},
            ],
            "conflicts": [
                {"field_path": "facility.transformers.count"},
            ],
            "warnings": [],
            "engineering_validation": {"status": "PASS", "review_flag_count": 0, "summary": {}},
            "calibration_summary": {"status": "NONE", "summary": {}},
            "reconciliation_summary": {},
        },
    }


def _build_translation_result(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "TRANSLATED",
        "translated_at": "2026-04-17T00:00:00+00:00",
        "model_outputs": {"steady_state": {"p_mw": 120.0}},
        "output_parameters": [{"parameter_path": "steady_state.p_mw", "value": 120.0, "confidence_tag": "MODERATE"}],
        "assumptions": [],
        "confidence_summary": {"high": 0, "medium": 1, "low": 0},
        "schema_validation": {},
        "translation_support": {
            "review_notes": [],
            "low_confidence_parameters": [],
            "assumption_backed_parameters": [],
            "missing_dependency_parameters": [],
        },
    }


def _build_scenario_result(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "SCENARIOS_GENERATED",
        "generated_at": "2026-04-17T00:00:00+00:00",
        "scenarios": {"Typical": {"label": "Typical"}},
        "scenario_variants": [{"label": "Typical"}],
        "scenario_families": {"baseline": ["Typical"]},
    }


def _build_ingestion_result() -> dict[str, Any]:
    return {
        "status": "ARTIFACTS_INGESTED",
        "artifact_count": 2,
        "artifacts": [{"artifact_id": "artifact_001"}, {"artifact_id": "artifact_002"}],
        "intake_session": {
            "session_id": "intake_registry_001",
            "session_path": "/tmp/intake_registry_001.json",
            "status": "COMPLETE",
            "required_artifact_count": 2,
            "uploaded_artifact_count": 2,
            "missing_required_count": 0,
            "requirements": [],
        },
    }


def test_registry_packet_coverage_summarizes_resolved_review_and_conflicting_fields() -> None:
    canonical_state = _build_canonical_state_result("run_registry_packet_coverage")["canonical_state"]
    validation_report = _build_validation_result("run_registry_packet_coverage")["validation_report"]

    summary = summarize_registry_packet_coverage(canonical_state, validation_report)

    assert summary["total_field_count"] > 0
    assert summary["required_field_count"] > 0
    assert summary["resolved_count"] > 0
    assert summary["review_required_count"] > 0
    assert summary["conflicting_count"] > 0
    assert summary["missing_count"] > 0
    assert any(section["section_id"] == "generator_system" for section in summary["sections"])


def test_export_packet_includes_registry_coverage_and_section_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRIDSENPAI_EXPORT_PLANNER_PACKET_MD", "1")
    actor = Actor(
        actor_id="engineer_registry_001",
        role=Role.ENGINEER,
        display_name="Engineer User",
        email="engineer@example.com",
    )
    context = _build_context(tmp_path, actor=actor)
    run_id = context.run_id

    result = run_service(
        context=context,
        canonical_state_result=_build_canonical_state_result(run_id),
        validation_result=_build_validation_result(run_id),
        translation_result=_build_translation_result(run_id),
        scenario_result=_build_scenario_result(run_id),
        ingestion_result=_build_ingestion_result(),
    )

    exports_dir = context.run_dir / "exports"
    planner_packet = (exports_dir / "planner_packet.md").read_text(encoding="utf-8")
    run_manifest = json.loads((exports_dir / "run_manifest.json").read_text(encoding="utf-8"))

    assert result["status"] in {"EXPORTED", "EXPORTED_PROVISIONAL"}
    assert "## Planner Registry Coverage" in planner_packet
    assert "## Planner Packet Section Coverage" in planner_packet
    assert "### Project And Process Context" in planner_packet
    assert "Project Name: Registry Test Project" in planner_packet
    assert run_manifest["summary"]["planner_registry_total_field_count"] > 0
    assert run_manifest["summary"]["planner_registry_required_field_count"] > 0
