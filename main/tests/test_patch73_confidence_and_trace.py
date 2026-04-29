from __future__ import annotations

from shared.planner_field_ledger import build_planner_field_ledger


def test_planner_ledger_normalizes_confidence_and_repairs_trace() -> None:
    rows = build_planner_field_ledger([
        {
            "field_id": "peak_demand_mw",
            "field_path": "facility.load_schedule.peak_demand_mw",
            "label": "Peak Demand MW",
            "accepted_value": 180.0,
            "accepted_confidence": 326.475,
            "confidence_band": "LOW",
            "status": "accepted",
            "accepted_unit": "MW",
            "candidates": [{"candidate_id": "c1", "value": 180.0, "confidence": 0.9, "source_anchor": "01.pdf"}],
            "accepted_candidate_id": "c1",
            "adjudication_trace": {
                "accepted_value_text": "2 MW",
                "planner_narrative": "Peak Demand MW accepted 2 MW with status conflicting and confidence LOW. Runner-up 180 remained plausible.",
            },
        }
    ])
    row = next(item for item in rows if item["field_id"] == "peak_demand_mw")
    assert 0.0 <= row["confidence_score"] <= 1.0
    assert row["confidence_band"] == "HIGH"
    assert row["adjudication_trace"]["accepted_value_text"] == "180.0 MW"
    assert "accepted 180.0 MW" in row["adjudication_trace"]["planner_narrative"]
