from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_service_module():
    path = Path(__file__).resolve().parents[1] / "services" / "interview_service" / "service.py"
    spec = importlib.util.spec_from_file_location("interview_service_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compact_questions_for_agent_caps_count_and_payload_shape() -> None:
    service = _load_service_module()
    questions = []
    for index in range(75):
        questions.append(
            {
                "question_id": f"Q{index}",
                "field_path": f"facility.field_{index}",
                "question": "What is the value? " * 80,
                "reason": "Long reason. " * 120,
                "question_category": "missing",
                "priority": 100 - index,
                "source": "planner_registry_resolution_backlog",
                "metadata": {
                    "field_id": f"FIELD_{index}",
                    "planner_critical": index < 10,
                    "accepted_value": "x" * 1000,
                    "candidate_summary": {"large": "payload should not be copied"},
                    "source_anchors": ["a" * 1000],
                    "triage_rank": 0 if index < 5 else 2,
                },
            }
        )

    compact = service._compact_questions_for_agent(questions, max_count=30)

    assert len(compact) == 30
    assert all("candidate_summary" not in item.get("metadata", {}) for item in compact)
    assert all(len(item["question"]) <= 500 for item in compact)
    assert all(len(item["reason"]) <= 600 for item in compact)


def test_agent_enrichment_is_capped_after_triage(monkeypatch) -> None:
    service = _load_service_module()
    calls: list[str] = []

    monkeypatch.setattr(service, "_can_run_agent", lambda context: True)

    def fake_enrich(*, context, question_record):
        calls.append(question_record["question_id"])
        enriched = dict(question_record)
        metadata = dict(enriched.get("metadata", {}))
        metadata["agent_status"] = "MOCKED"
        enriched["metadata"] = metadata
        return enriched

    monkeypatch.setattr(service, "_enrich_question_with_agent", fake_enrich)
    questions = [
        {
            "question_id": f"Q{index}",
            "field_path": f"facility.field_{index}",
            "question": "Provide value.",
            "reason": "Needed.",
            "metadata": {"triage_rank": 0 if index < 30 else 2},
            "triage_rank": 0 if index < 30 else 2,
        }
        for index in range(50)
    ]

    enriched = service._enrich_question_records_capped(context=object(), questions=questions, max_count=25)

    assert len(calls) == 25
    assert calls == [f"Q{index}" for index in range(25)]
    assert enriched[25]["metadata"]["agent_enrichment_status"] == "SKIPPED_AFTER_TRIAGE_CAP"
    assert enriched[-1]["metadata"]["agent_enrichment_status"] == "SKIPPED_AFTER_TRIAGE_CAP"
