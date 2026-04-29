from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent

DEFAULT_SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
DEFAULT_DOCS_DIR = PROJECT_ROOT / "docs"
DEFAULT_SCHEMAS_DIR = PROJECT_ROOT / "shared" / "schemas"
DEFAULT_MODELS_DIR = PROJECT_ROOT / "models"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


# ---------------------------------------------------------------------
# Core configuration models
# ---------------------------------------------------------------------

@dataclass(slots=True)
class PathConfig:
    """
    Centralized filesystem paths for the GridSenpAI application.
    """

    project_root: Path = PROJECT_ROOT
    sample_data_dir: Path = DEFAULT_SAMPLE_DATA_DIR
    runs_dir: Path = DEFAULT_RUNS_DIR
    docs_dir: Path = DEFAULT_DOCS_DIR
    schemas_dir: Path = DEFAULT_SCHEMAS_DIR
    models_dir: Path = DEFAULT_MODELS_DIR

    def ensure_directories(self) -> None:
        """
        Create the directories the application expects to exist.
        Safe to call repeatedly.
        """
        for path in (
            self.sample_data_dir,
            self.runs_dir,
            self.docs_dir,
            self.schemas_dir,
            self.models_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, str]:
        return {
            "project_root": str(self.project_root),
            "sample_data_dir": str(self.sample_data_dir),
            "runs_dir": str(self.runs_dir),
            "docs_dir": str(self.docs_dir),
            "schemas_dir": str(self.schemas_dir),
            "models_dir": str(self.models_dir),
        }


@dataclass(slots=True)
class SchemaConfig:
    """
    Canonical schema versioning and expected schema file locations.
    """

    input_schema_version: str = "0.1.0"
    output_schema_version: str = "0.1.0"
    input_schema_file: str = "gridsenpai_inputs_schema.json"
    output_schema_file: str = "gridsenpai_outputs_schema.json"
    planner_required_fields_file: str = "planner_required_fields.json"

    def input_schema_path(self, paths: PathConfig) -> Path:
        return paths.schemas_dir / self.input_schema_file

    def output_schema_path(self, paths: PathConfig) -> Path:
        return paths.schemas_dir / self.output_schema_file

    def planner_required_fields_path(self, paths: PathConfig) -> Path:
        return paths.schemas_dir / self.planner_required_fields_file

    def primary_planner_contract_path(self, paths: PathConfig) -> Path:
        return self.planner_required_fields_path(paths)

    def to_dict(self, paths: PathConfig) -> dict[str, str]:
        return {
            "primary_planner_contract_path": str(self.primary_planner_contract_path(paths)),
            "planner_required_fields_path": str(self.planner_required_fields_path(paths)),
            "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version,
            "input_schema_path": str(self.input_schema_path(paths)),
            "output_schema_path": str(self.output_schema_path(paths)),
        }


@dataclass(slots=True)
class RetrievalConfig:
    """
    Retrieval settings for the application.
    These are local development defaults and can later map to deployment-specific services.
    """

    top_k: int = 5
    rerank: bool = False
    corpus_vendor: str = "equipment_catalog"
    corpus_modeling: str = "modeling_references"

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_k": self.top_k,
            "rerank": self.rerank,
            "corpus_vendor": self.corpus_vendor,
            "corpus_modeling": self.corpus_modeling,
        }


@dataclass(slots=True)
class ModelConfig:
    """
    Model and prompt-related configuration for governed runs.

    ``prompt_template_version`` is a run-trace label for the active governed
    prompt contract used by the bounded-assist runtime.

    ``model_version`` is a run-trace label for the active model backend or
    deterministic mode. When not explicitly provided, it is inferred from the
    configured local runtime so run artifacts reflect the real execution path
    instead of a placeholder string.
    """

    prompt_template_version: str = "governed-field-resolution-v1"
    model_version: str = "runtime-inferred"
    allow_model_assistance: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_template_version": self.prompt_template_version,
            "model_version": self.model_version,
            "allow_model_assistance": self.allow_model_assistance,
        }


@dataclass(slots=True)
class LLMRuntimeConfigModel:
    """
    Runtime configuration for local llama.cpp inference or IBM watsonx.ai chat inference.
    """

    enabled: bool = False
    provider: str = "llama_cpp"
    model_path: str = ""
    model_alias: str = "local-qwen"
    n_ctx: int = 8192
    n_threads: int = 12
    n_batch: int = 512
    n_gpu_layers: int = 40
    temperature: float = 0.1
    top_p: float = 0.95
    max_tokens: int = 512
    watsonx_url: str = "https://us-south.ml.cloud.ibm.com"
    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    watsonx_space_id: str = ""
    watsonx_model_id: str = "ibm/granite-3-3-8b-instruct"
    watsonx_api_version: str = "2024-10-08"
    watsonx_iam_url: str = "https://iam.cloud.ibm.com/identity/token"
    watsonx_time_limit_ms: int = 10000

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model_path": self.model_path,
            "model_alias": self.model_alias,
            "n_ctx": self.n_ctx,
            "n_threads": self.n_threads,
            "n_batch": self.n_batch,
            "n_gpu_layers": self.n_gpu_layers,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "watsonx_url": self.watsonx_url,
            "watsonx_project_id": self.watsonx_project_id,
            "watsonx_space_id": self.watsonx_space_id,
            "watsonx_model_id": self.watsonx_model_id,
            "watsonx_api_version": self.watsonx_api_version,
            "watsonx_iam_url": self.watsonx_iam_url,
            "watsonx_time_limit_ms": self.watsonx_time_limit_ms,
            "watsonx_api_key_configured": bool(self.watsonx_api_key),
        }


@dataclass(slots=True)
class RuntimeArchitectureConfig:
    """
    Revamp-aligned runtime architecture contract for the active production spine.
    This is descriptive governance metadata, not a stage executor.
    """

    public_spine: tuple[str, ...] = (
        "ingestion",
        "extraction",
        "normalization",
        "gap_resolution",
        "validation",
        "canonical_state",
        "translation",
        "scenarios",
        "export",
    )
    gap_resolution_substages: tuple[str, ...] = (
        "gap_resolution::retrieval",
        "gap_resolution::interview",
    )
    active_bounded_assist_backend: str = "agent_runtime_service"
    inactive_compatibility_layers: tuple[str, ...] = ()
    canonical_knowledge_families: tuple[str, ...] = (
        "equipment_catalog",
        "vendor_documents",
        "modeling_references",
        "interconnection_guidance",
    )
    legacy_knowledge_fallbacks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "public_spine": list(self.public_spine),
            "gap_resolution_substages": list(self.gap_resolution_substages),
            "active_bounded_assist_backend": self.active_bounded_assist_backend,
            "inactive_compatibility_layers": list(self.inactive_compatibility_layers),
            "canonical_knowledge_families": list(self.canonical_knowledge_families),
            "legacy_knowledge_fallbacks": list(self.legacy_knowledge_fallbacks),
        }


@dataclass(slots=True)
class LoggingConfig:
    """
    Logging configuration for local development.
    """

    level: str = "INFO"
    logger_name: str = "gridsenpai"

    def to_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "logger_name": self.logger_name,
        }



@dataclass(slots=True)
class AgentBudgetConfig:
    """
    Bounded-assist prompt packet budgets.

    These limits are intentionally separate from the LLM model context window.
    The model may support a large context, but GridSenpAI agents should receive
    scoped, reviewable packets rather than raw run artifacts.
    """

    max_prompt_chars: int = 24000
    max_response_chars: int = 2500
    max_packet_fields: int = 25
    max_evidence_chars: int = 1200
    document_interpretation_max_prompt_chars: int = 16000
    evidence_resolution_max_prompt_chars: int = 20000
    adjudication_support_max_prompt_chars: int = 24000
    applicant_interview_max_prompt_chars: int = 16000
    planner_support_max_prompt_chars: int = 24000

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_prompt_chars": self.max_prompt_chars,
            "max_response_chars": self.max_response_chars,
            "max_packet_fields": self.max_packet_fields,
            "max_evidence_chars": self.max_evidence_chars,
            "document_interpretation_max_prompt_chars": self.document_interpretation_max_prompt_chars,
            "evidence_resolution_max_prompt_chars": self.evidence_resolution_max_prompt_chars,
            "adjudication_support_max_prompt_chars": self.adjudication_support_max_prompt_chars,
            "applicant_interview_max_prompt_chars": self.applicant_interview_max_prompt_chars,
            "planner_support_max_prompt_chars": self.planner_support_max_prompt_chars,
        }


@dataclass(slots=True)
class OCRConfig:
    """
    OCR configuration for PaddleOCR model selection and rasterization behavior.

    ``enabled`` is intentionally separate from LLM runtime configuration so
    pytest can disable OCR provider initialization without changing normal
    ``python -m app.main`` behavior or editing the local .env file.
    """

    enabled: bool = True
    lang: str = "en"
    render_scale: float = 2.0
    text_detection_model_name: str = "PP-OCRv5_server_det"
    text_recognition_model_name: str = "PP-OCRv5_server_rec"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "lang": self.lang,
            "render_scale": self.render_scale,
            "text_detection_model_name": self.text_detection_model_name,
            "text_recognition_model_name": self.text_recognition_model_name,
        }


@dataclass(slots=True)
class AppConfig:
    """
    Master application configuration for GridSenpAI.

    This file is intended to become the single place to manage:
    - local paths
    - schema versions
    - retrieval defaults
    - model / prompt settings
    - future Watson integration mappings
    """

    project_name: str = ""
    environment: str = "local-dev"
    paths: PathConfig = field(default_factory=PathConfig)
    schemas: SchemaConfig = field(default_factory=SchemaConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    llm_runtime: LLMRuntimeConfigModel = field(default_factory=LLMRuntimeConfigModel)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    agent_budgets: AgentBudgetConfig = field(default_factory=AgentBudgetConfig)
    runtime_architecture: RuntimeArchitectureConfig = field(default_factory=RuntimeArchitectureConfig)

    def initialize(self) -> None:
        """
        Ensure required local directories exist.
        """
        self.paths.ensure_directories()

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "environment": self.environment,
            "paths": self.paths.to_dict(),
            "schemas": self.schemas.to_dict(self.paths),
            "retrieval": self.retrieval.to_dict(),
            "model": self.model.to_dict(),
            "llm_runtime": self.llm_runtime.to_dict(),
            "logging": self.logging.to_dict(),
            "ocr": self.ocr.to_dict(),
            "agent_budgets": self.agent_budgets.to_dict(),
            "runtime_architecture": self.runtime_architecture.to_dict(),
        }


# ---------------------------------------------------------------------
# Environment variable helpers
# ---------------------------------------------------------------------

def _strip_wrapping_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped


def _load_env_file(env_path: Path | None = None) -> None:
    path = DEFAULT_ENV_FILE if env_path is None else Path(env_path)
    if not path.exists() or not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, _strip_wrapping_quotes(raw_value))


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value is not None else default



def infer_model_version(llm_runtime: "LLMRuntimeConfigModel") -> str:
    """Return a stable run-provenance label for the active runtime path."""

    if not llm_runtime.enabled:
        return "deterministic-governed-runtime"

    provider = str(getattr(llm_runtime, "provider", "llama_cpp") or "llama_cpp").strip() or "llama_cpp"
    provider_label = "llama-cpp" if provider == "llama_cpp" else provider
    alias = (llm_runtime.model_alias or "").strip()
    if alias:
        return f"{provider_label}::{alias}"

    model_path = (llm_runtime.model_path or "").strip()
    if model_path:
        return f"{provider_label}::{Path(model_path).stem}"

    return f"{provider_label}::unlabeled-runtime"


def load_config() -> AppConfig:
    """
    Load application configuration with optional environment overrides.

    Supported environment variables:
    - GRIDSENPAI_ENV
    - GRIDSENPAI_LOG_LEVEL
    - GRIDSENPAI_TOP_K
    - GRIDSENPAI_RERANK
    - GRIDSENPAI_ALLOW_MODEL_ASSISTANCE
    - GRIDSENPAI_MODEL_VERSION
    - GRIDSENPAI_PROMPT_TEMPLATE_VERSION
    - GRIDSENPAI_OCR_RUNTIME_ENABLED
    - GRIDSENPAI_OCR_LANG
    - GRIDSENPAI_OCR_RENDER_SCALE
    - GRIDSENPAI_OCR_TEXT_DETECTION_MODEL
    - GRIDSENPAI_OCR_TEXT_RECOGNITION_MODEL
    - GRIDSENPAI_AGENT_MAX_PROMPT_CHARS
    - GRIDSENPAI_AGENT_MAX_PACKET_FIELDS
    - GRIDSENPAI_AGENT_MAX_EVIDENCE_CHARS

    LLM runtime environment variables:
    - GRIDSENPAI_LLM_RUNTIME_ENABLED
    - GRIDSENPAI_LLM_PROVIDER
    - GRIDSENPAI_LLM_MODEL_PATH
    - GRIDSENPAI_LLM_MODEL_ALIAS
    - GRIDSENPAI_LLM_N_CTX
    - GRIDSENPAI_LLM_N_THREADS
    - GRIDSENPAI_LLM_N_BATCH
    - GRIDSENPAI_LLM_N_GPU_LAYERS
    - GRIDSENPAI_LLM_TEMPERATURE
    - GRIDSENPAI_LLM_TOP_P
    - GRIDSENPAI_LLM_MAX_TOKENS
    - GRIDSENPAI_WATSONX_URL
    - GRIDSENPAI_WATSONX_API_KEY
    - GRIDSENPAI_WATSONX_PROJECT_ID
    - GRIDSENPAI_WATSONX_SPACE_ID
    - GRIDSENPAI_WATSONX_MODEL_ID
    - GRIDSENPAI_WATSONX_API_VERSION
    - GRIDSENPAI_WATSONX_IAM_URL
    - GRIDSENPAI_WATSONX_TIME_LIMIT_MS
    """

    _load_env_file()

    llm_runtime = LLMRuntimeConfigModel(
        enabled=_env_bool("GRIDSENPAI_LLM_RUNTIME_ENABLED", False),
        provider=_env_str("GRIDSENPAI_LLM_PROVIDER", "llama_cpp"),
        model_path=_env_str("GRIDSENPAI_LLM_MODEL_PATH", ""),
        model_alias=_env_str("GRIDSENPAI_LLM_MODEL_ALIAS", "local-qwen"),
        n_ctx=_env_int("GRIDSENPAI_LLM_N_CTX", 8192),
        n_threads=_env_int("GRIDSENPAI_LLM_N_THREADS", 12),
        n_batch=_env_int("GRIDSENPAI_LLM_N_BATCH", 512),
        n_gpu_layers=_env_int("GRIDSENPAI_LLM_N_GPU_LAYERS", 40),
        temperature=_env_float("GRIDSENPAI_LLM_TEMPERATURE", 0.1),
        top_p=_env_float("GRIDSENPAI_LLM_TOP_P", 0.95),
        max_tokens=_env_int("GRIDSENPAI_LLM_MAX_TOKENS", 512),
        watsonx_url=_env_str("GRIDSENPAI_WATSONX_URL", "https://us-south.ml.cloud.ibm.com"),
        watsonx_api_key=_env_str("GRIDSENPAI_WATSONX_API_KEY", ""),
        watsonx_project_id=_env_str("GRIDSENPAI_WATSONX_PROJECT_ID", ""),
        watsonx_space_id=_env_str("GRIDSENPAI_WATSONX_SPACE_ID", ""),
        watsonx_model_id=_env_str("GRIDSENPAI_WATSONX_MODEL_ID", "ibm/granite-3-3-8b-instruct"),
        watsonx_api_version=_env_str("GRIDSENPAI_WATSONX_API_VERSION", "2024-10-08"),
        watsonx_iam_url=_env_str("GRIDSENPAI_WATSONX_IAM_URL", "https://iam.cloud.ibm.com/identity/token"),
        watsonx_time_limit_ms=_env_int("GRIDSENPAI_WATSONX_TIME_LIMIT_MS", 10000),
    )

    config = AppConfig(
        environment=_env_str("GRIDSENPAI_ENV", "local-dev"),
        retrieval=RetrievalConfig(
            top_k=_env_int("GRIDSENPAI_TOP_K", 5),
            rerank=_env_bool("GRIDSENPAI_RERANK", False),
            corpus_vendor=_env_str(
                "GRIDSENPAI_VENDOR_CORPUS",
                "equipment_catalog",
            ),
            corpus_modeling=_env_str(
                "GRIDSENPAI_MODELING_CORPUS",
                "modeling_references",
            ),
        ),
        model=ModelConfig(
            prompt_template_version=_env_str(
                "GRIDSENPAI_PROMPT_TEMPLATE_VERSION",
                "governed-field-resolution-v1",
            ),
            model_version=_env_str(
                "GRIDSENPAI_MODEL_VERSION",
                infer_model_version(llm_runtime),
            ),
            allow_model_assistance=_env_bool(
                "GRIDSENPAI_ALLOW_MODEL_ASSISTANCE",
                False,
            ),
        ),
        llm_runtime=llm_runtime,
        logging=LoggingConfig(
            level=_env_str("GRIDSENPAI_LOG_LEVEL", "INFO"),
            logger_name=_env_str("GRIDSENPAI_LOGGER_NAME", "gridsenpai"),
        ),
        ocr=OCRConfig(
            enabled=_env_bool("GRIDSENPAI_OCR_RUNTIME_ENABLED", True),
            lang=_env_str("GRIDSENPAI_OCR_LANG", "en"),
            render_scale=_env_float("GRIDSENPAI_OCR_RENDER_SCALE", 2.0),
            text_detection_model_name=_env_str("GRIDSENPAI_OCR_TEXT_DETECTION_MODEL", "PP-OCRv5_server_det"),
            text_recognition_model_name=_env_str("GRIDSENPAI_OCR_TEXT_RECOGNITION_MODEL", "PP-OCRv5_server_rec"),
        ),
        agent_budgets=AgentBudgetConfig(
            max_prompt_chars=_env_int("GRIDSENPAI_AGENT_MAX_PROMPT_CHARS", 24000),
            max_response_chars=_env_int("GRIDSENPAI_AGENT_MAX_RESPONSE_CHARS", 2500),
            max_packet_fields=_env_int("GRIDSENPAI_AGENT_MAX_PACKET_FIELDS", 25),
            max_evidence_chars=_env_int("GRIDSENPAI_AGENT_MAX_EVIDENCE_CHARS", 1200),
            document_interpretation_max_prompt_chars=_env_int("GRIDSENPAI_DOCUMENT_AGENT_MAX_PROMPT_CHARS", _env_int("GRIDSENPAI_AGENT_MAX_PROMPT_CHARS", 24000)),
            evidence_resolution_max_prompt_chars=_env_int("GRIDSENPAI_EVIDENCE_AGENT_MAX_PROMPT_CHARS", _env_int("GRIDSENPAI_AGENT_MAX_PROMPT_CHARS", 24000)),
            adjudication_support_max_prompt_chars=_env_int("GRIDSENPAI_ADJUDICATION_AGENT_MAX_PROMPT_CHARS", _env_int("GRIDSENPAI_AGENT_MAX_PROMPT_CHARS", 24000)),
            applicant_interview_max_prompt_chars=_env_int("GRIDSENPAI_INTERVIEW_AGENT_MAX_PROMPT_CHARS", _env_int("GRIDSENPAI_AGENT_MAX_PROMPT_CHARS", 24000)),
            planner_support_max_prompt_chars=_env_int("GRIDSENPAI_PLANNER_AGENT_MAX_PROMPT_CHARS", _env_int("GRIDSENPAI_AGENT_MAX_PROMPT_CHARS", 24000)),
        ),
    )

    config.initialize()
    return config


# ---------------------------------------------------------------------
# Shared singleton-style config for app use
# ---------------------------------------------------------------------

CONFIG = load_config()


def apply_llm_runtime_overrides(
    *,
    enabled: bool | None = None,
    provider: str | None = None,
    model_path: str | Path | None = None,
    model_alias: str | None = None,
    n_ctx: int | None = None,
    n_batch: int | None = None,
    watsonx_url: str | None = None,
    watsonx_api_key: str | None = None,
    watsonx_project_id: str | None = None,
    watsonx_space_id: str | None = None,
    watsonx_model_id: str | None = None,
    watsonx_api_version: str | None = None,
    watsonx_iam_url: str | None = None,
) -> AppConfig:
    """Mutate the shared CONFIG singleton with runtime selections chosen at launch time."""

    runtime = CONFIG.llm_runtime
    if enabled is not None:
        runtime.enabled = bool(enabled)
    if provider is not None and str(provider).strip():
        runtime.provider = str(provider).strip()
    if model_path is not None:
        runtime.model_path = str(model_path).strip()
    if model_alias is not None and str(model_alias).strip():
        runtime.model_alias = str(model_alias).strip()
    if n_ctx is not None:
        runtime.n_ctx = int(n_ctx)
    if n_batch is not None:
        runtime.n_batch = int(n_batch)
    if watsonx_url is not None and str(watsonx_url).strip():
        runtime.watsonx_url = str(watsonx_url).strip()
    if watsonx_api_key is not None:
        runtime.watsonx_api_key = str(watsonx_api_key).strip()
    if watsonx_project_id is not None:
        runtime.watsonx_project_id = str(watsonx_project_id).strip()
    if watsonx_space_id is not None:
        runtime.watsonx_space_id = str(watsonx_space_id).strip()
    if watsonx_model_id is not None and str(watsonx_model_id).strip():
        runtime.watsonx_model_id = str(watsonx_model_id).strip()
    if watsonx_api_version is not None and str(watsonx_api_version).strip():
        runtime.watsonx_api_version = str(watsonx_api_version).strip()
    if watsonx_iam_url is not None and str(watsonx_iam_url).strip():
        runtime.watsonx_iam_url = str(watsonx_iam_url).strip()

    CONFIG.model.model_version = infer_model_version(runtime)
    return CONFIG
