from __future__ import annotations

import json

from services.extraction_service.review_packets import build_extraction_review_packet_plan


def test_extraction_review_packets_are_compact_and_do_not_include_full_artifacts() -> None:
    artifacts = [
        {
            "artifact_id": "application_form",
            "filename": "large_load_request.pdf",
            "artifact_type": "application_request_form",
            "text": "FULL_ARTIFACT_TEXT_SHOULD_NOT_APPEAR " * 5000,
        }
    ]
    candidates = [
        {
            "field_path": f"facility.test_field_{index % 5}",
            "value": f"candidate-{index}",
            "confidence": 0.51 if index % 2 else 0.66,
            "artifact_id": "application_form",
            "method": "schema_field_extraction",
            "metadata": {
                "source_role": "application_request_form",
                "evidence_snippet": "OVERSIZED_EVIDENCE_SNIPPET_SHOULD_BE_CAPPED " * 300,
            },
        }
        for index in range(20)
    ]

    plan = build_extraction_review_packet_plan(
        artifacts=artifacts,
        schema_field_candidates=candidates,
        warnings=["conflict detected between candidates"],
        uncovered_planner_registry_fields=[f"facility.missing_{index}" for index in range(30)],
    )

    assert plan.status == "READY"
    assert plan.packets
    for packet in plan.packets:
        raw = json.dumps(packet, sort_keys=True, default=str)
        assert len(raw) <= plan.max_input_chars
        assert "FULL_ARTIFACT_TEXT_SHOULD_NOT_APPEAR" not in raw
        assert raw.count("OVERSIZED_EVIDENCE_SNIPPET_SHOULD_BE_CAPPED") < 20
        assert "schema_field_candidates" not in packet
        assert "artifacts" not in packet
        assert "entities" not in packet
        assert "ontology" not in packet


def test_extraction_review_packets_split_and_shrink_when_payload_would_exceed_cap() -> None:
    artifacts = [{"artifact_id": "a1", "filename": "source.pdf", "text": "x" * 10000}]
    candidates = [
        {
            "field_path": f"facility.compact_field_{index}",
            "value": "value " * 80,
            "confidence": 0.40,
            "artifact_id": "a1",
            "method": "low_confidence_extraction",
            "metadata": {"evidence_snippet": "long snippet " * 300},
        }
        for index in range(12)
    ]

    plan = build_extraction_review_packet_plan(
        artifacts=artifacts,
        schema_field_candidates=candidates,
        warnings=["low confidence"],
        uncovered_planner_registry_fields=[],
        max_input_chars=1800,
        max_fields_per_packet=4,
        max_candidates_per_field=3,
        max_snippet_chars=180,
    )

    assert plan.packets
    assert plan.shrink_events
    assert all(len(json.dumps(packet, default=str)) <= 1800 for packet in plan.packets)
