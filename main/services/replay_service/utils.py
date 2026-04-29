from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.runtime_stage_contract import (
    GAP_RESOLUTION_RETRIEVAL_STAGE,
    gap_resolution_substage_order,
    public_stage_order,
)


PIPELINE_STAGE_ORDER = public_stage_order()
GAP_RESOLUTION_SUBSTAGE_ORDER = gap_resolution_substage_order()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False, default=str)


def require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def valid_stage_boundaries() -> tuple[str, ...]:
    return tuple([*PIPELINE_STAGE_ORDER, *GAP_RESOLUTION_SUBSTAGE_ORDER])


def validate_stage_boundary(stage_boundary: str) -> str:
    normalized = require_non_empty_string(stage_boundary, "replay_stage_boundary")
    if normalized not in valid_stage_boundaries():
        raise ValueError(
            "replay_stage_boundary must be one of: "
            + ", ".join(valid_stage_boundaries())
            + f". Got: {normalized}"
        )
    return normalized


def compute_reused_and_rerun_stages(stage_boundary: str) -> tuple[list[str], list[str], str]:
    normalized_boundary = validate_stage_boundary(stage_boundary)

    if normalized_boundary in GAP_RESOLUTION_SUBSTAGE_ORDER:
        gap_index = PIPELINE_STAGE_ORDER.index("gap_resolution")
        reused_stages = PIPELINE_STAGE_ORDER[:gap_index]
        rerun_stages = PIPELINE_STAGE_ORDER[gap_index:]
        return reused_stages, rerun_stages, "gap_resolution"

    boundary_index = PIPELINE_STAGE_ORDER.index(normalized_boundary)
    reused_stages = PIPELINE_STAGE_ORDER[: boundary_index + 1]
    rerun_stages = PIPELINE_STAGE_ORDER[boundary_index + 1 :]
    resume_from_stage = rerun_stages[0] if rerun_stages else PIPELINE_STAGE_ORDER[-1]
    return reused_stages, rerun_stages, resume_from_stage


def compute_reused_gap_resolution_substages(stage_boundary: str) -> list[str]:
    normalized_boundary = validate_stage_boundary(stage_boundary)
    if normalized_boundary not in GAP_RESOLUTION_SUBSTAGE_ORDER:
        return []
    boundary_index = GAP_RESOLUTION_SUBSTAGE_ORDER.index(normalized_boundary)
    return GAP_RESOLUTION_SUBSTAGE_ORDER[: boundary_index + 1]


def stage_output_path(run_dir: Path, stage_name: str) -> Path:
    return run_dir / "stages" / f"{stage_name}.json"


def substage_output_path(run_dir: Path, stage_name: str, substage_name: str) -> Path:
    return run_dir / "stages" / f"{stage_name}__{substage_name}.json"


def canonical_state_path(run_dir: Path) -> Path:
    return run_dir / "state" / "canonical_facility_state.json"