from __future__ import annotations

from services.interview_service.service import _build_questions_from_registry_resolution_backlog


def test_interview_questions_include_best_value_and_alternatives_from_resolution_backlog() -> None:
    canonical_state_result = {
        "canonical_state": {
            "field_resolution": {
                "backlog": [
                    {
                        "field_id": "generator_rated_kw_per_unit",
                        "field_path": "generator_rated_kw_per_unit",
                        "label": "Generator rated kW per unit",
                        "accepted_status": "conflicting",
                        "status": "conflicting",
                        "accepted_value": 3125,
                        "alternatives": [{"value": 3000}, {"value": 3300}],
                        "why_accepted": ["Selected candidate had exact model match evidence."],
                        "resolution_priority": 1,
                        "requiredness": "required",
                        "planner_critical": True,
                    }
                ]
            }
        }
    }
    questions = _build_questions_from_registry_resolution_backlog(canonical_state_result, set())
    assert questions
    prompt = questions[0]["question"]
    reason = questions[0]["reason"]
    assert "3125" in prompt
    assert "3000" in prompt
    assert "Current best-evidence rationale" in reason
