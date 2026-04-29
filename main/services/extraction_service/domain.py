from __future__ import annotations

from typing import Any

from services.canonical_state_service.service import merge_extraction_candidates
from services.drawing_interpretation_service.service import DrawingInterpretationService
from services.extraction_service.entity_resolution import EntityResolutionCoordinator
from services.extraction_service.models import (
    EntityObservationRecord,
    ExtractionCandidate,
    ExtractionPipelineInput,
    ExtractionPipelineResult,
    ResolvedEntity,
)
from services.extraction_service.review import ExtractionReviewCoordinator
from services.extraction_service.routing import ExtractionRoute, ExtractionRouter
from services.extraction_service.workers.spec_sheets import SpecSheetExtractionService
from services.extraction_service.workers.table_schedules import TableScheduleExtractionService
from services.retrieval_service.domain import RetrievalDomainCoordinator


class ExtractionDomainCoordinator:
    """Authoritative extraction-domain coordinator for the active runtime path."""

    def __init__(self) -> None:
        self.router = ExtractionRouter()
        self.drawing_worker = DrawingInterpretationService()
        self.table_worker = TableScheduleExtractionService()
        self.spec_worker = SpecSheetExtractionService()
        self.retrieval_worker = RetrievalDomainCoordinator()
        self.entity_resolution = EntityResolutionCoordinator()
        self.review = ExtractionReviewCoordinator()

    def run_orchestrated_extraction(
        self,
        *,
        artifacts: list[dict[str, Any]],
        field_paths: list[str],
        context: Any | None = None,
        escalation_policy: dict[str, dict[str, Any]] | None = None,
    ) -> list[ExtractionCandidate]:
        routed = self.router.route_fields(field_paths)
        extraction_candidates: list[ExtractionCandidate] = []
        for route in routed:
            for result in self._extract_for_route(
                route=route,
                artifacts=artifacts,
                context=context,
                escalation_policy=escalation_policy,
            ):
                extraction_candidates.append(
                    ExtractionCandidate(
                        field_path=str(result.get("field_path", "")).strip(),
                        value=result.get("value"),
                        confidence=self._coerce_confidence(result.get("confidence")),
                        source_artifact_id=str(result.get("source_artifact_id", "")).strip(),
                        method=str(result.get("method", "")).strip(),
                        evidence=self._coerce_evidence(result.get("evidence")),
                        metadata=self._coerce_evidence(result.get("metadata")),
                    )
                )
        return self.review.apply_review(
            context=context,
            artifacts=artifacts,
            extraction_candidates=extraction_candidates,
        )

    def run_pipeline(self, pipeline_input: ExtractionPipelineInput) -> ExtractionPipelineResult:
        canonical_state = self._initialize_canonical_state(pipeline_input.canonical_state)
        extraction_candidates = self.run_orchestrated_extraction(
            artifacts=pipeline_input.artifacts,
            field_paths=pipeline_input.field_paths,
            context=pipeline_input.context,
        )
        updated_canonical_state = merge_extraction_candidates(
            candidates=extraction_candidates,
            canonical_state=canonical_state,
        )
        unresolved_fields = self._derive_unresolved_requested_fields(
            requested_field_paths=pipeline_input.field_paths,
            canonical_state=updated_canonical_state,
        )
        return ExtractionPipelineResult(
            canonical_state=updated_canonical_state,
            extraction_candidates=extraction_candidates,
            unresolved_fields=unresolved_fields,
            interview_questions=[],
        )

    def collect_entity_observations(self, artifacts: list[dict[str, Any]]) -> list[EntityObservationRecord]:
        return self.entity_resolution.collect_entity_observations(artifacts)

    def resolve_entities(self, observations: list[EntityObservationRecord] | list[dict[str, Any]]) -> list[ResolvedEntity]:
        return self.entity_resolution.resolve_entities(observations)

    def _extract_for_route(
        self,
        *,
        route: ExtractionRoute,
        artifacts: list[dict[str, Any]],
        context: Any | None,
        escalation_policy: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        worker = self._resolve_worker(route.worker)
        if worker is None:
            return []
        return self._call_worker_extract(
            worker=worker,
            artifacts=artifacts,
            field_paths=route.normalized_fields,
            context=context,
            escalation_policy=escalation_policy if route.worker == "drawing_worker" else None,
        )

    def _resolve_worker(self, worker_name: str) -> Any | None:
        if worker_name == "drawing_worker":
            return self.drawing_worker
        if worker_name == "table_worker":
            return self.table_worker
        if worker_name == "spec_worker":
            return self.spec_worker
        if worker_name == "retrieval_worker":
            return self.retrieval_worker
        return None

    def _initialize_canonical_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        canonical_state = dict(payload) if isinstance(payload, dict) else {}
        canonical_state.setdefault("field_records", [])
        canonical_state.setdefault("conflict_records", [])
        canonical_state.setdefault("review_flags", [])
        return canonical_state

    def _derive_unresolved_requested_fields(
        self,
        *,
        requested_field_paths: list[str],
        canonical_state: dict[str, Any],
    ) -> list[str]:
        unresolved: list[str] = []
        for field_path in requested_field_paths:
            normalized_path = str(field_path).strip()
            if not normalized_path:
                continue
            state_entry = canonical_state.get(normalized_path)
            if not isinstance(state_entry, dict):
                unresolved.append(normalized_path)
                continue
            value = state_entry.get("value")
            status = str(state_entry.get("status", "")).strip().lower()
            if value is None or (isinstance(value, str) and not value.strip()) or status in {"missing", "unresolved"}:
                unresolved.append(normalized_path)
        return unresolved

    def _call_worker_extract(
        self,
        *,
        worker: Any,
        artifacts: list[dict[str, Any]],
        field_paths: list[str],
        context: Any | None,
        escalation_policy: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            if escalation_policy is not None:
                return worker.extract(
                    artifacts,
                    field_paths,
                    context=context,
                    escalation_policy=escalation_policy,
                )
            return worker.extract(artifacts, field_paths, context=context)
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            return worker.extract(artifacts, field_paths)

    def _coerce_confidence(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            label = str(value or "").strip().upper()
            return {"HIGH": 0.86, "MODERATE": 0.62, "LOW": 0.35}.get(label, 0.0)

    def _coerce_evidence(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return dict(value[0])
        return {}


__all__ = ["ExtractionDomainCoordinator", "ExtractionRoute", "ExtractionRouter"]
