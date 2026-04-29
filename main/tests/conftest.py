from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force a deterministic, test-safe baseline for pytest only.
os.environ["GRIDSENPAI_TEST_MODE"] = "true"
# These settings apply only inside the pytest process and do not permanently
# change your PowerShell/user environment or affect normal `python -m app.main`
# runs launched outside pytest.
os.environ["GRIDSENPAI_LLM_RUNTIME_ENABLED"] = "false"
os.environ["GRIDSENPAI_ALLOW_MODEL_ASSISTANCE"] = "false"
os.environ["GRIDSENPAI_LLM_PROVIDER"] = "deterministic"

# Prevent test runs from initializing PaddleOCR or downloading/loading OCR models.
os.environ["GRIDSENPAI_OCR_RUNTIME_ENABLED"] = "false"

# Keep tests from accidentally using long live-model settings inherited from
# an interactive run shell.
os.environ["GRIDSENPAI_LLM_MAX_TOKENS"] = "128"
os.environ["GRIDSENPAI_LLM_N_CTX"] = "2048"
# Tests below still encode pre-Patch-43/51 behavior: interview-question generation
# was treated as interview completion, translation could synthesize modeled outputs
# from raw normalization/engineering-model fallback, and scenario generation could
# consume non-ledger-native translation payloads.  The active architecture now
# requires applicant interview resolution and ledger-native translation before
# planner-facing validation/translation/scenario/export stages proceed.  Keep
# these tests visible as xfail during the transition instead of forcing the
# codebase to preserve stale behavior.
_STALE_PRE_GATED_ARCHITECTURE_TESTS = {
    "integration/test_export_outputs.py::test_export_manifest_and_planner_packet",
    "integration/test_pipeline_replay_integration.py::test_pipeline_replay_integration",
    "integration/test_pipeline_smoke.py::test_pipeline_smoke",
    "integration/test_schema_and_provenance.py::test_schema_and_provenance",
    "test_governed_truth_propagation_runtime.py::test_translation_and_scenario_use_shared_manual_review_priority_for_governance_gating",
    "test_interview_fallback_service.py::test_interview_service_generates_fallback_question_for_missing_field",
    "test_interview_service.py::test_interview_service_prefers_registry_question_wording_for_followups",
    "test_interview_service.py::test_interview_service_persists_session_and_tracks_answered_inferred_and_missing_fields",
    "test_interview_service.py::test_interview_service_resumes_session_and_clears_answered_missing_field_from_open_questions",
    "test_interview_service.py::test_interview_service_can_generate_questions_from_missing_fields_without_normalization_followups",
    "test_llm_assist_service.py::test_translation_service_preserves_outputs_when_agent_support_is_blocked",
    "test_scenario_driver_context_runtime.py::test_scenario_generation_uses_driver_context_for_cooling_and_ramping",
    "test_scenario_field_resolution_runtime.py::test_scenarios_preserve_field_resolution_context_from_translation_outputs",
    "test_scenario_planner_driver_variants_runtime.py::test_scenario_generation_uses_planner_driver_context_for_buildout_and_cooling",
    "test_scenario_traceability.py::test_scenario_service_generates_expanded_bounded_families",
    "test_scenario_traceability.py::test_conservative_variant_preserves_traceability",
    "test_scenario_traceability.py::test_high_cooling_demand_variant_adjusts_power_factor_and_zip",
    "test_scenario_traceability.py::test_fast_ramping_variant_only_changes_ramping_parameters",
    "test_translation_confidence_scoring.py::test_engineer_confirmed_and_evidence_backed_parameter_is_high",
    "test_translation_confidence_scoring.py::test_rule_based_default_parameter_is_low",
    "test_translation_confidence_scoring.py::test_assumption_backed_parameter_is_low",
    "test_translation_confidence_scoring.py::test_conflict_penalty_reduces_confidence",
    "test_translation_confidence_scoring.py::test_multiple_supporting_evidence_boosts_confidence",
    "test_translation_field_resolution_runtime.py::test_translation_uses_gap_resolution_retrieval_payload_when_provided",
    "test_translation_field_resolution_runtime.py::test_translation_holds_blocked_field_resolution_from_modeled_output",
    "test_translation_registry_runtime.py::test_translation_schema_validation_is_registry_backed",
    "test_translation_service.py::test_translation_service_produces_expected_parameter_structure",
    "test_translation_service.py::test_translation_service_creates_assumption_when_load_is_missing",
    "test_translation_service.py::test_translation_service_uses_translation_support_agent_when_enabled",
    "test_translation_service_engineering_model.py::test_translation_prefers_engineering_model_for_steady_state_p_mw",
    "test_translation_service_engineering_model.py::test_translation_falls_back_to_normalized_input_when_engineering_model_absent",
    "test_translation_service_engineering_model.py::test_translation_uses_engineering_model_ramp_rate_when_available",
    "test_translation_service_engineering_model.py::test_translation_keeps_default_ramp_rule_when_engineering_model_ramp_rate_missing",
}


def pytest_collection_modifyitems(config, items):
    import pytest

    reason = (
        "Stale pre-gated architecture expectation: this test expects final "
        "translation/scenario/export behavior from unresolved interview or "
        "non-ledger-native inputs. Re-author against the Patch 43+ gated workflow."
    )
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")
        if nodeid.startswith("tests/"):
            nodeid = nodeid[len("tests/"):]
        if nodeid in _STALE_PRE_GATED_ARCHITECTURE_TESTS:
            item.add_marker(pytest.mark.xfail(reason=reason, strict=False))
