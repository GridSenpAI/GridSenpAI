from __future__ import annotations

from types import SimpleNamespace

from services.calibration_comparison_service.service import compare_against_datasets, run_service as run_calibration_comparison_service
from services.calibration_dataset_service.service import build_calibration_datasets, run_service as run_calibration_dataset_service


def _context() -> SimpleNamespace:
    return SimpleNamespace(run_id="test_run_phase4")


def test_calibration_dataset_service_normalizes_units_and_returns_summary() -> None:
    canonical_state = {
        "artifacts": [
            {
                "artifact_id": "artifact_001",
                "file_name": "benchmark_reference.pdf",
            }
        ]
    }

    ingestion_result = {
        "calibration_datasets": [
            {
                "dataset_id": "calds_001",
                "dataset_type": "PLANNING_BENCHMARK",
                "version": "1.0.0",
                "source_artifact_id": "artifact_001",
                "parameters": [
                    {
                        "field_path": "facility.load_schedule.phase_1_mw",
                        "value": 75000,
                        "units": "kW",
                        "target_units": "MW",
                        "metadata": {"tolerance_percent": 5},
                    }
                ],
            }
        ]
    }

    datasets = build_calibration_datasets(canonical_state=canonical_state, ingestion_result=ingestion_result)
    service_result = run_calibration_dataset_service(
        context=_context(),
        canonical_state=canonical_state,
        ingestion_result=ingestion_result,
    )

    assert len(datasets) == 1
    assert datasets[0]["parameters"][0]["normalized_value"] == 75.0
    assert datasets[0]["parameters"][0]["units"] == "kW"
    assert datasets[0]["parameters"][0]["target_units"] == "MW"
    assert service_result["status"] == "CALIBRATION_DATASETS_READY"
    assert service_result["summary"]["dataset_count"] == 1


def test_calibration_comparison_creates_lineage_and_reconciliation_records() -> None:
    canonical_state = {
        "field_records": [
            {
                "field_record_id": "fr_001",
                "field_path": "facility.load_schedule.phase_1_mw",
                "value": 75.0,
                "is_primary": True,
                "source_stage": "normalization",
                "source_type": "document",
                "validation_status": "VALIDATED",
                "review_status": "CLOSED",
                "conflict_status": "NO_CONFLICT",
                "evidence_strength": "STRONG",
                "source_artifact_id": "artifact_001",
                "metadata": {"source_method": "spec_sheet"},
            }
        ],
        "assumption_registry": [
            {
                "assumption_id": "assump_001",
                "field_path": "facility.load_schedule.phase_1_mw",
                "status": "ACTIVE",
            }
        ],
    }

    calibration_datasets = [
        {
            "dataset_id": "calds_001",
            "dataset_type": "PLANNING_BENCHMARK",
            "version": "1.0.0",
            "source_artifact_id": "artifact_001",
            "source_file_name": "benchmark_reference.pdf",
            "parameters": [
                {
                    "field_path": "facility.load_schedule.phase_1_mw",
                    "normalized_value": 82.0,
                    "units": "MW",
                    "target_units": "MW",
                    "source_ref": [
                        {
                            "artifact_id": "artifact_001",
                            "page": 4,
                            "snippet_id": "snippet_001",
                            "source_name": "benchmark_reference.pdf",
                        }
                    ],
                    "metadata": {"tolerance_percent": 2.0},
                }
            ],
        }
    ]

    result = compare_against_datasets(
        canonical_state=canonical_state,
        calibration_datasets=calibration_datasets,
        comparison_run_id="test_run_phase4::calibration_compare",
    )

    service_result = run_calibration_comparison_service(
        context=_context(),
        canonical_state=canonical_state,
        calibration_datasets=calibration_datasets,
    )

    assert result["status"] == "CALIBRATION_COMPARISON_COMPLETE"
    assert result["summary"]["dataset_count"] == 1
    assert result["summary"]["calibration_record_count"] == 1
    assert result["summary"]["reconciliation_record_count"] == 1
    assert result["summary"]["change_log_count"] == 1
    assert result["summary"]["conflict_count"] == 1

    calibration_record = result["calibration_records"][0]
    assert calibration_record["comparison_run_id"] == "test_run_phase4::calibration_compare"
    assert calibration_record["status"] == "CALIBRATION_CONFLICT"
    assert calibration_record["linked_field_record_ids"] == ["fr_001"]
    assert calibration_record["linked_assumption_ids"] == ["assump_001"]
    assert calibration_record["lineage"]["primary_record"]["field_record_id"] == "fr_001"

    assert service_result["status"] == "CALIBRATION_COMPARISON_COMPLETE"
    assert service_result["summary"]["conflict_count"] == 1
