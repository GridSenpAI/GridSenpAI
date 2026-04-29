from __future__ import annotations

import pytest

from services.retrieval_service.domain import _build_resolution_backlog


def test_retrieval_backlog_uses_registry_profiles_for_priority_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "services.retrieval_service.domain.build_followup_profile",
        lambda field_path: {
            "field_id": "point_of_interconnection_voltage_kv",
            "field_path": field_path,
            "label": "POI nominal voltage kV",
            "requiredness": "required",
            "planner_critical": True,
            "preferred_sources": ["one_line_diagram", "validated_applicant_answer"],
            "search_keywords": ["poi voltage", "interconnection voltage"],
        },
    )
    monkeypatch.setattr(
        "services.retrieval_service.domain.preferred_corpora_for_field",
        lambda field_path: ["interconnection_guidance", "vendor_documents"],
    )

    backlog = _build_resolution_backlog(
        requested_field_paths=["facility.poi_voltage_kv"],
        review_required_field_paths=[],
        out_of_scope_field_paths=[],
        equipment_result=None,
        gap_fill_strategy="grounded_retrieval_then_interview",
        official_web_lookup_required=True,
        default_reason="",
    )

    assert len(backlog) == 1
    item = backlog[0]
    assert item["field_id"] == "point_of_interconnection_voltage_kv"
    assert item["field_path"] == "facility.poi_voltage_kv"
    assert item["label"] == "POI nominal voltage kV"
    assert item["planner_critical"] is True
    assert item["requiredness"] == "required"
    assert item["priority"] == "HIGH"
    assert item["preferred_sources"] == ["one_line_diagram", "validated_applicant_answer"]
    assert item["search_keywords"] == ["poi voltage", "interconnection voltage"]
    assert item["attempted_resolution_steps"] == [
        "interconnection_guidance",
        "vendor_documents",
        "equipment_catalog",
        "official_web",
    ]


def test_retrieval_backlog_uses_lower_priority_for_noncritical_deferred_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "services.retrieval_service.domain.build_followup_profile",
        lambda field_path: {
            "field_id": "decorative_optional_field",
            "field_path": field_path,
            "label": "Decorative optional field",
            "requiredness": "optional",
            "planner_critical": False,
            "preferred_sources": ["site_plan"],
            "search_keywords": ["decorative field"],
        },
    )
    monkeypatch.setattr(
        "services.retrieval_service.domain.preferred_corpora_for_field",
        lambda field_path: ["interconnection_guidance"],
    )

    backlog = _build_resolution_backlog(
        requested_field_paths=[],
        review_required_field_paths=[],
        out_of_scope_field_paths=["facility.optional.decorative"],
        equipment_result=None,
        gap_fill_strategy="grounded_retrieval_then_interview",
        official_web_lookup_required=False,
        default_reason="",
    )

    assert len(backlog) == 1
    item = backlog[0]
    assert item["category"] == "retrieval_deferred"
    assert item["priority"] == "LOW"
    assert item["planner_critical"] is False
    assert item["requiredness"] == "optional"
    assert item["attempted_resolution_steps"] == [
        "interconnection_guidance",
        "applicant_documents",
        "canonical_inputs",
        "interview",
    ]
