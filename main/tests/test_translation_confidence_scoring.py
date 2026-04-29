from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.translation_service.service import run_service


@dataclass
class _TestConfig:
    schema_version_output: str = "1.0.0"


@dataclass
class _TestContext:
    run_id: str = "translation_confidence_test"
    config: _TestConfig = field(default_factory=_TestConfig)


def _build_normalization_result(
    phase_1_mw: float | None,
    *,
    confirmed_field_paths: list[str] | None = None,
    conflicts: list[dict[str, str]] | None = None,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "normalized_input": {
            "facility": {
                "load_schedule": {
                    "phase_1_mw": phase_1_mw,
                }
            }
        },
        "validation_report": {
            "schema_valid": True,
            "missing_fields": missing_fields or [],
            "conflicts": conflicts or [],
            "interview_summary": {
                "confirmed_field_paths": confirmed_field_paths or [],
            },
        },
    }


def _build_retrieval_result(
    topics: list[str] | None = None,
) -> dict[str, Any]:
    snippets: list[dict[str, Any]] = []

    for index, topic in enumerate(topics or [], start=1):
        snippets.append(
            {
                "snippet_id": f"snippet_{index}",
                "text": f"Evidence for {topic}",
                "metadata": {
                    "topic": topic,
                },
            }
        )

    return {
        "snippets": snippets,
    }


def _get_parameter(
    translation_result: dict[str, Any],
    parameter_path: str,
) -> dict[str, Any]:
    parameters = translation_result["output_parameters"]
    assert isinstance(parameters, list)

    for parameter in parameters:
        assert isinstance(parameter, dict)
        if parameter.get("parameter_path") == parameter_path:
            return parameter

    raise AssertionError(f"Parameter '{parameter_path}' was not produced.")


def test_engineer_confirmed_and_evidence_backed_parameter_is_high() -> None:
    context = _TestContext(run_id="translation_confidence_high_case")
    normalization_result = _build_normalization_result(
        120.0,
        confirmed_field_paths=["facility.load_schedule.phase_1_mw"],
    )
    retrieval_result = _build_retrieval_result(
        topics=["Load schedule", "Load schedule"],
    )

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )

    parameter = _get_parameter(result, "steady_state.p_mw")

    assert parameter["provenance_type"] == "rule"
    assert parameter["confidence_score"] == 1.0
    assert parameter["confidence_tag"] == "HIGH"
    assert parameter["dependency_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert parameter["source_field_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert parameter["supporting_snippet_ids"] == ["snippet_1", "snippet_2"]

    factors = parameter["confidence_factors"]
    assert isinstance(factors, dict)
    assert factors["engineer_confirmed"] is True
    assert factors["direct_evidence_count"] == 2
    assert factors["conflict_present"] is False
    assert factors["missing_dependency"] is False


def test_rule_based_default_parameter_is_low() -> None:
    context = _TestContext(run_id="translation_confidence_rule_case")
    normalization_result = _build_normalization_result(100.0)
    retrieval_result = _build_retrieval_result()

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )

    parameter = _get_parameter(result, "zip_model.constant_power_fraction")

    assert parameter["provenance_type"] == "rule"
    assert parameter["confidence_score"] == 0.55
    assert parameter["confidence_tag"] == "LOW"
    assert parameter["dependency_paths"] == ["facility.ups.topology"]
    assert parameter["source_field_paths"] == ["facility.ups.topology"]
    assert parameter["supporting_snippet_ids"] == []

    factors = parameter["confidence_factors"]
    assert isinstance(factors, dict)
    assert factors["engineer_confirmed"] is False
    assert factors["direct_evidence_count"] == 0
    assert factors["derived_from_rule"] is True
    assert factors["uses_default_rule"] is True
    assert factors["conflict_present"] is False
    assert factors["missing_dependency"] is False


def test_assumption_backed_parameter_is_low() -> None:
    context = _TestContext(run_id="translation_confidence_assumption_case")
    normalization_result = _build_normalization_result(
        None,
        missing_fields=["facility.load_schedule.phase_1_mw"],
    )
    retrieval_result = _build_retrieval_result()

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )

    parameter = _get_parameter(result, "steady_state.p_mw")

    assert parameter["provenance_type"] == "assumption"
    assert parameter["confidence_score"] == 0.0
    assert parameter["confidence_tag"] == "LOW"
    assert parameter["dependency_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert parameter["source_field_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert parameter["supporting_snippet_ids"] == []

    factors = parameter["confidence_factors"]
    assert isinstance(factors, dict)
    assert factors["assumption_used"] is True
    assert factors["missing_dependency"] is True
    assert factors["engineer_confirmed"] is False
    assert factors["direct_evidence_count"] == 0


def test_conflict_penalty_reduces_confidence() -> None:
    context = _TestContext(run_id="translation_confidence_conflict_case")
    normalization_result = _build_normalization_result(
        90.0,
        conflicts=[
            {
                "field_path": "facility.load_schedule.phase_1_mw",
                "extracted_value": "80",
                "confirmed_value": "90",
            }
        ],
    )
    retrieval_result = _build_retrieval_result(
        topics=["Load schedule"],
    )

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )

    parameter = _get_parameter(result, "steady_state.p_mw")

    assert parameter["provenance_type"] == "rule"
    assert parameter["confidence_score"] == 0.7
    assert parameter["confidence_tag"] == "MODERATE"
    assert parameter["dependency_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert parameter["source_field_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert parameter["supporting_snippet_ids"] == ["snippet_1"]

    factors = parameter["confidence_factors"]
    assert isinstance(factors, dict)
    assert factors["conflict_present"] is True
    assert factors["direct_evidence_count"] == 1
    assert factors["engineer_confirmed"] is False
    assert factors["missing_dependency"] is False


def test_multiple_supporting_evidence_boosts_confidence() -> None:
    context = _TestContext(run_id="translation_confidence_evidence_boost_case")
    normalization_result = _build_normalization_result(75.0)
    retrieval_result = _build_retrieval_result(
        topics=["Load schedule", "Load schedule"],
    )

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )

    parameter = _get_parameter(result, "steady_state.p_mw")

    assert parameter["confidence_score"] == 1.0
    assert parameter["confidence_tag"] == "HIGH"
    assert parameter["dependency_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert parameter["source_field_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert parameter["supporting_snippet_ids"] == ["snippet_1", "snippet_2"]

    factors = parameter["confidence_factors"]
    assert isinstance(factors, dict)
    assert factors["direct_evidence_count"] == 2
    assert factors["engineer_confirmed"] is False
    assert factors["conflict_present"] is False
    assert factors["missing_dependency"] is False


def test_translation_confidence_summary_matches_parameter_tags() -> None:
    context = _TestContext(run_id="translation_confidence_summary_case")
    normalization_result = _build_normalization_result(
        110.0,
        confirmed_field_paths=["facility.load_schedule.phase_1_mw"],
    )
    retrieval_result = _build_retrieval_result(
        topics=["Load schedule", "Load schedule"],
    )

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )

    parameters = result["output_parameters"]
    assert isinstance(parameters, list)

    recomputed_summary = {
        "HIGH": 0,
        "MODERATE": 0,
        "LOW": 0,
        "UNRESOLVED": 0,
    }

    for parameter in parameters:
        assert isinstance(parameter, dict)
        recomputed_summary[str(parameter["confidence_tag"])] += 1

    assert result["confidence_summary"] == recomputed_summary