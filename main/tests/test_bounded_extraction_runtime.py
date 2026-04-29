from __future__ import annotations

from services.extraction_service.utils import (
    bounded_evidence_excerpt,
    bounded_text_value,
    _poi_voltage_context_rejected,
)


def test_bounded_text_value_stops_at_next_form_label() -> None:
    raw_value = (
        "Blue Creek 138 kV Switching Station Point of change in ownership Customer dead-end structure "
        "Nominal service voltage 138 kV Export condition Import only Page 1 of 4"
    )

    assert (
        bounded_text_value(
            raw_value,
            field_path="interconnection_context.point_of_interconnection.poi_name",
        )
        == "Blue Creek 138 kV Switching Station"
    )


def test_bounded_text_value_caps_long_flattened_rows_without_destroying_value() -> None:
    raw_value = (
        "North Valley Substation and associated 345 kV terminal bay with enough trailing OCR "
        "noise to exceed the ledger scalar limit and should not pull the next unrelated row "
        "Requested initial in-service 2029-05-01"
    )

    value = bounded_text_value(raw_value, field_path="interconnection_context.point_of_interconnection.poi_name", max_chars=72)

    assert value.startswith("North Valley Substation")
    assert "Requested initial" not in value
    assert len(value) <= 72


def test_poi_voltage_context_rejects_internal_distribution_voltage() -> None:
    rejected_context = "Downstream campus medium-voltage distribution uses 13.8 kV switchgear voltage."
    accepted_context = "Point of interconnection nominal service voltage is 138 kV at the utility terminal."

    assert _poi_voltage_context_rejected(rejected_context) is True
    assert _poi_voltage_context_rejected(accepted_context) is False


def test_bounded_evidence_excerpt_preserves_short_source_context() -> None:
    text = "Nominal service voltage 138 kV. " + "footer noise " * 80
    excerpt = bounded_evidence_excerpt(text, 0, 31, max_chars=120)

    assert "Nominal service voltage 138 kV" in excerpt
    assert len(excerpt) <= 120
