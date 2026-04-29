from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.canonical_state_service.service import build_canonical_state
from services.translation_service.service import run_service as run_translation_service
from services.scenario_service.service import run_service as run_scenario_service


@dataclass(slots=True)
class DummyConfig:
    schema_version_input: str = "1.0.0"
    schema_version_output: str = "1.0.0"
    project_name: str = "GridSenpAI Test Project"


@dataclass(slots=True)
class DummyContext:
    run_id: str
    run_dir: Path | None = None
    config: DummyConfig = field(default_factory=DummyConfig)


def test_canonical_state_build_exposes_governed_truth_summary(tmp_path: Path) -> None:
    context = DummyContext(run_id="governed_truth_summary_build", run_dir=tmp_path / "governed_truth_summary_build")
    normalization_result = {
        "run_id": context.run_id,
        "status": "NORMALIZED",
        "normalized_input": {
            "run_id": context.run_id,
            "schema_version": "1.0.0",
            "facility": {
                "project_name": "GridSenpAI Test Project",
                "peak_demand_mw": 120.0,
                "generators": {"count": 2},
            },
            "source_summary": {},
        },
        "validation_report": {"errors": [], "warnings": [], "missing_fields": [], "conflicts": [], "schema_valid": True},
        "followup_questions": [],
    }
    retrieval_result = {
        "run_id": context.run_id,
        "status": "EVIDENCE_RETRIEVED",
        "equipment_reference_resolution": {
            "candidate_fields": [
                {
                    "canonical_field_key": "generator_rated_kw_per_unit",
                    "value": 3000,
                    "confidence": 0.89,
                    "manufacturer": "cummins",
                    "model": "abc",
                    "source_ref": ["datasheet"],
                    "source_type": "vendor_pdf",
                    "lookup_strategy": "manufacturer_model_specific_spec",
                    "equipment_family": "generator",
                },
                {
                    "canonical_field_key": "generator_rated_kw_per_unit",
                    "value": 3600,
                    "confidence": 0.88,
                    "manufacturer": "cummins",
                    "model": "abc",
                    "source_ref": ["alternate_datasheet"],
                    "source_type": "vendor_pdf",
                    "lookup_strategy": "manufacturer_model_specific_spec",
                    "equipment_family": "generator",
                },
            ]
        },
    }
    result = build_canonical_state(context=context, normalization_result=normalization_result, retrieval_result=retrieval_result)
    summary = result["canonical_state"]["governed_truth_summary"]
    assert summary["planner_registry_backed"] is True
    assert summary["accepted_planner_field_count"] >= 1
    assert summary["high_materiality_conflict_count"] >= 1
    assert isinstance(summary["top_backlog_field_ids"], list)
    assert "governed_distinction_summary" in summary


def test_translation_and_scenario_propagate_governed_truth_summary() -> None:
    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {"facility": {"load_schedule": {"phase_1_mw": 60.0}}},
            "validation_report": {"schema_valid": True, "missing_fields": [], "conflicts": [], "interview_summary": {"confirmed_field_paths": []}},
            "evidence_snippets": [],
            "governed_truth_summary": {
                "accepted_planner_field_count": 4,
                "planner_review_count": 2,
                "applicant_confirmation_needed_count": 1,
                "high_materiality_conflict_count": 1,
                "review_required_count": 2,
                "conflicting_count": 1,
                "top_backlog_field_ids": ["generator_rated_kw_per_unit"],
                "governed_distinction_summary": {"review_required": 2},
            },
            "field_resolution": {
                "accepted_field_index": {
                    "accepted_peak_demand_mw": {
                        "accepted_value": 60.0,
                        "accepted_status": "resolved",
                        "accepted_confidence": 0.86,
                        "confidence_band": "HIGH",
                        "why_accepted": ["Peak demand reconciled across applicant evidence."],
                        "source_anchors": ["schedule.pdf / page 2"],
                        "planner_review_flag": False,
                        "needs_applicant_confirmation": False,
                        "decision_basis": "reconciled demand package",
                    },
                    "net_power_factor_at_poi": {
                        "accepted_value": 0.8,
                        "accepted_status": "review_required",
                        "accepted_confidence": 0.55,
                        "confidence_band": "LOW",
                        "why_accepted": ["PF provided in applicant load information form."],
                        "source_anchors": ["load_form.pdf / page 1"],
                        "planner_review_flag": True,
                        "needs_applicant_confirmation": True,
                        "decision_basis": "validated applicant answer",
                    },
                }
            },
        }
    }
    translation = run_translation_service(context=DummyContext(run_id="translation_governance"), canonical_state_result=canonical_state_result)
    assert translation["governed_truth_summary"]["planner_review_count"] == 2
    assert translation["governance_alerts"]["has_governance_attention"] is True
    assert translation["governance_alerts"]["top_backlog_field_ids"] == ["generator_rated_kw_per_unit"]

    scenarios = run_scenario_service(context=DummyContext(run_id="scenario_governance"), translation_result=translation)
    assert scenarios["governed_truth_summary"]["high_materiality_conflict_count"] == 1
    assert scenarios["governance_alerts"]["applicant_confirmation_needed_count"] == 1
    typical = next(item for item in scenarios["scenario_variants"] if item["label"] == "Typical")
    assert typical["metadata"]["governance_alerts"]["planner_review_count"] == 2


def test_translation_and_scenario_use_shared_manual_review_priority_for_governance_gating() -> None:
    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {"facility": {"load_schedule": {"phase_1_mw": 60.0}}},
            "validation_report": {"schema_valid": True, "missing_fields": [], "conflicts": [], "interview_summary": {"confirmed_field_paths": []}},
            "evidence_snippets": [],
            "governed_truth_summary": {
                "accepted_planner_field_count": 2,
                "planner_review_count": 0,
                "applicant_confirmation_needed_count": 0,
                "high_materiality_conflict_count": 0,
                "review_required_count": 0,
                "conflicting_count": 0,
                "top_backlog_field_ids": [],
                "governed_distinction_summary": {},
            },
            "field_resolution": {
                "ledger": [
                    {
                        "field_id": "net_power_factor_at_poi",
                        "field_path": "facility.poi.power_factor",
                        "label": "POI Power Factor",
                        "accepted_status": "review_required",
                        "accepted_value": 0.8,
                        "confidence_band": "LOW",
                        "planner_critical": True,
                        "needs_applicant_confirmation": True,
                        "unresolved_reason": "POI PF still needs applicant confirmation.",
                    }
                ],
                "accepted_field_index": {
                    "net_power_factor_at_poi": {
                        "accepted_value": 0.8,
                        "accepted_status": "review_required",
                        "accepted_confidence": 0.45,
                        "confidence_band": "LOW",
                        "why_accepted": ["Applicant form supplied PF."],
                        "source_anchors": ["load_form.pdf / page 1"],
                        "planner_review_flag": False,
                        "needs_applicant_confirmation": False,
                        "decision_basis": "validated applicant answer",
                    },
                },
            },
            "planner_packet_field_rows": {},
            "source_candidate_inputs": {"evidence_route_records": []},
        }
    }
    translation = run_translation_service(context=DummyContext(run_id="translation_review_priority"), canonical_state_result=canonical_state_result)
    assert translation["governance_alerts"]["manual_review_interview_dependency_count"] == 1
    assert translation["governance_alerts"]["manual_review_planner_critical_count"] == 1
    assert translation["governance_alerts"]["has_governance_attention"] is True
    pf_param = next(item for item in translation["output_parameters"] if item["parameter_path"] == "steady_state.power_factor")
    assert pf_param["confidence_tag"] == "LOW"
    assert pf_param["planner_review_flag"] is True
    assert pf_param["needs_applicant_confirmation"] is True
    assert pf_param["shared_review_priority_bucket"] == "interview_dependency"

    scenarios = run_scenario_service(context=DummyContext(run_id="scenario_review_priority"), translation_result=translation)
    typical = next(item for item in scenarios["scenario_variants"] if item["label"] == "Typical")
    assert typical["confidence"] == "LOW"
    assert typical["metadata"]["manual_review_queue_summary"]["interview_dependency_count"] == 1
    assert translation["governance_alerts"]["field_governance_summary"]["field_count"] >= 1
    assert typical["metadata"]["field_governance_summary"]["field_count"] >= 1
