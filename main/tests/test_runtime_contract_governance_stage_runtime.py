from shared.runtime_stage_contract import canonical_stage_status_order, display_stage_name


def test_runtime_contract_includes_canonical_governance_stage_label() -> None:
    order = canonical_stage_status_order()
    assert "canonical_state_governance" in order
    assert display_stage_name("canonical_state_governance") == "Canonical Governance"
