from __future__ import annotations

from types import SimpleNamespace

from services.scenario_service.service import generate_scenarios
from services.translation_service.service import run_service as run_translation_service


def test_translation_blocks_when_planner_ledger_native_inputs_missing() -> None:
    context = SimpleNamespace(run_id="run_001")
    result = run_translation_service(
        context=context,
        canonical_state_result={"canonical_state": {}},
        validation_result={"validation_report": {}},
        normalization_result={},
        retrieval_result={},
        gap_resolution_result={},
    )
    assert result["status"] == "TRANSLATION_BLOCKED_LEDGER_FIRST_REQUIRED"
    assert result["model_outputs"] == {}
    assert result["translation_source_contract"]["blocked_reason"] == "LEDGER_FIRST_TRANSLATION_REQUIRED"


def test_scenarios_block_when_translation_has_no_ledger_native_outputs() -> None:
    context = SimpleNamespace(run_id="run_002")
    result = generate_scenarios(
        context=context,
        translation_result={
            "status": "TRANSLATION_BLOCKED_LEDGER_FIRST_REQUIRED",
            "model_outputs": {"legacy": True},
            "ledger_native_model_outputs": {},
        },
    )
    assert result["status"] == "SCENARIOS_BLOCKED_LEDGER_FIRST_REQUIRED"
    assert result["scenario_variants"] == []
    assert result["scenario_input_contract"]["blocked_reason"] == "LEDGER_NATIVE_TRANSLATION_REQUIRED"
