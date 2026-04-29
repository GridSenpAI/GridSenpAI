from __future__ import annotations

from shared.ledger_downstream_governance import (
    apply_ledger_governance_to_parameters,
    resolve_planner_ledger_value,
)


def _canonical_state() -> dict:
    return {
        "planner_field_contract": {
            "planner_field_ledger": [
                {
                    "field_path": "facility.load_schedule.phase_1_mw",
                    "field_id": "accepted_peak_demand_mw",
                    "field_label": "Phase 1 MW",
                    "accepted_value": "60",
                    "confidence_score": 0.94,
                    "confidence_band": "HIGH",
                    "status": "ACCEPTED",
                    "release_state": "READY",
                    "translation_use_policy": "use",
                    "scenario_use_policy": "use",
                    "source_document": "request_form.pdf",
                    "source_page": "1",
                },
                {
                    "field_path": "net_power_factor_at_poi",
                    "field_id": "net_power_factor_at_poi",
                    "field_label": "Net Power Factor at POI",
                    "accepted_value": "UNRESOLVED",
                    "confidence_score": 0.0,
                    "confidence_band": "UNRESOLVED",
                    "status": "UNRESOLVED",
                    "release_state": "BLOCKED",
                    "translation_use_policy": "do_not_use",
                    "scenario_use_policy": "do_not_use",
                    "source_document": "No direct source found",
                },
            ]
        }
    }


def test_resolve_planner_ledger_value_prefers_closed_ledger() -> None:
    resolved = resolve_planner_ledger_value(
        _canonical_state(),
        "accepted_peak_demand_mw",
        "facility.load_schedule.phase_1_mw",
    )

    assert resolved is not None
    assert resolved["value"] == "60"
    assert resolved["used_planner_field_ledger"] is True
    assert resolved["field_release_profile"]["release_state"] == "READY"


def test_blocked_ledger_row_gates_downstream_parameter() -> None:
    params = [
        {
            "parameter_path": "steady_state.q_mvar",
            "value": 6.0,
            "confidence_score": 0.9,
            "confidence_tag": "HIGH",
            "source_field_paths": ["net_power_factor_at_poi"],
            "dependency_paths": [],
        }
    ]

    summary = apply_ledger_governance_to_parameters(
        params,
        _canonical_state(),
        use_case="translation",
    )

    assert summary["gated_parameter_count"] == 1
    assert params[0]["confidence_tag"] == "LOW"
    assert params[0]["field_release_state"] == "BLOCKED"
    assert params[0]["ledger_downstream_gated"] is True
