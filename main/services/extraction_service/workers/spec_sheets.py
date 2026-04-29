from __future__ import annotations

from typing import Any, Dict, List

from services.extraction_service.workers.common import (
    coerce_spec_llm_value,
    ensure_runtime,
    get_artifact_text,
    infer_generator_ratings,
    infer_transformer_ratings,
    infer_ups_topology,
    is_spec_artifact,
    llm_enabled,
)


class SpecSheetExtractionService:
    def _maybe_llm_extract(
        self,
        *,
        artifact: Dict[str, Any],
        field_path: str,
        text: str,
        deterministic_value: Any,
        deterministic_confidence: float,
    ) -> tuple[Any, float, str]:
        if not llm_enabled() or (deterministic_value is not None and deterministic_confidence >= 0.72) or not text.strip():
            return deterministic_value, deterministic_confidence, "spec_sheet_extraction"

        try:
            from services.llm_runtime_service.models import LLMTaskRequest
            from services.llm_runtime_service.service import run_llm_task

            ensure_runtime()
            request = LLMTaskRequest(
                task_name="spec_sheet_extraction",
                prompt_template_id="phase4.spec_sheet_extraction.v1",
                system_prompt=(
                    "You are a bounded engineering specification extraction worker. "
                    "Return only valid JSON and do not invent unsupported values."
                ),
                user_prompt=(
                    f"Field path: {field_path}\n"
                    f"Deterministic value: {deterministic_value!r}\n"
                    f"Specification text:\n{text}\n\n"
                    "Return JSON with a single key named value."
                ),
                response_schema={
                    "type": "object",
                    "properties": {"value": {}},
                    "required": ["value"],
                },
                json_mode=True,
                metadata={
                    "service": "extraction_service",
                    "worker": "spec_sheet_extraction",
                    "artifact_id": artifact.get("artifact_id"),
                    "field_path": field_path,
                },
            )
            runtime_result = run_llm_task(
                run_id=str(artifact.get("artifact_id", "spec_sheet_extraction")),
                request=request,
            )
        except Exception:
            return deterministic_value, deterministic_confidence, "spec_sheet_extraction"

        payload = runtime_result.parsed_json if isinstance(runtime_result.parsed_json, dict) else {}
        coerced_value = coerce_spec_llm_value(field_path, payload.get("value"))
        if coerced_value is None:
            return deterministic_value, deterministic_confidence, "spec_sheet_extraction"
        return coerced_value, max(deterministic_confidence, 0.74), "spec_sheet_extraction_llm"

    def extract(self, artifacts: List[Dict[str, Any]], field_paths: List[str], context: Any | None = None) -> List[Dict[str, Any]]:
        del context
        results: List[Dict[str, Any]] = []
        for artifact in artifacts:
            if not is_spec_artifact(artifact):
                continue
            artifact_id = artifact.get("artifact_id", "unknown_artifact")
            text = get_artifact_text(artifact)

            for field_path in field_paths:
                value: Any = None
                confidence = 0.0
                method = "spec_sheet_extraction"

                if field_path in {"facility.transformers.ratings_mva", "facility.transformer_ratings"}:
                    value = infer_transformer_ratings(text)
                    confidence = 0.78 if value is not None else 0.0
                elif field_path in {"facility.generators.ratings", "facility.generator_ratings"}:
                    value = infer_generator_ratings(text)
                    confidence = 0.78 if value is not None else 0.0
                elif field_path in {"facility.ups.topology", "facility.ups_topology"}:
                    value = infer_ups_topology(text)
                    confidence = 0.72 if value is not None else 0.0

                value, confidence, method = self._maybe_llm_extract(
                    artifact=artifact,
                    field_path=field_path,
                    text=text,
                    deterministic_value=value,
                    deterministic_confidence=confidence,
                )
                results.append(
                    {
                        "field_path": field_path,
                        "value": value,
                        "confidence": confidence,
                        "source_artifact_id": artifact_id,
                        "method": method,
                        "evidence": {
                            "page": artifact.get("page"),
                            "section": artifact.get("section"),
                        },
                    }
                )
        return results


__all__ = [
    "SpecSheetExtractionService",
    "coerce_spec_llm_value",
    "get_artifact_text",
    "infer_generator_ratings",
    "infer_transformer_ratings",
    "infer_ups_topology",
    "is_spec_artifact",
]
