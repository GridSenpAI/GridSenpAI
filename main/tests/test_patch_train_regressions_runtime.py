from __future__ import annotations

from pathlib import Path

from shared.confidence_utils import normalize_confidence_score
from shared.value_quality import contamination_reasons
from services.ingestion_service.utils import classify_artifact, requirement_ids_for_file


def test_confidence_scores_are_probability_like() -> None:
    assert normalize_confidence_score(34.425) == 0.3442
    assert normalize_confidence_score(271.0) == 1.0
    assert normalize_confidence_score("HIGH", band="HIGH") == 0.9
    assert normalize_confidence_score(-5) == 0.0


def test_value_quality_rejects_page_footer_identity_contamination() -> None:
    reasons = contamination_reasons("load_customer_name", "Prairie Horizon Digital Infrastructure LLC Page 1")
    assert reasons
    assert any("identity/name" in reason or "document-control" in reason for reason in reasons)


def test_value_quality_rejects_scalar_summary_fields() -> None:
    reasons = contamination_reasons("buildout_phases_summary", 180.0)
    assert any("summary/schedule" in reason for reason in reasons)


def test_intake_filename_aliases_map_realistic_site_and_phasing_documents() -> None:
    site_control = Path("03_site_control_and_parcel_exhibit.pdf")
    site_plan = Path("04_civil_electrical_site_plan.pdf")
    phasing = Path("10_construction_phasing_and_energization_plan.pdf")

    assert classify_artifact(site_control) == "site_control_package"
    assert classify_artifact(site_plan) == "site_civil_plan"
    assert classify_artifact(phasing) == "construction_phasing_plan"

    assert "site_location_and_poi_selection_package" in requirement_ids_for_file(site_control, classify_artifact(site_control))
    assert "site_location_and_poi_selection_package" in requirement_ids_for_file(site_plan, classify_artifact(site_plan))
    assert "standalone_large_load_energization_request_package" in requirement_ids_for_file(phasing, classify_artifact(phasing))
