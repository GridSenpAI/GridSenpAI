from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_run_quality import audit_run


def test_audit_discovers_current_run_artifact_shapes(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_001"
    exports = run_dir / "exports"
    stages = run_dir / "stages"
    exports.mkdir(parents=True)
    stages.mkdir(parents=True)
    (run_dir / "pipeline_summary.json").write_text(json.dumps({"status": "SUCCESS_PROVISIONAL"}), encoding="utf-8")
    (exports / "run_manifest.json").write_text(
        json.dumps({"status": "EXPORTED_PROVISIONAL", "summary": {"planner_packet_generated": True, "planner_packet_release_state": "DRAFT_BLOCKED", "draft_outputs_allowed": True}}),
        encoding="utf-8",
    )
    (stages / "extraction.json").write_text(
        json.dumps({"ocr_result": {"status": "OCR_FAILED_ALL_DOCUMENTS", "provider_health": {"aggregate_status": "OCR_FAILED_ALL_DOCUMENTS"}, "documents": [{"ocr_status": "OCR_FAILED", "pages": [{"char_count": 0}]}]}}),
        encoding="utf-8",
    )
    (exports / "planner_field_ledger.json").write_text(
        json.dumps([{"field_id": "accepted_peak_demand_mw", "field_path": "peak_demand_mw", "accepted_value": 180.0, "confidence_score": 0.91, "adjudication_trace": {"accepted_value_text": "180.0", "planner_narrative": "Peak demand accepted 180.0 MW."}}]),
        encoding="utf-8",
    )
    (exports / "translated_parameters.json").write_text(
        json.dumps({"status": "TRANSLATED", "output_parameters": [{"parameter_path": "steady_state.p_mw", "value": 180.0}]}),
        encoding="utf-8",
    )

    report = audit_run(run_dir)

    assert report["pipeline_status"] == "SUCCESS_PROVISIONAL"
    assert report["ocr"]["document_result_count"] == 1
    assert report["ledger"]["row_count"] == 1
    assert report["translation"]["steady_state_p_mw"] == 180.0
