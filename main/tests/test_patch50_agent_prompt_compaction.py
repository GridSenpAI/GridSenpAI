from __future__ import annotations

from services.agent_runtime_service.service import _compact_agent_inputs


def test_agent_input_compaction_caps_translation_support_payloads() -> None:
    payload = {
        "output_parameters": [
            {"parameter_path": f"p{index}", "evidence": [{"text": "x" * 5000} for _ in range(30)]}
            for index in range(100)
        ],
        "validation_report": {"raw_text": "y" * 10000},
    }
    compacted = _compact_agent_inputs(payload)
    assert len(compacted["output_parameters"]) == 41
    assert compacted["output_parameters"][-1]["_truncated"] is True
    assert len(compacted["output_parameters"][0]["evidence"]) == 21
    assert len(compacted["validation_report"]["raw_text"]) < 1300
