from __future__ import annotations

from typing import Any, Dict, List, Optional
import hashlib

from app.config import CONFIG
from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent

from .utils import (
    artifact_is_relevant_for_field,
    artifact_relevance_score,
    build_evidence_payload,
    coerce_drawing_llm_value,
    document_family_for_artifact,
    document_role_for_artifact,
    drawing_candidate_budget_for_field,
    field_family_for_drawing_path,
    get_artifact_text,
    normalize_field_path,
    infer_generator_count,
    infer_internal_voltage_levels,
    infer_poi_voltage_kv,
    infer_substation_configuration,
    infer_transformer_count,
    infer_transformer_ratings,
    infer_ups_count,
    infer_ups_topology,
    is_drawing_artifact,
    rank_candidate_artifacts_for_field,
)


class DrawingInterpretationService:
    """
    Phase 4 drawing interpretation service with bounded document-interpretation support.

    Public contract is preserved:
        extract(self, artifacts, field_paths, context=None) -> List[Dict[str, Any]]
    """

    def __init__(self) -> None:
        self.escalation_decisions: list[dict[str, Any]] = []
        self._agent_attempt_signatures: set[str] = set()

    def _record_escalation_decision(
        self,
        *,
        field_path: str,
        artifact: Dict[str, Any],
        decision: str,
        reason: str,
        deterministic_confidence: float,
        deterministic_value: Optional[Any],
    ) -> None:
        self.escalation_decisions.append(
            {
                "field_path": field_path,
                "artifact_id": artifact.get("artifact_id"),
                "file_name": artifact.get("file_name"),
                "decision": decision,
                "reason": reason,
                "deterministic_confidence": deterministic_confidence,
                "deterministic_value_present": deterministic_value is not None,
            }
        )

    def _build_result(
        self,
        *,
        field_path: str,
        value: Optional[Any],
        confidence: float,
        artifact: Dict[str, Any],
        method: str,
        rationale: str,
    ) -> Dict[str, Any]:
        artifact_id = artifact.get("artifact_id", "unknown_artifact")
        evidence = build_evidence_payload(artifact)
        evidence["document_role"] = document_role_for_artifact(artifact)
        evidence["document_family"] = document_family_for_artifact(artifact)
        result: Dict[str, Any] = {
            "field_path": field_path,
            "value": value,
            "confidence": confidence,
            "source_artifact_id": artifact_id,
            "method": method,
            "evidence": evidence,
            "metadata": {
                "field_family": field_family_for_drawing_path(field_path),
                "document_role": document_role_for_artifact(artifact),
                "document_family": document_family_for_artifact(artifact),
                "artifact_relevance_score": artifact_relevance_score(field_path, artifact, get_artifact_text(artifact)),
            },
            "rationale": rationale,
        }
        return result

    def _llm_enabled(self) -> bool:
        config = getattr(CONFIG, "llm_runtime", None)
        if config is None:
            return False
        return bool(getattr(config, "enabled", False)) and bool(
            str(getattr(config, "model_path", "") or "").strip()
        )

    def _ensure_runtime(self) -> None:
        from services.llm_runtime_service.models import LLMRuntimeConfig
        from services.llm_runtime_service.service import initialize_runtime

        config = CONFIG.llm_runtime
        runtime_config = LLMRuntimeConfig(
            model_path=str(config.model_path),
            model_alias=str(config.model_alias),
            n_ctx=int(config.n_ctx),
            n_threads=int(config.n_threads),
            n_batch=int(config.n_batch),
            n_gpu_layers=int(config.n_gpu_layers),
            temperature=float(config.temperature),
            top_p=float(config.top_p),
            max_tokens=int(config.max_tokens),
        )
        initialize_runtime(runtime_config)

    def _can_run_agent(self, context: Any | None) -> bool:
        if context is None:
            return False

        run_id = getattr(context, "run_id", None)
        return isinstance(run_id, str) and bool(run_id.strip())

    def _coerce_assisted_value(
        self,
        *,
        field_path: str,
        candidate_value: Any,
    ) -> Any:
        coerced_value = coerce_drawing_llm_value(field_path, candidate_value)
        if coerced_value is not None:
            return coerced_value

        if field_path in {
            "facility.substation.configuration",
            "facility.substation_configuration",
            "facility.ups.topology",
            "facility.ups_topology",
        } and isinstance(candidate_value, str):
            normalized = candidate_value.strip()
            if normalized:
                return normalized

        if field_path in {
            "facility.transformers.ratings_mva",
            "facility.transformer_ratings",
        } and isinstance(candidate_value, list):
            numeric_values: list[float] = []
            for item in candidate_value:
                if isinstance(item, (int, float)):
                    numeric_values.append(float(item))
            if numeric_values:
                return numeric_values

        return None

    def _legacy_llm_extract(
        self,
        *,
        artifact: Dict[str, Any],
        field_path: str,
        text: str,
        deterministic_value: Optional[Any],
        deterministic_confidence: float,
        escalation_policy: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[Optional[Any], float, str, str]:
        if not self._llm_enabled():
            return deterministic_value, deterministic_confidence, "drawing_interpretation", ""

        should_escalate, reason = self._should_escalate_to_llm(
            artifact=artifact,
            field_path=field_path,
            text=text,
            deterministic_value=deterministic_value,
            deterministic_confidence=deterministic_confidence,
            escalation_policy=escalation_policy,
            context=None,
        )
        if not should_escalate:
            self._record_escalation_decision(
                field_path=field_path,
                artifact=artifact,
                decision="SKIPPED",
                reason=reason,
                deterministic_confidence=deterministic_confidence,
                deterministic_value=deterministic_value,
            )
            method = "drawing_interpretation" if deterministic_value is not None else "drawing_interpretation_deferred"
            return deterministic_value, deterministic_confidence, method, reason
        self._record_escalation_decision(
            field_path=field_path,
            artifact=artifact,
            decision="ESCALATED",
            reason=reason,
            deterministic_confidence=deterministic_confidence,
            deterministic_value=deterministic_value,
        )

        try:
            from services.llm_runtime_service.models import LLMTaskRequest
            from services.llm_runtime_service.service import run_llm_task

            self._ensure_runtime()
            request = LLMTaskRequest(
                task_name="drawing_interpretation",
                prompt_template_id="phase4.drawing_interpretation.v1",
                system_prompt=(
                    "You are a bounded engineering drawing extraction worker. "
                    "Return only valid JSON. Infer a value only if supported by the drawing text."
                ),
                user_prompt=(
                    f"Field path: {field_path}\n"
                    f"Deterministic value: {deterministic_value!r}\n"
                    f"Deterministic confidence: {deterministic_confidence}\n"
                    f"Drawing text:\n{text[:1800]}\n\n"
                    "Return JSON with keys value and rationale."
                ),
                response_schema={
                    "type": "object",
                    "properties": {
                        "value": {},
                        "rationale": {"type": "string"},
                    },
                    "required": ["value"],
                },
                json_mode=True,
                metadata={
                    "service": "drawing_interpretation_service",
                    "artifact_id": artifact.get("artifact_id"),
                    "field_path": field_path,
                },
            )
            runtime_result = run_llm_task(
                run_id=str(artifact.get("artifact_id", "drawing_interpretation")),
                request=request,
            )
        except Exception:
            return deterministic_value, deterministic_confidence, "drawing_interpretation", ""

        payload = runtime_result.parsed_json if isinstance(runtime_result.parsed_json, dict) else {}
        candidate_value = payload.get("value")
        coerced_value = self._coerce_assisted_value(
            field_path=field_path,
            candidate_value=candidate_value,
        )
        if coerced_value is None:
            return deterministic_value, deterministic_confidence, "drawing_interpretation", ""

        rationale = str(payload.get("rationale", "")).strip()
        return coerced_value, max(deterministic_confidence, 0.74), "drawing_interpretation_llm", rationale

    def _global_agent_attempt_signatures(self, context: Any | None) -> set[str]:
        if context is None:
            return self._agent_attempt_signatures
        cache = getattr(context, "_gridsenpai_drawing_agent_attempt_signatures", None)
        if not isinstance(cache, set):
            cache = set()
            try:
                setattr(context, "_gridsenpai_drawing_agent_attempt_signatures", cache)
            except Exception:
                return self._agent_attempt_signatures
        return cache

    def _is_scalar_or_inventory_field(self, field_path: str) -> bool:
        normalized = normalize_field_path(field_path).lower()
        return (
            normalized.endswith(".count")
            or normalized in {
                "facility.poi_voltage_kv",
                "facility.electrical_configuration.internal_voltage_levels",
                "facility.transformers.ratings_mva",
            }
        )

    def _should_escalate_to_llm(
        self,
        *,
        artifact: Dict[str, Any],
        field_path: str,
        text: str,
        deterministic_value: Optional[Any],
        deterministic_confidence: float,
        escalation_policy: Optional[Dict[str, Dict[str, Any]]] = None,
        context: Any | None = None,
    ) -> tuple[bool, str]:
        """Return whether drawing LLM interpretation is justified for this field/artifact."""
        normalized_field = field_path.strip()
        text = text.strip()
        if not text:
            return False, "no drawing text available"

        policy = (escalation_policy or {}).get(normalized_field, {})
        if policy.get("evidence_sufficient") is True:
            return False, str(policy.get("reason") or "project-primary evidence is sufficient")

        if deterministic_value is not None and deterministic_confidence >= 0.70:
            return False, "deterministic drawing extraction is already sufficient"

        if self._is_scalar_or_inventory_field(normalized_field):
            return False, "drawing LLM escalation is disabled for scalar/count/rating fields; use deterministic project evidence, retrieval, or applicant interview"

        relevance = artifact_relevance_score(field_path, artifact, text)
        if relevance < 0.58:
            return False, "artifact lacked field-relevant signal"

        field_family = field_family_for_drawing_path(field_path)
        normalized_lower = normalized_field.lower()
        if field_family == "equipment_count" or any(token in normalized_lower for token in (".count", "_count")):
            lowered_text = text.lower()
            quantity_context = any(
                token in lowered_text
                for token in (
                    "qty",
                    "quantity",
                    "count",
                    "schedule",
                    "equipment list",
                    "one-line count",
                    "total ups",
                    "total generators",
                    "total transformers",
                )
            )
            explicit_label_context = any(
                token in text.upper()
                for token in ("UPS-", "GEN-", "TX-", "XFMR-", "TRANSFORMER-")
            )
            if deterministic_value is None and not quantity_context and not explicit_label_context:
                return False, "unresolved count lacks explicit quantity/label context; defer to project evidence or interview"
            if relevance < 8.0 and deterministic_value is None:
                return False, "count evidence is too weak for LLM escalation"

        signature_material = f"{artifact.get('artifact_id')}|{normalized_field}|{text[:1200]}"
        signature = hashlib.sha256(signature_material.encode("utf-8", errors="ignore")).hexdigest()
        global_cache = self._global_agent_attempt_signatures(context)
        if signature in self._agent_attempt_signatures or signature in global_cache:
            return False, "duplicate drawing interpretation request suppressed for this run"
        self._agent_attempt_signatures.add(signature)
        global_cache.add(signature)

        return True, "field remains unresolved or materially uncertain after deterministic checks"

    def _agent_extract(
        self,
        *,
        artifact: Dict[str, Any],
        field_path: str,
        text: str,
        deterministic_value: Optional[Any],
        deterministic_confidence: float,
        context: Any,
        escalation_policy: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[Optional[Any], float, str, str]:
        should_escalate, reason = self._should_escalate_to_llm(
            artifact=artifact,
            field_path=field_path,
            text=text,
            deterministic_value=deterministic_value,
            deterministic_confidence=deterministic_confidence,
            escalation_policy=escalation_policy,
            context=context,
        )
        if not should_escalate:
            self._record_escalation_decision(
                field_path=field_path,
                artifact=artifact,
                decision="SKIPPED",
                reason=reason,
                deterministic_confidence=deterministic_confidence,
                deterministic_value=deterministic_value,
            )
            method = "drawing_interpretation" if deterministic_value is not None else "drawing_interpretation_deferred"
            return deterministic_value, deterministic_confidence, method, reason
        self._record_escalation_decision(
            field_path=field_path,
            artifact=artifact,
            decision="ESCALATED",
            reason=reason,
            deterministic_confidence=deterministic_confidence,
            deterministic_value=deterministic_value,
        )
        if len(text) > 1800:
            text = text[:1800]

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="document_interpretation_agent",
                stage_name="extraction",
                task_name="document_interpretation",
                inputs={
                    "region_id": str(artifact.get("artifact_id", "drawing_region")).strip() or "drawing_region",
                    "artifact_kind": str(artifact.get("artifact_type", artifact.get("classification", "electrical_drawing"))).strip() or "electrical_drawing",
                    "page_number": artifact.get("page"),
                    "raw_text": text,
                    "field_path": field_path,
                    "deterministic_value": deterministic_value,
                    "deterministic_confidence": deterministic_confidence,
                    "source_anchor": build_evidence_payload(artifact),
                },
                metadata={
                    "service": "drawing_interpretation_service",
                    "artifact_id": artifact.get("artifact_id"),
                },
                trigger_reason="drawing_field_low_confidence_or_unresolved",
                associated_field_paths=[field_path],
                evidence_anchors=[
                    {
                        "anchor_type": "drawing_artifact",
                        "artifact_id": str(artifact.get("artifact_id", "")).strip(),
                        "page": artifact.get("page"),
                        "file_name": artifact.get("file_name"),
                    }
                ],
                suggested_output_fields=[
                    "candidate_text",
                    "candidate_label",
                    "candidate_value",
                    "candidate_interpretations",
                    "interpretation_notes",
                    "source_anchor",
                    "rationale",
                    "confidence",
                ],
            ),
        )

        structured_output = result.get("structured_output", {})
        if not isinstance(structured_output, dict):
            structured_output = {}

        candidate_value = structured_output.get("candidate_value")
        if candidate_value in {"", None}:
            candidate_value = structured_output.get("candidate_text")

        coerced_value = self._coerce_assisted_value(
            field_path=field_path,
            candidate_value=candidate_value,
        )
        if coerced_value is None:
            return deterministic_value, deterministic_confidence, "drawing_interpretation", ""

        rationale = str(structured_output.get("rationale", "")).strip()
        if not rationale:
            rationale = "Low-confidence drawing interpretation was assisted by the OCR ambiguity agent."

        return coerced_value, max(deterministic_confidence, 0.74), "drawing_interpretation_agent", rationale

    def _maybe_assisted_extract(
        self,
        *,
        artifact: Dict[str, Any],
        field_path: str,
        text: str,
        deterministic_value: Optional[Any],
        deterministic_confidence: float,
        context: Any | None,
        escalation_policy: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[Optional[Any], float, str, str]:
        if self._can_run_agent(context):
            try:
                return self._agent_extract(
                    artifact=artifact,
                    field_path=field_path,
                    text=text,
                    deterministic_value=deterministic_value,
                    deterministic_confidence=deterministic_confidence,
                    context=context,
                    escalation_policy=escalation_policy,
                )
            except Exception:
                return self._legacy_llm_extract(
                    artifact=artifact,
                    field_path=field_path,
                    text=text,
                    deterministic_value=deterministic_value,
                    deterministic_confidence=deterministic_confidence,
                    escalation_policy=escalation_policy,
                )

        return self._legacy_llm_extract(
            artifact=artifact,
            field_path=field_path,
            text=text,
            deterministic_value=deterministic_value,
            deterministic_confidence=deterministic_confidence,
            escalation_policy=escalation_policy,
        )

    def _deterministic_extract_for_field(
        self,
        *,
        field_path: str,
        text: str,
    ) -> tuple[Optional[Any], float, str]:
        value: Optional[Any] = None
        confidence = 0.0
        rationale = "No drawing evidence matched the requested field."

        if field_path in {"facility.poi_voltage_kv"}:
            value = infer_poi_voltage_kv(text)
            confidence = 0.78 if value is not None else 0.0
            rationale = (
                "POI voltage inferred from drawing text voltage context."
                if value is not None
                else rationale
            )
        elif field_path in {"facility.electrical_configuration.internal_voltage_levels"}:
            levels = infer_internal_voltage_levels(text)
            value = levels if levels else None
            confidence = 0.68 if value is not None else 0.0
            rationale = (
                "Internal voltage levels inferred from drawing text voltage labels."
                if value is not None
                else rationale
            )
        elif field_path in {"facility.transformers.count", "facility.transformer_count"}:
            value = infer_transformer_count(text)
            confidence = 0.80 if value is not None else 0.0
            rationale = (
                "Transformer count inferred from drawing label heuristics."
                if value is not None
                else rationale
            )
        elif field_path in {"facility.generators.count", "facility.generator_count"}:
            value = infer_generator_count(text)
            confidence = 0.80 if value is not None else 0.0
            rationale = (
                "Generator count inferred from drawing label heuristics."
                if value is not None
                else rationale
            )
        elif field_path in {"facility.ups.count", "facility.ups_count"}:
            value = infer_ups_count(text)
            confidence = 0.80 if value is not None else 0.0
            rationale = (
                "UPS count inferred from drawing label heuristics."
                if value is not None
                else rationale
            )
        elif field_path in {
            "facility.substation.configuration",
            "facility.substation_configuration",
        }:
            value = infer_substation_configuration(text)
            confidence = 0.70 if value is not None else 0.0
            rationale = (
                "Substation configuration inferred from drawing text patterns."
                if value is not None
                else rationale
            )
        elif field_path in {
            "facility.transformers.ratings_mva",
            "facility.transformer_ratings",
        }:
            ratings = infer_transformer_ratings(text)
            value = ratings if ratings else None
            confidence = 0.65 if value is not None else 0.0
            rationale = (
                "Transformer ratings inferred from drawing text MVA patterns."
                if value is not None
                else rationale
            )
        elif field_path in {
            "facility.ups.topology",
            "facility.ups_topology",
        }:
            value = infer_ups_topology(text)
            confidence = 0.65 if value is not None else 0.0
            rationale = (
                "UPS topology inferred from drawing text topology patterns."
                if value is not None
                else rationale
            )

        return value, confidence, rationale

    def extract(
        self,
        artifacts: List[Dict[str, Any]],
        field_paths: List[str],
        context: Any | None = None,
        escalation_policy: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        drawing_artifacts = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, dict) and is_drawing_artifact(artifact)
        ]

        for field_path in field_paths:
            candidate_artifacts = rank_candidate_artifacts_for_field(drawing_artifacts, field_path)
            candidate_budget = drawing_candidate_budget_for_field(field_path)

            for artifact in candidate_artifacts[:candidate_budget]:
                text = get_artifact_text(artifact)
                if not artifact_is_relevant_for_field(field_path, artifact, text):
                    continue

                value, confidence, rationale = self._deterministic_extract_for_field(
                    field_path=field_path,
                    text=text,
                )
                method = "drawing_interpretation"

                value, confidence, method, assisted_rationale = self._maybe_assisted_extract(
                    artifact=artifact,
                    field_path=field_path,
                    text=text,
                    deterministic_value=value,
                    deterministic_confidence=confidence,
                    context=context,
                    escalation_policy=escalation_policy,
                )
                if assisted_rationale:
                    rationale = assisted_rationale

                results.append(
                    self._build_result(
                        field_path=field_path,
                        value=value,
                        confidence=confidence,
                        artifact=artifact,
                        method=method,
                        rationale=rationale,
                    )
                )

        return results
