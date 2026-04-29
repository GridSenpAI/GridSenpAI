from pathlib import Path
from types import SimpleNamespace

from services.validation_service.service import validate_canonical_state


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        run_id="run_validation_reconcile_001",
        run_dir=tmp_path / "run_validation_reconcile_001",
        config=SimpleNamespace(),
    )


def test_validation_reconciliation_resolves_scalar_conflicts_and_preserves_provenance(tmp_path: Path) -> None:
    context = _context(tmp_path)

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_001",
                    "file_name": "one_line.pdf",
                    "artifact_type": "one_line_diagram",
                }
            ],
            "entities": [],
            "topology_cues": [],
            "source_anchors": [
                {
                    "anchor_id": "anchor_001",
                    "artifact_id": "artifact_001",
                }
            ],
            "evidence_snippets": [],
            "normalized_input": {
                "facility": {
                    "poi_voltage_kv": 138.0,
                    "transformers": {
                        "count": 2,
                    },
                }
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
                "schema_valid": True,
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "field_records": [
                {
                    "field_record_id": "field_001",
                    "field_path": "facility.poi_voltage_kv",
                    "value": 138.0,
                    "source_stage": "normalization",
                    "source_type": "normalized_input",
                    "source_ref": ["anchor_001", "artifact_001"],
                    "confidence_score": 0.91,
                    "confidence_tag": "HIGH",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "MODERATE",
                    "conflict_status": "CONFLICT",
                    "metadata": {},
                },
                {
                    "field_record_id": "field_002",
                    "field_path": "facility.poi_voltage_kv",
                    "value": 115.0,
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "source_ref": ["artifact_001"],
                    "confidence_score": 0.55,
                    "confidence_tag": "MODERATE",
                    "validation_status": "VALID",
                    "review_status": "REVIEW_REQUIRED",
                    "evidence_strength": "WEAK",
                    "conflict_status": "CONFLICT",
                    "metadata": {
                        "source_method": "llm_worker",
                    },
                },
                {
                    "field_record_id": "field_003",
                    "field_path": "facility.transformers.count",
                    "value": 2,
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "source_ref": ["artifact_001"],
                    "confidence_score": 0.60,
                    "confidence_tag": "MODERATE",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "WEAK",
                    "conflict_status": "NO_CONFLICT",
                    "metadata": {},
                },
                {
                    "field_record_id": "field_004",
                    "field_path": "facility.transformers.count",
                    "value": 3,
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "source_ref": ["artifact_001"],
                    "confidence_score": 0.59,
                    "confidence_tag": "MODERATE",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "WEAK",
                    "conflict_status": "NO_CONFLICT",
                    "metadata": {},
                },
            ],
            "conflict_records": [
                {
                    "conflict_id": "conflict_001",
                    "field_path": "facility.poi_voltage_kv",
                    "conflict_type": "VALUE_MISMATCH",
                    "severity": "HIGH",
                    "status": "OPEN",
                    "record_ids": ["field_001", "field_002"],
                    "candidate_values": [138.0, 115.0],
                    "source_stages": ["normalization", "extraction"],
                    "details": {},
                }
            ],
            "review_flags": [
                {
                    "review_flag_id": "review_001",
                    "category": "CONFLICT",
                    "severity": "HIGH",
                    "status": "OPEN",
                    "message": "Conflict detected for field 'facility.poi_voltage_kv'.",
                    "field_path": "facility.poi_voltage_kv",
                    "record_ids": ["field_001", "field_002"],
                    "metadata": {},
                }
            ],
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
                "canonical_state": "CANONICAL_STATE_BUILT",
                "canonical_state_governance": "GOVERNED",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(context=context, canonical_state_result=canonical_state_result)

    assert result["status"] == "VALIDATED"
    field_records = result["canonical_state"]["field_records"]
    poi_records = [record for record in field_records if record["field_path"] == "facility.poi_voltage_kv"]
    primary = next(record for record in poi_records if record.get("is_primary") is True)
    superseded = next(record for record in poi_records if record.get("field_record_id") == "field_002")

    assert primary["field_record_id"] == "field_001"
    assert primary["status"] == "validated"
    assert primary["validation_status"] == "VALIDATED"
    assert superseded["status"] == "superseded"
    assert superseded["validation_status"] == "SUPERSEDED"

    conflict_paths = {item.get("field_path") for item in result["canonical_state"]["conflict_records"]}
    assert "facility.poi_voltage_kv" not in conflict_paths

    reconciliation_paths = {item.get("field_path") for item in result["canonical_state"]["reconciliation_records"]}
    assert "facility.poi_voltage_kv" in reconciliation_paths

    transformer_records = [
        record
        for record in field_records
        if record["field_path"] == "facility.transformers.count"
    ]
    assert len(transformer_records) == 2


def test_validation_reconciliation_suppresses_malformed_scalar_candidate(tmp_path: Path) -> None:
    context = _context(tmp_path)

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_001",
                    "file_name": "spec.pdf",
                    "artifact_type": "spec_sheet",
                }
            ],
            "entities": [],
            "topology_cues": [],
            "source_anchors": [],
            "evidence_snippets": [],
            "normalized_input": {
                "facility": {
                    "project_name": "North Campus",
                }
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
                "schema_valid": True,
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "field_records": [
                {
                    "field_record_id": "field_001",
                    "field_path": "facility.project_name",
                    "value": "North Campus",
                    "source_stage": "normalization",
                    "source_type": "normalized_input",
                    "source_ref": ["artifact_001"],
                    "confidence_score": 0.88,
                    "confidence_tag": "HIGH",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "MODERATE",
                    "conflict_status": "NO_CONFLICT",
                    "metadata": {},
                },
                {
                    "field_record_id": "field_002",
                    "field_path": "facility.project_name",
                    "value": {"bad": "shape"},
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "source_ref": ["artifact_001"],
                    "confidence_score": 0.95,
                    "confidence_tag": "HIGH",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "WEAK",
                    "conflict_status": "NO_CONFLICT",
                    "metadata": {"source_method": "llm_worker"},
                },
            ],
            "conflict_records": [],
            "review_flags": [],
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
                "canonical_state": "CANONICAL_STATE_BUILT",
                "canonical_state_governance": "GOVERNED",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(context=context, canonical_state_result=canonical_state_result)

    field_records = result["canonical_state"]["field_records"]
    malformed = next(record for record in field_records if record["field_record_id"] == "field_002")
    assert malformed["status"] in {"conflicting", "superseded"}

    reconciliation_paths = {item.get("field_path") for item in result["canonical_state"]["reconciliation_records"]}
    assert "facility.project_name" in reconciliation_paths
def test_validation_reconciliation_prefers_main_title_block_over_appendix_llm(tmp_path: Path) -> None:
    context = _context(tmp_path)

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_main",
                    "file_name": "one_line.pdf",
                    "artifact_type": "one_line_diagram",
                },
                {
                    "artifact_id": "artifact_appendix",
                    "file_name": "appendix_notes.pdf",
                    "artifact_type": "narrative_document",
                },
            ],
            "entities": [],
            "topology_cues": [],
            "source_anchors": [],
            "evidence_snippets": [],
            "normalized_input": {
                "facility": {
                    "poi_voltage_kv": 138.0,
                }
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
                "schema_valid": True,
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "field_records": [
                {
                    "field_record_id": "field_main",
                    "field_path": "facility.poi_voltage_kv",
                    "value": 138.0,
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "source_ref": ["artifact_main"],
                    "confidence_score": 0.72,
                    "confidence_tag": "MODERATE",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "STRONG",
                    "conflict_status": "CONFLICT",
                    "metadata": {
                        "artifact_type": "one_line_diagram",
                        "region_type": "TITLE_BLOCK_REGION",
                        "page_number": 1,
                        "section_label": "Main Title Block",
                        "document_role": "primary",
                        "source_method": "deterministic_region_scoped",
                    },
                },
                {
                    "field_record_id": "field_appendix",
                    "field_path": "facility.poi_voltage_kv",
                    "value": 115.0,
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "source_ref": ["artifact_appendix"],
                    "confidence_score": 0.90,
                    "confidence_tag": "HIGH",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "WEAK",
                    "conflict_status": "CONFLICT",
                    "metadata": {
                        "artifact_type": "narrative_document",
                        "region_type": "TEXT_EVIDENCE_REGION",
                        "page_number": 12,
                        "section_label": "Appendix A Narrative Notes",
                        "document_role": "appendix",
                        "source_method": "llm_worker",
                    },
                },
            ],
            "conflict_records": [
                {
                    "conflict_id": "conflict_001",
                    "field_path": "facility.poi_voltage_kv",
                    "conflict_type": "VALUE_MISMATCH",
                    "severity": "HIGH",
                    "status": "OPEN",
                    "record_ids": ["field_main", "field_appendix"],
                    "candidate_values": [138.0, 115.0],
                    "source_stages": ["extraction"],
                    "details": {},
                }
            ],
            "review_flags": [],
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
                "canonical_state": "CANONICAL_STATE_BUILT",
                "canonical_state_governance": "GOVERNED",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(context=context, canonical_state_result=canonical_state_result)

    poi_records = [
        record
        for record in result["canonical_state"]["field_records"]
        if record["field_path"] == "facility.poi_voltage_kv"
    ]
    primary = next(record for record in poi_records if record.get("is_primary") is True)
    superseded = next(record for record in poi_records if record["field_record_id"] == "field_appendix")

    assert primary["field_record_id"] == "field_main"
    assert primary["validation_status"] == "VALIDATED"
    assert superseded["validation_status"] == "SUPERSEDED"


def test_validation_reconciliation_marks_narrow_scalar_winner_for_review(tmp_path: Path) -> None:
    context = _context(tmp_path)

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_001",
                    "file_name": "facility_summary.pdf",
                    "artifact_type": "engineering_report",
                }
            ],
            "entities": [],
            "topology_cues": [],
            "source_anchors": [],
            "evidence_snippets": [],
            "normalized_input": {
                "facility": {
                    "project_name": "North Campus",
                }
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
                "schema_valid": True,
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "field_records": [
                {
                    "field_record_id": "field_001",
                    "field_path": "facility.project_name",
                    "value": "North Campus",
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "source_ref": ["artifact_001"],
                    "confidence_score": 0.69,
                    "confidence_tag": "MODERATE",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "MODERATE",
                    "conflict_status": "CONFLICT",
                    "metadata": {
                        "artifact_type": "engineering_report",
                        "region_type": "TEXT_EVIDENCE_REGION",
                        "page_number": 2,
                        "section_label": "Facility Summary",
                        "document_role": "main",
                        "source_method": "llm_worker",
                    },
                },
                {
                    "field_record_id": "field_002",
                    "field_path": "facility.project_name",
                    "value": "North Campus Phase A",
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "source_ref": ["artifact_001"],
                    "confidence_score": 0.67,
                    "confidence_tag": "MODERATE",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "MODERATE",
                    "conflict_status": "CONFLICT",
                    "metadata": {
                        "artifact_type": "engineering_report",
                        "region_type": "TEXT_EVIDENCE_REGION",
                        "page_number": 2,
                        "section_label": "Facility Summary",
                        "document_role": "main",
                        "source_method": "llm_worker",
                    },
                },
            ],
            "conflict_records": [
                {
                    "conflict_id": "conflict_001",
                    "field_path": "facility.project_name",
                    "conflict_type": "VALUE_MISMATCH",
                    "severity": "HIGH",
                    "status": "OPEN",
                    "record_ids": ["field_001", "field_002"],
                    "candidate_values": ["North Campus", "North Campus Phase A"],
                    "source_stages": ["extraction"],
                    "details": {},
                }
            ],
            "review_flags": [],
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
                "canonical_state": "CANONICAL_STATE_BUILT",
                "canonical_state_governance": "GOVERNED",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(context=context, canonical_state_result=canonical_state_result)

    field_records = result["canonical_state"]["field_records"]
    primary = next(
        record
        for record in field_records
        if record["field_path"] == "facility.project_name" and record.get("is_primary") is True
    )
    assert primary["validation_status"] == "REVIEW_REQUIRED"
    assert primary["review_status"] == "REVIEW_REQUIRED"

    review_flags = result["canonical_state"]["review_flags"]
    assert any(
        flag.get("category") == "SCALAR_REVIEW_REQUIRED"
        and flag.get("field_path") == "facility.project_name"
        for flag in review_flags
    )

    reconciliation_records = result["canonical_state"]["reconciliation_records"]
    matching = [
        item
        for item in reconciliation_records
        if item.get("field_path") == "facility.project_name"
    ]
    assert matching
    assert matching[-1]["reconciliation_status"] == "REVIEW_REQUIRED"

def test_validation_reconciliation_prefers_calibration_record_over_extraction(tmp_path: Path) -> None:
    context = _context(tmp_path)

    canonical_state_result = {
        "run_id": context.run_id,
        "canonical_state": {
            "run_id": context.run_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_001",
                    "file_name": "facility_spec.pdf",
                    "artifact_type": "engineering_report",
                }
            ],
            "entities": [],
            "topology_cues": [],
            "source_anchors": [],
            "evidence_snippets": [],
            "normalized_input": {
                "facility": {
                    "poi_voltage_kv": 138.0,
                }
            },
            "validation_report": {
                "errors": [],
                "warnings": [],
                "info": [],
                "missing_fields": [],
                "conflicts": [],
                "schema_valid": True,
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "field_records": [
                {
                    "field_record_id": "field_extract",
                    "field_path": "facility.poi_voltage_kv",
                    "value": 115.0,
                    "source_stage": "extraction",
                    "source_type": "schema_field_candidate",
                    "source_ref": ["artifact_001"],
                    "confidence_score": 0.72,
                    "confidence_tag": "MODERATE",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "WEAK",
                    "conflict_status": "CONFLICT",
                    "metadata": {
                        "artifact_type": "engineering_report",
                        "region_type": "TEXT_EVIDENCE_REGION",
                        "page_number": 2,
                        "section_label": "Facility Description",
                        "document_role": "main",
                        "source_method": "llm_worker",
                    },
                },
                {
                    "field_record_id": "field_calibration",
                    "field_path": "facility.poi_voltage_kv",
                    "value": 138.0,
                    "source_stage": "validation",
                    "source_type": "calibration_comparison",
                    "source_ref": ["artifact_001"],
                    "confidence_score": 0.80,
                    "confidence_tag": "HIGH",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "STRONG",
                    "conflict_status": "CONFLICT",
                    "metadata": {
                        "deviation": {"percent": 2.0}
                    },
                },
            ],
            "conflict_records": [],
            "review_flags": [],
            "stage_status": {
                "ingestion": "ARTIFACTS_INGESTED",
                "extraction": "EXTRACTED",
                "retrieval": "EVIDENCE_RETRIEVED",
                "interview": "QUESTIONS_GENERATED",
                "normalization": "NORMALIZED",
                "canonical_state": "CANONICAL_STATE_BUILT",
                "canonical_state_governance": "GOVERNED",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(context=context, canonical_state_result=canonical_state_result)

    poi_records = [
        r for r in result["canonical_state"]["field_records"]
        if r["field_path"] == "facility.poi_voltage_kv"
    ]

    primary = next(r for r in poi_records if r.get("is_primary") is True)

    assert primary["field_record_id"] == "field_calibration"
    assert primary["validation_status"] == "VALIDATED"

def test_validation_reconciliation_prefers_lower_deviation_calibration_record(tmp_path: Path) -> None:
    context = _context(tmp_path)

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
                "schema_valid": True,
            },
            "followup_questions": [],
            "model_outputs": {},
            "output_parameters": [],
            "assumptions": [],
            "scenarios": {},
            "field_records": [
                {
                    "field_record_id": "cal_1",
                    "field_path": "facility.poi_voltage_kv",
                    "value": 138.0,
                    "source_stage": "validation",
                    "source_type": "calibration_comparison",
                    "source_ref": [],
                    "confidence_score": 0.75,
                    "confidence_tag": "HIGH",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "STRONG",
                    "conflict_status": "CONFLICT",
                    "metadata": {
                        "deviation": {"percent": 8.0}
                    },
                },
                {
                    "field_record_id": "cal_2",
                    "field_path": "facility.poi_voltage_kv",
                    "value": 137.5,
                    "source_stage": "validation",
                    "source_type": "calibration_comparison",
                    "source_ref": [],
                    "confidence_score": 0.75,
                    "confidence_tag": "HIGH",
                    "validation_status": "VALID",
                    "review_status": "CLEAR",
                    "evidence_strength": "STRONG",
                    "conflict_status": "CONFLICT",
                    "metadata": {
                        "deviation": {"percent": 1.5}
                    },
                },
            ],
            "conflict_records": [],
            "review_flags": [],
            "stage_status": {
                "canonical_state": "CANONICAL_STATE_BUILT",
                "canonical_state_governance": "GOVERNED",
            },
        },
        "build_summary": {},
        "warnings": [],
        "status": "CANONICAL_STATE_BUILT",
    }

    result = validate_canonical_state(context=context, canonical_state_result=canonical_state_result)

    poi_records = [
        r for r in result["canonical_state"]["field_records"]
        if r["field_path"] == "facility.poi_voltage_kv"
    ]

    primary = next(r for r in poi_records if r.get("is_primary") is True)

    assert primary["field_record_id"] == "cal_2"