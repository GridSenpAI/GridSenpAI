from dataclasses import dataclass, field
from pathlib import Path

from services.drawing_interpretation_service.service import DrawingInterpretationService


@dataclass(slots=True)
class _DrawingTestConfig:
    schema_version_output: str = "1.0.0"


@dataclass(slots=True)
class _DrawingTestContext:
    run_id: str
    run_dir: Path
    config: _DrawingTestConfig = field(default_factory=_DrawingTestConfig)


def test_drawing_interpretation_extracts_transformer_generator_and_ups_counts() -> None:
    service = DrawingInterpretationService()

    artifacts = [
        {
            "artifact_id": "artifact_001",
            "artifact_type": "one_line_diagram",
            "file_name": "facility_one_line.pdf",
            "text": "TX-1 TX-2 GEN-1 UPS-1 UPS-2 ring bus arrangement",
        }
    ]

    field_paths = [
        "facility.transformers.count",
        "facility.generators.count",
        "facility.ups.count",
        "facility.substation_configuration",
    ]

    results = service.extract(artifacts, field_paths)

    by_path = {item["field_path"]: item for item in results}

    assert by_path["facility.transformers.count"]["value"] == 2
    assert by_path["facility.generators.count"]["value"] == 1
    assert by_path["facility.ups.count"]["value"] == 2
    assert by_path["facility.substation_configuration"]["value"] == "ring bus"


def test_drawing_interpretation_extracts_transformer_ratings_and_ups_topology() -> None:
    service = DrawingInterpretationService()

    artifacts = [
        {
            "artifact_id": "artifact_002",
            "classification": "electrical_drawing",
            "file_name": "switchyard_sld.pdf",
            "text": "Main service includes 25 MVA transformer and backup 12.5 MVA transformer. UPS topology is 2N.",
        }
    ]

    field_paths = [
        "facility.transformers.ratings_mva",
        "facility.ups.topology",
    ]

    results = service.extract(artifacts, field_paths)
    by_path = {item["field_path"]: item for item in results}

    assert by_path["facility.transformers.ratings_mva"]["value"] == [25.0, 12.5]
    assert by_path["facility.ups.topology"]["value"] == "2N"


def test_drawing_interpretation_ignores_non_drawing_artifacts() -> None:
    service = DrawingInterpretationService()

    artifacts = [
        {
            "artifact_id": "artifact_003",
            "artifact_type": "equipment_schedule",
            "file_name": "equipment_schedule.xlsx",
            "text": "TX-1 TX-2 GEN-1 UPS-1",
        }
    ]

    field_paths = ["facility.transformers.count"]

    results = service.extract(artifacts, field_paths)

    assert results == []


def test_drawing_interpretation_returns_none_for_unmatched_field() -> None:
    service = DrawingInterpretationService()

    artifacts = [
        {
            "artifact_id": "artifact_004",
            "artifact_type": "one_line_diagram",
            "file_name": "facility_one_line.pdf",
            "text": "No useful labels here.",
        }
    ]

    field_paths = ["facility.transformers.count"]

    results = service.extract(artifacts, field_paths)

    assert results == []

from app.config import CONFIG


def test_drawing_interpretation_uses_llm_fallback_for_substation_configuration(monkeypatch) -> None:
    service = DrawingInterpretationService()
    original_enabled = CONFIG.llm_runtime.enabled
    original_model_path = CONFIG.llm_runtime.model_path
    CONFIG.llm_runtime.enabled = True
    CONFIG.llm_runtime.model_path = "models/test.gguf"

    monkeypatch.setattr("services.llm_runtime_service.service.initialize_runtime", lambda config: None)

    class _Result:
        parsed_json = {"value": "breaker and a half", "rationale": "Diagram labels support breaker-and-a-half topology."}

    monkeypatch.setattr("services.llm_runtime_service.service.run_llm_task", lambda **kwargs: _Result())

    try:
        artifacts = [{"artifact_id": "drawing-llm-1", "artifact_type": "one_line_diagram", "parsed_text": "Main bus A and bus B with three breakers between circuits."}]
        results = service.extract(artifacts, ["facility.substation.configuration"])
        assert len(results) == 1
        assert results[0]["value"] == "breaker and a half"
        assert results[0]["method"] == "drawing_interpretation_llm"
        assert results[0]["confidence"] >= 0.74
    finally:
        CONFIG.llm_runtime.enabled = original_enabled
        CONFIG.llm_runtime.model_path = original_model_path


def test_drawing_interpretation_uses_document_interpretation_agent_when_context_present(tmp_path: Path) -> None:
    service = DrawingInterpretationService()
    context = _DrawingTestContext(
        run_id="drawing_interpretation_agent_test",
        run_dir=tmp_path / "drawing_interpretation_agent_test",
    )

    artifacts = [
        {
            "artifact_id": "drawing-agent-1",
            "artifact_type": "one_line_diagram",
            "parsed_text": "Main bus A and bus B with three breakers between circuits.",
        }
    ]
    results = service.extract(artifacts, ["facility.substation.configuration"], context=context)
    assert len(results) == 1
    assert results[0]["method"] == "drawing_interpretation_agent"
    assert results[0]["confidence"] >= 0.74



def test_drawing_interpretation_limits_agent_to_ranked_candidates(tmp_path: Path, monkeypatch) -> None:
    service = DrawingInterpretationService()
    context = _DrawingTestContext(
        run_id="drawing_interpretation_budget_test",
        run_dir=tmp_path / "drawing_interpretation_budget_test",
    )

    artifacts = []
    for index in range(10):
        artifacts.append(
            {
                "artifact_id": f"drawing-{index}",
                "artifact_type": "one_line_diagram",
                "file_name": f"drawing_{index}.pdf",
                "parsed_text": f"Main bus A and bus B with breaker lineup {index} in substation one-line",
            }
        )

    call_count = 0

    def _fake_run_agent(*, context, request):
        nonlocal call_count
        call_count += 1
        return {"structured_output": {"candidate_value": 2, "rationale": "bounded candidate"}}

    monkeypatch.setattr("services.drawing_interpretation_service.service.run_agent", _fake_run_agent)

    results = service.extract(artifacts, ["facility.substation.configuration"], context=context)

    assert len(results) == 3
    assert call_count == 3
    assert all(item["field_path"] == "facility.substation.configuration" for item in results)


def test_drawing_interpretation_prefers_primary_topology_and_preserves_role_metadata() -> None:
    service = DrawingInterpretationService()

    artifacts = [
        {
            "artifact_id": "artifact_topology",
            "artifact_type": "one_line_diagram",
            "file_name": "facility_one_line.pdf",
            "parsed_text": "Main bus A and bus B with breaker and a half arrangement.",
            "ontology": {"document_role": "primary_topology", "document_family": "drawing"},
        },
        {
            "artifact_id": "artifact_legend",
            "artifact_type": "one_line_diagram",
            "file_name": "facility_legend.pdf",
            "parsed_text": "Legend general notes revision history breaker and a half reference only.",
            "ontology": {"document_role": "legend_notes", "document_family": "drawing"},
        },
    ]

    results = service.extract(artifacts, ["facility.substation.configuration"])

    assert len(results) == 1
    assert results[0]["source_artifact_id"] == "artifact_topology"
    assert results[0]["metadata"]["document_role"] == "primary_topology"
    assert results[0]["metadata"]["field_family"] == "topology_configuration"
