from __future__ import annotations

import os
import pytest

from services.field_resolution_service.service import build_field_resolution_result
from services.export_service.service import _build_planner_packet

requires_audit_mode = pytest.mark.skipif(os.getenv("GRIDSENPAI_AUDIT_MODE", "0") != "1", reason="Audit-mode planner packet sections are disabled in current environment.")

def test_field_acceptance_policy_blocks_planner_critical_conflict_with_material_runner_up() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "poi-official",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 138,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.89,
                "evidence_strength": "STRONG",
                "source_ref": ["official_poi_guide"],
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "source_method": "official_interconnection_source",
                    "specificity": "direct_field_match",
                    "evidence_tier": "official_interconnection_source",
                },
            },
            {
                "field_record_id": "poi-vendor",
                "field_path": "point_of_interconnection_voltage_kv",
                "value": 115,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.84,
                "evidence_strength": "STRONG",
                "source_ref": ["vendor_poi_sheet"],
                "metadata": {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "source_method": "vendor_pdf",
                    "specificity": "direct_field_match",
                    "evidence_tier": "vendor_document_pointer",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "point_of_interconnection_voltage_kv")
    policy = entry["acceptance_policy_result"]
    assert policy["outcome"] == "blocked_conflict"
    assert policy["status_recommendation"] == "conflicting"
    assert policy["required_next_action"] == "obtain_applicant_clarification"
    assert entry["accepted_status"] == "conflicting"


@requires_audit_mode
def test_export_packet_includes_field_acceptance_policy_matrix() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "point_of_interconnection_voltage_kv",
                    "field_path": "interconnection.point_of_interconnection_voltage_kv",
                    "label": "POI nominal voltage kV",
                    "planner_critical": True,
                    "planner_review_flag": True,
                    "acceptance_policy_result": {
                        "outcome": "accepted_provisional",
                        "support_strength_tier": "MODERATE",
                        "acceptance_threshold_met": False,
                        "status_recommendation": "review_required",
                        "required_next_action": "obtain_applicant_clarification",
                        "reasons": [
                            "Support tier evaluated as MODERATE using source hierarchy, specificity, agreement, and conflict checks.",
                            "Winner confidence did not clear the governed threshold (0.80).",
                        ],
                    },
                }
            ],
            "summary": {},
        },
        "entities": [],
        "field_records": [],
    }
    payload = _build_planner_packet(
        run_id="run-1",
        canonical_state=canonical_state,
        validation_result={"validation_report": {}},
        translation_result={"output_parameters": [], "model_outputs": {}, "assumptions": [], "confidence_summary": {}},
        scenario_result={"scenarios": {}},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "## Field Acceptance Policy Matrix" in payload
    assert "- POI nominal voltage kV: accepted_provisional [MODERATE; threshold_met=no]" in payload
    assert "  - status_recommendation: review_required" in payload
    assert "  - next_action: obtain_applicant_clarification" in payload


def test_field_acceptance_policy_blocks_planner_critical_topology_field_on_medium_conflict() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "gen-count-doc",
                "field_path": "generator_unit_count",
                "value": 24,
                "source_stage": "extraction",
                "source_type": "schema_field_candidate",
                "confidence_score": 0.91,
                "evidence_strength": "STRONG",
                "source_ref": ["one_line"],
                "metadata": {
                    "field_id": "generator_unit_count",
                    "specificity": "direct_field_match",
                    "artifact_name": "one_line.pdf",
                },
            },
            {
                "field_record_id": "gen-count-vendor",
                "field_path": "generator_unit_count",
                "value": 25,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "confidence_score": 0.87,
                "evidence_strength": "STRONG",
                "source_ref": ["equipment_schedule"],
                "metadata": {
                    "field_id": "generator_unit_count",
                    "source_method": "vendor_pdf",
                    "specificity": "direct_field_match",
                    "evidence_tier": "vendor_document_pointer",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "generator_unit_count")
    policy = entry["acceptance_policy_result"]
    assert policy["field_class"] == "planner_critical"
    assert policy["materiality_class"] == "topology_configuration"
    assert policy["outcome"] == "blocked_conflict"
    assert entry["accepted_status"] == "conflicting"


def test_field_acceptance_policy_allows_supporting_descriptive_field_as_inferred_when_single_source() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "county-only",
                "field_path": "county_or_parish",
                "value": "McLennan",
                "source_stage": "normalization",
                "source_type": "normalized_input",
                "confidence_score": 0.66,
                "evidence_strength": "MODERATE",
                "source_ref": ["intake_form"],
                "metadata": {
                    "field_id": "county_or_parish",
                    "specificity": "direct_field_match",
                },
            },
        ]
    }

    result = build_field_resolution_result(canonical_state)
    entry = next(item for item in result["ledger"] if item["field_id"] == "county_or_parish")
    policy = entry["acceptance_policy_result"]
    assert policy["field_class"] == "planner_relevant"
    assert policy["materiality_class"] == "descriptive_identity"
    assert policy["outcome"] == "accepted_inferred"
    assert entry["accepted_status"] == "resolved"


@requires_audit_mode
def test_export_packet_acceptance_policy_matrix_includes_field_policy_classes() -> None:
    canonical_state = {
        "field_resolution": {
            "ledger": [
                {
                    "field_id": "generator_unit_count",
                    "field_path": "generation.generator_unit_count",
                    "label": "Generator unit count",
                    "planner_critical": True,
                    "planner_review_flag": True,
                    "field_policy_class": "planner_critical",
                    "field_materiality_class": "topology_configuration",
                    "acceptance_policy_result": {
                        "outcome": "blocked_conflict",
                        "support_strength_tier": "MODERATE",
                        "acceptance_threshold_met": True,
                        "field_class": "planner_critical",
                        "materiality_class": "topology_configuration",
                        "status_recommendation": "conflicting",
                        "required_next_action": "obtain_applicant_clarification",
                        "reasons": [
                            "Support tier evaluated as MODERATE using source hierarchy, specificity, agreement, and conflict checks.",
                        ],
                    },
                }
            ],
            "summary": {},
        },
        "entities": [],
        "field_records": [],
    }
    payload = _build_planner_packet(
        run_id="run-1",
        canonical_state=canonical_state,
        validation_result={"validation_report": {}},
        translation_result={"output_parameters": [], "model_outputs": {}, "assumptions": [], "confidence_summary": {}},
        scenario_result={"scenarios": {}},
        intake_summary={},
        agent_audit_summary={},
        interview_readiness={},
        retrieval_result={},
        interview_result={},
        gap_resolution_result={},
        export_result={},
    )
    assert "  - field_policy: class=planner_critical; materiality=topology_configuration" in payload
