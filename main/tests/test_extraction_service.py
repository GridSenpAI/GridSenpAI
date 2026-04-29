from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services.extraction_service.service import run_service


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


def test_extraction_service_emits_blueprint_coverage_and_schema_candidates(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    one_line_path = input_dir / "facility_one-line.txt"
    one_line_path.write_text(
        "\n".join(
            [
                "Point of Interconnection: North POI 138 kV",
                "Peak demand 125 MW",
                "2 transformers rated 50 MVA each",
                "UPS topology double conversion",
                "UPS module count 8",
                "Generator count 6",
                "SCADA interface present",
                "Breaker count 12",
                "Bus section count 2",
                "Power factor 0.98",
                "Reactive capability 45 MVAR",
            ]
        ),
        encoding="utf-8",
    )

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_001",
        project_name="Test Project",
    )

    ingestion_result = {
        "run_id": context.run_id,
        "status": "ARTIFACTS_INGESTED",
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "file_name": one_line_path.name,
                "file_path": str(one_line_path),
                "classification": "one_line_diagram",
            }
        ],
    }

    result = run_service(
        context=context,
        ingestion_result=ingestion_result,
        document_parser_result=None,
        layout_analysis_result=None,
        ocr_result=None,
    )

    assert result["run_id"] == context.run_id
    assert result["status"] == "EXTRACTED"
    assert "schema_field_candidates" in result
    assert "planner_registry_summary" in result
    assert "planner_registry_field_targets" in result
    assert "uncovered_planner_registry_fields" in result
    assert "llm_assistance" in result

    schema_candidates = result["schema_field_candidates"]
    assert isinstance(schema_candidates, list)
    assert schema_candidates

    field_paths = {candidate["field_path"] for candidate in schema_candidates}
    assert "facility.transformers.count" in field_paths
    assert "facility.generators.count" in field_paths

    entity_field_paths = {
        entity.get("attributes", {}).get("parameter_path")
        for entity in result["entities"]
        if isinstance(entity, dict)
    }
    assert "facility.poi_voltage_kv" in entity_field_paths
    assert "facility.load_schedule.phase_1_mw" in entity_field_paths
    assert "facility.ups.topology" in entity_field_paths

    planner_registry_summary = result["planner_registry_summary"]
    assert planner_registry_summary["planner_registry_field_count"] >= planner_registry_summary["mapped_planner_registry_field_count"]
    assert planner_registry_summary["mapped_planner_registry_field_count"] >= planner_registry_summary["covered_mapped_planner_registry_field_count"]
    assert planner_registry_summary["uncovered_mapped_planner_registry_field_count"] >= 0

    planner_registry_targets = result["planner_registry_field_targets"]
    assert isinstance(planner_registry_targets, list)
    assert planner_registry_targets

    uncovered = result["uncovered_planner_registry_fields"]
    assert isinstance(uncovered, list)

    llm_assistance = result["llm_assistance"]
    assert isinstance(llm_assistance, dict)


def test_extraction_service_uses_document_parser_blocks_as_evidence_sources(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    placeholder_path = input_dir / "substation_notes.pdf"
    placeholder_path.write_text("placeholder", encoding="utf-8")

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_002",
        project_name="Test Project",
    )

    ingestion_result = {
        "run_id": context.run_id,
        "status": "ARTIFACTS_INGESTED",
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "file_name": placeholder_path.name,
                "file_path": str(placeholder_path),
                "classification": "poi_interconnection_documentation",
            }
        ],
    }

    document_parser_result = {
        "parsed_documents": [
            {
                "artifact_id": "artifact_001",
                "file_name": placeholder_path.name,
                "pages": [
                    {
                        "page_number": 1,
                        "extracted_text": "Point of Interconnection 138 kV breaker count 10 SCADA present",
                        "text_blocks": [
                            {
                                "block_id": "blk_001",
                                "text": "Point of Interconnection 138 kV",
                                "bbox": {"x0": 0, "y0": 0, "x1": 100, "y1": 25},
                            },
                            {
                                "block_id": "blk_002",
                                "text": "breaker count 10 SCADA present",
                                "bbox": {"x0": 0, "y0": 30, "x1": 120, "y1": 60},
                            },
                        ],
                    }
                ],
            }
        ]
    }

    result = run_service(
        context=context,
        ingestion_result=ingestion_result,
        document_parser_result=document_parser_result,
        layout_analysis_result=None,
        ocr_result=None,
    )

    assert result["status"] == "EXTRACTED"

    source_anchors = result["source_anchors"]
    assert isinstance(source_anchors, list)
    assert source_anchors
    assert any(anchor.get("parser_block_id") == "blk_001" for anchor in source_anchors)
    assert any(anchor.get("parser_block_id") == "blk_002" for anchor in source_anchors)

    entity_field_paths = {
        entity.get("attributes", {}).get("parameter_path")
        for entity in result["entities"]
        if isinstance(entity, dict)
    }
    assert "facility.poi_voltage_kv" in entity_field_paths

def test_extraction_service_uses_ocr_text_for_region_scoped_extraction_and_persists_relevance_plan(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    placeholder_path = input_dir / "facility_one_line.pdf"
    placeholder_path.write_text("placeholder", encoding="utf-8")

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_003",
        project_name="Test Project",
    )

    ingestion_result = {
        "run_id": context.run_id,
        "status": "ARTIFACTS_INGESTED",
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "file_name": placeholder_path.name,
                "file_path": str(placeholder_path),
                "classification": "one_line_diagram",
            }
        ],
    }

    document_parser_result = {
        "parsed_documents": [
            {
                "artifact_id": "artifact_001",
                "file_name": placeholder_path.name,
                "route_hint": "HYBRID_PARSE_AND_OCR",
                "pages": [
                    {
                        "page_number": 1,
                        "extracted_text": "",
                        "text_blocks": [],
                    }
                ],
            }
        ]
    }

    layout_analysis_result = {
        "documents": [
            {
                "artifact_id": "artifact_001",
                "document_classification": "DIAGRAM_DOCUMENT",
                "pages": [
                    {
                        "page_number": 1,
                        "page_classification": "DIAGRAM_PAGE",
                        "extraction_profiles": ["DIAGRAM_EVIDENCE_EXTRACTION"],
                        "candidate_regions": [
                            {
                                "region_id": "artifact_001_p0001_diag",
                                "region_type": "DIAGRAM_EVIDENCE_REGION",
                                "bbox": {"x0": 0, "top": 0, "x1": 400, "bottom": 200},
                            }
                        ],
                    }
                ],
            }
        ]
    }

    ocr_result = {
        "documents": [
            {
                "artifact_id": "artifact_001",
                "pages": [
                    {
                        "page_number": 1,
                        "extracted_text": "TX-1 TX-2 GEN-1 UPS-1 ring bus",
                        "text_regions": [
                            {
                                "region_id": "ocr_001",
                                "text": "TX-1 TX-2 GEN-1 UPS-1 ring bus",
                                "bbox": {"x0": 10, "top": 10, "x1": 300, "bottom": 100},
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result = run_service(
        context=context,
        ingestion_result=ingestion_result,
        document_parser_result=document_parser_result,
        layout_analysis_result=layout_analysis_result,
        ocr_result=ocr_result,
    )

    assert result["status"] == "EXTRACTED"
    assert "relevance_plan" in result
    assert isinstance(result["relevance_plan"], list)
    assert result["relevance_plan"]

    first_plan = result["relevance_plan"][0]
    assert first_plan["artifact_id"] == "artifact_001"
    assert first_plan["planned_regions"]
    assert first_plan["planned_regions"][0]["region_id"] == "artifact_001_p0001_diag"
    assert "ocr_regions" in first_plan["planned_regions"][0]["source_preferences"]
    assert "region_priority" in first_plan["planned_regions"][0]
    assert isinstance(first_plan["planned_regions"][0]["region_priority"], int)
    assert first_plan["planned_regions"][0]["region_priority"] > 0
    assert first_plan["planned_regions"][0]["region_confidence"] in {"HIGH", "MODERATE", "LOW"}

    field_paths = {
        entity["attributes"].get("parameter_path")
        for entity in result["entities"]
        if isinstance(entity, dict) and isinstance(entity.get("attributes"), dict)
    }

    assert "facility.transformers.count" in field_paths
    assert "facility.generators.count" in field_paths
    assert "facility.ups.count" in field_paths

def test_extraction_service_promotes_interconnection_study_identity_and_requirements(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    study_path = input_dir / "pjm_facilities_study.txt"
    study_path.write_text(
        "\n".join(
            [
                "Facilities Study Report",
                "For",
                "Physical Interconnection of",
                "PJM Generation Interconnection Request Project IDs AE2-341 / AF1-030",
                "Sandwich-Plano 138kV",
                "The Project Developer (PD) has proposed a Solar Generating Facility.",
                "The Generating Facility will interconnect with the Commonwealth Edison transmission system via a newly constructed 138kV breaker-and-a-half substation.",
                "Point of Interconnection (POI): TSS 978 Miller Road tapping the TSS 146 Sandwich - TSS 167 Plano 138kV line.",
                "Metering is required to be installed per ComEd & PJM standards.",
                "Project Developer to include over/under frequency and voltage protection at solar farm collector bus.",
                "Dual bus protection for 34.5kV bus.",
                "The following relay references apply: SEL-421 and SEL-351. Firmware version R154-V0.",
            ]
        ),
        encoding="utf-8",
    )

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_004",
        project_name="Test Project",
    )

    ingestion_result = {
        "run_id": context.run_id,
        "status": "ARTIFACTS_INGESTED",
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "file_name": study_path.name,
                "file_path": str(study_path),
                "classification": "poi_interconnection_documentation",
            }
        ],
    }

    result = run_service(
        context=context,
        ingestion_result=ingestion_result,
        document_parser_result=None,
        layout_analysis_result=None,
        ocr_result=None,
    )

    schema_candidates = result["schema_field_candidates"]
    by_field = {}
    for candidate in schema_candidates:
        by_field.setdefault(candidate["field_path"], []).append(candidate)

    assert any(item["value"] == "AE2-341 / AF1-030" for item in by_field["application_or_queue_id"])
    assert any(item["value"] == "PJM" for item in by_field["study_region_or_iso"])
    assert any("Metering is required to be installed" in str(item["value"]) for item in by_field["revenue_metering_configuration"])
    assert any("underfrequency" in str(item["value"]).lower() or "under frequency" in str(item["value"]).lower() for item in by_field["protection_scheme_summary"])
    assert any("SEL-421" in str(item["value"]) for item in by_field["relay_model_and_firmware_summary"])
    assert any(item.get("source_method") == "promotion.interconnection_identity" for item in by_field["application_or_queue_id"])
    assert any(item.get("source_method") == "promotion.relay_reference" for item in by_field["relay_model_and_firmware_summary"])



def test_extraction_service_does_not_map_internal_distribution_voltage_to_poi(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)
    notes_path = input_dir / "distribution_notes.txt"
    notes_path.write_text("Main MV switchgear lineup operates at 13.8 kV distribution voltage for campus feeders.", encoding="utf-8")
    context = _build_context(project_root=project_root, input_dir=input_dir, run_id="run_internal_voltage", project_name="Test Project")
    ingestion_result = {"run_id": context.run_id, "status": "ARTIFACTS_INGESTED", "artifacts": [{"artifact_id": "artifact_001", "file_name": notes_path.name, "file_path": str(notes_path), "classification": "equipment_schedule"}]}
    result = run_service(context=context, ingestion_result=ingestion_result, document_parser_result=None, layout_analysis_result=None, ocr_result=None)
    poi_mapped_entities = [entity for entity in result["entities"] if entity.get("attributes", {}).get("parameter_path") == "facility.poi_voltage_kv"]
    assert not poi_mapped_entities


def test_extraction_service_maps_phase_specific_mw_without_promoting_buildout_total(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)
    schedule_path = input_dir / "load_schedule.txt"
    schedule_path.write_text("Phase 1 demand is 60 MW. Phase 2 demand is 120 MW. Full build out demand is 180 MW.", encoding="utf-8")
    context = _build_context(project_root=project_root, input_dir=input_dir, run_id="run_phase_mw", project_name="Test Project")
    ingestion_result = {"run_id": context.run_id, "status": "ARTIFACTS_INGESTED", "artifacts": [{"artifact_id": "artifact_001", "file_name": schedule_path.name, "file_path": str(schedule_path), "classification": "load_schedule"}]}
    result = run_service(context=context, ingestion_result=ingestion_result, document_parser_result=None, layout_analysis_result=None, ocr_result=None)
    mapped_mw = {(entity.get("attributes", {}).get("parameter_path"), entity.get("attributes", {}).get("normalized_value")) for entity in result["entities"] if entity.get("type") == "mw_value"}
    assert ("facility.load_schedule.phase_1_mw", 60.0) in mapped_mw
    assert ("facility.load_schedule.phase_2_mw", 120.0) in mapped_mw
    assert (None, None) in mapped_mw



def test_extraction_service_relevance_plan_carries_document_role_contract(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    input_dir = project_root / "sample_data"
    input_dir.mkdir(parents=True, exist_ok=True)

    schedule_path = input_dir / "switchgear_schedule.txt"
    schedule_path.write_text(
        "switchgear schedule bus rating 4000 amps interrupting rating 65 kA",
        encoding="utf-8",
    )

    context = _build_context(
        project_root=project_root,
        input_dir=input_dir,
        run_id="run_role_plan",
        project_name="Test Project",
    )

    ingestion_result = {
        "run_id": context.run_id,
        "status": "ARTIFACTS_INGESTED",
        "artifacts": [
            {
                "artifact_id": "artifact_schedule",
                "file_name": schedule_path.name,
                "file_path": str(schedule_path),
                "classification": "equipment_schedule",
            }
        ],
    }

    result = run_service(
        context=context,
        ingestion_result=ingestion_result,
        document_parser_result=None,
        layout_analysis_result=None,
        ocr_result=None,
    )

    assert result["relevance_plan"]
    plan = result["relevance_plan"][0]
    assert plan["document_role"] == "equipment_schedule"
    assert plan["document_family"] == "schedule"
    assert "table_worker" in plan["worker_bias"]
