from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_working_canonical_state_result(
    *,
    run_id: str,
    extraction_result: dict[str, Any] | None = None,
    normalization_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a governed interim canonical-state payload for gap resolution.

    This is intentionally *not* the final authoritative canonical state. It is the
    working candidate state assembled after extraction/normalization and passed into
    gap-resolution branches such as retrieval and interview.
    """

    extraction_payload = extraction_result or {}
    normalization_payload = normalization_result or {}

    canonical_state = deepcopy(extraction_payload.get("canonical_state", {}))
    if not isinstance(canonical_state, dict):
        canonical_state = {}

    normalized_input = normalization_payload.get("normalized_input", {})
    if isinstance(normalized_input, dict) and normalized_input:
        canonical_state["normalized_input"] = deepcopy(normalized_input)

    validation_report = normalization_payload.get("validation_report", {})
    if isinstance(validation_report, dict) and validation_report:
        canonical_state["validation_report"] = deepcopy(validation_report)

    normalized_field_index = normalization_payload.get("normalized_field_index", {})
    if isinstance(normalized_field_index, dict) and normalized_field_index:
        canonical_state["normalized_field_index"] = deepcopy(normalized_field_index)

    stage_status = canonical_state.get("stage_status", {})
    if not isinstance(stage_status, dict):
        stage_status = {}
    stage_status.setdefault("extraction", str(extraction_payload.get("status", "EXTRACTED")).strip() or "EXTRACTED")
    if normalization_payload:
        stage_status["normalization"] = str(normalization_payload.get("status", "NORMALIZED")).strip() or "NORMALIZED"
    canonical_state["stage_status"] = stage_status

    canonical_state["state_role"] = "WORKING_CANDIDATE_STATE"
    canonical_state["authoritative"] = False

    return {
        "run_id": run_id,
        "status": "WORKING_CANONICAL_STATE_READY",
        "canonical_state": canonical_state,
        "state_role": "WORKING_CANDIDATE_STATE",
        "authoritative": False,
    }


def annotate_final_canonical_state_result(
    canonical_state_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Mark a canonical-state service result as the final authoritative state."""

    if not isinstance(canonical_state_result, dict):
        return canonical_state_result

    payload = canonical_state_result.get("canonical_state")
    if isinstance(payload, dict):
        payload["state_role"] = "FINAL_CANONICAL_STATE"
        payload["authoritative"] = True

    canonical_state_result["state_role"] = "FINAL_CANONICAL_STATE"
    canonical_state_result["authoritative"] = True
    return canonical_state_result
