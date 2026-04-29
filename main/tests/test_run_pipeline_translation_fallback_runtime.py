from __future__ import annotations

from types import SimpleNamespace

import app.orchestration.run_pipeline as run_pipeline


def _build_context(run_id: str = "run_translation_fallback") -> SimpleNamespace:
    return SimpleNamespace(run_id=run_id, config=SimpleNamespace(schema_version_output="1.0.0"))


def test_default_translation_fallback_emits_translation_support_even_without_agent() -> None:
    result = run_pipeline.default_translation(_build_context(run_id=""))

    translation_support = result["translation_support"]
    assert translation_support["agent_id"] == "translation_support_agent"
    assert translation_support["agent_status"] == "NOT_RUN"
    assert "steady_state.p_mw" in translation_support["low_confidence_parameters"]

    steady_state_parameter = next(item for item in result["output_parameters"] if item["parameter_path"] == "steady_state.p_mw")
    assert "planner_note" in steady_state_parameter
    assert "review_note" in steady_state_parameter
    assert "confidence_explanation" in steady_state_parameter

    steady_state_assumption = next(item for item in result["assumptions"] if item["parameter_path"] == "steady_state.p_mw")
    assert "Translation Support Agent confirmed this assumption remains planner-visible." in steady_state_assumption["planner_note"]


def test_default_translation_fallback_surfaces_agent_result_when_called(monkeypatch) -> None:
    def _fake_run_agent(*, context, request):
        assert request.agent_id == "translation_support_agent"
        return {
            "agent_id": "translation_support_agent",
            "status": "SUCCEEDED",
            "audit_path": "",
            "policy": {"allowed": True},
            "structured_output": {
                "review_notes": ["Planner review is recommended for low-confidence parameters."],
                "low_confidence_parameters": ["steady_state.p_mw"],
                "assumption_backed_parameters": ["steady_state.p_mw"],
                "missing_dependency_parameters": ["steady_state.p_mw"],
                "parameter_explanation": "Deterministic parameter values remain unchanged. This advisory output only adds bounded review context.",
                "planner_note": "Review low-confidence and assumption-backed parameters before external publication.",
                "review_note": "This agent does not modify deterministic parameter values.",
                "assumption_summary": "1 active assumptions inform the current translation output.",
                "missing_info_summary": "Additional evidence is recommended for parameters that remain low-confidence or assumption-backed.",
                "confidence_explanation": "Confidence remains constrained by upstream evidence gaps.",
                "rationale": "Translation support output was derived from deterministic translation metadata and confidence tags.",
                "confidence": "MODERATE",
            },
        }

    monkeypatch.setattr(run_pipeline, "run_agent", _fake_run_agent)
    result = run_pipeline.default_translation(_build_context())

    assert result["llm_assistance"]["agent_id"] == "translation_support_agent"
    assert result["llm_assistance"]["status"] == "SUCCEEDED"
    assert result["translation_support"]["agent_status"] == "SUCCEEDED"
    assert result["translation_support"]["agent_policy"]["allowed"] is True
