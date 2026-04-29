from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services.interview_service.service import (
    _apply_confirmed_answers_to_canonical_state,
    ingest_interviews,
)


def _build_context(*, project_root: Path, input_dir: Path, run_id: str, project_name: str):
    run_dir = project_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        run_id=run_id,
        project_root=project_root,
        input_dir=input_dir,
        output_dir=run_dir / "outputs",
        run_dir=run_dir,
        config=SimpleNamespace(project_name=project_name),
    )


def test_interview_service_generates_registry_backlog_questions_without_reasking_answered_fields(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_intake_resolution_001",
        project_name="Test Project",
    )

    canonical_state_result = {
        "canonical_state": {
            "field_records": [
                {
                    "field_path": "facility.poi_voltage_kv",
                    "value": 138.0,
                    "status": "resolved",
                    "confidence": 0.92,
                    "is_primary": True,
                }
            ],
            "field_resolution": {
                "backlog": [
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "label": "POI nominal voltage kV",
                        "category": "review_required",
                        "priority": "HIGH",
                        "planner_critical": True,
                        "requiredness": "required",
                        "reason": "voltage conflict requires confirmation",
                        "preferred_sources": ["one_line_diagram"],
                    },
                    {
                        "field_id": "generator_unit_count",
                        "field_path": "facility.generators.count",
                        "label": "Generator unit count",
                        "category": "missing",
                        "priority": "HIGH",
                        "planner_critical": True,
                        "requiredness": "required",
                        "reason": "generator count missing",
                        "preferred_sources": ["equipment_schedule"],
                    },
                ]
            },
            "validation_report": {
                "missing_fields": [
                    {"field_path": "facility.generators.count"},
                ]
            },
            "normalized_input": {},
        }
    }

    result = ingest_interviews(
        context=context,
        input_dir=input_dir,
        extraction_result={},
        normalization_result={"followup_questions": []},
        retrieval_result={},
        canonical_state_result=canonical_state_result,
    )

    questions = result["questions"]
    assert questions
    field_paths = {item["field_path"] for item in questions}
    assert "facility.generators.count" in field_paths
    assert "facility.poi_voltage_kv" in field_paths
    assert any(item["metadata"].get("planner_registry_backed") is True for item in questions)

    tracking_backlog = result["field_tracking"]["planner_registry_resolution_backlog"]
    assert tracking_backlog
    assert any(item["field_path"] == "facility.generators.count" for item in tracking_backlog)


def test_confirmed_interview_answers_update_field_resolution_and_clear_review_queue() -> None:
    canonical_state_result = {
        "canonical_state": {
            "field_records": [
                {
                    "field_path": "facility.poi_voltage_kv",
                    "value": 69.0,
                    "status": "review_required",
                    "validation_status": "review_required",
                    "review_status": "needs_applicant_confirmation",
                    "conflict_status": "candidate_conflict",
                }
            ],
            "validation_report": {},
            "field_resolution": {
                "ledger": [
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "label": "POI nominal voltage kV",
                        "accepted_value": 69.0,
                        "accepted_status": "review_required",
                        "accepted_confidence": 0.55,
                        "confidence_band": "LOW",
                        "requiredness": "required",
                        "planner_critical": True,
                        "packet_section": "interconnection_topology",
                        "packet_section_label": "Interconnection Topology",
                        "planner_review_flag": True,
                        "needs_applicant_confirmation": True,
                        "conflict_materiality": "high",
                        "why_accepted": ["Weak conflict winner from vendor data."],
                        "source_anchors": ["vendor_pdf_page_2"],
                        "alternatives": [{"value": 138.0}],
                    }
                ],
                "accepted_field_index": {
                    "point_of_interconnection_voltage_kv": {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "accepted_value": 69.0,
                        "accepted_status": "review_required",
                        "planner_review_flag": True,
                        "needs_applicant_confirmation": True,
                        "conflict_materiality": "high",
                    },
                    "facility.poi_voltage_kv": {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "accepted_value": 69.0,
                        "accepted_status": "review_required",
                        "planner_review_flag": True,
                        "needs_applicant_confirmation": True,
                        "conflict_materiality": "high",
                    },
                },
                "backlog": [
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "accepted_status": "review_required",
                        "planner_review_flag": True,
                    }
                ],
                "planner_review_queue": [
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "accepted_status": "review_required",
                        "planner_review_flag": True,
                    }
                ],
                "high_materiality_conflicts": [
                    {
                        "field_id": "point_of_interconnection_voltage_kv",
                        "field_path": "facility.poi_voltage_kv",
                        "accepted_status": "review_required",
                        "conflict_materiality": "high",
                    }
                ],
                "summary": {
                    "planner_review_count": 1,
                    "high_materiality_conflict_count": 1,
                    "applicant_confirmation_needed_count": 1,
                },
            },
            "field_resolution_overview": {
                "planner_review_queue": [
                    {"field_path": "facility.poi_voltage_kv"},
                ],
                "high_materiality_conflicts": [
                    {"field_path": "facility.poi_voltage_kv"},
                ],
                "backlog_top": [
                    {"field_path": "facility.poi_voltage_kv"},
                ],
                "summary": {"planner_review_count": 1},
            },
        }
    }

    updated = _apply_confirmed_answers_to_canonical_state(
        canonical_state_result,
        [
            {
                "field_path": "facility.poi_voltage_kv",
                "confirmed_answer": 138.0,
                "source_name": "applicant_interview.json",
            }
        ],
    )

    canonical_state = updated["canonical_state"]
    assert canonical_state["facility.poi_voltage_kv"]["value"] == 138.0
    field_record = canonical_state["field_records"][0]
    assert field_record["status"] == "interview_confirmed"
    assert field_record["source_ref"] == ["applicant_interview.json"]

    accepted = canonical_state["field_resolution"]["accepted_field_index"]["facility.poi_voltage_kv"]
    assert accepted["accepted_value"] == 138.0
    assert accepted["accepted_status"] == "resolved"
    assert accepted["planner_review_flag"] is False
    assert accepted["needs_applicant_confirmation"] is False
    assert accepted["conflict_materiality"] == "none"
    assert accepted["confidence_band"] == "HIGH"
    assert any("Applicant confirmed" in line for line in accepted["why_accepted"])

    assert canonical_state["field_resolution"]["planner_review_queue"] == []
    assert canonical_state["field_resolution"]["high_materiality_conflicts"] == []
    assert canonical_state["field_resolution_overview"]["planner_review_queue"] == []
    assert canonical_state["planner_registry_resolution_backlog"]["planner_registry_backed"] is True
