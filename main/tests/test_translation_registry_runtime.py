from types import SimpleNamespace

from shared.planner_registry import translation_parameter_config
from services.translation_service.service import translate_parameters
from services.translation_service.utils import get_dependency_paths, get_source_field_paths


class _Config(SimpleNamespace):
    schema_version_output: str = "1.0.0"


def test_translation_registry_runtime_config_exposes_dependency_and_source_paths() -> None:
    config = translation_parameter_config("steady_state.p_mw")

    assert config["accepted_field_id"] == "accepted_peak_demand_mw"
    assert "facility.load_schedule.phase_1_mw" in config["dependency_paths"]
    assert "engineering_model.load_system.peak_demand_mw" in config["source_field_paths"]


def test_translation_utils_read_dependency_and_source_paths_from_registry() -> None:
    dependency_paths = get_dependency_paths("zip_model.constant_power_fraction")
    source_field_paths = get_source_field_paths("ramping.max_ramp_up_mw_per_min")

    assert "facility.ups.topology" in dependency_paths
    assert "facility.dynamic_behavior.max_ramp_up_mw_per_min" in source_field_paths


def test_translation_schema_validation_is_registry_backed(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.translation_service.service.run_agent",
        lambda **kwargs: {
            "run_id": "run-translation-registry",
            "agent_id": "translation_support_agent",
            "status": "SKIPPED",
            "policy": {},
            "audit_path": "",
            "structured_output": {},
        },
    )

    context = SimpleNamespace(run_id="run-translation-registry", config=_Config())
    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {
                "facility": {
                    "load_schedule": {"phase_1_mw": 120.0},
                    "ups": {"topology": "2N"},
                }
            },
            "evidence_snippets": [],
        }
    }

    result = translate_parameters(
        context=context,
        canonical_state_result=canonical_state_result,
        validation_result=None,
        normalization_result=None,
        retrieval_result=None,
        gap_resolution_result=None,
    )

    schema_validation = result["schema_validation"]
    assert schema_validation["planner_registry_backed"] is True
    assert schema_validation["validation_mode"] == "planner_required_fields.translation_runtime"
    assert schema_validation["configured_parameter_count"] >= 1
    assert schema_validation["missing_parameter_count"] == 0
