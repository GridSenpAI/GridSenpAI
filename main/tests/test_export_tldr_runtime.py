from __future__ import annotations

from services.export_service.service import _build_planner_tldr_summary, _build_planner_tldr_markdown


def test_planner_tldr_separates_settled_provisional_and_blocked_values() -> None:
    ledger = [
        {
            "label": "POI voltage",
            "field_path": "facility.poi_voltage_kv",
            "accepted_status": "accepted",
            "accepted_value": 138.0,
            "accepted_confidence": 0.96,
            "confidence_band": "HIGH",
            "planner_critical": True,
            "source_document": "utility_guide.pdf",
            "planner_trust_row": {
                "confidence_band": "HIGH",
                "trust_posture": "settled",
                "support_summary": "Official utility guide.",
            },
            "field_release_profile": {"release_state": "READY"},
        },
        {
            "label": "UPS topology",
            "field_path": "facility.ups.topology",
            "accepted_status": "review_required",
            "accepted_value": "2N",
            "accepted_confidence": 0.71,
            "confidence_band": "MODERATE",
            "planner_critical": True,
            "planner_review_flag": True,
            "source_document": "equipment_schedule.pdf",
            "planner_trust_row": {
                "confidence_band": "MODERATE",
                "trust_posture": "provisional",
                "support_summary": "Best current value from equipment schedule.",
            },
            "field_release_profile": {"release_state": "PROVISIONAL"},
        },
        {
            "label": "Generator count",
            "field_path": "facility.generators.count",
            "accepted_status": "conflicting",
            "accepted_value": 12,
            "accepted_confidence": 0.44,
            "confidence_band": "LOW",
            "planner_critical": True,
            "source_document": "one_line.pdf",
            "planner_trust_row": {
                "confidence_band": "LOW",
                "trust_posture": "contested",
                "support_summary": "Conflicting schedule and one-line counts.",
            },
            "field_release_profile": {"release_state": "BLOCKED"},
        },
    ]
    summary = _build_planner_tldr_summary(ledger, manual_review_queue={"summary": {"total_count": 2}})
    markdown = _build_planner_tldr_markdown("run_001", summary)
    assert summary["summary"]["settled_count"] == 1
    assert summary["summary"]["provisional_count"] == 1
    assert summary["summary"]["blocked_count"] >= 1
    assert "## Best current provisional values" in markdown
    assert "best current value 2N" in markdown
    assert "## Blocked fields" in markdown
    assert "current best value 12" in markdown
