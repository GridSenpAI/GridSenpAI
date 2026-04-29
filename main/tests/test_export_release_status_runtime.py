from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from services.export_service.service import run_service
from shared.security.models import Actor
from shared.security.permissions import Role

@dataclass
class DummyContext:
    run_id: str
    run_dir: Path
    actor: Actor | None = None
    audit_logger: Any | None = None

def _build_context(tmp_path: Path, *, run_id: str) -> DummyContext:
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return DummyContext(run_id=run_id, run_dir=run_dir, actor=Actor(actor_id="engineer-1", role=Role.ENGINEER), audit_logger=None)

def test_export_status_is_not_final_when_release_is_not_ready(tmp_path: Path) -> None:
    context = _build_context(tmp_path, run_id="run_export_provisional")
    run_id = context.run_id
    result = run_service(context=context, canonical_state_result={"run_id": run_id, "canonical_state": {"run_id": run_id, "artifacts": [], "entities": [], "evidence_snippets": [], "normalized_input": {"facility": {"project_name": "Test Project", "poi_voltage_kv": 138.0, "frequency_hz": 60.0, "load_schedule": {"phase_1_mw": 25.0}, "ups": {"topology": "2N", "count": 2}, "generators": {"present": True, "count": 4}, "transformers": {"count": 2, "ratings_mva": [50.0, 50.0]}}, "source_summary": {"artifact_count": 1}}, "field_records": [], "field_resolution": {"ledger": [{"field_id": "generator_rated_kw_per_unit", "field_path": "facility.generators.rated_kw_per_unit", "label": "Generator rated kW per unit", "accepted_status": "review_required", "confidence_band": "MODERATE", "planner_critical": True, "needs_applicant_confirmation": True}]}, "stage_status": {"canonical_state": "CANONICAL_STATE_BUILT", "validation": "VALIDATED", "translation": "TRANSLATED", "scenarios": "SCENARIOS_GENERATED"}, "calibration_datasets": [], "calibration_records": [], "assumption_registry": [], "validation_runs": [], "reconciliation_records": [], "change_log": []}}, validation_result={"run_id": run_id, "status": "VALIDATED", "canonical_state": {}, "summary": {"final_export_ready": False}, "validation_report": {"missing_fields": [], "conflicts": [], "warnings": [], "engineering_validation": {"status": "PASS", "review_flag_count": 0, "summary": {}}, "calibration_summary": {"status": "CALIBRATION_COMPARISON_COMPLETE", "summary": {}}, "reconciliation_summary": {"open_reconciliation_count": 0, "conflict_count": 0}}}, translation_result={"run_id": run_id, "status": "TRANSLATED", "translated_at": "2026-03-16T00:00:00+00:00", "model_outputs": {}, "output_parameters": [], "assumptions": [], "confidence_summary": {}, "schema_validation": {}, "translation_support": {"review_notes": ["Low-confidence translation note."]}, "governance_alerts": {"has_governance_attention": True, "planner_review_count": 1, "high_priority_manual_review_count": 1, "manual_review_queue_summary": {"total_count": 1}}}, scenario_result={"run_id": run_id, "status": "SCENARIOS_GENERATED", "generated_at": "2026-03-16T00:00:00+00:00", "scenarios": {"Typical": {"label": "Typical"}}, "scenario_variants": [{"label": "Typical", "confidence": "LOW", "metadata": {"manual_review_queue_summary": {"total_count": 1}}}], "scenario_families": {"baseline": ["Typical"]}, "governance_alerts": {"has_governance_attention": True, "manual_review_queue_summary": {"total_count": 1}}}, ingestion_result={"status": "ARTIFACTS_INGESTED", "artifacts": []}, retrieval_result={"status": "EVIDENCE_RETRIEVED", "snippets": []}, interview_result={"interview_readiness": {"completion_state": "NEEDS_CRITICAL_APPLICANT_INPUT", "ready_for_validation": False, "ready_for_final_output": False, "blocking_categories": ["missing"], "remaining_question_count": 1, "open_clarification_count": 0, "question_categories": {"missing": 1}, "planner_critical_remaining_question_count": 1, "planner_critical_open_clarification_count": 0, "planner_critical_conflicting_field_count": 0}})
    assert result["status"] in {"EXPORTED_PROVISIONAL", "EXPORTED_BLOCKED"}
    assert result["export_manifest"]["summary"]["final_export_ready"] is False
