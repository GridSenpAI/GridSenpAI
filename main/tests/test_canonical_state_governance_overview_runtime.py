from types import SimpleNamespace

from services.canonical_state_service.service import build_canonical_state


def test_canonical_state_overview_exposes_governance_posture_summary(tmp_path) -> None:
    run_id = "run-governance-overview"
    ingestion_result = {"run_id": run_id, "status": "ARTIFACTS_INGESTED", "artifacts": []}
    extraction_result = {
        "run_id": run_id,
        "status": "EXTRACTED",
        "canonical_state": {},
        "artifacts": [],
        "entities": [],
        "topology_cues": [],
        "source_anchors": [],
        "evidence_snippets": [],
        "field_records": [],
        "conflict_records": [],
        "review_flags": [],
    }
    normalization_result = {
        "run_id": run_id,
        "status": "NORMALIZED",
        "normalized_input": {},
        "validation_report": {"schema_valid": True},
        "followup_questions": [],
    }
    retrieval_result = {
        "run_id": run_id,
        "status": "EVIDENCE_RETRIEVED",
        "field_candidates": [
            {
                "field_path": "facility.poi_voltage_kv",
                "value": 138,
                "confidence": 0.94,
                "source_stage": "retrieval",
                "source_type": "equipment_reference_candidate",
                "source_stream": "retrieval_record",
                "source_hierarchy": "official_interconnection_source",
                "specificity": "direct_field_match",
                "source_anchor": "utility_study.pdf:p4",
                "metadata": {"field_support_strength": "STRONG"},
            }
        ],
    }
    interview_result = {"run_id": run_id, "status": "QUESTIONS_GENERATED", "interview_packet": {"question_sequence": []}}
    context = SimpleNamespace(run_id=run_id)

    result = build_canonical_state(
        context,
        ingestion_result=ingestion_result,
        extraction_result=extraction_result,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
        interview_result=interview_result,
    )

    overview = result["canonical_state"]["field_resolution_overview"]
    posture = overview["governance_posture_summary"]

    assert "release_state_counts" in posture
    assert posture["blocked_field_count"] >= 1
    assert result["build_summary"]["field_resolution_governance_posture"]["blocked_field_count"] == posture["blocked_field_count"]
