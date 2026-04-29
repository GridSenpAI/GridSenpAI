from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.orchestration.run_pipeline import default_normalization


def test_default_normalization_tracks_unresolved_master_fields_without_emitting_interview_questions(tmp_path: Path) -> None:
    context = SimpleNamespace(
        run_id="run_001",
        config=SimpleNamespace(project_name="Test Project", schema_version_input="0.1.0"),
    )
    extraction_result = {
        "canonical_state": {},
        "entities": [],
        "candidate_entities": [],
        "topology_cues": [],
        "unresolved_fields": ["facility.poi_voltage_kv", "facility.ups.topology"],
        "interview_questions": [{"field_path": "facility.poi_voltage_kv"}],
    }

    result = default_normalization(context, extraction_result)

    assert result["validation_report"]["missing_fields"] == ["facility.poi_voltage_kv", "facility.ups.topology"]
    assert result["followup_questions"] == []
    assert result["pre_gap_resolution_unresolved_fields"] == ["facility.poi_voltage_kv", "facility.ups.topology"]
