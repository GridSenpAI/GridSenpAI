from __future__ import annotations

from services.canonical_state_service.service import merge_extraction_candidates
from services.extraction_service.models import ExtractionCandidate


def test_merge_extraction_candidates_normalizes_alias_and_promotes_high_confidence_value() -> None:
    result = merge_extraction_candidates(
        candidates=[
            ExtractionCandidate(
                field_path="facility.ups_topology",
                value="2N",
                confidence=0.91,
                source_artifact_id="artifact_ups",
                method="spec_sheet",
                evidence={"snippet": "UPS topology is 2N"},
            )
        ],
        canonical_state={},
    )

    assert result["facility.ups.topology"]["value"] == "2N"
    assert result["facility.ups.topology"]["status"] == "provisional_extracted"
    assert result["field_records"][0]["field_path"] == "facility.ups.topology"
    assert result["conflict_records"] == []
    assert result["review_flags"] == []


def test_merge_extraction_candidates_marks_missing_value_and_creates_review_flag() -> None:
    result = merge_extraction_candidates(
        candidates=[
            ExtractionCandidate(
                field_path="facility.poi_voltage_kv",
                value=None,
                confidence=0.72,
                source_artifact_id="artifact_poi",
                method="drawing_review",
                evidence={"page": 1},
            )
        ],
        canonical_state={},
    )

    assert result["field_records"][0]["status"] == "missing"
    assert result["field_records"][0]["value"] is None
    assert result["review_flags"][0]["category"] == "MISSING_FIELD"
    assert result["review_flags"][0]["field_path"] == "facility.poi_voltage_kv"


def test_merge_extraction_candidates_preserves_conflict_and_marks_primary_state_conflicting() -> None:
    result = merge_extraction_candidates(
        candidates=[
            ExtractionCandidate(
                field_path="facility.poi_voltage_kv",
                value=138.0,
                confidence=0.82,
                source_artifact_id="artifact_a",
                method="drawing_review",
                evidence={"page": 2},
            ),
            ExtractionCandidate(
                field_path="facility.poi_voltage_kv",
                value=230.0,
                confidence=0.71,
                source_artifact_id="artifact_b",
                method="spec_sheet",
                evidence={"page": 5},
            ),
        ],
        canonical_state={},
    )

    assert result["facility.poi_voltage_kv"]["value"] == 138.0
    assert result["facility.poi_voltage_kv"]["status"] == "conflicting"
    assert len(result["conflict_records"]) == 1
    assert result["conflict_records"][0]["field_path"] == "facility.poi_voltage_kv"
    assert result["review_flags"][0]["category"] == "CONFLICTING_FIELD"
    assert {record["status"] for record in result["field_records"]} == {
        "provisional_extracted",
        "conflicting",
    }


def test_merge_extraction_candidates_marks_low_confidence_primary_for_review() -> None:
    result = merge_extraction_candidates(
        candidates=[
            ExtractionCandidate(
                field_path="facility.generators.count",
                value=2,
                confidence=0.52,
                source_artifact_id="artifact_gens",
                method="drawing_review",
                evidence={"snippet": "2 generators"},
            )
        ],
        canonical_state={},
    )

    assert result["facility.generators.count"]["status"] == "review_required"
    assert result["review_flags"][0]["category"] == "LOW_CONFIDENCE_FIELD"
