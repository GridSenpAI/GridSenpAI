from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.translation_service.utils import (
    build_confidence_factors,
    collect_confirmed_field_paths,
    collect_conflict_field_paths,
    collect_missing_fields,
    compute_confidence_score,
    count_supporting_evidence,
    get_dependency_paths,
    get_source_field_paths,
    get_supporting_snippet_ids,
    map_confidence_tag,
)


def test_collect_conflict_field_paths_returns_expected_set() -> None:
    validation_report = {
        "conflicts": [
            {"field_path": "facility.load_schedule.phase_1_mw"},
            {"field_path": "facility.ups.topology"},
            {"field_path": ""},
            {"not_field_path": "ignored"},
            "invalid",
            123,
        ]
    }

    result = collect_conflict_field_paths(validation_report)

    assert result == {
        "facility.load_schedule.phase_1_mw",
        "facility.ups.topology",
    }


def test_collect_missing_fields_returns_expected_set() -> None:
    validation_report = {
        "missing_fields": [
            "facility.load_schedule.phase_1_mw",
            "facility.ups.topology",
            "",
            None,
            5,
        ]
    }

    result = collect_missing_fields(validation_report)

    assert result == {
        "facility.load_schedule.phase_1_mw",
        "facility.ups.topology",
    }


def test_collect_confirmed_field_paths_returns_expected_set() -> None:
    validation_report = {
        "interview_summary": {
            "confirmed_field_paths": [
                "facility.load_schedule.phase_1_mw",
                "facility.ups.topology",
                "",
                None,
                5,
            ]
        }
    }

    result = collect_confirmed_field_paths(validation_report)

    assert result == {
        "facility.load_schedule.phase_1_mw",
        "facility.ups.topology",
    }


def test_get_dependency_paths_returns_current_registry_paths() -> None:
    result = get_dependency_paths("steady_state.p_mw")

    assert result == [
        "engineering_model.buildout_and_ramping.ramp_characteristics.block_load_step_mw",
        "engineering_model.load_system.peak_demand_mw",
        "facility.load_schedule.phase_1_mw",
    ]


def test_get_dependency_paths_returns_empty_list_for_unknown_parameter() -> None:
    result = get_dependency_paths("unknown.parameter")

    assert result == []


def test_get_source_field_paths_matches_dependency_paths() -> None:
    dependency_paths = get_dependency_paths("zip_model.constant_power_fraction")
    source_field_paths = get_source_field_paths("zip_model.constant_power_fraction")

    assert dependency_paths == ["facility.ups.topology", "steady_state_zip_fraction_p"]
    assert source_field_paths == dependency_paths


def test_count_supporting_evidence_counts_matching_topics_only() -> None:
    snippets: list[dict[str, Any]] = [
        {
            "snippet_id": "snippet_1",
            "metadata": {"topic": "Load schedule"},
        },
        {
            "snippet_id": "snippet_2",
            "metadata": {"topic": "Load schedule"},
        },
        {
            "snippet_id": "snippet_3",
            "metadata": {"topic": "UPS topology"},
        },
        {
            "snippet_id": "snippet_4",
            "metadata": {},
        },
        {
            "snippet_id": "snippet_5",
            "metadata": "invalid",
        },
    ]

    result = count_supporting_evidence(
        parameter_path="steady_state.p_mw",
        snippets=snippets,
    )

    assert result == 2


def test_get_supporting_snippet_ids_returns_matching_ids_only() -> None:
    snippets: list[dict[str, Any]] = [
        {
            "snippet_id": "snippet_1",
            "metadata": {"topic": "Load schedule"},
        },
        {
            "snippet_id": "snippet_2",
            "metadata": {"topic": "Load schedule"},
        },
        {
            "snippet_id": "snippet_3",
            "metadata": {"topic": "UPS topology"},
        },
        {
            "snippet_id": "",
            "metadata": {"topic": "Load schedule"},
        },
        {
            "snippet_id": "snippet_5",
            "metadata": {},
        },
        {
            "snippet_id": "snippet_6",
            "metadata": "invalid",
        },
    ]

    result = get_supporting_snippet_ids(
        parameter_path="steady_state.p_mw",
        snippets=snippets,
    )

    assert result == ["snippet_1", "snippet_2"]


def test_get_supporting_snippet_ids_returns_empty_list_for_unknown_parameter() -> None:
    snippets: list[dict[str, Any]] = [
        {
            "snippet_id": "snippet_1",
            "metadata": {"topic": "Load schedule"},
        }
    ]

    result = get_supporting_snippet_ids(
        parameter_path="unknown.parameter",
        snippets=snippets,
    )

    assert result == []


def test_build_confidence_factors_for_confirmed_evidence_backed_parameter() -> None:
    validation_report = {
        "conflicts": [],
        "missing_fields": [],
        "interview_summary": {
            "confirmed_field_paths": ["facility.load_schedule.phase_1_mw"],
        },
    }

    snippets: list[dict[str, Any]] = [
        {
            "snippet_id": "snippet_1",
            "metadata": {"topic": "Load schedule"},
        },
        {
            "snippet_id": "snippet_2",
            "metadata": {"topic": "Load schedule"},
        },
    ]

    factors = build_confidence_factors(
        parameter_path="steady_state.p_mw",
        provenance_type="rule",
        provenance_ref="RULE.NORMALIZED_LOAD_TO_STEADY_STATE_P.v1",
        validation_report=validation_report,
        snippets=snippets,
        assumption_used=False,
        derived_from_rule=True,
    )

    assert factors == {
        "engineer_confirmed": True,
        "direct_evidence_count": 2,
        "derived_from_rule": True,
        "assumption_used": False,
        "conflict_present": False,
        "missing_dependency": False,
        "uses_default_rule": False,
    }


def test_compute_confidence_score_rewards_confirmed_evidence() -> None:
    score = compute_confidence_score(
        provenance_type="rule",
        factors={
            "engineer_confirmed": True,
            "direct_evidence_count": 2,
            "derived_from_rule": True,
            "assumption_used": False,
            "conflict_present": False,
            "missing_dependency": False,
            "uses_default_rule": False,
        },
    )

    assert score == 1.0
    assert map_confidence_tag(score) == "HIGH"


def test_compute_confidence_score_penalizes_assumptions_and_conflicts() -> None:
    score = compute_confidence_score(
        provenance_type="assumption",
        factors={
            "engineer_confirmed": False,
            "direct_evidence_count": 0,
            "derived_from_rule": False,
            "assumption_used": True,
            "conflict_present": True,
            "missing_dependency": True,
            "uses_default_rule": True,
        },
    )

    assert score == 0.0
    assert map_confidence_tag(score) == "LOW"
