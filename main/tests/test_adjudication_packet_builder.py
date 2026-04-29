from __future__ import annotations

import json

from services.field_resolution_service.adjudication_packets import build_adjudication_packet_plan


def test_adjudication_packet_builder_keeps_policy_sized_packets() -> None:
    ledger = []
    for index in range(8):
        ledger.append(
            {
                "field_id": f"field_{index}",
                "field_path": f"facility.test_{index}",
                "label": f"Test Field {index}",
                "accepted_status": "conflicting",
                "planner_critical": True,
                "requiredness": "required",
                "accepted_value": "accepted-value-" + ("x" * 120),
                "accepted_confidence": 0.51,
                "accepted_unit": "kV",
                "alternatives": [
                    {
                        "candidate_id": f"alt_{index}_{candidate_index}",
                        "value": "candidate-value-" + ("y" * 240),
                        "score": 0.9 - (candidate_index * 0.1),
                        "source_hierarchy": "applicant_direct_document",
                        "specificity": "direct_field_match",
                        "metadata": {
                            "source_document": "application.pdf",
                            "page": 1,
                            "evidence_snippet": "evidence " + ("z" * 2500),
                        },
                    }
                    for candidate_index in range(8)
                ],
                "contradiction_summary": "conflict " + ("c" * 1000),
            }
        )

    plan = build_adjudication_packet_plan(
        ledger=ledger,
        summary={"resolved_count": 0},
        max_input_chars=2600,
    )

    assert plan.packets
    assert plan.status in {"ADJUDICATION_PACKETS_READY", "ADJUDICATION_PARTIAL"}
    assert all(len(json.dumps(packet, default=str)) <= 2600 for packet in plan.packets)
    assert plan.shrink_events
