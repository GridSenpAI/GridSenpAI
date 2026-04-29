import json
import subprocess
import sys
from pathlib import Path


def test_audit_run_quality_reports_manifest_semantics(tmp_path: Path):
    run = tmp_path / "run_test"
    exports = run / "exports"
    exports.mkdir(parents=True)
    (run / "pipeline_summary.json").write_text(json.dumps({"status": "SUCCESS_PROVISIONAL"}))
    (exports / "run_manifest.json").write_text(json.dumps({
        "status": "EXPORTED_PROVISIONAL",
        "summary": {
            "planner_packet_generated": True,
            "planner_packet_final_ready": False,
            "planner_packet_release_state": "DRAFT_BLOCKED",
            "draft_outputs_allowed": True,
            "interview_completion_state": "SKIPPED_OR_DEFERRED_BY_USER",
        }
    }))
    (exports / "planner_field_ledger.json").write_text(json.dumps({"rows": []}))
    (exports / "translated_parameters.json").write_text(json.dumps({"status": "TRANSLATED", "model_outputs": {}}))

    result = subprocess.run(
        [sys.executable, "scripts/audit_run_quality.py", str(run), "--json"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    assert report["pipeline_status"] == "SUCCESS_PROVISIONAL"
    assert report["manifest"]["planner_packet_generated"] is True
    assert report["manifest"]["planner_packet_final_ready"] is False
