from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services.ingestion_service.service import run_service
from services.ingestion_service.utils import build_requirement_catalog


def _build_context(*, project_root: Path, input_dir: Path, run_id: str, project_name: str):
    run_dir = project_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        run_id=run_id,
        project_root=project_root,
        input_dir=input_dir,
        output_dir=run_dir / "outputs",
        run_dir=run_dir,
        config=SimpleNamespace(project_name=project_name),
    )


def test_ingestion_requirement_catalog_is_registry_backed() -> None:
    catalog = build_requirement_catalog()
    assert catalog

    labels = {item["label"] for item in catalog}
    assert "Completed utility/ISO load information form" in labels
    assert "Customer One-Line Diagram / Interconnection Single-Line Diagram" in labels
    assert "Electrical Load Study and Demand Forecast" in labels

    lif_item = next(
        item for item in catalog
        if item["label"] == "Completed utility/ISO load information form"
    )
    assert lif_item["required"] is True
    assert "load_information_form" in lif_item["accepted_classifications"]

    one_line_item = next(
        item for item in catalog
        if item["label"] == "Customer One-Line Diagram / Interconnection Single-Line Diagram"
    )
    assert one_line_item["required"] is True
    assert "one_line_diagram" in one_line_item["accepted_classifications"]


def test_ingestion_service_creates_intake_session_and_marks_missing_required_artifacts(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "facility_one-line.pdf").write_text("placeholder", encoding="utf-8")

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_001",
        project_name="Test Project",
    )

    result = run_service(context)

    assert result["artifact_count"] == 1
    assert "intake_session" in result
    assert "artifacts_discovered" in result
    assert result["artifacts_discovered"] == result["artifacts"]

    session = result["intake_session"]
    assert session["status"] == "IN_PROGRESS"
    assert session["missing_required_count"] >= 1

    requirement_states = {
        item["label"]: item["state"]
        for item in session["requirements"]
    }
    assert requirement_states["Customer One-Line Diagram / Interconnection Single-Line Diagram"] == "UPLOADED"
    assert requirement_states["Completed utility/ISO load information form"] == "MISSING"
    assert requirement_states["Electrical Load Study and Demand Forecast"] == "MISSING"

    artifact = result["artifacts"][0]
    assert artifact["classification"] == "one_line_diagram"
    assert artifact["association_status"] == "ASSOCIATED"

    session_path = Path(session["session_path"])
    assert session_path.exists()


def test_ingestion_service_resumes_session_and_completes_required_artifact_catalog(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    (input_dir / "facility_one-line.pdf").write_text("placeholder", encoding="utf-8")

    first_context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_001",
        project_name="Test Project",
    )
    first_result = run_service(first_context)
    first_session = first_result["intake_session"]
    assert first_session["missing_required_count"] >= 1

    (input_dir / "utility_iso_load_information_form.txt").write_text("LIF data", encoding="utf-8")
    (input_dir / "electrical_load_study_and_demand_forecast.txt").write_text(
        "peak demand 125 MW",
        encoding="utf-8",
    )
    (input_dir / "transformer_datasheet.txt").write_text(
        "transformer 50 MVA",
        encoding="utf-8",
    )
    (input_dir / "site_plan_layout_drawing.txt").write_text(
        "site layout",
        encoding="utf-8",
    )

    second_context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_002",
        project_name="Test Project",
    )
    second_result = run_service(second_context)

    session = second_result["intake_session"]
    assert second_result["artifacts_discovered"] == second_result["artifacts"]

    requirement_states = {
        item["label"]: item["state"]
        for item in session["requirements"]
    }
    assert requirement_states["Completed utility/ISO load information form"] == "UPLOADED"
    assert requirement_states["Customer One-Line Diagram / Interconnection Single-Line Diagram"] == "UPLOADED"
    assert requirement_states["Electrical Load Study and Demand Forecast"] == "UPLOADED"
    assert requirement_states["Transformer Datasheets"] == "UPLOADED"

    if "Site Location and POI Selection Package" in requirement_states:
        assert requirement_states["Site Location and POI Selection Package"] == "UPLOADED"

    uploaded_labels = {
        item["label"]
        for item in session["requirements"]
        if item["state"] == "UPLOADED"
    }
    assert any("one-line" in label.lower() or "single-line" in label.lower() for label in uploaded_labels)
    assert any("load information form" in label.lower() or "(lif)" in label.lower() for label in uploaded_labels)
    assert any("load study" in label.lower() or "demand forecast" in label.lower() for label in uploaded_labels)
    assert any("transformer" in label.lower() for label in uploaded_labels)

    assert session["missing_required_count"] >= 0
    if session["missing_required_count"] == 0:
        assert session["status"] == "COMPLETE"
    else:
        assert session["status"] == "IN_PROGRESS"