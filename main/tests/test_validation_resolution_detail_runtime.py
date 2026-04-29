from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from services.validation_service import service as validation_service


def test_validation_summary_persists_registry_value_kind_and_attention_counts(monkeypatch) -> None:
    canonical_state = {
        "project_name": "Test Project",
        "field_records": [],
        "field_resolution": {
            "accepted_field_index": {
                "generator_rated_kw_per_unit": {
                    "field_id": "generator_rated_kw_per_unit",
                    "accepted_status": "accepted",
                    "accepted_value": 3000,
                    "accepted_confidence": 0.95,
                    "accepted_value_kind": "direct_fact",
                    "planner_attention_tier": "normal",
                    "why_accepted": ["Matches applicant one-line schedule"],
                    "source_anchors": ["one_line.pdf:p12"],
                },
                "generator_prime_or_standby_rating_basis": {
                    "field_id": "generator_prime_or_standby_rating_basis",
                    "accepted_status": "review_required",
                    "accepted_value": "standby",
                    "accepted_confidence": 0.61,
                    "accepted_value_kind": "applicant_confirmed",
                    "planner_attention_tier": "review",
                    "needs_applicant_confirmation": True,
                    "planner_review_flag": True,
                    "why_accepted": ["Applicant clarified standby basis"],
                    "source_anchors": ["interview:generator_rating_basis"],
                },
            },
            "summary": {
                "accepted_field_index_count": 2,
                "applicant_confirmation_needed_count": 1,
                "planner_review_count": 1,
            },
        },
        "stage_status": {},
    }

    monkeypatch.setattr(validation_service, "run_calibration_dataset_service", lambda **kwargs: {"status": "COMPLETED", "calibration_datasets": []})
    monkeypatch.setattr(validation_service, "run_engineering_validation", lambda **kwargs: {"status": "COMPLETED", "errors": [], "warnings": [], "review_flags": []})
    monkeypatch.setattr(validation_service, "run_calibration_comparison_service", lambda **kwargs: {"status": "COMPLETED", "calibration_records": []})
    monkeypatch.setattr(validation_service, "build_field_resolution_result", lambda *args, **kwargs: canonical_state["field_resolution"])

    with TemporaryDirectory() as tmpdir:
        context = SimpleNamespace(run_id="test-run", run_dir=Path(tmpdir))
        result = validation_service.validate_canonical_state(
            context,
            canonical_state_result={"canonical_state": canonical_state},
        )
    summary = result["validation_report"]["summary"]
    assert summary["planner_registry_value_kind_counts"]["direct_fact"] >= 1
    assert summary["planner_registry_value_kind_counts"]["applicant_confirmed"] >= 1
    assert summary["planner_registry_attention_tier_counts"]["normal"] >= 1
    assert summary["planner_registry_attention_tier_counts"]["review"] >= 1
