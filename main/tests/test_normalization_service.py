from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from services.normalization_service.service import normalize_inputs, run_service


@dataclass(slots=True)
class _Config:
    schema_version_input: str = "0.1.0"
    project_name: str = "GridSenpAI Test Project"


@dataclass(slots=True)
class _Context:
    run_id: str
    run_dir: Path
    config: _Config = field(default_factory=_Config)



def test_normalization_service_normalizes_available_inputs_and_surfaces_registry_backlog(tmp_path: Path) -> None:
    context = _Context(run_id="norm_001", run_dir=tmp_path / "norm_001")

    extraction_result = {
        "canonical_state": {
            "facility.poi_voltage_kv": {
                "value": 138,
                "method": "drawing_review",
                "source_artifact_id": "artifact_poi",
                "confidence": 0.92,
            },
            "facility.ups.topology": {
                "value": "2N",
                "method": "spec_sheet",
                "source_artifact_id": "artifact_ups",
                "confidence": 0.87,
            },
        },
        "entities": [
            {
                "type": "generator",
                "name": "Generator A",
                "entity_id": "gen_001",
                "source_anchor_id": "anchor_gen",
                "confidence": "HIGH",
                "attributes": {"count": 2},
            }
        ],
        "calibration_datasets": [
            {
                "dataset_id": "dataset_001",
                "dataset_type": "COMMISSIONING",
                "version": "1.0.0",
                "source_artifact_id": "artifact_cal",
                "source_file_name": "commissioning.csv",
                "provenance": {"source_type": "commissioning"},
                "parameters": [
                    {
                        "field_path": "facility.load_schedule.phase_1_mw",
                        "value": 1250,
                        "units": "kW",
                        "target_units": "MW",
                    }
                ],
            }
        ],
    }
    interview_result = {
        "answers_confirmed": [
            {
                "field_path": "facility.load_schedule.phase_1_mw",
                "confirmed_answer": 24,
                "question_id": "q_001",
                "source_name": "engineer interview",
            }
        ],
        "clarifications": [],
    }
    retrieval_result = {"snippets": [{"snippet_id": "snippet_001"}]}

    result = normalize_inputs(
        context=context,
        extraction_result=extraction_result,
        interview_result=interview_result,
        retrieval_result=retrieval_result,
    )

    assert result["status"] == "FAILED_SCHEMA_VALIDATION"
    assert result["normalized_input"]["facility"]["poi_voltage_kv"] == 138.0
    assert result["normalized_input"]["facility"]["load_schedule"]["phase_1_mw"] == 24.0
    assert result["normalized_input"]["facility"]["ups"]["topology"] == "2N"
    assert result["normalized_input"]["facility"]["generators"]["present"] is True
    assert result["normalized_input"]["facility"]["generators"]["count"] == 1
    assert result["normalized_input"]["source_summary"]["evidence_snippet_count"] == 1
    assert result["calibration_dataset_count"] == 1
    assert result["calibration_datasets"][0]["parameters"][0]["normalized_value"] == 1.25
    assert result["validation_report"]["schema_valid"] is False
    assert result["validation_report"]["planner_registry_required_field_count"] > result["validation_report"]["planner_registry_resolved_required_field_count"]

    missing_field_ids = {item["field_id"] for item in result["validation_report"]["missing_fields"]}
    assert "ups_unit_count" in missing_field_ids
    assert "generator_rated_kw_per_unit" in missing_field_ids
    assert "interconnection_transformer_unit_count" in missing_field_ids

    followup_paths = {item["field_path"] for item in result["followup_questions"]}
    assert "facility.ups.count" in followup_paths
    assert "facility.generators.ratings" in followup_paths
    assert "facility.transformers.count" in followup_paths



def test_normalization_service_uses_failed_schema_validation_to_drive_followups(tmp_path: Path) -> None:
    context = _Context(run_id="norm_002", run_dir=tmp_path / "norm_002")

    result = run_service(
        context=context,
        extraction_result={"entities": [], "topology_cues": [], "canonical_state": {}},
        interview_result=None,
        retrieval_result=None,
    )

    assert result["status"] == "FAILED_SCHEMA_VALIDATION"
    assert result["validation_report"]["schema_valid"] is False
    assert result["validation_report"]["planner_registry_required_field_count"] >= 1
    assert result["validation_report"]["planner_registry_missing_required_field_count"] >= len(result["validation_report"]["missing_fields"])

    missing_field_ids = {item["field_id"] for item in result["validation_report"]["missing_fields"]}
    assert "point_of_interconnection_voltage_kv" in missing_field_ids
    assert "peak_demand_mw" in missing_field_ids
    assert "ups_topology" in missing_field_ids

    followup_paths = {item["field_path"] for item in result["followup_questions"]}
    assert "facility.poi_voltage_kv" in followup_paths
    assert "facility.load_schedule.phase_1_mw" in followup_paths
    assert "facility.ups.topology" in followup_paths



def test_normalization_service_preserves_conflict_and_generates_conflict_followup(tmp_path: Path) -> None:
    context = _Context(run_id="norm_003", run_dir=tmp_path / "norm_003")

    extraction_result = {
        "canonical_state": {
            "facility.ups.topology": {
                "value": "2N",
                "method": "spec_sheet",
                "source_artifact_id": "artifact_ups",
                "confidence": 0.93,
            },
            "facility.poi_voltage_kv": {
                "value": 138,
                "method": "drawing_review",
                "source_artifact_id": "artifact_poi",
                "confidence": 0.9,
            },
        }
    }
    interview_result = {
        "answers_confirmed": [
            {
                "field_path": "facility.ups.topology",
                "confirmed_answer": "N+1",
                "question_id": "q_ups_topology",
                "source_name": "engineer interview",
            },
            {
                "field_path": "facility.load_schedule.phase_1_mw",
                "confirmed_answer": 31,
                "question_id": "q_phase_1",
                "source_name": "engineer interview",
            },
        ],
        "clarifications": [],
    }

    result = run_service(
        context=context,
        extraction_result=extraction_result,
        interview_result=interview_result,
        retrieval_result=None,
    )

    assert result["validation_report"]["conflicts"]
    conflict = result["validation_report"]["conflicts"][0]
    assert conflict["field_path"] == "facility.ups.topology"
    assert conflict["existing_value"] == "2N"
    assert conflict["candidate_value"] == "N+1"
    assert any(
        item["field_path"] == "facility.ups.topology" and item["question_id"].startswith("conflict_")
        for item in result["followup_questions"]
    )



def test_normalization_service_tracks_switchgear_fields_in_planner_field_model(tmp_path: Path) -> None:
    context = _Context(run_id="norm_switchgear", run_dir=tmp_path / "norm_switchgear")

    extraction_result = {
        "canonical_state": {
            "switchgear_unit_count": {
                "value": 3,
                "method": "equipment_schedule",
                "source_artifact_id": "artifact_sg",
                "confidence": "HIGH",
            },
            "switchgear_bus_rating_amps": {
                "value": 4000,
                "method": "equipment_schedule",
                "source_artifact_id": "artifact_sg",
                "confidence": "HIGH",
            },
            "switchgear_interrupting_rating_ka": {
                "value": 65,
                "method": "equipment_schedule",
                "source_artifact_id": "artifact_sg",
                "confidence": "HIGH",
            },
        }
    }

    result = normalize_inputs(
        context=context,
        extraction_result=extraction_result,
        interview_result=None,
        retrieval_result=None,
    )

    assert result["normalized_input"]["facility"]["switchgear"]["count"] == 3
    assert result["normalized_input"]["facility"]["switchgear"]["bus_rating_amps"] == 4000
    assert result["normalized_input"]["facility"]["switchgear"]["interrupting_rating_ka"] == 65
    assert result["normalized_input"]["planner_field_values"]["switchgear_unit_count"] == 3
    assert result["normalized_input"]["planner_field_values"]["switchgear_bus_rating_amps"] == 4000
    assert result["normalized_input"]["planner_field_values"]["switchgear_interrupting_rating_ka"] == 65
