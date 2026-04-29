from services.export_service.service import _build_planner_tldr_markdown, _build_planner_tldr_summary


def test_planner_tldr_is_field_quick_reference_not_run_report() -> None:
    summary = _build_planner_tldr_summary([
        {
            "field_id": "poi_voltage_kv",
            "field_path": "facility.poi_voltage_kv",
            "field_label": "POI voltage",
            "status": "ACCEPTED",
            "accepted_value": 138.0,
            "confidence_score": 0.91,
            "confidence_band": "HIGH",
            "source_document": "application.pdf",
            "source_page": "4",
            "source_section": "Electrical Service",
            "planner_critical": True,
        }
    ])
    markdown = _build_planner_tldr_markdown("run-test", summary)

    assert "GridSenpAI Planner Field Quick Reference" in markdown
    assert "| Use status | Planner field | Winning value | Confidence | Source |" in markdown
    assert "POI voltage" in markdown
    assert "138.0" in markdown
    assert "0.91 (HIGH)" in markdown
    assert "application.pdf (page 4; section: Electrical Service)" in markdown

    assert "## Executive snapshot" not in markdown
    assert "## Ledger-driven action plan" not in markdown
    assert "## Source index" not in markdown
    assert "## Master planner field ledger" not in markdown
    assert "Fields requiring compact adjudication" not in markdown
