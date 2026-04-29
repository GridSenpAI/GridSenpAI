from __future__ import annotations

import pytest
import json
import subprocess
import sys
from pathlib import Path

from tests.integration.helpers import prepare_writable_workspace


VALID_CONFIDENCE_TAGS = {
    "HIGH",
    "MODERATE",
    "LOW",
    "UNRESOLVED",
}


def _assert_confidence_consistency(parameter: dict[str, object]) -> None:
    assert "confidence_score" in parameter
    assert "confidence_tag" in parameter

    confidence_score = parameter["confidence_score"]
    confidence_tag = parameter["confidence_tag"]

    assert isinstance(confidence_score, (int, float))
    assert 0.0 <= float(confidence_score) <= 1.0
    assert confidence_tag in VALID_CONFIDENCE_TAGS

    if confidence_tag == "HIGH":
        assert float(confidence_score) >= 0.85
    elif confidence_tag == "MODERATE":
        assert 0.60 <= float(confidence_score) < 0.85
    elif confidence_tag == "LOW":
        assert float(confidence_score) < 0.60


@pytest.mark.integration
def test_schema_and_provenance(tmp_path: Path) -> None:
    project_root = prepare_writable_workspace(tmp_path)
    output_root = project_root / "runs"
    run_id = "schema_provenance_test"

    result = subprocess.run(
        [sys.executable, "-m", "app.main", "--run-id", run_id, "--output-dir", str(output_root)],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Pipeline failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    run_dir = output_root / run_id

    normalization_stage = json.loads(
        (run_dir / "stages" / "normalization.json").read_text(encoding="utf-8")
    )
    translation_stage = json.loads(
        (run_dir / "stages" / "translation.json").read_text(encoding="utf-8")
    )

    normalization_report = normalization_stage["validation_report"]
    assert normalization_report["schema_valid"] is False
    assert normalization_report["missing_fields"]
    assert "schema_path" in normalization_report

    translation_schema_validation = translation_stage["schema_validation"]
    assert translation_schema_validation["schema_valid"] is True
    assert translation_schema_validation["planner_registry_backed"] is True
    assert "registry_path" in translation_schema_validation
    assert "configured_parameter_count" in translation_schema_validation
    assert "missing_parameter_count" in translation_schema_validation

    output_parameters = translation_stage["output_parameters"]
    assert output_parameters, "No output parameters were produced."

    for parameter in output_parameters:
        assert "parameter_path" in parameter
        assert "value" in parameter
        assert "units" in parameter
        assert "provenance_type" in parameter
        assert "provenance_ref" in parameter

        assert "dependency_paths" in parameter
        assert "source_field_paths" in parameter
        assert "supporting_snippet_ids" in parameter

        assert "confidence_score" in parameter
        assert "confidence_tag" in parameter
        assert "confidence_factors" in parameter

        assert parameter["provenance_type"] in {"evidence", "rule", "assumption"}

        assert isinstance(parameter["dependency_paths"], list)
        assert all(isinstance(path, str) and path.strip() for path in parameter["dependency_paths"])

        assert isinstance(parameter["source_field_paths"], list)
        assert all(isinstance(path, str) and path.strip() for path in parameter["source_field_paths"])

        assert isinstance(parameter["supporting_snippet_ids"], list)
        assert all(
            isinstance(snippet_id, str) and snippet_id.strip()
            for snippet_id in parameter["supporting_snippet_ids"]
        )

        assert isinstance(parameter["confidence_factors"], dict)

        _assert_confidence_consistency(parameter)

        if parameter["provenance_type"] == "evidence":
            assert isinstance(parameter["provenance_ref"], list)
            assert parameter["provenance_ref"], (
                f"Evidence provenance missing snippet refs for {parameter['parameter_path']}"
            )

        if parameter["provenance_type"] == "rule":
            assert isinstance(parameter["provenance_ref"], str)
            assert parameter["provenance_ref"].strip()

        if parameter["provenance_type"] == "assumption":
            assert isinstance(parameter["provenance_ref"], str)
            assert parameter["provenance_ref"].strip()


