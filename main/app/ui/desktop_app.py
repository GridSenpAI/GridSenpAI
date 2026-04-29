from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from tkinter import END, LEFT, RIGHT, VERTICAL, filedialog, messagebox
import tkinter as tk
from tkinter import ttk
from typing import Any, Protocol, cast

from app.config import CONFIG
from app.ui.workflow import (
    apply_ui_llm_runtime_selection,
    build_default_input_dir,
    build_interview_review_text,
    build_run_completion_snapshot,
    discover_local_gguf_models,
    build_question_display_context,
    clear_interview_ui_state,
    determine_export_manifest_path,
    determine_interview_audit_path,
    determine_tldr_path,
    load_pending_interview_resume_bundle,
    mark_interview_ui_skipped,
    save_interview_ui_state,
    extract_interview_overview,
    extract_interview_questions,
    infer_model_alias_from_path,
    open_path_on_host,
    prepare_uploaded_files,
    preview_interview_answer,
    reset_interview_session,
    run_pipeline_for_ui,
    run_post_interview_pipeline_for_ui,
    save_interview_answers,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    DND_FILES = None
    TkinterDnD = None


class TkinterDndWidget(Protocol):
    def drop_target_register(self, *dndtypes: Any) -> None:
        ...

    def dnd_bind(self, sequence: str | None = None, func: Any | None = None, add: Any | None = None) -> Any:
        ...

class GridSenpAIDesktopApp:
    def __init__(self) -> None:
        base_cls = TkinterDnD.Tk if TkinterDnD is not None else tk.Tk
        self.root = base_cls()
        self.root.title("GridSenpAI Intake Console")
        self.root.geometry("1260x900")
        self.root.minsize(1120, 780)

        self.project_root = CONFIG.paths.project_root
        self.input_dir = build_default_input_dir()
        self.output_dir = CONFIG.paths.runs_dir
        self.project_name = CONFIG.project_name

        self.selected_files: list[Path] = []
        self.available_model_paths: list[Path] = []
        self.current_questions: list[dict[str, Any]] = []
        self.answer_drafts: dict[str, str] = {}
        self.interview_dialog: tk.Toplevel | None = None
        self.dialog_question_text: tk.Text | None = None
        self.dialog_context_text: tk.Text | None = None
        self.dialog_answer_text: tk.Text | None = None
        self.dialog_question_title_var = tk.StringVar(value="")
        self.dialog_question_meta_var = tk.StringVar(value="")
        self.dialog_status_var = tk.StringVar(value="")
        self.current_question_index = 0
        self.latest_run_id: str | None = None
        self.initial_run_id: str | None = None
        self.worker_thread: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self._initialize_runtime_selection()
        self._build_layout()
        self._apply_runtime_visibility()
        self._update_runtime_summary()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_selected_files()
        self._restore_pending_interview_if_available()
        self.root.after(150, self._poll_events)

    def _initialize_runtime_selection(self) -> None:
        runtime_enabled = bool(getattr(CONFIG.llm_runtime, "enabled", False))
        self.runtime_mode_var = tk.StringVar(value=(str(getattr(CONFIG.llm_runtime, "provider", "llama_cpp") or "llama_cpp") if runtime_enabled else "deterministic"))
        configured_model_path = str(getattr(CONFIG.llm_runtime, "model_path", "") or "").strip()
        self.model_path_var = tk.StringVar(value=configured_model_path)
        configured_alias = str(getattr(CONFIG.llm_runtime, "model_alias", "") or "").strip() or infer_model_alias_from_path(configured_model_path)
        self.model_alias_var = tk.StringVar(value=configured_alias)
        self.n_ctx_var = tk.StringVar(value=str(int(getattr(CONFIG.llm_runtime, "n_ctx", 8192) or 8192)))
        self.n_batch_var = tk.StringVar(value=str(int(getattr(CONFIG.llm_runtime, "n_batch", 512) or 512)))
        self.watsonx_url_var = tk.StringVar(value=str(getattr(CONFIG.llm_runtime, "watsonx_url", "https://us-south.ml.cloud.ibm.com") or "https://us-south.ml.cloud.ibm.com"))
        self.watsonx_api_key_var = tk.StringVar(value=str(getattr(CONFIG.llm_runtime, "watsonx_api_key", "") or ""))
        self.watsonx_project_id_var = tk.StringVar(value=str(getattr(CONFIG.llm_runtime, "watsonx_project_id", "") or ""))
        self.watsonx_space_id_var = tk.StringVar(value=str(getattr(CONFIG.llm_runtime, "watsonx_space_id", "") or ""))
        self.watsonx_model_id_var = tk.StringVar(value=str(getattr(CONFIG.llm_runtime, "watsonx_model_id", "ibm/granite-3-3-8b-instruct") or "ibm/granite-3-3-8b-instruct"))
        self.watsonx_api_version_var = tk.StringVar(value=str(getattr(CONFIG.llm_runtime, "watsonx_api_version", "2024-10-08") or "2024-10-08"))
        self.runtime_summary_var = tk.StringVar(value="Choose deterministic mode, a local GGUF model, or IBM watsonx Granite API inference.")
        self._refresh_model_candidates()

    def _restore_pending_interview_if_available(self) -> None:
        bundle = load_pending_interview_resume_bundle(
            project_root=self.project_root,
            project_name=self.project_name,
            output_dir=self.output_dir,
        )
        if not bundle:
            return
        self.latest_run_id = str(bundle.get("run_id", "")).strip() or self.latest_run_id
        self.initial_run_id = self.latest_run_id or self.initial_run_id
        self.current_questions = list(bundle.get("questions", []))
        self.answer_drafts = dict(bundle.get("answer_drafts", {}))
        self.current_question_index = int(bundle.get("current_question_index", 0) or 0)
        overview = bundle.get("overview", {}) if isinstance(bundle.get("overview"), dict) else {}
        self.oversight_var.set(str(overview.get("status_line", "Interview questions restored.")))
        self.interview_status_var.set(
            f"Resumed applicant follow-up for run {self.latest_run_id}. "
            f"{len(self.current_questions)} question(s) remain before GridSenpAI can finalize the run."
        )
        self._set_completion_state(
            "Interview resumed.",
            "GridSenpAI restored saved applicant responses. Review or continue the interview, then submit answers to resume the governed pipeline.",
        )
        self._append_log(f"Resumed pending applicant interview for run: {self.latest_run_id}")
        self._set_busy(False, "Pending interview restored.")
        self._render_question_state()

    def _persist_interview_ui_state(self) -> None:
        if not self.current_questions or not self.latest_run_id:
            return
        save_interview_ui_state(
            project_root=self.project_root,
            project_name=self.project_name,
            run_id=self.latest_run_id,
            questions=self.current_questions,
            answers_by_question_id=self.answer_drafts,
            current_question_index=self.current_question_index,
            output_dir=self.output_dir,
        )

    def _on_close(self) -> None:
        self._persist_current_answer_draft()
        self._persist_interview_ui_state()
        self.root.destroy()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=3)
        self.root.columnconfigure(1, weight=2)
        self.root.rowconfigure(1, weight=0)
        self.root.rowconfigure(2, weight=1)
        self.root.rowconfigure(3, weight=1)

        header = ttk.Frame(self.root, padding=(16, 14))
        header.grid(row=0, column=0, columnspan=2, sticky="nsew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="GridSenpAI Intake Console", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=(
                "Upload the applicant package, run the governed pipeline, then let the applicant interview agent drive "
                "follow-up questions one at a time with evidence-aware context."
            ),
            wraplength=1040,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        runtime_frame = ttk.LabelFrame(self.root, text="1) Inference runtime", padding=12)
        runtime_frame.grid(row=1, column=0, sticky="ew", padx=(16, 8), pady=(0, 10))
        runtime_frame.columnconfigure(1, weight=1)

        ttk.Label(runtime_frame, text="Mode").grid(row=0, column=0, sticky="w")
        mode_box = ttk.Combobox(runtime_frame, state="readonly", textvariable=self.runtime_mode_var, values=["deterministic", "llama_cpp", "ibm_watsonx"], width=18)
        mode_box.grid(row=0, column=1, sticky="w")
        mode_box.bind("<<ComboboxSelected>>", self._on_runtime_mode_changed)

        self.local_runtime_frame = ttk.Frame(runtime_frame)
        self.local_runtime_frame.grid(row=1, column=0, columnspan=4, sticky="ew")
        self.local_runtime_frame.columnconfigure(1, weight=1)

        ttk.Label(self.local_runtime_frame, text="Model GGUF").grid(row=0, column=0, sticky="w", pady=(8, 0))
        self.model_combo = ttk.Combobox(self.local_runtime_frame, textvariable=self.model_path_var, values=[], width=80)
        self.model_combo.grid(row=0, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(self.local_runtime_frame, text="Browse Model", command=self._browse_model_file).grid(row=0, column=2, sticky="e", padx=(8, 0), pady=(8, 0))
        ttk.Button(self.local_runtime_frame, text="Refresh Models", command=self._refresh_model_candidates).grid(row=0, column=3, sticky="e", padx=(8, 0), pady=(8, 0))

        ttk.Label(self.local_runtime_frame, text="Model alias").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(self.local_runtime_frame, textvariable=self.model_alias_var, width=24).grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(self.local_runtime_frame, text="n_ctx").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(self.local_runtime_frame, textvariable=self.n_ctx_var, width=12).grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Label(self.local_runtime_frame, text="n_batch").grid(row=2, column=2, sticky="e", pady=(8, 0))
        ttk.Entry(self.local_runtime_frame, textvariable=self.n_batch_var, width=12).grid(row=2, column=3, sticky="w", pady=(8, 0))

        self.ibm_runtime_frame = ttk.Frame(runtime_frame)
        self.ibm_runtime_frame.grid(row=2, column=0, columnspan=4, sticky="ew")
        self.ibm_runtime_frame.columnconfigure(1, weight=1)

        ttk.Label(self.ibm_runtime_frame, text="watsonx URL").grid(row=0, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(self.ibm_runtime_frame, textvariable=self.watsonx_url_var, width=48).grid(row=0, column=1, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(self.ibm_runtime_frame, text="Project ID").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(self.ibm_runtime_frame, textvariable=self.watsonx_project_id_var, width=32).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(self.ibm_runtime_frame, text="Space ID").grid(row=1, column=2, sticky="e", pady=(8, 0))
        ttk.Entry(self.ibm_runtime_frame, textvariable=self.watsonx_space_id_var, width=24).grid(row=1, column=3, sticky="w", pady=(8, 0))
        ttk.Label(self.ibm_runtime_frame, text="Granite model ID").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(self.ibm_runtime_frame, textvariable=self.watsonx_model_id_var, width=48).grid(row=2, column=1, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(self.ibm_runtime_frame, text="API version").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(self.ibm_runtime_frame, textvariable=self.watsonx_api_version_var, width=18).grid(row=3, column=1, sticky="w", pady=(8, 0))
        ttk.Label(self.ibm_runtime_frame, text="API key").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(self.ibm_runtime_frame, textvariable=self.watsonx_api_key_var, width=48, show="*").grid(row=4, column=1, columnspan=3, sticky="ew", pady=(8, 0))

        ttk.Label(runtime_frame, textvariable=self.runtime_summary_var, wraplength=720, foreground="#1f4f82").grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))

        intake_frame = ttk.LabelFrame(self.root, text="2) Applicant documents", padding=12)
        intake_frame.grid(row=2, column=0, sticky="nsew", padx=(16, 8), pady=(0, 10))
        intake_frame.columnconfigure(0, weight=1)
        intake_frame.rowconfigure(3, weight=1)

        self.drop_zone = ttk.Label(
            intake_frame,
            text=(
                "Drag and drop the application files here\n"
                "-or-\n"
                "Use Browse Files\n\n"
                "Recommended sources: one-line diagrams, load schedules, equipment schedules, relay settings, "
                "interconnection studies, and narrative design documents."
            ),
            anchor="center",
            relief="solid",
            padding=22,
        )
        self.drop_zone.grid(row=0, column=0, sticky="ew")
        if TkinterDnD is not None and DND_FILES is not None:
            drop_zone_dnd = cast(TkinterDndWidget, self.drop_zone)
            drop_zone_dnd.drop_target_register(DND_FILES)
            drop_zone_dnd.dnd_bind("<<Drop>>", self._on_drop_files)
        else:
            self.drop_zone.configure(text=self.drop_zone.cget("text") + "\n\nNative drag-and-drop needs tkinterdnd2 on Windows.")

        ttk.Label(
            intake_frame,
            text="Accepted by current pipeline: PDFs, TXT, JSON, DOCX, and engineering support documents that the parser/OCR path can inspect.",
            wraplength=720,
        ).grid(row=1, column=0, sticky="w", pady=(10, 0))

        buttons = ttk.Frame(intake_frame)
        buttons.grid(row=2, column=0, sticky="ew", pady=(10, 10))
        ttk.Button(buttons, text="Browse Files", command=self._browse_files).pack(side=LEFT)
        ttk.Button(buttons, text="Remove Selected", command=self._remove_selected_files).pack(side=LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Clear Selection", command=self._clear_selected_files).pack(side=LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open sample_data folder", command=self._open_input_dir).pack(side=LEFT, padx=(8, 0))
        self.start_button = ttk.Button(buttons, text="Start Intake Run", command=self._start_initial_run)
        self.start_button.pack(side=RIGHT)

        self.file_list = tk.Listbox(intake_frame, height=12, selectmode=tk.EXTENDED)
        self.file_list.grid(row=3, column=0, sticky="nsew")

        log_frame = ttk.LabelFrame(self.root, text="3) Run status", padding=12)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=(16, 8), pady=(0, 16))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(log_frame, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.log_text = tk.Text(log_frame, wrap="word", height=18)
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        log_scroll = ttk.Scrollbar(log_frame, orient=VERTICAL, command=self.log_text.yview)
        log_scroll.grid(row=1, column=1, sticky="ns", pady=(8, 0))
        self.log_text.configure(yscrollcommand=log_scroll.set)

        interview_frame = ttk.LabelFrame(self.root, text="4) Applicant follow-up interview", padding=12)
        interview_frame.grid(row=1, column=1, rowspan=3, sticky="nsew", padx=(8, 16), pady=(0, 16))
        interview_frame.columnconfigure(0, weight=1)
        interview_frame.rowconfigure(5, weight=1)
        interview_frame.rowconfigure(7, weight=1)

        self.interview_status_var = tk.StringVar(value="No active applicant follow-up questions.")
        ttk.Label(interview_frame, textvariable=self.interview_status_var, font=("Segoe UI", 10, "bold"), wraplength=430).grid(row=0, column=0, sticky="w")

        self.oversight_var = tk.StringVar(value="Awaiting interview stage output.")
        ttk.Label(interview_frame, textvariable=self.oversight_var, wraplength=430, foreground="#1f4f82").grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.question_title_var = tk.StringVar(value="")
        ttk.Label(interview_frame, textvariable=self.question_title_var, font=("Segoe UI", 11, "bold"), wraplength=430).grid(row=2, column=0, sticky="w", pady=(10, 4))

        self.question_meta_var = tk.StringVar(value="")
        ttk.Label(interview_frame, textvariable=self.question_meta_var, wraplength=430).grid(row=3, column=0, sticky="w")

        ttk.Label(interview_frame, text="Question").grid(row=4, column=0, sticky="w", pady=(10, 4))
        question_body = ttk.Frame(interview_frame)
        question_body.grid(row=5, column=0, sticky="nsew")
        question_body.columnconfigure(0, weight=1)
        question_body.rowconfigure(0, weight=1)
        self.question_text = tk.Text(question_body, wrap="word", height=8)
        self.question_text.grid(row=0, column=0, sticky="nsew")
        q_scroll = ttk.Scrollbar(question_body, orient=VERTICAL, command=self.question_text.yview)
        q_scroll.grid(row=0, column=1, sticky="ns")
        self.question_text.configure(yscrollcommand=q_scroll.set, state="disabled")

        ttk.Label(interview_frame, text="Why this is being asked").grid(row=6, column=0, sticky="w", pady=(10, 4))
        context_body = ttk.Frame(interview_frame)
        context_body.grid(row=7, column=0, sticky="nsew")
        context_body.columnconfigure(0, weight=1)
        context_body.rowconfigure(0, weight=1)
        self.context_text = tk.Text(context_body, wrap="word", height=7)
        self.context_text.grid(row=0, column=0, sticky="nsew")
        c_scroll = ttk.Scrollbar(context_body, orient=VERTICAL, command=self.context_text.yview)
        c_scroll.grid(row=0, column=1, sticky="ns")
        self.context_text.configure(yscrollcommand=c_scroll.set, state="disabled")

        ttk.Label(interview_frame, text="Applicant response").grid(row=8, column=0, sticky="w", pady=(12, 4))
        answer_body = ttk.Frame(interview_frame)
        answer_body.grid(row=9, column=0, sticky="nsew")
        answer_body.columnconfigure(0, weight=1)
        answer_body.rowconfigure(0, weight=1)
        self.answer_text = tk.Text(answer_body, wrap="word", height=5)
        self.answer_text.grid(row=0, column=0, sticky="nsew")
        a_scroll = ttk.Scrollbar(answer_body, orient=VERTICAL, command=self.answer_text.yview)
        a_scroll.grid(row=0, column=1, sticky="ns")
        self.answer_text.configure(yscrollcommand=a_scroll.set)
        self.answer_text.bind("<KeyRelease>", self._on_answer_changed)

        self.answer_preview_var = tk.StringVar(value="Enter an answer. GridSenpAI will validate and normalize it before the pipeline continues.")
        ttk.Label(interview_frame, textvariable=self.answer_preview_var, wraplength=430, foreground="#3d3d3d").grid(row=10, column=0, sticky="w", pady=(6, 0))

        nav = ttk.Frame(interview_frame)
        nav.grid(row=11, column=0, sticky="ew", pady=(10, 0))
        self.prev_button = ttk.Button(nav, text="Previous", command=self._prev_question, state="disabled")
        self.prev_button.pack(side=LEFT)
        self.next_button = ttk.Button(nav, text="Next", command=self._next_question, state="disabled")
        self.next_button.pack(side=LEFT, padx=(8, 0))
        self.clarify_button = ttk.Button(nav, text="Clarify", command=self._show_question_clarification, state="disabled")
        self.clarify_button.pack(side=LEFT, padx=(8, 0))
        self.open_interview_button = ttk.Button(nav, text="Open Interview Workspace", command=self._open_interview_workspace, state="disabled")
        self.open_interview_button.pack(side=LEFT, padx=(8, 0))
        self.skip_interview_button = ttk.Button(nav, text="Skip Interview For Now", command=self._skip_interview_for_now, state="disabled")
        self.skip_interview_button.pack(side=LEFT, padx=(8, 0))
        self.finish_button = ttk.Button(nav, text="Submit Answers and Continue", command=self._submit_interview_answers, state="disabled")
        self.finish_button.pack(side=RIGHT)

        result_actions = ttk.Frame(interview_frame)
        result_actions.grid(row=12, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(result_actions, text="Open latest run folder", command=self._open_latest_run_dir).pack(side=LEFT)
        ttk.Button(result_actions, text="Open exports folder", command=self._open_latest_exports_dir).pack(side=LEFT, padx=(8, 0))
        ttk.Button(result_actions, text="Open latest manifest", command=self._open_latest_manifest).pack(side=LEFT, padx=(8, 0))
        ttk.Button(result_actions, text="Open latest TLDR", command=self._open_latest_tldr).pack(side=LEFT, padx=(8, 0))
        ttk.Button(result_actions, text="Open interview audit", command=self._open_latest_interview_audit).pack(side=LEFT, padx=(8, 0))

        ttk.Label(interview_frame, text="4) Completion summary").grid(row=13, column=0, sticky="w", pady=(14, 4))
        self.completion_status_var = tk.StringVar(value="No completed run yet.")
        ttk.Label(interview_frame, textvariable=self.completion_status_var, wraplength=430, foreground="#1f4f82").grid(row=14, column=0, sticky="w")

        completion_body = ttk.Frame(interview_frame)
        completion_body.grid(row=15, column=0, sticky="nsew", pady=(6, 0))
        completion_body.columnconfigure(0, weight=1)
        completion_body.rowconfigure(0, weight=1)
        self.completion_text = tk.Text(completion_body, wrap="word", height=8)
        self.completion_text.grid(row=0, column=0, sticky="nsew")
        completion_scroll = ttk.Scrollbar(completion_body, orient=VERTICAL, command=self.completion_text.yview)
        completion_scroll.grid(row=0, column=1, sticky="ns")
        self.completion_text.configure(yscrollcommand=completion_scroll.set, state="disabled")

    def _append_log(self, message: str) -> None:
        self.log_text.insert(END, message.rstrip() + "\n")
        self.log_text.see(END)

    def _browse_files(self) -> None:
        file_paths = filedialog.askopenfilenames(title="Select GridSenpAI application documents")
        if not file_paths:
            return
        self._add_selected_files([Path(item) for item in file_paths])

    def _refresh_model_candidates(self) -> None:
        discovered = discover_local_gguf_models(self.project_root)
        configured = str(self.model_path_var.get()).strip()
        merged: list[str] = []
        for item in discovered:
            merged.append(str(item))
        if configured and configured not in merged:
            merged.insert(0, configured)
        self.available_model_paths = [Path(item) for item in merged if str(item).strip()]
        if hasattr(self, "model_combo"):
            self.model_combo.configure(values=merged)
        if not self.model_alias_var.get().strip() and configured:
            self.model_alias_var.set(infer_model_alias_from_path(configured))
        self._update_runtime_summary()

    def _browse_model_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Choose GGUF model",
            filetypes=[("GGUF Models", "*.gguf"), ("All Files", "*.*")],
        )
        if not file_path:
            return
        self.model_path_var.set(file_path)
        self.model_alias_var.set(infer_model_alias_from_path(file_path))
        self._refresh_model_candidates()

    def _on_runtime_mode_changed(self, _event: Any = None) -> None:
        self._apply_runtime_visibility()
        self._update_runtime_summary()

    def _apply_runtime_visibility(self) -> None:
        mode = self.runtime_mode_var.get().strip().lower()
        if getattr(self, "ibm_runtime_frame", None) is not None:
            if mode == "ibm_watsonx":
                self.ibm_runtime_frame.grid()
            else:
                self.ibm_runtime_frame.grid_remove()
        if getattr(self, "local_runtime_frame", None) is not None:
            if mode == "ibm_watsonx":
                self.local_runtime_frame.grid_remove()
            else:
                self.local_runtime_frame.grid()

    def _update_runtime_summary(self) -> None:
        mode = self.runtime_mode_var.get().strip().lower()
        if mode == "deterministic":
            self.runtime_summary_var.set("Deterministic-only bounded flows will run without model inference. Select llama_cpp for local GGUF inference or ibm_watsonx for hosted Granite API inference.")
            return
        if mode == "ibm_watsonx":
            model_id = str(self.watsonx_model_id_var.get()).strip() or "ibm/granite-3-3-8b-instruct"
            scope = str(self.watsonx_project_id_var.get()).strip() or str(self.watsonx_space_id_var.get()).strip() or "<project-or-space-id-required>"
            self.runtime_summary_var.set(f"IBM watsonx runtime selected. Granite model '{model_id}' will be called through the watsonx chat API. Scope: {scope}. n_ctx metadata={self.n_ctx_var.get().strip() or '8192'}, max batch metadata={self.n_batch_var.get().strip() or '512'}.")
            return
        model_path = str(self.model_path_var.get()).strip()
        alias = str(self.model_alias_var.get()).strip() or infer_model_alias_from_path(model_path)
        provider_note = "IBM Granite GGUF is supported here" if "granite" in model_path.lower() or "granite" in alias.lower() else "Any llama.cpp-compatible GGUF can be selected here"
        self.runtime_summary_var.set(f"Local llama.cpp runtime selected. {provider_note}. Use the first shard for split GGUF models. Alias: {alias or 'local-gguf-model'}. n_ctx={self.n_ctx_var.get().strip() or '8192'}, n_batch={self.n_batch_var.get().strip() or '512'}.")

    def _apply_runtime_selection(self) -> bool:
        mode = self.runtime_mode_var.get().strip().lower()
        model_path = str(self.model_path_var.get()).strip()
        model_alias = str(self.model_alias_var.get()).strip()
        if mode == "llama_cpp":
            if not model_path:
                messagebox.showwarning("GridSenpAI", "Choose a GGUF model path before starting the run.")
                return False
            if not Path(model_path).exists():
                messagebox.showwarning("GridSenpAI", "The selected GGUF model path does not exist.")
                return False
        elif mode == "ibm_watsonx":
            if not str(self.watsonx_url_var.get()).strip():
                messagebox.showwarning("GridSenpAI", "Enter the IBM watsonx endpoint URL before starting the run.")
                return False
            if not str(self.watsonx_api_key_var.get()).strip():
                messagebox.showwarning("GridSenpAI", "Enter the IBM watsonx API key before starting the run.")
                return False
            if not (str(self.watsonx_project_id_var.get()).strip() or str(self.watsonx_space_id_var.get()).strip()):
                messagebox.showwarning("GridSenpAI", "Enter either a watsonx project ID or space ID before starting the run.")
                return False
            if not str(self.watsonx_model_id_var.get()).strip():
                messagebox.showwarning("GridSenpAI", "Enter the IBM Granite model ID before starting the run.")
                return False
        try:
            n_ctx = int(str(self.n_ctx_var.get()).strip() or "8192")
            n_batch = int(str(self.n_batch_var.get()).strip() or "512")
        except ValueError:
            messagebox.showwarning("GridSenpAI", "n_ctx and n_batch must be whole numbers.")
            return False
        apply_ui_llm_runtime_selection(
            runtime_mode=mode,
            model_path=model_path,
            model_alias=model_alias,
            n_ctx=n_ctx,
            n_batch=n_batch,
            watsonx_url=str(self.watsonx_url_var.get()).strip(),
            watsonx_api_key=str(self.watsonx_api_key_var.get()).strip(),
            watsonx_project_id=str(self.watsonx_project_id_var.get()).strip(),
            watsonx_space_id=str(self.watsonx_space_id_var.get()).strip(),
            watsonx_model_id=str(self.watsonx_model_id_var.get()).strip(),
            watsonx_api_version=str(self.watsonx_api_version_var.get()).strip(),
        )
        self._append_log(f"Configured runtime mode: {mode}")
        if mode == "llama_cpp":
            self._append_log(f"  - model: {model_path}")
            self._append_log(f"  - alias: {CONFIG.llm_runtime.model_alias}")
            self._append_log(f"  - n_ctx: {CONFIG.llm_runtime.n_ctx}")
            self._append_log(f"  - n_batch: {CONFIG.llm_runtime.n_batch}")
        else:
            self._append_log("  - local LLM runtime disabled for this run")
        self._update_runtime_summary()
        return True

    def _on_drop_files(self, event: Any) -> None:
        raw = str(getattr(event, "data", "") or "").strip()
        if not raw:
            return
        files = self.root.tk.splitlist(raw)
        self._add_selected_files([Path(item) for item in files])

    def _add_selected_files(self, files: list[Path]) -> None:
        existing = {str(path).lower() for path in self.selected_files}
        for path in files:
            if not path.exists() or not path.is_file():
                continue
            key = str(path).lower()
            if key in existing:
                continue
            self.selected_files.append(path)
            existing.add(key)
        self.selected_files.sort(key=lambda item: item.name.lower())
        self._refresh_selected_files()

    def _refresh_selected_files(self) -> None:
        self.file_list.delete(0, END)
        for path in self.selected_files:
            self.file_list.insert(END, str(path))

    def _remove_selected_files(self) -> None:
        selected_indices = list(self.file_list.curselection())
        if not selected_indices:
            return
        selected_paths = {str(self.file_list.get(index)) for index in selected_indices}
        self.selected_files = [path for path in self.selected_files if str(path) not in selected_paths]
        self._refresh_selected_files()

    def _clear_selected_files(self) -> None:
        self.selected_files = []
        self._initialize_runtime_selection()
        self._refresh_selected_files()

    def _set_busy(self, busy: bool, status: str) -> None:
        self.status_var.set(status)
        self.start_button.configure(state="disabled" if busy else "normal")
        self.finish_button.configure(state="disabled" if busy or not self.current_questions else "normal")
        self.next_button.configure(state="disabled" if busy or not self.current_questions else "normal")
        self.prev_button.configure(state="disabled" if busy or not self.current_questions else "normal")

    def _start_initial_run(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("GridSenpAI", "A pipeline run is already in progress.")
            return
        if not self.selected_files:
            messagebox.showwarning("GridSenpAI", "Select at least one applicant document first.")
            return

        if not self._apply_runtime_selection():
            return

        copied = prepare_uploaded_files(self.input_dir, self.selected_files)
        if not copied:
            messagebox.showerror("GridSenpAI", "No valid files were copied into sample_data/current_application.")
            return

        reset_interview_session(self.project_root, self.project_name)
        self.current_questions = []
        self.answer_drafts = {}
        self.current_question_index = 0
        self.oversight_var.set("Awaiting interview stage output.")
        self._render_question_state()
        self._append_log(f"Prepared intake bundle at: {self.input_dir}")
        for item in copied:
            self._append_log(f"  - copied: {item.name}")
        self._set_busy(True, "Running initial governed intake pass...")
        self.worker_thread = threading.Thread(target=self._run_pipeline_worker, kwargs={"parent_run_id": None, "phase": "initial"}, daemon=True)
        self.worker_thread.start()

    def _run_pipeline_worker(self, *, parent_run_id: str | None, phase: str) -> None:
        try:
            if phase == "post_interview":
                source_run_id = str(parent_run_id or "").strip()
                if not source_run_id:
                    raise ValueError("Post-interview continuation requires the initial run ID.")
                summary = run_post_interview_pipeline_for_ui(
                    input_dir=self.input_dir,
                    output_dir=self.output_dir,
                    source_run_id=source_run_id,
                )
            else:
                summary = run_pipeline_for_ui(
                    input_dir=self.input_dir,
                    output_dir=self.output_dir,
                    parent_run_id=parent_run_id,
                )
            self.events.put(("run_complete", {"summary": summary, "phase": phase}))
        except Exception as exc:  # pragma: no cover - defensive runtime surface
            self.events.put(
                (
                    "run_error",
                    {
                        "phase": phase,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
            )

    def _poll_events(self) -> None:
        while True:
            try:
                event_name, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event_name == "run_complete":
                self._handle_run_complete(payload)
            elif event_name == "run_error":
                self._handle_run_error(payload)
        self.root.after(150, self._poll_events)

    def _handle_run_complete(self, payload: dict[str, Any]) -> None:
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        phase = str(payload.get("phase", "initial"))
        run_id = str(summary.get("run_id", "")).strip()
        self.latest_run_id = run_id or self.latest_run_id
        if phase == "initial" and run_id:
            self.initial_run_id = run_id
        run_dir = self.output_dir / run_id if run_id else None
        self._append_log(f"Run complete [{phase}]: {run_id or 'unknown_run'}")
        self._append_log(f"  - status: {summary.get('status', 'UNKNOWN')}")
        if run_dir is None:
            self._set_busy(False, "Run completed, but no run_id was returned.")
            return

        questions = extract_interview_questions(run_dir)
        oversight = extract_interview_overview(run_dir)
        remaining = len(questions)
        self._append_log(f"  - interview questions remaining: {remaining}")
        if oversight.get("status_line"):
            self._append_log(f"  - {oversight['status_line']}")
        if oversight.get("detail_text"):
            for line in str(oversight["detail_text"]).splitlines():
                self._append_log(f"    {line}")

        if phase == "initial" and questions:
            self.current_questions = questions
            self.current_question_index = 0
            bundle = load_pending_interview_resume_bundle(
                project_root=self.project_root,
                project_name=self.project_name,
                output_dir=self.output_dir,
            )
            if str(bundle.get("run_id", "")).strip() == run_id:
                self.answer_drafts = dict(bundle.get("answer_drafts", {}))
                self.current_question_index = int(bundle.get("current_question_index", 0) or 0)
                self._append_log("  - restored saved applicant response drafts for this interview.")
            else:
                self.answer_drafts = {}
            self.oversight_var.set(str(oversight.get("status_line", "Interview questions are ready.")))
            self._persist_interview_ui_state()
            self._render_question_state()
            self._open_interview_workspace()
            self._set_completion_state("Interview not complete yet.", "GridSenpAI is waiting for applicant answers before the final rerun.")
            self._set_busy(False, "Interview questions are ready for applicant response.")
            self.interview_status_var.set(f"{remaining} targeted applicant follow-up question(s) remain before GridSenpAI can finalize the run.")
            return

        self.current_questions = []
        self.answer_drafts = {}
        self.current_question_index = 0
        clear_interview_ui_state(
            self.project_root,
            self.project_name,
            run_id=self.initial_run_id or self.latest_run_id,
            output_dir=self.output_dir,
        )
        self.oversight_var.set(str(oversight.get("status_line", "Interview complete.")))
        self._render_question_state()
        completion = build_run_completion_snapshot(run_dir, summary)
        self._set_completion_state(completion.get("headline", "Run complete."), completion.get("detail_text", ""))
        self._set_busy(False, "Pipeline complete. Opening final TLDR summary...")
        tldr_path = determine_tldr_path(run_dir)
        if tldr_path is not None:
            opened = open_path_on_host(tldr_path)
            self._append_log(f"  - TLDR summary: {tldr_path}")
            if not opened:
                self._append_log("  - automatic open was skipped because host path launching is unavailable in this environment.")
        else:
            self._append_log("  - TLDR summary document was not found; planner packet DOCX remains available in exports.")

    def _set_completion_state(self, headline: str, detail_text: str) -> None:
        self.completion_status_var.set(headline.strip() or "Run status unavailable.")
        self.completion_text.configure(state="normal")
        self.completion_text.delete("1.0", END)
        self.completion_text.insert("1.0", detail_text.strip() or "No completion details are available yet.")
        self.completion_text.configure(state="disabled")

    def _handle_run_error(self, payload: dict[str, Any]) -> None:
        phase = str(payload.get("phase", "run"))
        error = str(payload.get("error", "Unknown error"))
        tb = str(payload.get("traceback", "")).strip()
        self._append_log(f"Run failed [{phase}]: {error}")
        if tb:
            self._append_log(tb)
        self._set_busy(False, "Run failed.")
        messagebox.showerror("GridSenpAI", error)

    def _current_question(self) -> dict[str, Any] | None:
        if not self.current_questions:
            return None
        if self.current_question_index < 0 or self.current_question_index >= len(self.current_questions):
            return None
        return self.current_questions[self.current_question_index]

    def _persist_current_answer_draft(self) -> None:
        question = self._current_question()
        if question is None:
            return
        question_id = str(question.get("question_id", "")).strip()
        if not question_id:
            return
        draft_value = self.answer_text.get("1.0", END).strip()
        if self.dialog_answer_text is not None and self.interview_dialog is not None and self.interview_dialog.winfo_exists():
            dialog_value = self.dialog_answer_text.get("1.0", END).strip()
            if dialog_value or not draft_value:
                draft_value = dialog_value
                self.answer_text.delete("1.0", END)
                if draft_value:
                    self.answer_text.insert("1.0", draft_value)
        self.answer_drafts[question_id] = draft_value
        self._persist_interview_ui_state()

    def _set_text_widget(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", END)
        widget.insert(END, value)
        widget.configure(state="disabled")

    def _update_answer_preview(self) -> None:
        question = self._current_question()
        if question is None:
            self.answer_preview_var.set("Enter an answer. GridSenpAI will validate and normalize it before the pipeline continues.")
            return
        raw_answer = self.answer_text.get("1.0", END).strip()
        preview = preview_interview_answer(question, raw_answer)
        self.answer_preview_var.set(str(preview.get("message", "")))

    def _on_answer_changed(self, _event: Any) -> None:
        self._persist_current_answer_draft()
        self._update_answer_preview()

    def _render_question_state(self) -> None:
        question = self._current_question()
        self.answer_text.delete("1.0", END)

        if question is None:
            self.question_title_var.set("")
            self.question_meta_var.set("")
            self._set_text_widget(self.question_text, "No active follow-up questions.")
            self._set_text_widget(self.context_text, "The applicant interview panel will populate after the governed pipeline identifies the small set of remaining missing, conflicting, or low-confidence fields that truly need applicant confirmation.")
            self.answer_preview_var.set("Enter an answer. GridSenpAI will validate and normalize it before the pipeline continues.")
            self.prev_button.configure(state="disabled")
            self.next_button.configure(state="disabled")
            self.clarify_button.configure(state="disabled")
            self.open_interview_button.configure(state="disabled")
            self.skip_interview_button.configure(state="disabled")
            self.finish_button.configure(state="disabled")
            self._render_interview_dialog_state()
            return

        context = build_question_display_context(question)
        index_label = f"Question {self.current_question_index + 1} of {len(self.current_questions)} — {context['field_label']}"
        self.question_title_var.set(index_label)
        self.question_meta_var.set(context["summary_line"])

        self._set_text_widget(self.question_text, context["prompt_text"])
        self._set_text_widget(self.context_text, context["context_text"] + "\n\n" + context["agent_line"])

        question_id = str(question.get("question_id", "")).strip()
        draft = self.answer_drafts.get(question_id, "")
        if draft:
            self.answer_text.insert("1.0", draft)
        self._update_answer_preview()

        self.prev_button.configure(state="normal" if self.current_question_index > 0 else "disabled")
        self.next_button.configure(state="normal" if self.current_question_index < len(self.current_questions) - 1 else "disabled")
        self.clarify_button.configure(state="normal")
        self.open_interview_button.configure(state="normal")
        self.skip_interview_button.configure(state="normal")
        self.finish_button.configure(state="normal")
        self._render_interview_dialog_state()

    def _prev_question(self) -> None:
        if self.current_question_index <= 0:
            return
        self._persist_current_answer_draft()
        self.current_question_index -= 1
        self._render_question_state()

    def _next_question(self) -> None:
        if self.current_question_index >= len(self.current_questions) - 1:
            return
        self._persist_current_answer_draft()
        self.current_question_index += 1
        self._render_question_state()

    def _show_question_clarification(self) -> None:
        question = self._current_question()
        if question is None:
            return
        context = build_question_display_context(question)
        messagebox.showinfo(
            "GridSenpAI Question Clarification",
            context["context_text"] + "\n\n" + context["agent_line"],
        )

    def _open_interview_workspace(self) -> None:
        if self.interview_dialog is not None and self.interview_dialog.winfo_exists():
            self.interview_dialog.deiconify()
            self.interview_dialog.lift()
            self._render_interview_dialog_state()
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("GridSenpAI Interview Workspace")
        dialog.geometry("980x760")
        dialog.minsize(860, 680)
        dialog.transient(self.root)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(3, weight=1)
        dialog.rowconfigure(5, weight=1)
        dialog.rowconfigure(7, weight=1)
        self.interview_dialog = dialog

        ttk.Label(dialog, textvariable=self.dialog_status_var, font=("Segoe UI", 11, "bold"), wraplength=920).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 6))
        ttk.Label(dialog, textvariable=self.dialog_question_title_var, font=("Segoe UI", 12, "bold"), wraplength=920).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 4))
        ttk.Label(dialog, textvariable=self.dialog_question_meta_var, wraplength=920).grid(row=2, column=0, sticky="w", padx=14)

        qframe = ttk.LabelFrame(dialog, text="Question", padding=8)
        qframe.grid(row=3, column=0, sticky="nsew", padx=14, pady=(10, 6))
        qframe.columnconfigure(0, weight=1)
        qframe.rowconfigure(0, weight=1)
        self.dialog_question_text = tk.Text(qframe, wrap="word", height=10)
        self.dialog_question_text.grid(row=0, column=0, sticky="nsew")
        qscroll = ttk.Scrollbar(qframe, orient=VERTICAL, command=self.dialog_question_text.yview)
        qscroll.grid(row=0, column=1, sticky="ns")
        self.dialog_question_text.configure(yscrollcommand=qscroll.set, state="disabled")

        cframe = ttk.LabelFrame(dialog, text="Why GridSenpAI is asking", padding=8)
        cframe.grid(row=5, column=0, sticky="nsew", padx=14, pady=6)
        cframe.columnconfigure(0, weight=1)
        cframe.rowconfigure(0, weight=1)
        self.dialog_context_text = tk.Text(cframe, wrap="word", height=8)
        self.dialog_context_text.grid(row=0, column=0, sticky="nsew")
        cscroll = ttk.Scrollbar(cframe, orient=VERTICAL, command=self.dialog_context_text.yview)
        cscroll.grid(row=0, column=1, sticky="ns")
        self.dialog_context_text.configure(yscrollcommand=cscroll.set, state="disabled")

        aframe = ttk.LabelFrame(dialog, text="Applicant response", padding=8)
        aframe.grid(row=7, column=0, sticky="nsew", padx=14, pady=6)
        aframe.columnconfigure(0, weight=1)
        aframe.rowconfigure(0, weight=1)
        self.dialog_answer_text = tk.Text(aframe, wrap="word", height=7)
        self.dialog_answer_text.grid(row=0, column=0, sticky="nsew")
        ascroll = ttk.Scrollbar(aframe, orient=VERTICAL, command=self.dialog_answer_text.yview)
        ascroll.grid(row=0, column=1, sticky="ns")
        self.dialog_answer_text.configure(yscrollcommand=ascroll.set)
        self.dialog_answer_text.bind("<KeyRelease>", self._on_dialog_answer_changed)

        actions = ttk.Frame(dialog)
        actions.grid(row=8, column=0, sticky="ew", padx=14, pady=(8, 14))
        ttk.Button(actions, text="Previous", command=self._prev_question).pack(side=LEFT)
        ttk.Button(actions, text="Next", command=self._next_question).pack(side=LEFT, padx=(8, 0))
        ttk.Button(actions, text="Clarify", command=self._show_question_clarification).pack(side=LEFT, padx=(8, 0))
        ttk.Button(actions, text="Skip Interview For Now", command=self._skip_interview_for_now).pack(side=LEFT, padx=(8, 0))
        ttk.Button(actions, text="Save and Continue Later", command=dialog.withdraw).pack(side=RIGHT)
        ttk.Button(actions, text="Submit Answers and Continue", command=self._submit_interview_answers).pack(side=RIGHT, padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", dialog.withdraw)
        self._render_interview_dialog_state()

    def _on_dialog_answer_changed(self, _event: Any) -> None:
        question = self._current_question()
        if question is None or self.dialog_answer_text is None:
            return
        question_id = str(question.get("question_id", "")).strip()
        self.answer_drafts[question_id] = self.dialog_answer_text.get("1.0", END).strip()
        self.answer_text.delete("1.0", END)
        self.answer_text.insert("1.0", self.answer_drafts[question_id])
        self._update_answer_preview()
        self._persist_interview_ui_state()

    def _render_interview_dialog_state(self) -> None:
        if self.interview_dialog is None or not self.interview_dialog.winfo_exists():
            return
        question = self._current_question()
        self.dialog_status_var.set(self.interview_status_var.get())
        if question is None:
            self.dialog_question_title_var.set("No active follow-up questions.")
            self.dialog_question_meta_var.set("")
            if self.dialog_question_text is not None:
                self._set_text_widget(self.dialog_question_text, "No active follow-up questions.")
            if self.dialog_context_text is not None:
                self._set_text_widget(self.dialog_context_text, "The applicant interview workspace will reopen when GridSenpAI has targeted follow-up questions.")
            if self.dialog_answer_text is not None:
                self.dialog_answer_text.delete("1.0", END)
            return

        context = build_question_display_context(question)
        self.dialog_question_title_var.set(f"Question {self.current_question_index + 1} of {len(self.current_questions)} — {context['field_label']}")
        self.dialog_question_meta_var.set(context["summary_line"])
        if self.dialog_question_text is not None:
            self._set_text_widget(self.dialog_question_text, context["prompt_text"])
        if self.dialog_context_text is not None:
            self._set_text_widget(self.dialog_context_text, context["context_text"] + "\n\n" + context["agent_line"])
        if self.dialog_answer_text is not None:
            question_id = str(question.get("question_id", "")).strip()
            draft = self.answer_drafts.get(question_id, "")
            current = self.dialog_answer_text.get("1.0", END).strip()
            if current != draft:
                self.dialog_answer_text.delete("1.0", END)
                if draft:
                    self.dialog_answer_text.insert("1.0", draft)

    def _skip_interview_for_now(self) -> None:
        if not self.current_questions or not self.latest_run_id:
            return
        self._persist_current_answer_draft()
        if self.dialog_answer_text is not None and self.interview_dialog is not None and self.interview_dialog.winfo_exists():
            self._on_dialog_answer_changed(None)
        if not messagebox.askyesno(
            "Skip Interview For Now",
            "Continue the governed pipeline without answering the applicant interview right now? GridSenpAI will mark the interview as user-skipped for this rerun, and confidence may be reduced.",
        ):
            return
        mark_interview_ui_skipped(
            project_root=self.project_root,
            project_name=self.project_name,
            run_id=self.latest_run_id,
            questions=self.current_questions,
            answers_by_question_id=self.answer_drafts,
            current_question_index=self.current_question_index,
            decision_reason="User chose to continue without completing the applicant interview.",
            output_dir=self.output_dir,
        )
        self._append_log("Applicant interview skipped for now. Continuing from the completed retrieval stage without rerunning intake, OCR, extraction, or normalization.")
        self._set_busy(True, "Skipping applicant interview and continuing from retrieval...")
        self.worker_thread = threading.Thread(
            target=self._run_pipeline_worker,
            kwargs={"parent_run_id": self.initial_run_id, "phase": "post_interview"},
            daemon=True,
        )
        self.worker_thread.start()

    def _show_interview_review_dialog(self) -> bool:
        review_text = build_interview_review_text(self.current_questions, self.answer_drafts)
        dialog = tk.Toplevel(self.root)
        dialog.title("Review Applicant Responses")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("860x620")
        dialog.minsize(760, 520)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        ttk.Label(
            dialog,
            text="Review Applicant Responses",
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 8))

        body = tk.Text(dialog, wrap="word")
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        body.insert("1.0", review_text)
        body.configure(state="disabled")

        actions = ttk.Frame(dialog)
        actions.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 14))

        decision = {"continue": False}

        def _continue() -> None:
            decision["continue"] = True
            dialog.destroy()

        ttk.Button(actions, text="Back to Edit Answers", command=dialog.destroy).pack(side=LEFT)
        ttk.Button(actions, text="Continue to Pipeline", command=_continue).pack(side=RIGHT)

        self.root.wait_window(dialog)
        return bool(decision["continue"])

    def _submit_interview_answers(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("GridSenpAI", "A pipeline run is already in progress.")
            return
        if not self.current_questions:
            messagebox.showinfo("GridSenpAI", "There are no active interview questions to submit.")
            return

        self._persist_current_answer_draft()
        missing = [
            item for item in self.current_questions
            if not str(self.answer_drafts.get(str(item.get("question_id", "")).strip(), "")).strip()
        ]
        if missing:
            proceed = messagebox.askyesno(
                "Continue With Partial Answers?",
                f"{len(missing)} follow-up question(s) are still unanswered. Continue the governed pipeline with only the answers entered so far? Remaining fields will stay unresolved unless you skip the interview or answer them later.",
            )
            if not proceed:
                return

        if not self._show_interview_review_dialog():
            self._append_log("Applicant answer review canceled. Waiting for edits before rerun.")
            return

        session_path, confirmed, clarifications = save_interview_answers(
            project_root=self.project_root,
            project_name=self.project_name,
            questions=self.current_questions,
            answers_by_question_id=self.answer_drafts,
            run_id=self.initial_run_id or self.latest_run_id,
            output_dir=self.output_dir,
        )
        if clarifications:
            problem_fields = ", ".join(
                str(item.get("field_path", "")).strip() or "Unknown"
                for item in clarifications
                if isinstance(item, dict)
            )
            messagebox.showwarning(
                "GridSenpAI",
                "Some responses could not be parsed into the expected field type. "
                f"Please revise them before continuing. Fields: {problem_fields}",
            )
            self._append_log(f"Interview submission blocked by clarification requirements: {problem_fields}")
            return

        self._append_log(f"Saved {len(confirmed)} interview answer(s) to: {session_path}")
        self._set_busy(True, "Continuing pipeline with applicant responses...")
        self.worker_thread = threading.Thread(
            target=self._run_pipeline_worker,
            kwargs={"parent_run_id": self.initial_run_id, "phase": "post_interview"},
            daemon=True,
        )
        self.worker_thread.start()

    def _open_input_dir(self) -> None:
        self.input_dir.mkdir(parents=True, exist_ok=True)
        if not open_path_on_host(self.input_dir):
            self._append_log(f"sample_data folder: {self.input_dir}")

    def _open_latest_run_dir(self) -> None:
        if not self.latest_run_id:
            return
        run_dir = self.output_dir / self.latest_run_id
        if not open_path_on_host(run_dir):
            self._append_log(f"Latest run directory: {run_dir}")

    def _open_latest_exports_dir(self) -> None:
        if not self.latest_run_id:
            return
        exports_dir = self.output_dir / self.latest_run_id / "exports"
        if not open_path_on_host(exports_dir):
            self._append_log(f"Latest exports directory: {exports_dir}")

    def _open_latest_manifest(self) -> None:
        if not self.latest_run_id:
            return
        manifest_path = determine_export_manifest_path(self.output_dir / self.latest_run_id)
        if not open_path_on_host(manifest_path):
            self._append_log(f"Latest manifest: {manifest_path}")

    def _open_latest_tldr(self) -> None:
        if not self.latest_run_id:
            return
        tldr_path = determine_tldr_path(self.output_dir / self.latest_run_id)
        if tldr_path is None:
            self._append_log("No TLDR summary is available for the latest run yet.")
            return
        if not open_path_on_host(tldr_path):
            self._append_log(f"Latest TLDR summary: {tldr_path}")

    def _open_latest_interview_audit(self) -> None:
        if not self.latest_run_id:
            return
        audit_path = determine_interview_audit_path(self.output_dir / self.latest_run_id)
        if audit_path is None:
            self._append_log("No interview audit artifact is available for the latest run yet.")
            return
        if not open_path_on_host(audit_path):
            self._append_log(f"Latest interview audit: {audit_path}")

    def run(self) -> int:
        self.root.mainloop()
        return 0


def launch_desktop_app() -> int:
    app = GridSenpAIDesktopApp()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(launch_desktop_app())
