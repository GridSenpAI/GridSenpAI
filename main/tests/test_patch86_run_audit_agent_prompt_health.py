import json
from pathlib import Path

from scripts.audit_run_quality import audit_run


def test_run_audit_flags_agent_prompt_chunking_health(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_test"
    audit_dir = run_dir / "agent_audit"
    audit_dir.mkdir(parents=True)
    (run_dir / "pipeline_summary.json").write_text(json.dumps({"status": "SUCCESS_PROVISIONAL"}), encoding="utf-8")
    (audit_dir / "translation_support_agent_parameter_review.json").write_text(
        json.dumps(
            {
                "prompt_payload": {"prompt_telemetry": {"chunking_enabled": True, "max_prompt_chars": 24000, "total_prompt_chars_after_compaction": 100000}},
                "response_payload": {
                    "agent_prompt_health": {
                        "chunking_enabled": True,
                        "chunk_count": 5,
                        "failed_chunk_count": 0,
                        "largest_chunk_chars": 11000,
                        "max_prompt_chars": 24000,
                    },
                    "runtime_payload": {"chunking_enabled": True, "chunk_count": 5, "failed_chunk_count": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    report = audit_run(run_dir)
    health = report["agent_prompt_health"]
    assert health["chunked_agent_calls"] == 1
    assert health["oversized_prompt_failures"] == 0
    assert health["health"] == "GREEN"
