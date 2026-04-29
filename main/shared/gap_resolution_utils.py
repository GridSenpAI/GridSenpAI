from __future__ import annotations

from typing import Any


def resolve_gap_resolution_stage_inputs(
    *,
    retrieval_result: dict[str, Any] | None = None,
    interview_result: dict[str, Any] | None = None,
    gap_resolution_result: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve retrieval/interview payloads from the bundled gap-resolution stage.

    The public runtime spine treats retrieval and interview as substages under
    ``gap_resolution``. Downstream services may still accept direct substage
    payloads for compatibility, but should derive them from ``gap_resolution``
    when available.
    """

    if isinstance(gap_resolution_result, dict):
        if retrieval_result is None:
            candidate_retrieval = gap_resolution_result.get("retrieval")
            if isinstance(candidate_retrieval, dict):
                retrieval_result = candidate_retrieval
        if interview_result is None:
            candidate_interview = gap_resolution_result.get("interview")
            if isinstance(candidate_interview, dict):
                interview_result = candidate_interview

    return retrieval_result, interview_result
