from __future__ import annotations

from pathlib import Path

from app import config as config_module


def test_load_env_file_sets_values_without_overriding_existing_env(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
# comment
GRIDSENPAI_LLM_N_CTX=32768
GRIDSENPAI_LLM_PROVIDER=llama_cpp
export GRIDSENPAI_LLM_MODEL_ALIAS='granite-local'
GRIDSENPAI_LOG_LEVEL="DEBUG"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("GRIDSENPAI_LLM_N_CTX", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_MODEL_ALIAS", raising=False)
    monkeypatch.setenv("GRIDSENPAI_LOG_LEVEL", "INFO")

    config_module._load_env_file(env_file)

    assert config_module.os.environ["GRIDSENPAI_LLM_N_CTX"] == "32768"
    assert config_module.os.environ["GRIDSENPAI_LLM_PROVIDER"] == "llama_cpp"
    assert config_module.os.environ["GRIDSENPAI_LLM_MODEL_ALIAS"] == "granite-local"
    assert config_module.os.environ["GRIDSENPAI_LOG_LEVEL"] == "INFO"


def test_load_config_reads_project_dotenv(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
GRIDSENPAI_LLM_RUNTIME_ENABLED=true
GRIDSENPAI_LLM_PROVIDER=llama_cpp
GRIDSENPAI_LLM_MODEL_ALIAS=granite-local
GRIDSENPAI_LLM_N_CTX=32768
GRIDSENPAI_LLM_N_BATCH=512
GRIDSENPAI_LOG_LEVEL=DEBUG
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.delenv("GRIDSENPAI_LLM_RUNTIME_ENABLED", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_MODEL_ALIAS", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_N_CTX", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_N_BATCH", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LOG_LEVEL", raising=False)

    config = config_module.load_config()

    assert config.llm_runtime.enabled is True
    assert config.llm_runtime.provider == "llama_cpp"
    assert config.llm_runtime.model_alias == "granite-local"
    assert config.llm_runtime.n_ctx == 32768
    assert config.llm_runtime.n_batch == 512
    assert config.logging.level == "DEBUG"


def test_os_environment_overrides_dotenv(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GRIDSENPAI_LLM_N_CTX=32768\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.setenv("GRIDSENPAI_LLM_N_CTX", "16384")

    config = config_module.load_config()

    assert config.llm_runtime.n_ctx == 16384


def test_load_config_infers_model_version_from_runtime(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
GRIDSENPAI_LLM_RUNTIME_ENABLED=true
GRIDSENPAI_LLM_PROVIDER=llama_cpp
GRIDSENPAI_LLM_MODEL_ALIAS=granite-local
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.delenv("GRIDSENPAI_MODEL_VERSION", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_RUNTIME_ENABLED", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_MODEL_ALIAS", raising=False)

    config = config_module.load_config()

    assert config.model.model_version == "llama-cpp::granite-local"
    assert config.model.prompt_template_version == "governed-field-resolution-v1"


def test_load_config_honors_explicit_model_version_override(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
GRIDSENPAI_LLM_RUNTIME_ENABLED=true
GRIDSENPAI_LLM_PROVIDER=llama_cpp
GRIDSENPAI_LLM_MODEL_ALIAS=granite-local
GRIDSENPAI_MODEL_VERSION=granite-eval-build
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.delenv("GRIDSENPAI_MODEL_VERSION", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_RUNTIME_ENABLED", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GRIDSENPAI_LLM_MODEL_ALIAS", raising=False)

    config = config_module.load_config()

    assert config.model.model_version == "granite-eval-build"


def test_load_config_reads_watsonx_values_from_dotenv(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
GRIDSENPAI_LLM_RUNTIME_ENABLED=true
GRIDSENPAI_LLM_PROVIDER=ibm_watsonx
GRIDSENPAI_WATSONX_URL=https://us-south.ml.cloud.ibm.com
GRIDSENPAI_WATSONX_API_KEY=secret-key
GRIDSENPAI_WATSONX_PROJECT_ID=project-123
GRIDSENPAI_WATSONX_MODEL_ID=ibm/granite-3-3-8b-instruct
GRIDSENPAI_WATSONX_API_VERSION=2024-10-08
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", env_file)
    for name in [
        "GRIDSENPAI_LLM_RUNTIME_ENABLED",
        "GRIDSENPAI_LLM_PROVIDER",
        "GRIDSENPAI_WATSONX_URL",
        "GRIDSENPAI_WATSONX_API_KEY",
        "GRIDSENPAI_WATSONX_PROJECT_ID",
        "GRIDSENPAI_WATSONX_MODEL_ID",
        "GRIDSENPAI_WATSONX_API_VERSION",
        "GRIDSENPAI_MODEL_VERSION",
    ]:
        monkeypatch.delenv(name, raising=False)

    config = config_module.load_config()

    assert config.llm_runtime.provider == "ibm_watsonx"
    assert config.llm_runtime.watsonx_url == "https://us-south.ml.cloud.ibm.com"
    assert config.llm_runtime.watsonx_api_key == "secret-key"
    assert config.llm_runtime.watsonx_project_id == "project-123"
    assert config.llm_runtime.watsonx_model_id == "ibm/granite-3-3-8b-instruct"
    assert config.model.model_version.startswith("ibm_watsonx::")

def test_load_config_reads_ocr_model_overrides_from_dotenv(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
GRIDSENPAI_OCR_LANG=en
GRIDSENPAI_OCR_RENDER_SCALE=2.5
GRIDSENPAI_OCR_TEXT_DETECTION_MODEL=PP-OCRv5_server_det
GRIDSENPAI_OCR_TEXT_RECOGNITION_MODEL=PP-OCRv5_server_rec
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", env_file)
    for name in [
        "GRIDSENPAI_OCR_LANG",
        "GRIDSENPAI_OCR_RENDER_SCALE",
        "GRIDSENPAI_OCR_TEXT_DETECTION_MODEL",
        "GRIDSENPAI_OCR_TEXT_RECOGNITION_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)

    config = config_module.load_config()

    assert config.ocr.lang == "en"
    assert config.ocr.render_scale == 2.5
    assert config.ocr.text_detection_model_name == "PP-OCRv5_server_det"
    assert config.ocr.text_recognition_model_name == "PP-OCRv5_server_rec"


def test_load_config_reads_ocr_runtime_enabled(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GRIDSENPAI_OCR_RUNTIME_ENABLED=false\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.delenv("GRIDSENPAI_OCR_RUNTIME_ENABLED", raising=False)

    config = config_module.load_config()

    assert config.ocr.enabled is False
    assert config.ocr.to_dict()["enabled"] is False
