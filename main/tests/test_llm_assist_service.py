from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from services.agent_models.models import AgentRequest
from services.agent_runtime_service.service import run_agent
from services.translation_service.service import run_service as run_translation_service


@dataclass(slots=True)
class _TestConfig:
    schema_version_output: str = "1.0.0"


@dataclass(slots=True)
class _TestContext:
    run_id: str
    run_dir: Path
    config: _TestConfig = field(default_factory=_TestConfig)


def test_agent_runtime_returns_bounded_advisory_output(tmp_path: Path) -> None:
    context = _TestContext(
        run_id="agent_runtime_translation_support_test",
        run_dir=tmp_path / "agent_runtime_translation_support_test",
    )

    result = run_agent(
        context=context,
        request=AgentRequest(
            agent_id="translation_support_agent",
            stage_name="translation",
            task_name="parameter_review",
            inputs={
                "output_parameters": [
                    {
                        "parameter_path": "steady_state.p_mw",
                        "confidence_tag": "LOW",
                        "provenance_type": "assumption",
                        "confidence_factors": {"missing_dependency": True},
                    }
                ],
                "assumptions": [{"assumption_id": "assumption_001"}],
            },
        ),
    )

    assert result["status"] == "COMPLETED"
    assert result["policy"]["allowed"] is True
    advisory = result["structured_output"]
    assert advisory["deterministic_override_allowed"] is False
    assert advisory["low_confidence_parameters"] == ["steady_state.p_mw"]
    assert advisory["assumption_backed_parameters"] == ["steady_state.p_mw"]
    assert advisory["missing_dependency_parameters"] == ["steady_state.p_mw"]


def test_translation_service_preserves_outputs_when_agent_support_is_blocked(tmp_path: Path) -> None:
    context = _TestContext(
        run_id="translation_agent_blocked_test",
        run_dir=tmp_path / "translation_agent_blocked_test",
    )

    normalization_result = {
        "normalized_input": {
            "facility": {
                "load_schedule": {
                    "phase_1_mw": None,
                }
            }
        },
        "validation_report": {
            "schema_valid": True,
            "missing_fields": ["facility.load_schedule.phase_1_mw"],
            "conflicts": [],
            "interview_summary": {"confirmed_field_paths": []},
        },
    }

    retrieval_result = {"snippets": []}

    result = run_translation_service(
        context=context,
        normalization_result=normalization_result,
        retrieval_result=retrieval_result,
    )

    assert result["status"] == "TRANSLATED"
    assert "translation_support" in result
    support = result["translation_support"]
    assert support["agent_status"] == "PROMPT_TOO_LARGE"
    assert support["agent_policy"]["allowed"] is False

    model_outputs = result["model_outputs"]
    output_parameters = result["output_parameters"]
    assert model_outputs["steady_state"]["p_mw"] == 0.0
    p_parameter = next(
        parameter
        for parameter in output_parameters
        if parameter["parameter_path"] == "steady_state.p_mw"
    )
    assert p_parameter["provenance_type"] == "assumption"
    assert p_parameter["value"] == 0.0
