from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config import CONFIG
from services.translation_service.service import run_service


@dataclass(slots=True)
class DummyConfig:
    schema_version_output: str = "1.0.0"


@dataclass(slots=True)
class DummyContext:
    run_id: str
    config: DummyConfig = field(default_factory=DummyConfig)
    run_dir: Path | None = None


def _get_parameter(
    translation_result: dict[str, object],
    parameter_path: str,
) -> dict[str, object]:
    for item in translation_result["output_parameters"]:  # type: ignore[index]
        assert isinstance(item, dict)
        if item.get("parameter_path") == parameter_path:
            return item
    raise AssertionError(f"Parameter '{parameter_path}' was not produced.")


def test_translation_service_produces_expected_parameter_structure() -> None:
    context = DummyContext(run_id="translation_test_001")

    normalization_result = {
        "normalized_input": {
            "facility": {
                "load_schedule": {"phase_1_mw": 42.0},
                "ups": {"topology": "double_conversion"},
            }
        },
        "validation_report": {
            "missing_fields": [],
            "conflicts": [],
            "interview_summary": {"confirmed_field_paths": ["facility.load_schedule.phase_1_mw"]},
        },
    }

    retrieval_result = {
        "snippets": [
            {
                "snippet_id": "snip_001",
                "source_ref": "load_doc.txt",
                "text": "Load schedule phase 1 MW is 42.",
                "metadata": {"topic": "load schedule"},
            },
            {
                "snippet_id": "snip_002",
                "source_ref": "ups_doc.txt",
                "text": "UPS topology is double conversion.",
                "metadata": {"topic": "ups topology"},
            },
        ]
    }

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )

    assert result["run_id"] == "translation_test_001"
    assert result["status"] == "TRANSLATED"
    assert isinstance(result["model_outputs"], dict)
    assert isinstance(result["output_parameters"], list)
    assert result["output_parameters"]
    assert isinstance(result["assumptions"], list)
    assert isinstance(result["confidence_summary"], dict)
    assert isinstance(result["schema_validation"], dict)
    assert isinstance(result["translation_support"], dict)
    assert isinstance(result["llm_assistance"], dict)

    parameter_paths = {
        item["parameter_path"]
        for item in result["output_parameters"]
        if isinstance(item, dict)
    }

    assert "steady_state.p_mw" in parameter_paths
    assert "steady_state.q_mvar" in parameter_paths
    assert "zip_model.constant_power_fraction" in parameter_paths
    assert "zip_model.constant_current_fraction" in parameter_paths
    assert "zip_model.constant_impedance_fraction" in parameter_paths
    assert "ramping.max_ramp_up_mw_per_min" in parameter_paths
    assert "ramping.max_ramp_down_mw_per_min" in parameter_paths

    translation_support = result["translation_support"]
    assert isinstance(translation_support, dict)
    assert "parameter_explanation" in translation_support
    assert "planner_note" in translation_support
    assert "review_note" in translation_support
    assert "assumption_summary" in translation_support
    assert "missing_info_summary" in translation_support
    assert "confidence_explanation" in translation_support

    llm_assistance = result["llm_assistance"]
    assert isinstance(llm_assistance, dict)
    assert llm_assistance["agent_id"] == "translation_support_agent"
    assert "bounded_response" in llm_assistance


def test_translation_service_creates_assumption_when_load_is_missing() -> None:
    context = DummyContext(run_id="translation_test_002")

    normalization_result = {
        "normalized_input": {
            "facility": {
                "ups": {"topology": "double_conversion"},
            }
        },
        "validation_report": {
            "missing_fields": ["facility.load_schedule.phase_1_mw"],
            "conflicts": [],
            "interview_summary": {"confirmed_field_paths": []},
        },
    }

    result = run_service(
        context=context,
        normalization_result=normalization_result,
        retrieval_result={"snippets": []},
    )

    assert result["status"] == "TRANSLATED"
    steady_state_parameter = _get_parameter(result, "steady_state.p_mw")
    assert steady_state_parameter["value"] == 0.0
    assert steady_state_parameter["provenance_type"] == "assumption"
    assert steady_state_parameter["provenance_ref"] == "assumption_steady_state_load"

    assumptions = result["assumptions"]
    assert assumptions
    assumption = next(
        item
        for item in assumptions
        if item["parameter_path"] == "steady_state.p_mw"
    )
    assert assumption["assumption_id"] == "assumption_steady_state_load"
    assert assumption["nominal_value"] == 0.0
    assert assumption["metadata"]["assumption_type"] == "MISSING_INPUT_DEFAULT"


def test_translation_service_uses_translation_support_agent_when_enabled(
    tmp_path: Path,
) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = DummyContext(
            run_id="translation_test_003",
            run_dir=tmp_path / "translation_test_003",
        )

        normalization_result = {
            "normalized_input": {
                "facility": {
                    "ups": {"topology": "double_conversion"},
                }
            },
            "validation_report": {
                "missing_fields": ["facility.load_schedule.phase_1_mw"],
                "conflicts": [],
                "interview_summary": {"confirmed_field_paths": []},
            },
        }

        result = run_service(
            context=context,
            normalization_result=normalization_result,
            retrieval_result={"snippets": []},
        )

        assert result["status"] == "TRANSLATED"
        assert isinstance(result["llm_assistance"], dict)
        assert result["llm_assistance"].get("agent_id") == "translation_support_agent"

        translation_support = result.get("translation_support", {})
        assert isinstance(translation_support, dict)
        assert "review_notes" in translation_support
        assert "low_confidence_parameters" in translation_support
        assert "assumption_backed_parameters" in translation_support
        assert "missing_dependency_parameters" in translation_support
        assert "agent_id" in translation_support
        assert "agent_status" in translation_support
        assert "agent_audit_path" in translation_support
        assert "agent_policy" in translation_support
        assert translation_support["agent_id"] == "translation_support_agent"

        output_parameters = result["output_parameters"]
        steady_state_parameter = next(
            item
            for item in output_parameters
            if item["parameter_path"] == "steady_state.p_mw"
        )
        assert "planner_note" in steady_state_parameter
        assert "review_note" in steady_state_parameter
        assert "confidence_explanation" in steady_state_parameter

        q_parameter = next(
            item
            for item in output_parameters
            if item["parameter_path"] == "steady_state.q_mvar"
        )
        assert "planner_note" in q_parameter
        assert "review_note" in q_parameter
        assert "confidence_explanation" in q_parameter

        # Current runtime may block advisory mutation when the bounded prompt exceeds policy limits.
        # In that case the agent still returns auditable policy metadata, but parameter rows remain unchanged.
        if translation_support.get("agent_status") == "PROMPT_TOO_LARGE":
            assert translation_support["agent_policy"].get("allowed") is False
            assert translation_support["review_notes"]
            assert steady_state_parameter["planner_note"] == ""
            assert q_parameter["confidence_explanation"] == ""
        else:
            assert steady_state_parameter["planner_note"] or q_parameter["confidence_explanation"]

        assumptions = result["assumptions"]
        assert assumptions
        steady_state_assumption = next(
            item
            for item in assumptions
            if item["parameter_path"] == "steady_state.p_mw"
        )
        assert "planner_note" in steady_state_assumption
        assert "Translation Support Agent confirmed this assumption remains planner-visible." in str(
            steady_state_assumption["planner_note"]
        )
    finally:
        CONFIG.model.allow_model_assistance = original_flag
