from __future__ import annotations

from collections import defaultdict
from typing import Any

from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent
from services.extraction_service.models import ExtractionCandidate

EXTRACTION_REVIEW_CONFIDENCE_THRESHOLD = 0.60
MAX_REVIEWED_FIELDS_PER_ARTIFACT_SCOPE = 8
MAX_CANDIDATES_PER_REVIEWED_FIELD = 8
PROJECT_PRIMARY_METHOD_PREFIXES = ("project_primary.", "table_schedule_extraction")


class ExtractionReviewCoordinator:
    def apply_review(
        self,
        *,
        context: Any | None,
        artifacts: list[dict[str, Any]],
        extraction_candidates: list[ExtractionCandidate],
    ) -> list[ExtractionCandidate]:
        if not self._can_run_agent(context):
            return extraction_candidates
        grouped: dict[str, list[ExtractionCandidate]] = defaultdict(list)
        for candidate in extraction_candidates:
            field_path = candidate.field_path.strip()
            if field_path:
                grouped[field_path].append(candidate)
        reviewed_field_count = 0
        for field_path, candidates in grouped.items():
            if not self._should_review_candidates(field_path, candidates):
                self._mark_best_deterministic_candidate(candidates)
                continue
            if reviewed_field_count >= MAX_REVIEWED_FIELDS_PER_ARTIFACT_SCOPE:
                self._mark_best_deterministic_candidate(candidates)
                continue
            reviewed_field_count += 1
            candidates = self._bounded_review_candidates(candidates)
            artifact_ids = sorted(
                {
                    candidate.source_artifact_id.strip()
                    for candidate in candidates
                    if isinstance(candidate.source_artifact_id, str) and candidate.source_artifact_id.strip()
                }
            )
            scoped_artifacts = [
                artifact
                for artifact in artifacts
                if isinstance(artifact, dict) and str(artifact.get("artifact_id", "")).strip() in artifact_ids
            ]
            agent_result = run_agent(
                context=context,
                request=AgentRequest(
                    agent_id="extraction_review_agent",
                    stage_name="extraction",
                    task_name="entity_review",
                    inputs={
                        "extraction_review_packet_version": "artifact_scope_compact_v1",
                        "field_path": field_path,
                        "artifact_summaries": [self._summarize_artifact(artifact) for artifact in scoped_artifacts],
                        "candidate_values": [self._summarize_candidate(candidate) for candidate in candidates],
                        "warnings": self._build_review_warnings(candidates),
                        "instruction": (
                            "Review only these compact candidate/source summaries. Do not rely on full artifacts or raw OCR text."
                        ),
                    },
                    metadata={"service": "extraction_service"},
                    trigger_reason="multiple_or_low_confidence_extraction_candidates",
                    associated_field_paths=[field_path],
                    evidence_anchors=[
                        {
                            "anchor_type": "extraction_candidate_artifact",
                            "artifact_id": candidate.source_artifact_id,
                            "field_path": candidate.field_path,
                            "method": candidate.method,
                        }
                        for candidate in candidates
                        if isinstance(candidate.source_artifact_id, str) and candidate.source_artifact_id.strip()
                    ],
                    suggested_output_fields=[
                        "recommended_candidate",
                        "candidate_rankings",
                        "review_flag",
                        "rationale",
                        "confidence",
                    ],
                ),
            )
            structured_output = agent_result.get("structured_output", {})
            if not isinstance(structured_output, dict):
                structured_output = {}
            recommended_candidate = structured_output.get("recommended_candidate")
            review_notes = structured_output.get("review_notes", [])
            agent_policy = agent_result.get("policy", {})
            recommended_index = self._resolve_recommended_index(recommended_candidate=recommended_candidate, candidates=candidates)
            for index, candidate in enumerate(candidates):
                if recommended_index is not None and index == recommended_index:
                    candidate.recommended = True
                candidate.agent_id = str(agent_result.get("agent_id", "")).strip() or "extraction_review_agent"
                candidate.agent_status = str(agent_result.get("status", "")).strip() or None
                candidate.agent_audit_path = str(agent_result.get("audit_path", "")).strip() or None
                candidate.agent_policy = dict(agent_policy) if isinstance(agent_policy, dict) else {}
                if isinstance(review_notes, list):
                    candidate.review_notes.extend(str(item).strip() for item in review_notes if isinstance(item, str) and item.strip())
        return extraction_candidates

    def _can_run_agent(self, context: Any | None) -> bool:
        if context is None:
            return False
        run_id = getattr(context, "run_id", None)
        return isinstance(run_id, str) and bool(run_id.strip())

    def _should_review_candidates(self, field_path: str, candidates: list[ExtractionCandidate]) -> bool:
        if not candidates:
            return False
        ranked = self._rank_candidates(candidates)
        best = ranked[0]
        if self._is_project_primary_candidate(best) and best.confidence >= 0.72:
            return False
        if len(ranked) == 1:
            return ranked[0].confidence < EXTRACTION_REVIEW_CONFIDENCE_THRESHOLD
        second = ranked[1]
        if best.confidence >= 0.80 and (best.confidence - second.confidence) >= 0.12:
            return False
        # Numeric project values from schedules/forms should not burn LLM review just because OEM/manual noise exists.
        if any(token in field_path.lower() for token in ("count", "demand", "date", "voltage", "rating", "mw", "mva", "kw")):
            if self._is_project_primary_candidate(best) and best.confidence >= 0.68:
                return False
        return True

    def _is_project_primary_candidate(self, candidate: ExtractionCandidate) -> bool:
        method = str(candidate.method or "").strip().lower()
        if method.startswith(PROJECT_PRIMARY_METHOD_PREFIXES):
            return True
        evidence = candidate.evidence if isinstance(candidate.evidence, dict) else {}
        metadata = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
        source_family = str(metadata.get("source_family", "")).strip().upper()
        return source_family in {"PROJECT_PRIMARY", "PROJECT_SUPPORTING"}

    def _candidate_rank_key(self, candidate: ExtractionCandidate) -> tuple[int, int, int]:
        method = str(candidate.method or "").strip().lower()
        evidence = candidate.evidence if isinstance(candidate.evidence, dict) else {}
        metadata = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
        source_family = str(metadata.get("source_family", "")).strip().upper()
        source_rank = {"PROJECT_PRIMARY": 5, "PROJECT_SUPPORTING": 4, "PROJECT_DRAWING": 3, "PROJECT_PACKAGE": 2, "OEM_REFERENCE": 1}.get(source_family, 1)
        method_rank = 4 if method.startswith("project_primary") else 3 if "table" in method or "schedule" in method else 2 if "drawing" in method else 1
        return (source_rank, method_rank, int(float(candidate.confidence or 0.0) * 100))

    def _rank_candidates(self, candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
        return sorted(candidates, key=self._candidate_rank_key, reverse=True)

    def _bounded_review_candidates(self, candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
        return self._rank_candidates(candidates)[:MAX_CANDIDATES_PER_REVIEWED_FIELD]

    def _mark_best_deterministic_candidate(self, candidates: list[ExtractionCandidate]) -> None:
        if not candidates:
            return
        best = self._rank_candidates(candidates)[0]
        best.recommended = True

    def _summarize_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        text = str(artifact.get("title") or artifact.get("heading") or artifact.get("text") or artifact.get("parsed_text") or "").strip()
        if len(text) > 220:
            text = text[:217].rstrip() + "..."
        return {
            "artifact_id": str(artifact.get("artifact_id") or artifact.get("id") or "").strip(),
            "filename": str(artifact.get("filename") or artifact.get("file_name") or artifact.get("name") or "").strip()[:160],
            "artifact_type": str(artifact.get("artifact_type") or artifact.get("classification") or "").strip()[:80],
            "page": artifact.get("page") or artifact.get("page_number"),
            "summary_text": text,
        }

    def _summarize_candidate(self, candidate: ExtractionCandidate) -> dict[str, Any]:
        evidence = candidate.evidence if isinstance(candidate.evidence, dict) else {}
        metadata = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
        snippet = ""
        for key in ("evidence_snippet", "snippet", "source_excerpt", "excerpt", "text_excerpt", "context", "raw_text"):
            value = evidence.get(key) or metadata.get(key)
            if value:
                snippet = str(value).strip()
                break
        if len(snippet) > 220:
            snippet = snippet[:217].rstrip() + "..."
        return {
            "field_path": candidate.field_path,
            "value": candidate.value,
            "confidence": candidate.confidence,
            "source_artifact_id": candidate.source_artifact_id,
            "method": candidate.method,
            "source_role": str(metadata.get("source_role") or metadata.get("document_role") or "").strip(),
            "source_location": {
                "page": evidence.get("page") or metadata.get("page") or metadata.get("source_page"),
                "section_table_row_line": str(
                    metadata.get("section") or metadata.get("source_section") or metadata.get("table") or metadata.get("row") or metadata.get("line") or ""
                ).strip()[:160],
            },
            "evidence_snippet": snippet,
        }

    def _build_review_warnings(self, candidates: list[ExtractionCandidate]) -> list[str]:
        warnings: list[str] = []
        if len(candidates) > 1:
            warnings.append("Multiple extraction candidates were produced for the same field path.")
        if any(candidate.confidence < EXTRACTION_REVIEW_CONFIDENCE_THRESHOLD for candidate in candidates):
            warnings.append("At least one extraction candidate is low-confidence.")
        return warnings

    def _resolve_recommended_index(self, *, recommended_candidate: Any, candidates: list[ExtractionCandidate]) -> int | None:
        if isinstance(recommended_candidate, int):
            return recommended_candidate if 0 <= recommended_candidate < len(candidates) else None
        if isinstance(recommended_candidate, dict):
            field_path = str(recommended_candidate.get("field_path", "")).strip()
            method = str(recommended_candidate.get("method", "")).strip()
            source_artifact_id = str(recommended_candidate.get("source_artifact_id", "")).strip()
            value = recommended_candidate.get("value")
            for index, candidate in enumerate(candidates):
                if field_path and candidate.field_path != field_path:
                    continue
                if method and candidate.method != method:
                    continue
                if source_artifact_id and candidate.source_artifact_id != source_artifact_id:
                    continue
                if value is not None and candidate.value != value:
                    continue
                return index
        return None
