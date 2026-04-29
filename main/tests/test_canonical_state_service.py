from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from services.canonical_state_service.service import build_canonical_state


@dataclass(slots=True)
class DummyConfig:
    schema_version_input: str = "0.1.0"
    schema_version_output: str = "0.1.0"
    project_name: str = "GridSenpAI Test Project"


@dataclass(slots=True)
class DummyContext:
    run_id: str
    run_dir: Path
    config: DummyConfig


def test_build_canonical_state_aggregates_upstream_payloads(tmp_path: Path) -> None:
    context = DummyContext(
        run_id="run_test_canonical_001",
        run_dir=tmp_path / "run_test_canonical_001",
        config=DummyConfig(),
    )

    ingestion_result = {
        "run_id": context.run_id,
        "status": "ARTIFACTS_INGESTED",
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "file_name": "one-line.pdf",
                "file_path": "/tmp/one-line.pdf",
                "file_suffix": ".pdf",
                "size_bytes": 1200,
                "ingested_at": "2026-03-09T00:00:00+00:00",
                "index_status": "PENDING",
                "classification": "ONE_LINE_DIAGRAM",
            }
        ],
    }

    extraction_result = {
        "run_id": context.run_id,
        "status": "EXTRACTED",
        "entities": [
            {
                "entity_id": "entity_001",
                "type": "voltage_value",
                "name": "POI Voltage",
                "attributes": {
                    "parameter_path": "facility.poi_voltage_kv",
                    "normalized_value": 138.0,
                },
                "source_anchor_id": "anchor_001",
            }
        ],
        "topology_cues": [
            {
                "type": "topology_2n",
                "artifact_id": "artifact_001",
                "confidence": "MODERATE",
            }
        ],
        "source_anchors": [
            {
                "anchor_id": "anchor_001",
                "artifact_id": "artifact_001",
                "file_name": "one-line.pdf",
                "page": 1,
                "text_pointer": "page_1",
            }
        ],
    }

    interview_result = {
        "run_id": context.run_id,
        "status": "QUESTIONS_GENERATED",
        "answers_confirmed": [],
        "clarifications": [],
    }

    normalization_result = {
        "run_id": context.run_id,
        "status": "NORMALIZED",
        "normalized_input": {
            "run_id": context.run_id,
            "schema_version": "0.1.0",
            "facility": {
                "project_name": "GridSenpAI Test Project",
                "poi_voltage_kv": 138.0,
                "frequency_hz": 60,
                "load_schedule": {
                    "phase_1_mw": 50.0,
                    "phase_2_mw": None,
                    "phase_3_mw": None,
                },
                "ups": {
                    "topology": "2N",
                    "count": 2,
                },
                "generators": {
                    "present": True,
                    "count": 4,
                },
                "transformers": {
                    "count": 2,
                    "ratings_mva": [75.0, 75.0],
                },
            },
            "source_summary": {
                "entity_count": 1,
                "topology_cue_count": 1,
                "evidence_snippet_count": 1,
                "confirmed_interview_count": 0,
                "clarification_count": 0,
            },
        },
        "validation_report": {
            "errors": [],
            "warnings": [],
            "missing_fields": [
                {"field_path": "facility.load_schedule.phase_2_mw"},
            ],
            "conflicts": [],
            "schema_valid": True,
        },
        "followup_questions": [
            {
                "question": "Confirm phase 2 MW loading.",
                "field_path": "facility.load_schedule.phase_2_mw",
            }
        ],
    }

    retrieval_result = {
        "run_id": context.run_id,
        "status": "EVIDENCE_RETRIEVED",
        "snippets": [
            {
                "snippet_id": "snippet_001",
                "source_ref": "ups_spec",
                "text": "UPS topology is 2N and supports constant-power behavior.",
            }
        ],
    }

    translation_result = {
        "run_id": context.run_id,
        "status": "TRANSLATED",
        "model_outputs": {
            "schema_version": "0.1.0",
        },
        "output_parameters": [
            {
                "parameter_path": "facility.poi_voltage_kv",
                "value": 138.0,
                "units": "kV",
                "provenance_type": "evidence",
                "provenance_ref": ["snippet_001"],
                "dependency_paths": ["facility.poi_voltage_kv"],
                "source_field_paths": ["facility.poi_voltage_kv"],
                "supporting_snippet_ids": ["snippet_001"],
                "confidence_score": 0.93,
                "confidence_tag": "HIGH",
                "confidence_factors": {
                    "evidence_count": 1,
                },
            }
        ],
        "assumptions": [],
    }

    result = build_canonical_state(
        context=context,
        ingestion_result=ingestion_result,
        extraction_result=extraction_result,
        interview_result=interview_result,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
        translation_result=translation_result,
    )

    assert result["run_id"] == context.run_id
    assert result["status"] == "CANONICAL_STATE_BUILT"

    canonical_state = result["canonical_state"]
    assert len(canonical_state["artifacts"]) == 1
    assert len(canonical_state["entities"]) == 1
    assert len(canonical_state["topology_cues"]) == 1
    assert len(canonical_state["source_anchors"]) == 1
    assert len(canonical_state["evidence_snippets"]) == 1

    assert canonical_state["normalized_input"]["facility"]["poi_voltage_kv"] == 138.0
    assert canonical_state["validation_report"]["schema_valid"] is True
    assert canonical_state["stage_status"]["ingestion"] == "ARTIFACTS_INGESTED"
    assert canonical_state["stage_status"]["extraction"] == "EXTRACTED"
    assert canonical_state["stage_status"]["normalization"] == "NORMALIZED"
    assert canonical_state["stage_status"]["gap_resolution::retrieval"] == "EVIDENCE_RETRIEVED"
    assert canonical_state["stage_status"]["gap_resolution::interview"] == "QUESTIONS_GENERATED"
    assert canonical_state["stage_status"]["canonical_state_governance"] == "GOVERNED"

    engineering_model = canonical_state["engineering_model"]
    assert engineering_model is not None
    assert engineering_model["schema_name"] == "gridsenpai_canonical_facility_model"
    assert engineering_model["project_context"]["run_id"] == context.run_id
    assert engineering_model["project_context"]["project_name"] == "GridSenpAI Test Project"
    assert (
        engineering_model["interconnection_context"]["point_of_interconnection"]["poi_voltage_kv"]["value"]
        == 138.0
    )
    assert (
        engineering_model["facility_electrical_system"]["utility_service"]["service_voltage_kv"]["value"]
        == 138.0
    )
    assert len(engineering_model["facility_electrical_system"]["transformers"]) == 2
    assert (
        engineering_model["facility_electrical_system"]["transformers"][0]["rating_mva"]["value"]
        == 75.0
    )
    assert len(engineering_model["power_conversion_and_ups"]["ups_systems"]) == 1
    assert (
        engineering_model["power_conversion_and_ups"]["ups_systems"][0]["topology"]["value"]
        == "2N"
    )
    assert (
        engineering_model["backup_power_system"]["generator_plant_present"]["value"]
        is True
    )
    assert len(engineering_model["backup_power_system"]["generator_units"]) == 1
    assert engineering_model["backup_power_system"]["generator_units"][0]["count"]["value"] == 4
    assert engineering_model["load_system"]["peak_demand_mw"]["value"] == 50.0
    assert engineering_model["load_system"]["minimum_demand_mw"]["value"] == 50.0
    assert len(engineering_model["load_system"]["load_blocks"]) == 3
    assert len(engineering_model["buildout_and_ramping"]["buildout_phases"]) == 3
    assert (
        engineering_model["buildout_and_ramping"]["buildout_phases"][0]["incremental_load_mw"]["value"]
        == 50.0
    )

    field_records = canonical_state["field_records"]
    conflict_records = canonical_state["conflict_records"]
    review_flags = canonical_state["review_flags"]

    assert isinstance(field_records, list)
    assert isinstance(conflict_records, list)
    assert isinstance(review_flags, list)
    assert field_records

    poi_records = [
        record
        for record in field_records
        if record["field_path"] == "facility.poi_voltage_kv"
    ]
    assert len(poi_records) == 2

    normalized_poi_record = next(
        record for record in poi_records if record["source_stage"] == "normalization"
    )
    translated_poi_record = next(
        record for record in poi_records if record["source_stage"] == "translation"
    )

    assert normalized_poi_record["source_type"] == "normalized_input"
    assert "anchor_001" in normalized_poi_record["source_ref"]
    assert translated_poi_record["source_type"] == "translation_output"
    assert "snippet_001" in translated_poi_record["source_ref"]
    assert translated_poi_record["confidence_tag"] == "HIGH"

    missing_phase_2_record = next(
        record
        for record in field_records
        if record["field_path"] == "facility.load_schedule.phase_2_mw"
    )
    assert missing_phase_2_record["is_missing"] is True
    assert missing_phase_2_record["validation_status"] in {"MISSING", "VALID"}

    review_categories = {flag["category"] for flag in review_flags}
    assert "MISSING_FIELD" in review_categories
    assert "FOLLOWUP_REQUIRED" in review_categories

    build_summary = result["build_summary"]
    assert build_summary["artifact_count"] == 1
    assert build_summary["entity_count"] == 1
    assert build_summary["source_anchor_count"] == 1
    assert build_summary["evidence_snippet_count"] == 1
    assert build_summary["field_record_count"] >= 1
    assert build_summary["review_flag_count"] >= 2
    assert build_summary["missing_field_count"] == 1
    assert build_summary["conflict_count"] == 0


def test_build_canonical_state_emits_conflict_records_for_mismatched_values(
    tmp_path: Path,
) -> None:
    context = DummyContext(
        run_id="run_test_canonical_conflict_001",
        run_dir=tmp_path / "run_test_canonical_conflict_001",
        config=DummyConfig(),
    )

    normalization_result = {
        "run_id": context.run_id,
        "status": "NORMALIZED",
        "normalized_input": {
            "facility": {
                "poi_voltage_kv": 138.0,
            }
        },
        "validation_report": {
            "errors": [],
            "warnings": [],
            "missing_fields": [],
            "conflicts": [],
            "schema_valid": True,
        },
        "followup_questions": [],
    }

    translation_result = {
        "run_id": context.run_id,
        "status": "TRANSLATED",
        "model_outputs": {},
        "output_parameters": [
            {
                "parameter_path": "facility.poi_voltage_kv",
                "value": 115.0,
                "units": "kV",
                "provenance_type": "evidence",
                "provenance_ref": ["snippet_001"],
                "dependency_paths": ["facility.poi_voltage_kv"],
                "source_field_paths": ["facility.poi_voltage_kv"],
                "supporting_snippet_ids": ["snippet_001"],
                "confidence_score": 0.81,
                "confidence_tag": "HIGH",
                "confidence_factors": {},
            }
        ],
        "assumptions": [],
    }

    retrieval_result = {
        "run_id": context.run_id,
        "status": "EVIDENCE_RETRIEVED",
        "snippets": [
            {
                "snippet_id": "snippet_001",
                "source_ref": "vendor_spec",
                "text": "POI voltage: 115 kV",
            }
        ],
    }

    result = build_canonical_state(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
        translation_result=translation_result,
    )

    canonical_state = result["canonical_state"]
    conflict_records = canonical_state["conflict_records"]
    review_flags = canonical_state["review_flags"]

    assert canonical_state["engineering_model"] is not None
    assert (
        canonical_state["engineering_model"]["interconnection_context"]["point_of_interconnection"]["poi_voltage_kv"]["value"]
        == 138.0
    )

    assert len(conflict_records) == 1
    conflict = conflict_records[0]
    assert conflict["field_path"] == "facility.poi_voltage_kv"
    assert conflict["conflict_type"] == "VALUE_MISMATCH"
    assert sorted(conflict["candidate_values"]) == [115.0, 138.0]

    conflicting_records = [
        record
        for record in canonical_state["field_records"]
        if record["field_path"] == "facility.poi_voltage_kv"
    ]
    assert all(record["conflict_status"] == "CONFLICT" for record in conflicting_records)
    assert all(record["review_status"] == "REVIEW_REQUIRED" for record in conflicting_records)

    assert any(flag["category"] == "CONFLICT" for flag in review_flags)


def test_build_canonical_state_rejects_mismatched_run_id(tmp_path: Path) -> None:
    context = DummyContext(
        run_id="run_test_canonical_002",
        run_dir=tmp_path / "run_test_canonical_002",
        config=DummyConfig(),
    )

    ingestion_result = {
        "run_id": "wrong_run_id",
        "status": "ARTIFACTS_INGESTED",
        "artifacts": [],
    }

    try:
        build_canonical_state(
            context=context,
            ingestion_result=ingestion_result,
        )
    except ValueError as exc:
        assert "run_id mismatch" in str(exc)
    else:
        raise AssertionError("Expected ValueError for mismatched stage run_id.")


def test_build_canonical_state_leaves_engineering_model_unset_without_normalization(
    tmp_path: Path,
) -> None:
    context = DummyContext(
        run_id="run_test_canonical_no_normalization_001",
        run_dir=tmp_path / "run_test_canonical_no_normalization_001",
        config=DummyConfig(),
    )

    result = build_canonical_state(
        context=context,
        ingestion_result={
            "run_id": context.run_id,
            "status": "ARTIFACTS_INGESTED",
            "artifacts": [],
        },
    )

    canonical_state = result["canonical_state"]
    assert canonical_state["engineering_model"] is None


def test_build_canonical_state_exposes_field_resolution_overview(tmp_path: Path) -> None:
    context = DummyContext(
        run_id="run_test_canonical_002",
        run_dir=tmp_path / "run_test_canonical_002",
        config=DummyConfig(),
    )

    normalization_result = {
        "run_id": context.run_id,
        "status": "NORMALIZED",
        "normalized_input": {
            "run_id": context.run_id,
            "schema_version": "0.1.0",
            "facility": {
                "project_name": "GridSenpAI Test Project",
                "peak_demand_mw": 90.0,
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

    result = build_canonical_state(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )

    canonical_state = result["canonical_state"]
    overview = canonical_state["field_resolution_overview"]
    assert "planner_review_queue" in overview
    assert "high_materiality_conflicts" in overview
    assert overview["summary"].get("high_materiality_conflict_count", 0) >= 1

    build_summary = result["build_summary"]
    assert build_summary["field_resolution_high_materiality_conflict_count"] >= 1
    assert build_summary["field_resolution_planner_review_queue_count"] >= 1
