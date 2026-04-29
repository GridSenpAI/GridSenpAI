from __future__ import annotations

from pathlib import Path

from services.ingestion_service.utils import classify_artifact, requirement_ids_for_classification


def test_site_control_and_parcel_exhibit_classifies_to_required_site_package(tmp_path: Path) -> None:
    path = tmp_path / "03_site_control_and_parcel_exhibit.pdf"
    path.write_text("placeholder", encoding="utf-8")
    classification = classify_artifact(path)
    assert classification == "site_control_package"
    assert requirement_ids_for_classification(classification)


def test_civil_electrical_site_plan_classifies_to_site_plan_requirement(tmp_path: Path) -> None:
    path = tmp_path / "04_civil_electrical_site_plan.pdf"
    path.write_text("placeholder", encoding="utf-8")
    classification = classify_artifact(path)
    assert classification in {"site_civil_plan", "site_plan"}
    assert requirement_ids_for_classification(classification)


def test_construction_phasing_energization_plan_classifies_to_phasing(tmp_path: Path) -> None:
    path = tmp_path / "10_construction_phasing_and_energization_plan.pdf"
    path.write_text("placeholder", encoding="utf-8")
    classification = classify_artifact(path)
    assert classification == "construction_phasing_plan"
    assert requirement_ids_for_classification(classification)
