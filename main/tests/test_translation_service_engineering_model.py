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
    run_id: str = "translation_engineering_model_test"
    config: _TestConfig = field(default_factory=_TestConfig)


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


def test_translation_prefers_engineering_model_for_steady_state_p_mw() -> None:
    context = _TestContext(run_id="translation_prefers_engineering_model_case")

    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {
                "facility": {
                    "load_schedule": {
                        "phase_1_mw": 25.0,
                    },
                    "ups": {
                        "topology": "2N",
                    },
                }
            },
            "validation_report": {
                "schema_valid": True,
                "missing_fields": [],
                "conflicts": [],
                "interview_summary": {
                    "confirmed_field_paths": [],
                },
            },
            "evidence_snippets": [],
            "engineering_model": {
                "load_system": {
                    "peak_demand_mw": {
                        "value": 50.0,
                        "unit": "MW",
                    }
                },
                "power_conversion_and_ups": {
                    "ups_systems": [
                        {
                            "topology": {
                                "value": "2N",
                            }
                        }
                    ]
                },
            },
        }
    }

    result = run_service(
        context=context,
        canonical_state_result=canonical_state_result,
    )

    p_mw = _get_parameter(result, "steady_state.p_mw")
    q_mvar = _get_parameter(result, "steady_state.q_mvar")

    assert p_mw["value"] == 50.0
    assert p_mw["provenance_type"] == "rule"
    assert p_mw["provenance_ref"] == "RULE.ENGINEERING_MODEL_TO_STEADY_STATE_P.v1"
    assert p_mw["dependency_paths"] == ["engineering_model.load_system.peak_demand_mw"]
    assert p_mw["source_field_paths"] == ["engineering_model.load_system.peak_demand_mw"]

    assert q_mvar["value"] == 5.0
    assert q_mvar["provenance_ref"] == "RULE.ENGINEERING_MODEL_DEFAULT_Q_FACTOR"
    assert q_mvar["dependency_paths"] == ["engineering_model.load_system.peak_demand_mw"]
    assert q_mvar["source_field_paths"] == ["engineering_model.load_system.peak_demand_mw"]


def test_translation_falls_back_to_normalized_input_when_engineering_model_absent() -> None:
    context = _TestContext(run_id="translation_fallback_to_normalized_case")

    normalization_result = {
        "normalized_input": {
            "facility": {
                "load_schedule": {
                    "phase_1_mw": 42.0,
                },
                "ups": {
                    "topology": "2N",
                },
            }
        },
        "validation_report": {
            "schema_valid": True,
            "missing_fields": [],
            "conflicts": [],
            "interview_summary": {
                "confirmed_field_paths": [],
            },
        },
    }

    result = run_service(
        context=context,
        normalization_result=normalization_result,
    )

    p_mw = _get_parameter(result, "steady_state.p_mw")
    q_mvar = _get_parameter(result, "steady_state.q_mvar")

    assert p_mw["value"] == 42.0
    assert p_mw["provenance_type"] == "rule"
    assert p_mw["provenance_ref"] == "RULE.NORMALIZED_LOAD_TO_STEADY_STATE_P.v1"
    assert p_mw["dependency_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert p_mw["source_field_paths"] == ["facility.load_schedule.phase_1_mw"]

    assert q_mvar["value"] == 4.2
    assert q_mvar["provenance_ref"] == "RULE.DEFAULT_Q_FACTOR"
    assert q_mvar["dependency_paths"] == ["facility.load_schedule.phase_1_mw"]
    assert q_mvar["source_field_paths"] == ["facility.load_schedule.phase_1_mw"]


def test_translation_uses_engineering_model_ramp_rate_when_available() -> None:
    context = _TestContext(run_id="translation_engineering_model_ramp_case")

    canonical_state_result = {
        "canonical_state": {
            "normalized_input": {
                "facility": {
                    "load_schedule": {
                        "phase_1_mw": 30.0,
                    },
                    "ups": {
                        "topology": "2N",
                    },
                }
            },
            "validation_report": {
                "schema_valid": True,
                "missing_fields": [],
                "conflicts": [],
                "interview_summary": {
                    "confirmed_field_paths": [],
                },
            },
            "evidence_snippets": [],
            "engineering_model": {
                "load_system": {
                    "peak_demand_mw": {
                        "value": 30.0,
                        "unit": "MW",
                    }
                },
                "buildout_and_ramping": {
                    "ramp_characteristics": {
                        "normal_ramp_rate_mw_per_min": {
                            "value": 3.5,
                            "unit": "MW/min",
                        }
                    }
                },
            },
        }
    }

    result = run_service(
        context=context,
        canonical_state_result=canonical_state_result,
    )

    ramp_up = _get_parameter(result, "ramping.max_ramp_up_mw_per_min")
    ramp_down = _get_parameter(result, "ramping.max_ramp_down_mw_per_min")

    assert ramp_up["value"] == 3.5
    assert ramp_down["value"] == 3.5
    assert ramp_up["provenance_ref"] == "RULE.ENGINEERING_MODEL_RAMP_RATE.v1"
    assert ramp_down["provenance_ref"] == "RULE.ENGINEERING_MODEL_RAMP_RATE.v1"
    assert ramp_up["dependency_paths"] == [
        "engineering_model.buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min"
    ]
    assert ramp_down["dependency_paths"] == [
        "engineering_model.buildout_and_ramping.ramp_characteristics.normal_ramp_rate_mw_per_min"
    ]


def test_translation_keeps_default_ramp_rule_when_engineering_model_ramp_rate_missing() -> None:
    context = _TestContext(run_id="translation_default_ramp_case")

    normalization_result = {
        "normalized_input": {
            "facility": {
                "load_schedule": {
                    "phase_1_mw": 30.0,
                },
                "ups": {
                    "topology": "2N",
                },
            }
        },
        "validation_report": {
            "schema_valid": True,
            "missing_fields": [],
            "conflicts": [],
            "interview_summary": {
                "confirmed_field_paths": [],
            },
        },
    }

    result = run_service(
        context=context,
        normalization_result=normalization_result,
    )

    ramp_up = _get_parameter(result, "ramping.max_ramp_up_mw_per_min")
    ramp_down = _get_parameter(result, "ramping.max_ramp_down_mw_per_min")

    assert ramp_up["value"] == 1.0
    assert ramp_down["value"] == 1.0
    assert ramp_up["provenance_ref"] == "RULE.RAMP.DEFAULTS.v1"
    assert ramp_down["provenance_ref"] == "RULE.RAMP.DEFAULTS.v1"