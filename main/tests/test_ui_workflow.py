from __future__ import annotations

import json
from pathlib import Path

from app.ui.workflow import (
    apply_ui_llm_runtime_selection,
    build_interview_review_rows,
    build_interview_review_text,
    build_interview_session_path,
    clear_interview_ui_state,
    build_run_completion_snapshot,
    determine_interview_audit_path,
    determine_tldr_path,
    discover_local_gguf_models,
    build_question_display_context,
    extract_interview_overview,
    extract_interview_questions,
    infer_model_alias_from_path,
    load_pending_interview_resume_bundle,
    mark_interview_ui_skipped,
    preview_interview_answer,
    prepare_uploaded_files,
    reset_interview_session,
    save_interview_answers,
    save_interview_ui_state,
)


def test_prepare_uploaded_files_copies_and_cleans_destination(tmp_path: Path) -> None:
    source_a = tmp_path / "one_line.pdf"
    source_b = tmp_path / "load_schedule.docx"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")

    destination = tmp_path / "sample_data" / "current_application"
    destination.mkdir(parents=True, exist_ok=True)
    stale = destination / "stale.txt"
    stale.write_text("old", encoding="utf-8")

    copied = prepare_uploaded_files(destination, [source_a, source_b])

    assert stale.exists() is False
    assert [item.name for item in copied] == ["one_line.pdf", "load_schedule.docx"]
    assert (destination / "one_line.pdf").read_text(encoding="utf-8") == "a"
    assert (destination / "load_schedule.docx").read_text(encoding="utf-8") == "b"


def test_extract_questions_and_save_answers_roundtrip(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_001"
    stages_dir = run_dir / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)

    question_payload = {
        "questions": [
            {
                "question_id": "FACILITY_POI_VOLTAGE_KV",
                "field_path": "facility.poi_voltage_kv",
                "question": "Please confirm the point of interconnection voltage.",
                "answer_type": "number",
                "required": True,
                "allowed_values": [],
                "examples": ["138", "69"],
                "priority": 100,
                "question_category": "retrieval_gap",
            }
        ]
    }
    (stages_dir / "gap_resolution__interview.json").write_text(
        json.dumps(question_payload, indent=2),
        encoding="utf-8",
    )

    questions = extract_interview_questions(run_dir)
    assert len(questions) == 1
    assert questions[0]["field_path"] == "facility.poi_voltage_kv"

    session_path, confirmed, clarifications = save_interview_answers(
        project_root=tmp_path,
        project_name="GridSenpAI",
        questions=questions,
        answers_by_question_id={"FACILITY_POI_VOLTAGE_KV": "138"},
    )

    assert session_path == build_interview_session_path(tmp_path, "GridSenpAI")
    assert len(confirmed) == 1
    assert clarifications == []

    payload = json.loads(session_path.read_text(encoding="utf-8"))
    assert payload["answers_confirmed"][0]["question_id"] == "FACILITY_POI_VOLTAGE_KV"
    assert payload["answers_confirmed"][0]["confirmed_answer"] == 138.0


def test_reset_session_and_determine_tldr_path(tmp_path: Path) -> None:
    session_path = build_interview_session_path(tmp_path, "GridSenpAI")
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text("{}", encoding="utf-8")

    reset_interview_session(tmp_path, "GridSenpAI")
    assert session_path.exists() is False

    run_dir = tmp_path / "runs" / "run_002"
    exports_dir = run_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    tldr_path = exports_dir / "planner_tldr_summary.md"
    tldr_path.write_text("placeholder", encoding="utf-8")
    (exports_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "exports": {
                    "planner_tldr_markdown": str(tldr_path),
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    assert determine_tldr_path(run_dir) == tldr_path


def test_extract_interview_overview_and_question_display_context(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_010"
    stages_dir = run_dir / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)

    question_payload = {
        "questions": [
            {
                "question_id": "FACILITY_POI_VOLTAGE_KV",
                "field_path": "facility.poi_voltage_kv",
                "question": "Please confirm the point of interconnection voltage.",
                "answer_type": "number",
                "priority": 120,
                "question_category": "conflicting",
                "help_text": "The applicant interview agent needs a direct engineering value.",
                "reason": "This field has conflicting evidence and needs applicant confirmation.",
                "suggested_sources": ["one_line.pdf", "interconnection_study.pdf"],
                "agent_id": "applicant_interview_agent",
                "agent_status": "COMPLETED",
                "metadata": {
                    "planner_critical": True,
                    "packet_section_label": "Electrical Configuration",
                    "triage_bucket": "planner_critical_blocking",
                    "triage_reason": "Planner-critical or conflict-driven question that blocks governed release.",
                    "accepted_value": 138.0,
                    "accepted_confidence": 0.62,
                    "confidence_band": "MODERATE",
                    "conflict_materiality": "high",
                    "dominance_profile": {"dominance_level": "contested"},
                    "runner_up_profile": {"source_anchor": "relay_settings.pdf"},
                    "conflict_profile": {"summary_text": "Conflicting values appear in one-line and study report."},
                    "governance_summary": {"planner_review_count": 2, "high_materiality_conflict_count": 1},
                },
            }
        ],
        "session_summary": {
            "planner_critical_blocking_question_count": 1,
            "high_value_clarification_question_count": 0,
            "informational_question_count": 0,
        },
        "interview_oversight": {
            "interview_readiness_summary": {"interview_readiness": "READY"},
            "sufficiency_assessment": "NEEDS_INTERVIEW",
            "rationale": "The interview should focus on unresolved gaps and low-confidence confirmations before final validation and export.",
            "review_notes": ["Interview oversight remains advisory and cannot persist canonical truth."],
            "question_sequence": ["FACILITY_POI_VOLTAGE_KV"],
        },
    }
    (stages_dir / "gap_resolution__interview.json").write_text(json.dumps(question_payload, indent=2), encoding="utf-8")

    overview = extract_interview_overview(run_dir)
    assert overview["readiness"] == "READY"
    assert "ask first 1" in overview["status_line"]
    assert "Agent sequence" in overview["detail_text"]

    context = build_question_display_context(question_payload["questions"][0])
    assert "POI nominal voltage kV" in context["summary_line"]
    assert "Current best value on file: 138" in context["context_text"]
    assert "recorded as applicant confirmation" in context["context_text"]
    assert "applicant_interview_agent" in context["agent_line"]


def test_preview_interview_answer_reports_parsed_value() -> None:
    question = {
        "question_id": "FACILITY_GENERATOR_COUNT",
        "field_path": "facility.generators.count",
        "question": "How many generators are installed?",
        "answer_type": "integer",
    }

    preview = preview_interview_answer(question, "12")
    assert preview["status"] == "CONFIRMED"
    assert "12" in preview["message"]

    bad_preview = preview_interview_answer(question, "twelve generators maybe")
    assert bad_preview["status"] == "CLARIFICATION_REQUIRED"


def test_build_interview_review_text_includes_parsed_values() -> None:
    questions = [
        {
            "question_id": "FACILITY_POI_VOLTAGE_KV",
            "field_path": "facility.poi_voltage_kv",
            "question": "Please confirm the point of interconnection voltage.",
            "answer_type": "number",
        },
        {
            "question_id": "FACILITY_GENERATOR_COUNT",
            "field_path": "facility.generators.count",
            "question": "How many generators are installed?",
            "answer_type": "integer",
        },
    ]
    answers = {
        "FACILITY_POI_VOLTAGE_KV": "138",
        "FACILITY_GENERATOR_COUNT": "12",
    }

    rows = build_interview_review_rows(questions, answers)
    assert rows[0]["parse_status"] == "CONFIRMED"
    assert rows[0]["normalized_value"] == "138"
    assert rows[1]["normalized_value"] == "12"

    review_text = build_interview_review_text(questions, answers)
    assert "Review applicant responses before GridSenpAI continues." in review_text
    assert "POI nominal voltage kV" in review_text
    assert "Parsed value: 138" in review_text
    assert "Parsed value: 12" in review_text


def test_build_run_completion_snapshot_reports_handoff_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_020"
    exports_dir = run_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    tldr_path = exports_dir / "planner_tldr_summary.md"
    tldr_path.write_text("placeholder", encoding="utf-8")
    (exports_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "summary": {
                    "governed_release_state": "READY_WITH_WARNINGS",
                    "planner_packet_readiness": "READY",
                    "field_governance_registry_unresolved_field_count": 2,
                    "planner_registry_review_required_count": 3,
                    "manual_review_queue_count": 4,
                    "planner_action_queue_count": 2,
                    "human_readable_packet_variants": ["pdf"],
                    "tldr_human_readable_variants": ["markdown"],
                },
                "exports": {
                    "planner_tldr_markdown": str(tldr_path),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    snapshot = build_run_completion_snapshot(run_dir, {"status": "EXPORTED"})
    assert "Release state: READY_WITH_WARNINGS" in snapshot["headline"]
    assert "Packet readiness: READY." in snapshot["headline"]
    assert "TLDR summary: ready." in snapshot["detail_text"]
    assert "Manual review queue items: 4." in snapshot["detail_text"]
    assert "Planner packet outputs: pdf" in snapshot["detail_text"]
    assert "TLDR outputs: markdown" in snapshot["detail_text"]
    assert "Open TLDR, Open exports folder, or Open latest manifest" in snapshot["detail_text"]


def test_save_and_resume_pending_interview_ui_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_030"
    stages_dir = run_dir / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)

    questions_payload = {
        "questions": [
            {
                "question_id": "FACILITY_POI_VOLTAGE_KV",
                "field_path": "facility.poi_voltage_kv",
                "question": "Please confirm the point of interconnection voltage.",
                "answer_type": "number",
            },
            {
                "question_id": "FACILITY_GENERATOR_COUNT",
                "field_path": "facility.generators.count",
                "question": "How many generators are installed?",
                "answer_type": "integer",
            },
        ],
        "interview_oversight": {
            "interview_readiness_summary": {"interview_readiness": "READY"},
            "sufficiency_assessment": "NEEDS_INTERVIEW",
        },
    }
    (stages_dir / "gap_resolution__interview.json").write_text(json.dumps(questions_payload, indent=2), encoding="utf-8")

    questions = extract_interview_questions(run_dir)
    save_interview_ui_state(
        project_root=tmp_path,
        project_name="GridSenpAI",
        run_id="run_030",
        questions=questions,
        answers_by_question_id={"FACILITY_POI_VOLTAGE_KV": "138"},
        current_question_index=1,
    )

    bundle = load_pending_interview_resume_bundle(
        project_root=tmp_path,
        project_name="GridSenpAI",
        output_dir=tmp_path / "runs",
    )
    assert bundle["run_id"] == "run_030"
    assert bundle["current_question_index"] == 1
    assert bundle["answer_drafts"]["FACILITY_POI_VOLTAGE_KV"] == "138"
    assert len(bundle["questions"]) == 2


def test_clear_interview_ui_state_prevents_resume(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_031"
    stages_dir = run_dir / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    (stages_dir / "gap_resolution__interview.json").write_text(
        json.dumps({
            "questions": [
                {
                    "question_id": "FACILITY_POI_VOLTAGE_KV",
                    "field_path": "facility.poi_voltage_kv",
                    "question": "Please confirm the point of interconnection voltage.",
                    "answer_type": "number",
                }
            ]
        }, indent=2),
        encoding="utf-8",
    )

    questions = extract_interview_questions(run_dir)
    save_interview_ui_state(
        project_root=tmp_path,
        project_name="GridSenpAI",
        run_id="run_031",
        questions=questions,
        answers_by_question_id={"FACILITY_POI_VOLTAGE_KV": "138"},
        current_question_index=0,
    )
    clear_interview_ui_state(tmp_path, "GridSenpAI")

    bundle = load_pending_interview_resume_bundle(
        project_root=tmp_path,
        project_name="GridSenpAI",
        output_dir=tmp_path / "runs",
    )
    assert bundle == {}


def test_discover_local_gguf_models_and_alias_inference(tmp_path: Path) -> None:
    models_dir = tmp_path / "models" / "granite"
    models_dir.mkdir(parents=True, exist_ok=True)
    granite = models_dir / "ibm-granite-3.1-8b-instruct-Q4_K_M.gguf"
    qwen = tmp_path / "models" / "qwen2.5-7b-instruct-q4_k_m.gguf"
    granite.write_text("g", encoding="utf-8")
    qwen.parent.mkdir(parents=True, exist_ok=True)
    qwen.write_text("q", encoding="utf-8")

    discovered = discover_local_gguf_models(tmp_path)

    assert discovered == [granite, qwen] or discovered == [qwen, granite]
    assert infer_model_alias_from_path(granite) == "granite-local"
    assert infer_model_alias_from_path(qwen) == "local-qwen"


def test_apply_ui_llm_runtime_selection_updates_shared_config(monkeypatch) -> None:
    from app.config import CONFIG

    original = (
        CONFIG.llm_runtime.enabled,
        getattr(CONFIG.llm_runtime, "provider", "llama_cpp"),
        CONFIG.llm_runtime.model_path,
        CONFIG.llm_runtime.model_alias,
        CONFIG.llm_runtime.n_ctx,
        CONFIG.llm_runtime.n_batch,
        CONFIG.model.model_version,
    )

    try:
        apply_ui_llm_runtime_selection(
            runtime_mode="llama_cpp",
            model_path=r"C:\models\ibm-granite-3.1-8b-instruct-Q4_K_M.gguf",
            model_alias="granite-local",
            n_ctx=32768,
            n_batch=512,
        )
        assert CONFIG.llm_runtime.enabled is True
        assert getattr(CONFIG.llm_runtime, "provider", "") == "llama_cpp"
        assert CONFIG.llm_runtime.model_alias == "granite-local"
        assert CONFIG.llm_runtime.n_ctx == 32768
        assert CONFIG.llm_runtime.n_batch == 512
        assert CONFIG.model.model_version == "llama-cpp::granite-local"

        apply_ui_llm_runtime_selection(runtime_mode="deterministic")
        assert CONFIG.llm_runtime.enabled is False
        assert CONFIG.model.model_version == "deterministic-governed-runtime"
    finally:
        (
            CONFIG.llm_runtime.enabled,
            CONFIG.llm_runtime.provider,
            CONFIG.llm_runtime.model_path,
            CONFIG.llm_runtime.model_alias,
            CONFIG.llm_runtime.n_ctx,
            CONFIG.llm_runtime.n_batch,
            CONFIG.model.model_version,
        ) = original


def test_determine_interview_audit_path_prefers_markdown_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_ui_001"
    exports_dir = run_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    audit_md = exports_dir / "interview_audit_trail.md"
    audit_md.write_text("# Interview Audit", encoding="utf-8")
    (exports_dir / "run_manifest.json").write_text(
        json.dumps({"exports": {"interview_audit_trail_markdown": str(audit_md)}}, indent=2),
        encoding="utf-8",
    )

    assert determine_interview_audit_path(run_dir) == audit_md


def test_load_pending_interview_resume_bundle_ignores_user_skipped_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_011"
    stages_dir = run_dir / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    (stages_dir / "gap_resolution__interview.json").write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "question_id": "FACILITY_POI_VOLTAGE_KV",
                        "field_path": "facility.poi_voltage_kv",
                        "question": "Please confirm the point of interconnection voltage.",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    mark_interview_ui_skipped(
        project_root=tmp_path,
        project_name="GridSenpAI",
        run_id="run_011",
        questions=extract_interview_questions(run_dir),
        answers_by_question_id={},
        current_question_index=0,
        decision_reason="User continued without the interview.",
    )

    bundle = load_pending_interview_resume_bundle(
        project_root=tmp_path,
        project_name="GridSenpAI",
        output_dir=tmp_path / "runs",
    )
    assert bundle == {}
