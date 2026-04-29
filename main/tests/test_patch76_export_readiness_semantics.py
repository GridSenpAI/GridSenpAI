import json
from pathlib import Path


def test_manifest_summary_distinguishes_generated_from_final_ready(tmp_path: Path):
    manifest = {
        "summary": {
            "planner_packet_ready": True,
            "planner_packet_generated": True,
            "planner_packet_final_ready": False,
            "planner_packet_release_state": "DRAFT_BLOCKED",
            "planner_packet_review_required": True,
        }
    }
    path = tmp_path / "run_manifest.json"
    path.write_text(json.dumps(manifest))

    loaded = json.loads(path.read_text())["summary"]
    assert loaded["planner_packet_generated"] is True
    assert loaded["planner_packet_final_ready"] is False
    assert loaded["planner_packet_release_state"] == "DRAFT_BLOCKED"
    assert loaded["planner_packet_review_required"] is True
