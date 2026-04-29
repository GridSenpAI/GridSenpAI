from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.config import CONFIG
from services.agent_runtime_service.models import AgentRequest
from services.agent_runtime_service.service import run_agent


@dataclass(slots=True)
class _TestConfig:
    schema_version_output: str = "1.0.0"


@dataclass(slots=True)
class _TestContext:
    run_id: str
    run_dir: Path
    config: _TestConfig = field(default_factory=_TestConfig)


def test_agent_runtime_without_model_assistance_uses_bounded_local_and_writes_audit(tmp_path: Path) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = False

    try:
        context = _TestContext(
            run_id="agent_runtime_disabled_test",
            run_dir=tmp_path / "agent_runtime_disabled_test",
        )

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="retrieval_planning_agent",
                stage_name="retrieval",
                task_name="query_review",
                inputs={
                    "queries": [],
                    "snippets": [],
                    "warnings": [],
                },
            ),
        )

        assert result["status"] == "COMPLETED"
        assert result["policy"]["allowed"] is True
        assert result["policy"]["provider_mode"] == "bounded_local"
        assert result["structured_output"]["deterministic_override_allowed"] is False
        assert result["runtime_payload"] == {}

        audit_path = Path(result["audit_path"])
        assert audit_path.exists()

        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        assert payload["agent_id"] == "retrieval_planning_agent"
        assert payload["stage_name"] == "retrieval"
        assert payload["task_name"] == "query_review"
        assert payload["status"] == "COMPLETED"
        assert payload["provider_mode"] == "bounded_local"
    finally:
        CONFIG.model.allow_model_assistance = original_flag


def test_retrieval_planning_agent_returns_canonical_knowledge_family_route(tmp_path: Path) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = _TestContext(
            run_id="retrieval_planning_agent_test",
            run_dir=tmp_path / "retrieval_planning_agent_test",
        )

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="retrieval_planning_agent",
                stage_name="retrieval",
                task_name="query_review",
                inputs={
                    "queries": ["ups topology"],
                    "snippets": [],
                    "warnings": ["no vendor snippets found"],
                    "normalized_input": {"facility": {}},
                    "validation_report": {
                        "missing_fields": [
                            "facility.ups.topology",
                            "facility.load_schedule.phase_1_mw",
                        ]
                    },
                },
            ),
        )

        assert result["status"] == "COMPLETED"
        assert result["policy"]["allowed"] is True
        assert result["structured_output"]["deterministic_override_allowed"] is False
        assert result["structured_output"]["agent_role"] == "retrieval_planning"
        assert result["structured_output"]["evidence_gap_flag"] is True

        routed_families = result["structured_output"]["knowledge_family_route"]
        assert "equipment_catalog" in routed_families
        assert "vendor_documents" in routed_families
        assert "modeling_references" in routed_families
        assert "canonical_state" not in result["structured_output"]
    finally:
        CONFIG.model.allow_model_assistance = original_flag


def test_translation_support_agent_preserves_bounded_behavior(tmp_path: Path) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = _TestContext(
            run_id="translation_support_agent_test",
            run_dir=tmp_path / "translation_support_agent_test",
        )

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="translation_support_agent",
                stage_name="translation",
                task_name="parameter_review",
                inputs={
                    "output_parameters": [
                        {
                            "parameter_path": "steady_state.p_mw",
                            "confidence_tag": "LOW",
                            "provenance_type": "assumption",
                            "confidence_factors": {"missing_dependency": True},
                        }
                    ],
                    "assumptions": [{"assumption_id": "assumption_001"}],
                },
            ),
        )

        assert result["status"] == "COMPLETED"
        assert result["structured_output"]["deterministic_override_allowed"] is False
        assert result["structured_output"]["low_confidence_parameters"] == ["steady_state.p_mw"]
        assert result["structured_output"]["assumption_backed_parameters"] == ["steady_state.p_mw"]
        assert result["structured_output"]["missing_dependency_parameters"] == ["steady_state.p_mw"]
    finally:
        CONFIG.model.allow_model_assistance = original_flag



def test_adjudication_support_agent_surfaces_conflicts_and_interview_targets(tmp_path: Path) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = _TestContext(
            run_id="adjudication_support_agent_test",
            run_dir=tmp_path / "adjudication_support_agent_test",
        )

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="adjudication_support_agent",
                stage_name="canonical_state",
                task_name="field_resolution_review",
                inputs={
                    "field_resolution_summary": {
                        "resolved_count": 10,
                        "planner_review_count": 2,
                        "conflicting_count": 1,
                        "missing_count": 1,
                    },
                    "backlog": [
                        {
                            "field_id": "generator_rated_kw",
                            "field_path": "facility.generators.rated_kw",
                            "label": "Generator Rated kW",
                            "accepted_status": "review_required",
                            "needs_applicant_confirmation": True,
                            "planner_attention_tier": "HIGH",
                            "confidence_band": "MODERATE",
                        }
                    ],
                    "planner_review_queue": [
                        {
                            "field_id": "ups_topology",
                            "field_path": "facility.ups.topology",
                            "label": "UPS Topology",
                            "accepted_status": "review_required",
                        }
                    ],
                    "high_materiality_conflicts": [
                        {
                            "field_id": "poi_voltage_kv",
                            "field_path": "facility.poi_voltage_kv",
                            "label": "POI Voltage",
                            "accepted_status": "conflicting",
                            "unresolved_reason": "Conflicting direct and inferred values.",
                        }
                    ],
                },
            ),
        )

        assert result["status"] == "COMPLETED"
        assert result["structured_output"]["deterministic_override_allowed"] is False
        assert result["structured_output"]["agent_role"] == "adjudication_support"
        assert result["structured_output"]["priority_conflicts"][0]["field_path"] == "facility.poi_voltage_kv"
        assert "facility.generators.rated_kw" in result["structured_output"]["recommended_interview_targets"]
    finally:
        CONFIG.model.allow_model_assistance = original_flag


def test_packet_review_agent_produces_trust_summary(tmp_path: Path) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = _TestContext(
            run_id="packet_review_agent_test",
            run_dir=tmp_path / "packet_review_agent_test",
        )

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="packet_review_agent",
                stage_name="export",
                task_name="planner_packet_review",
                inputs={
                    "planner_packet_excerpt": "# GridSenpAI Planner Packet\n\n## Summary\n- Planner review flags: 2",
                    "field_resolution_summary": {
                        "planner_review_count": 2,
                        "high_materiality_conflict_count": 1,
                        "applicant_confirmation_needed_count": 1,
                        "missing_count": 1,
                        "conflicting_count": 1,
                    },
                    "translation_support": {
                        "review_notes": ["Planner review is recommended for low-confidence parameters."]
                    },
                },
            ),
        )

        assert result["status"] == "COMPLETED"
        assert result["structured_output"]["deterministic_override_allowed"] is False
        assert result["structured_output"]["agent_role"] == "packet_review"
        assert result["structured_output"]["packet_readiness"] == "READY_WITH_WARNINGS"
        assert result["structured_output"]["trust_summary"]
    finally:
        CONFIG.model.allow_model_assistance = original_flag




def test_legacy_retrieval_planning_runtime_schema_preserves_query_plan_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_enabled = CONFIG.llm_runtime.enabled
    original_model_path = CONFIG.llm_runtime.model_path
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.llm_runtime.enabled = True
    CONFIG.llm_runtime.model_path = "models/test.gguf"
    CONFIG.model.allow_model_assistance = True

    captured: dict[str, object] = {}

    class _Result:
        def to_dict(self) -> dict[str, object]:
            return {"parsed_json": {"agent_role": "retrieval_planning", "query_plan": {"next": "vendor_pdf"}, "suggested_query_topics": ["ups topology"], "lookup_constraints": {"official_only": True}, "web_lookup_required": True}}

    def _fake_run_llm_task(*, run_id: str, request, context):
        captured["schema"] = request.response_schema
        return _Result()

    monkeypatch.setattr("services.agent_runtime_service.service.run_llm_task", _fake_run_llm_task)

    try:
        context = _TestContext(run_id="legacy_retrieval_runtime_schema", run_dir=tmp_path / "legacy_retrieval_runtime_schema")
        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="retrieval_planning_agent",
                stage_name="retrieval",
                task_name="query_review",
                inputs={"queries": ["ups topology"]},
            ),
        )

        schema = captured["schema"]
        assert isinstance(schema, dict)
        props = schema["properties"]
        assert "query_plan" in props
        assert "suggested_query_topics" in props
        assert "lookup_constraints" in props
        assert "web_lookup_required" in props
        assert result["agent_family_id"] == "evidence_resolution_agent"
        assert result["requested_agent_id"] == "retrieval_planning_agent"
        assert result["structured_output"]["query_plan"]["next"] == "vendor_pdf"
    finally:
        CONFIG.llm_runtime.enabled = original_enabled
        CONFIG.llm_runtime.model_path = original_model_path
        CONFIG.model.allow_model_assistance = original_flag


def test_legacy_packet_review_runtime_schema_preserves_packet_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_enabled = CONFIG.llm_runtime.enabled
    original_model_path = CONFIG.llm_runtime.model_path
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.llm_runtime.enabled = True
    CONFIG.llm_runtime.model_path = "models/test.gguf"
    CONFIG.model.allow_model_assistance = True

    captured: dict[str, object] = {}

    class _Result:
        def to_dict(self) -> dict[str, object]:
            return {"parsed_json": {"agent_role": "packet_review", "packet_review_notes": ["keep review tags"], "trust_summary": "Warnings remain.", "packet_readiness": "READY_WITH_WARNINGS"}}

    def _fake_run_llm_task(*, run_id: str, request, context):
        captured["schema"] = request.response_schema
        return _Result()

    monkeypatch.setattr("services.agent_runtime_service.service.run_llm_task", _fake_run_llm_task)

    try:
        context = _TestContext(run_id="legacy_packet_runtime_schema", run_dir=tmp_path / "legacy_packet_runtime_schema")
        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="packet_review_agent",
                stage_name="export",
                task_name="planner_packet_review",
                inputs={"planner_packet_excerpt": "summary"},
            ),
        )

        schema = captured["schema"]
        assert isinstance(schema, dict)
        props = schema["properties"]
        assert "packet_review_notes" in props
        assert "trust_summary" in props
        assert "packet_readiness" in props
        assert result["agent_family_id"] == "planner_support_agent"
        assert result["requested_agent_id"] == "packet_review_agent"
        assert result["structured_output"]["packet_readiness"] == "READY_WITH_WARNINGS"
    finally:
        CONFIG.llm_runtime.enabled = original_enabled
        CONFIG.llm_runtime.model_path = original_model_path
        CONFIG.model.allow_model_assistance = original_flag


def test_document_interpretation_agent_produces_candidate_interpretations(tmp_path: Path) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = _TestContext(
            run_id="document_interpretation_agent_test",
            run_dir=tmp_path / "document_interpretation_agent_test",
        )

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="document_interpretation_agent",
                stage_name="extraction",
                task_name="document_interpretation",
                inputs={
                    "artifact_kind": "electrical_drawing",
                    "region_id": "region_001",
                    "field_path": "facility.transformers.ratings_mva",
                    "raw_text": "Main service includes a 25 MVA transformer and backup 12.5 MVA transformer.",
                    "source_anchor": {"artifact_id": "artifact_001"},
                },
            ),
        )

        assert result["status"] == "COMPLETED"
        assert result["structured_output"]["agent_role"] == "document_interpretation"
        assert result["structured_output"]["candidate_interpretations"]
    finally:
        CONFIG.model.allow_model_assistance = original_flag


def test_evidence_resolution_agent_returns_library_first_routes(tmp_path: Path) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = _TestContext(
            run_id="evidence_resolution_agent_test",
            run_dir=tmp_path / "evidence_resolution_agent_test",
        )

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="evidence_resolution_agent",
                stage_name="retrieval",
                task_name="evidence_resolution",
                inputs={
                    "validation_report": {"missing_fields": ["facility.generators.rated_kw"]},
                    "equipment_reference_resolution": {
                        "unresolved_missing_fields": ["facility.generators.rated_kw"],
                        "review_required_fields": ["facility.generators.rated_kw"],
                        "web_lookup_required": True,
                        "web_lookup_plans": [{"field_path": "facility.generators.rated_kw"}],
                    },
                },
            ),
        )

        assert result["status"] == "COMPLETED"
        assert result["structured_output"]["agent_role"] == "evidence_resolution"
        assert result["structured_output"]["evidence_gap_flag"] is True
        assert result["structured_output"]["evidence_findings"][0]["preferred_route"] == "official_source_web"
    finally:
        CONFIG.model.allow_model_assistance = original_flag


def test_adjudication_support_agent_emits_per_field_reasoning_and_runner_up_summary(tmp_path: Path) -> None:
    original_flag = CONFIG.model.allow_model_assistance
    CONFIG.model.allow_model_assistance = True

    try:
        context = _TestContext(
            run_id="adjudication_support_agent_reasoning_test",
            run_dir=tmp_path / "adjudication_support_agent_reasoning_test",
        )

        result = run_agent(
            context=context,
            request=AgentRequest(
                agent_id="adjudication_support_agent",
                stage_name="canonical_state",
                task_name="field_resolution_review",
                inputs={
                    "field_resolution_summary": {
                        "resolved_count": 4,
                        "planner_review_count": 1,
                        "conflicting_count": 1,
                        "missing_count": 0,
                    },
                    "adjudication_targets": [
                        {
                            "field_id": "generator_rated_kw_per_unit",
                            "field_path": "facility.generators.rated_kw_per_unit",
                            "label": "Generator rated kW per unit",
                            "accepted_status": "review_required",
                            "accepted_value": 3125,
                            "accepted_source_hierarchy": "manufacturer_model_specific_spec",
                            "confidence_band": "MODERATE",
                            "decision_basis": "accepted_with_applicant_contradiction",
                            "why_accepted": ["Exact model sheet matched installed unit count."],
                            "alternatives": [{"value": 3000, "source_anchor": "one_line.pdf:p12"}],
                            "contradiction_summary": "Prime versus standby rating conflict remains.",
                            "needs_applicant_confirmation": True,
                            "conflict_materiality": "high",
                            "acceptance_margin": 12.0,
                        }
                    ],
                },
            ),
        )

        assert result["status"] == "COMPLETED"
        structured = result["structured_output"]
        assert structured["agent_role"] == "adjudication_support"
        assert structured["ask_applicant_recommendation"] is True
        assert structured["downgrade_recommendation"] is True
        assert structured["runner_up_summary"]
        assert structured["per_field_adjudication"][0]["field_path"] == "facility.generators.rated_kw_per_unit"
        assert "ranked strongest" in structured["per_field_adjudication"][0]["stronger_candidate_reasoning"]
        assert structured["per_field_adjudication"][0]["ask_applicant_recommendation"] is True
        assert "evidence_route_rationale" in structured["per_field_adjudication"][0]
        assert "source_quality_comparison" in structured["per_field_adjudication"][0]
        assert "specificity_comparison" in structured["per_field_adjudication"][0]
        assert "why_search_path_was_trusted" in structured["per_field_adjudication"][0]
    finally:
        CONFIG.model.allow_model_assistance = original_flag
