# tests/test_validation_service.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.validation_service.service import validate_canonical_state


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


def test_validate_canonical_state_marks_validated_when_required_sections_exist(
    tmp_path: Path,
) -> None:
    context = DummyContext(
        run_id="run_validation_001",
        run_dir=tmp_path / "run_validation_001",
        config=DummyConfig(),
    )

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_001",
                    "file_name": "one-line.pdf",
                }
            ],
            "entities": [
                {
                    "entity_id": "entity_001",
                    "type": "voltage_value",
                }
            ],
            "topology_cues": [],
            "source_anchors": [
                {
                    "anchor_id": "anchor_001",
                    "artifact_id": "artifact_001",
                }
            ],
            "evidence_snippets": [
                {
                    "snippet_id": "snippet_001",
                    "source_ref": "ups_spec",
                    "text": "UPS constant-power behavior.",
                }
            ],
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
                    "topology_cue_count": 0,
                    "evidence_snippet_count": 1,
                    "confirmed_interview_count": 0,
                    "clarification_count": 0,
                },
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(
        context=context,
        canonical_state_result=canonical_state_result,
    )

    assert result["run_id"] == context.run_id
    assert result["status"] == "VALIDATED"

    validation_report = result["validation_report"]
    assert validation_report["status"] == "VALIDATED"
    assert validation_report["summary"]["is_blocked"] is False
    assert result["canonical_state"]["stage_status"]["validation"] == "VALIDATED"


def test_validate_canonical_state_blocks_empty_normalized_input(tmp_path: Path) -> None:
    context = DummyContext(
        run_id="run_validation_002",
        run_dir=tmp_path / "run_validation_002",
        config=DummyConfig(),
    )

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [],
            "entities": [],
            "topology_cues": [],
            "source_anchors": [],
            "evidence_snippets": [],
            "normalized_input": {},
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(
        context=context,
        canonical_state_result=canonical_state_result,
    )

    assert result["status"] == "VALIDATION_FAILED"
    assert result["validation_report"]["summary"]["is_blocked"] is True

    error_codes = {
        issue["code"]
        for issue in result["validation_report"]["errors"]
    }
    assert "EMPTY_NORMALIZED_INPUT" in error_codes


def test_validate_canonical_state_surfaces_engineering_warning_summary(
    tmp_path: Path,
) -> None:
    context = DummyContext(
        run_id="run_validation_003",
        run_dir=tmp_path / "run_validation_003",
        config=DummyConfig(),
    )

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_001",
                    "file_name": "one-line.pdf",
                    "artifact_type": "one_line_diagram",
                }
            ],
            "entities": [
                {
                    "entity_id": "entity_001",
                    "type": "voltage_value",
                }
            ],
            "topology_cues": [],
            "source_anchors": [
                {
                    "anchor_id": "anchor_001",
                    "artifact_id": "artifact_001",
                }
            ],
            "evidence_snippets": [
                {
                    "snippet_id": "snippet_001",
                    "source_ref": "facility_summary",
                    "text": "Facility engineering summary.",
                }
            ],
            "field_records": [],
            "conflict_records": [],
            "review_flags": [],
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
                        "count": 0,
                    },
                    "transformers": {
                        "count": 2,
                        "ratings_mva": [75.0, 75.0],
                    },
                },
                "source_summary": {
                    "entity_count": 1,
                    "topology_cue_count": 0,
                    "evidence_snippet_count": 1,
                    "confirmed_interview_count": 0,
                    "clarification_count": 0,
                },
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
                "canonical_state": "CANONICAL_STATE_BUILT",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(
        context=context,
        canonical_state_result=canonical_state_result,
    )

    assert result["run_id"] == context.run_id
    assert result["status"] == "VALIDATED"

    validation_report = result["validation_report"]
    summary = validation_report["summary"]

    assert summary["engineering_error_count"] == 0
    assert summary["engineering_warning_count"] >= 1
    assert summary["engineering_review_flag_count"] >= 1
    assert summary["is_blocked"] is False

    engineering_validation = validation_report["engineering_validation"]
    assert isinstance(engineering_validation, dict)
    assert engineering_validation["status"] == "REVIEW_REQUIRED"
    assert engineering_validation["review_flag_count"] >= 1

    engineering_summary = engineering_validation["summary"]
    assert engineering_summary["warning_count"] >= 1
    assert engineering_summary["review_flag_count"] >= 1


def test_validate_canonical_state_blocks_on_engineering_error(
    tmp_path: Path,
) -> None:
    context = DummyContext(
        run_id="run_validation_004",
        run_dir=tmp_path / "run_validation_004",
        config=DummyConfig(),
    )

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_001",
                    "file_name": "one-line.pdf",
                    "artifact_type": "one_line_diagram",
                }
            ],
            "entities": [
                {
                    "entity_id": "entity_001",
                    "type": "voltage_value",
                }
            ],
            "topology_cues": [],
            "source_anchors": [
                {
                    "anchor_id": "anchor_001",
                    "artifact_id": "artifact_001",
                }
            ],
            "evidence_snippets": [
                {
                    "snippet_id": "snippet_001",
                    "source_ref": "facility_summary",
                    "text": "Facility engineering summary.",
                }
            ],
            "field_records": [],
            "conflict_records": [],
            "review_flags": [],
            "normalized_input": {
                "run_id": context.run_id,
                "schema_version": "0.1.0",
                "facility": {
                    "project_name": "GridSenpAI Test Project",
                    "poi_voltage_kv": 138.0,
                    "frequency_hz": 55,
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
                        "count": 1,
                    },
                    "transformers": {
                        "count": 2,
                        "ratings_mva": [75.0, 75.0],
                    },
                },
                "source_summary": {
                    "entity_count": 1,
                    "topology_cue_count": 0,
                    "evidence_snippet_count": 1,
                    "confirmed_interview_count": 0,
                    "clarification_count": 0,
                },
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
                "canonical_state": "CANONICAL_STATE_BUILT",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(
        context=context,
        canonical_state_result=canonical_state_result,
    )

    assert result["run_id"] == context.run_id
    assert result["status"] == "VALIDATION_FAILED"

    validation_report = result["validation_report"]
    summary = validation_report["summary"]

    assert summary["engineering_error_count"] >= 1
    assert summary["is_blocked"] is True
    assert result["canonical_state"]["stage_status"]["validation"] == "VALIDATION_FAILED"

    engineering_validation = validation_report["engineering_validation"]
    assert isinstance(engineering_validation, dict)
    assert engineering_validation["status"] == "FAILED"

    engineering_summary = engineering_validation["summary"]
    assert engineering_summary["error_count"] >= 1
    assert engineering_summary["is_blocked"] is True


def test_validate_canonical_state_materializes_engineering_findings_as_field_records(
    tmp_path: Path,
) -> None:
    context = DummyContext(
        run_id="run_validation_005",
        run_dir=tmp_path / "run_validation_005",
        config=DummyConfig(),
    )

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_001",
                    "file_name": "one-line.pdf",
                    "artifact_type": "one_line_diagram",
                }
            ],
            "entities": [
                {
                    "entity_id": "entity_001",
                    "type": "voltage_value",
                }
            ],
            "topology_cues": [],
            "source_anchors": [
                {
                    "anchor_id": "anchor_001",
                    "artifact_id": "artifact_001",
                }
            ],
            "evidence_snippets": [
                {
                    "snippet_id": "snippet_001",
                    "source_ref": "facility_summary",
                    "text": "Facility engineering summary.",
                }
            ],
            "field_records": [],
            "conflict_records": [],
            "review_flags": [],
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
                        "count": 0,
                    },
                    "transformers": {
                        "count": 2,
                        "ratings_mva": [75.0, 75.0],
                    },
                },
                "source_summary": {
                    "entity_count": 1,
                    "topology_cue_count": 0,
                    "evidence_snippet_count": 1,
                    "confirmed_interview_count": 0,
                    "clarification_count": 0,
                },
            },
            "engineering_model": {
                "project_context": {
                    "project_name": "GridSenpAI Test Project",
                },
                "interconnection_context": {
                    "point_of_interconnection": {
                        "poi_voltage_kv": {
                            "value": 138.0,
                            "unit": "kV",
                        }
                    }
                },
                "load_system": {
                    "load_blocks": [
                        {
                            "name": "phase_1_mw",
                            "connected_load_mw": {
                                "value": 50.0,
                                "unit": "MW",
                            },
                        }
                    ]
                },
                "facility_electrical_system": {
                    "transformers": [
                        {
                            "primary_voltage_kv": {
                                "value": 138.0,
                                "unit": "kV",
                            },
                            "secondary_voltage_kv": {
                                "value": 34.5,
                                "unit": "kV",
                            },
                            "rating_mva": {
                                "value": 75.0,
                                "unit": "MVA",
                            },
                        }
                    ]
                },
                "backup_power_system": {
                    "generator_plant_present": {
                        "value": True,
                    },
                    "generator_units": [
                        {
                            "count": {
                                "value": 0,
                                "unit": "count",
                            }
                        }
                    ],
                },
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
                "canonical_state": "CANONICAL_STATE_BUILT",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(
        context=context,
        canonical_state_result=canonical_state_result,
    )

    assert result["run_id"] == context.run_id
    assert result["status"] == "VALIDATED"

    canonical_state = result["canonical_state"]
    field_records = canonical_state["field_records"]

    engineering_records = [
        record
        for record in field_records
        if record.get("source_type") == "engineering_validation"
    ]
    assert engineering_records

    generator_count_records = [
        record
        for record in engineering_records
        if record.get("field_path") == "engineering_model.backup_power_system.generator_units"
    ]
    assert generator_count_records

    record = generator_count_records[0]
    assert record["source_stage"] == "validation"
    assert record["validation_status"] == "REVIEW_REQUIRED"
    assert record["review_status"] == "REVIEW_REQUIRED"

    metadata = record["metadata"]
    assert metadata["record_origin"] == "engineering_validation"
    assert metadata["engineering_issue_code"] == "GENERATOR_PRESENT_WITHOUT_COUNT"

    summary = result["validation_report"]["summary"]
    assert summary["review_flag_count"] >= 1
    assert summary["engineering_warning_count"] >= 1


def test_validate_canonical_state_blocks_on_calibration_conflict_and_surfaces_counts(
    tmp_path: Path,
) -> None:
    context = DummyContext(
        run_id="run_validation_006",
        run_dir=tmp_path / "run_validation_006",
        config=DummyConfig(),
    )

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_001",
                    "file_name": "benchmark_reference.pdf",
                    "artifact_type": "engineering_report",
                }
            ],
            "entities": [
                {
                    "entity_id": "entity_001",
                    "type": "load_value",
                }
            ],
            "topology_cues": [],
            "source_anchors": [
                {
                    "anchor_id": "anchor_001",
                    "artifact_id": "artifact_001",
                }
            ],
            "evidence_snippets": [
                {
                    "snippet_id": "snippet_001",
                    "source_ref": "benchmark_reference",
                    "text": "Reference benchmark for phase 1 load.",
                }
            ],
            "field_records": [
                {
                    "field_record_id": "field_00001",
                    "field_path": "facility.load_schedule.phase_1_mw",
                    "value": 90.0,
                    "source_stage": "normalization",
                    "source_type": "normalized_input",
                    "source_ref": ["anchor_001"],
                    "confidence_score": 0.95,
                    "confidence_tag": "HIGH",
                    "validation_status": "VALIDATED",
                    "review_status": "CLEAR",
                    "evidence_strength": "STRONG",
                    "conflict_status": "NO_CONFLICT",
                    "is_missing": False,
                    "is_primary": True,
                    "metadata": {},
                }
            ],
            "conflict_records": [],
            "review_flags": [],
            "calibration_datasets": [
                {
                    "dataset_id": "calds_001",
                    "dataset_type": "PLANNING_BENCHMARK",
                    "version": "1.0.0",
                    "source_artifact_id": "artifact_001",
                    "source_file_name": "benchmark_reference.pdf",
                    "parameters": [
                        {
                            "field_path": "facility.load_schedule.phase_1_mw",
                            "value": 75.0,
                            "normalized_value": 75.0,
                            "units": "MW",
                            "target_units": "MW",
                            "source_ref": [
                                {
                                    "artifact_id": "artifact_001",
                                    "page": 2,
                                    "snippet_id": "snippet_001",
                                    "source_name": "benchmark_reference.pdf",
                                }
                            ],
                            "metadata": {"tolerance_percent": 5},
                        }
                    ],
                }
            ],
            "normalized_input": {
                "run_id": context.run_id,
                "schema_version": "0.1.0",
                "facility": {
                    "project_name": "GridSenpAI Test Project",
                    "poi_voltage_kv": 138.0,
                    "frequency_hz": 60,
                    "load_schedule": {
                        "phase_1_mw": 90.0,
                        "phase_2_mw": None,
                        "phase_3_mw": None,
                    },
                    "ups": {
                        "topology": "2N",
                        "count": 2,
                    },
                    "generators": {
                        "present": False,
                        "count": 0,
                    },
                    "transformers": {
                        "count": 2,
                        "ratings_mva": [75.0, 75.0],
                    },
                },
                "source_summary": {
                    "entity_count": 1,
                    "topology_cue_count": 0,
                    "evidence_snippet_count": 1,
                    "confirmed_interview_count": 0,
                    "clarification_count": 0,
                },
            },
            "engineering_model": {
                "interconnection_context": {
                    "point_of_interconnection": {
                        "poi_voltage_kv": {
                            "value": 138.0,
                            "unit": "kV",
                        }
                    }
                },
                "load_system": {
                    "load_blocks": [
                        {
                            "name": "phase_1_mw",
                            "connected_load_mw": {
                                "value": 90.0,
                                "unit": "MW",
                            },
                        }
                    ]
                },
                "facility_electrical_system": {
                    "transformers": [
                        {
                            "primary_voltage_kv": {
                                "value": 138.0,
                                "unit": "kV",
                            },
                            "secondary_voltage_kv": {
                                "value": 34.5,
                                "unit": "kV",
                            },
                            "rating_mva": {
                                "value": 75.0,
                                "unit": "MVA",
                            },
                        },
                        {
                            "primary_voltage_kv": {
                                "value": 138.0,
                                "unit": "kV",
                            },
                            "secondary_voltage_kv": {
                                "value": 34.5,
                                "unit": "kV",
                            },
                            "rating_mva": {
                                "value": 75.0,
                                "unit": "MVA",
                            },
                        },
                    ]
                },
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
                "canonical_state": "CANONICAL_STATE_BUILT",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(
        context=context,
        canonical_state_result=canonical_state_result,
    )

    assert result["run_id"] == context.run_id
    assert result["status"] == "VALIDATION_FAILED"

    validation_report = result["validation_report"]
    summary = validation_report["summary"]

    assert summary["is_blocked"] is True
    assert summary["model_readiness"] == "BLOCKED"
    assert summary["calibration_record_count"] == 1
    assert summary["calibrated_match_count"] == 0
    assert summary["calibration_review_required_count"] == 0
    assert summary["calibration_conflict_count"] == 1
    assert summary["reconciliation_record_count"] == 1

    calibration_summary = validation_report["calibration_summary"]
    assert calibration_summary["calibration_record_count"] == 1
    assert calibration_summary["calibration_conflict_count"] == 1
    assert calibration_summary["calibrated_match_count"] == 0
    assert calibration_summary["calibration_review_required_count"] == 0
    assert calibration_summary["comparison_run_id"] == f"{context.run_id}::calibration_compare"
    assert calibration_summary["compared_at"]

    assert result["canonical_state"]["stage_status"]["validation"] == "VALIDATION_FAILED"

    canonical_state = result["canonical_state"]
    assert len(canonical_state["calibration_records"]) == 1
    assert len(canonical_state["reconciliation_records"]) >= 1
    assert len(canonical_state["change_log"]) >= 1

    calibration_record = canonical_state["calibration_records"][0]
    assert calibration_record["comparison_run_id"] == f"{context.run_id}::calibration_compare"
    assert calibration_record["status"] == "CALIBRATION_CONFLICT"
    assert calibration_record["severity"] == "error"
    assert calibration_record["reviewer_status"] == "OPEN"
    assert calibration_record["linked_field_record_ids"] == ["field_00001"]
    assert calibration_record["source_anchors"][0]["snippet_id"] == "snippet_001"

    calibration_reconciliation_records = [
        record
        for record in canonical_state["reconciliation_records"]
        if record.get("comparison_run_id") == f"{context.run_id}::calibration_compare"
        and record.get("reconciliation_status") == "CALIBRATION_CONFLICT"
    ]
    assert calibration_reconciliation_records

    reconciliation_record = calibration_reconciliation_records[0]
    assert reconciliation_record["severity"] == "error"
    assert reconciliation_record["reviewer_status"] == "OPEN"

    calibration_change_entries = [
        entry
        for entry in canonical_state["change_log"]
        if entry.get("change_type") == "CALIBRATION_COMPARISON_RECORDED"
    ]
    assert calibration_change_entries

    change_entry = calibration_change_entries[0]
    assert change_entry["metadata"]["status"] == "CALIBRATION_CONFLICT"