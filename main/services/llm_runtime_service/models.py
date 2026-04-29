from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LLMRuntimeConfig:
    model_path: str
    provider: str = "llama_cpp"
    model_alias: str = "local-gguf-model"
    chat_format: str = "chatml"
    n_ctx: int = 8192
    n_threads: int = 8
    n_batch: int = 512
    n_gpu_layers: int = 0
    temperature: float = 0.1
    top_p: float = 0.95
    top_k: int = 40
    max_tokens: int = 512
    repeat_penalty: float = 1.1
    seed: int = 42
    verbose: bool = False
    json_mode_default: bool = True
    stop: list[str] = field(default_factory=list)
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
            "provider": self.provider,
            "model_path": self.model_path,
            "model_alias": self.model_alias,
            "chat_format": self.chat_format,
            "n_ctx": self.n_ctx,
            "n_threads": self.n_threads,
            "n_batch": self.n_batch,
            "n_gpu_layers": self.n_gpu_layers,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": self.max_tokens,
            "repeat_penalty": self.repeat_penalty,
            "seed": self.seed,
            "verbose": self.verbose,
            "json_mode_default": self.json_mode_default,
            "stop": list(self.stop),
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
class LLMMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
        }


@dataclass(slots=True)
class LLMTaskRequest:
    task_name: str
    prompt_template_id: str
    system_prompt: str
    user_prompt: str
    response_schema: dict[str, Any] = field(default_factory=dict)
    messages: list[LLMMessage] = field(default_factory=list)
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    repeat_penalty: float | None = None
    stop: list[str] = field(default_factory=list)
    json_mode: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_name": self.task_name,
            "prompt_template_id": self.prompt_template_id,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "response_schema": dict(self.response_schema),
            "messages": [message.to_dict() for message in self.messages],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
            "stop": list(self.stop),
            "json_mode": self.json_mode,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class LLMInvocationRecord:
    invocation_id: str
    run_id: str
    task_name: str
    prompt_template_id: str
    model_alias: str
    provider: str
    model_path: str
    started_at: str
    completed_at: str
    duration_ms: int
    success: bool
    json_mode: bool
    input_token_estimate: int = 0
    output_token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "run_id": self.run_id,
            "task_name": self.task_name,
            "prompt_template_id": self.prompt_template_id,
            "model_alias": self.model_alias,
            "provider": self.provider,
            "model_path": self.model_path,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "json_mode": self.json_mode,
            "input_token_estimate": self.input_token_estimate,
            "output_token_estimate": self.output_token_estimate,
            "metadata": dict(self.metadata),
        }



@dataclass(slots=True)
class LLMRuntimeResult:
    run_id: str
    status: str
    invocation: LLMInvocationRecord
    raw_text: str
    parsed_json: dict[str, Any] | list[Any] | None = None
    parse_error: str = ""
    finish_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "invocation": self.invocation.to_dict(),
            "raw_text": self.raw_text,
            "parsed_json": self.parsed_json,
            "parse_error": self.parse_error,
            "finish_reason": self.finish_reason,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }