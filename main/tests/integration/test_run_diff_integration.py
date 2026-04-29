from __future__ import annotations

import pytest
import json
import subprocess
import sys
from pathlib import Path

from tests.integration.helpers import prepare_writable_workspace


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.integration
def test_run_diff_integration(tmp_path: Path) -> None:
    project_root = prepare_writable_workspace(tmp_path)
    output_root = project_root / "runs"
    baseline_run_id = "diff_baseline_smoke"
    candidate_run_id = "diff_candidate_smoke"

    baseline_result = subprocess.run(
        [sys.executable, "-m", "app.main", "--run-id", baseline_run_id, "--output-dir", str(output_root)],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert baseline_result.returncode == 0, (
        f"Baseline pipeline failed.\nSTDOUT:\n{baseline_result.stdout}\nSTDERR:\n{baseline_result.stderr}"
    )

    candidate_result = subprocess.run(
        [sys.executable, "-m", "app.main", "--run-id", candidate_run_id, "--output-dir", str(output_root)],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert candidate_result.returncode == 0, (
        f"Candidate pipeline failed.\nSTDOUT:\n{candidate_result.stdout}\nSTDERR:\n{candidate_result.stderr}"
    )

    diff_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.main",
            "--output-dir",
            str(output_root),
            "--diff-baseline-run-id",
            baseline_run_id,
            "--diff-candidate-run-id",
            candidate_run_id,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff_result.returncode == 0, (
        f"Run diff failed.\nSTDOUT:\n{diff_result.stdout}\nSTDERR:\n{diff_result.stderr}"
    )

    candidate_run_dir = output_root / candidate_run_id
    diff_path = candidate_run_dir / "diffs" / f"diff_vs_{baseline_run_id}.json"
    assert diff_path.exists()

    payload = _load_json(diff_path)
    assert payload["status"] == "RUN_DIFF_COMPLETED"
    assert payload["summary"]["baseline_run_id"] == baseline_run_id
    assert payload["summary"]["candidate_run_id"] == candidate_run_id
    assert "field_diffs" in payload
    assert "conflict_comparison" in payload
    assert "review_flag_comparison" in payload


