from shared.field_value_policies import source_role_from_candidate
from shared.master_field_policy import canonical_source_role, source_role_authority_score
from shared.planner_candidate_ledger import build_registry_candidate_ledger


def test_canonical_source_role_aliases_feed_authority_scores() -> None:
    assert canonical_source_role("one_line") == "one_line_diagram"
    assert canonical_source_role("vendor_datasheet") == "oem_reference"
    assert canonical_source_role("load_request_form") == "application_request_form"

    one_line_score = source_role_authority_score("facility.poi_voltage_kv", "one_line")
    unknown_score = source_role_authority_score("facility.poi_voltage_kv", "unknown")
    assert one_line_score > unknown_score


def test_source_role_from_nested_evidence_metadata() -> None:
    candidate = {
        "field_path": "facility.poi_voltage_kv",
        "value": "138 kV",
        "evidence": [
            {
                "text": "Nominal service voltage: 138 kV",
                "metadata": {"document_role": "load_request_form"},
            }
        ],
    }
    assert source_role_from_candidate(candidate) == "application_request_form"


def test_candidate_ledger_records_authority_notes_and_adjustment() -> None:
    ledger = build_registry_candidate_ledger(
        schema_field_candidates=[
            {
                "field_path": "facility.poi_voltage_kv",
                "value": "138 kV",
                "confidence": "HIGH",
                "evidence": [
                    {
                        "text": "Nominal service voltage: 138 kV",
                        "metadata": {"document_role": "load_request_form"},
                    }
                ],
            }
        ],
        include_optional=True,
    )
    rows = ledger["planner_candidate_ledger"]
    row = next(item for item in rows if item.get("field_path") == "facility.poi_voltage_kv")
    assert row["candidates"]
    candidate = row["candidates"][0]
    assert candidate["source_role"] == "application_request_form"
    assert isinstance(candidate["authority_adjustment"], int)
    assert candidate["authority_adjustment"] > 0
    assert candidate["policy_authority_note"]
