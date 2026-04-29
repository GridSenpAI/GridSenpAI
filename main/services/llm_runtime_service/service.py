from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

if TYPE_CHECKING:
    from llama_cpp import Llama


def _skip_llama_cpp_import_for_pytest() -> bool:
    """Keep pytest from importing llama-cpp native backend libraries.

    Importing llama-cpp-python can touch native/CUDA backend code even when no GGUF
    model is loaded. Pytest sets GRIDSENPAI_TEST_MODE=true and disables the LLM
    runtime in tests/conftest.py, so the runtime service should stay inert unless a
    test explicitly monkeypatches the runtime objects.
    """

    test_mode = str(os.environ.get("GRIDSENPAI_TEST_MODE", "") or "").strip().lower()
    runtime_enabled = str(os.environ.get("GRIDSENPAI_LLM_RUNTIME_ENABLED", "") or "").strip().lower()
    return test_mode in {"1", "true", "yes", "on"} and runtime_enabled not in {"1", "true", "yes", "on"}


if _skip_llama_cpp_import_for_pytest():
    llama_cpp_module = None
    LlamaRuntime = None
else:
    try:
        import llama_cpp as llama_cpp_module
        from llama_cpp import Llama as LlamaRuntime
    except ModuleNotFoundError:  # pragma: no cover - optional local runtime dependency
        llama_cpp_module = None
        LlamaRuntime = None

from services.audit_logging_service.service import initialize_audit_logger
from services.llm_runtime_service.models import (
    LLMInvocationRecord,
    LLMRuntimeConfig,
    LLMRuntimeResult,
    LLMTaskRequest,
)
from services.llm_runtime_service.utils import (
    apply_response_schema_hint,
    build_invocation_id,
    coerce_messages,
    elapsed_ms,
    estimate_message_token_count,
    estimate_token_count,
    extract_text_from_completion_response,
    messages_to_chat_payload,
    monotonic_ms,
    try_parse_json,
    utc_now_iso,
)


# ---------------------------------------------------------
# GLOBAL MODEL INSTANCE (single runtime for whole system)
# ---------------------------------------------------------

_model_lock = threading.Lock()
_model_instance: Any | None = None
_model_config: LLMRuntimeConfig | None = None


_watsonx_token_lock = threading.Lock()
_watsonx_token_cache: dict[str, Any] = {"api_key": "", "iam_url": "", "access_token": "", "expires_at": 0.0}


_runtime_diagnostics_lock = threading.Lock()
_runtime_diagnostics: dict[str, Any] = {
    "llama_cpp_module_available": llama_cpp_module is not None,
    "runtime_initialize_attempted": False,
    "runtime_initialized": False,
    "runtime_initialize_error": "",
    "provider": "",
    "model_path": "",
    "model_path_exists": False,
    "model_alias": "",
    "requested_n_ctx": 0,
    "requested_n_threads": 0,
    "requested_n_batch": 0,
    "requested_n_gpu_layers": 0,
    "gpu_offload_requested": False,
    "gpu_offload_supported": None,
    "gpu_offload_confirmed": None,
    "llama_system_info": "",
    "local_invocation_count": 0,
    "local_invocation_success_count": 0,
    "local_invocation_error_count": 0,
    "last_invocation_at": "",
}


def _safe_bool_call(target: Any, name: str) -> bool | None:
    try:
        fn = getattr(target, name, None)
        if fn is None:
            return None
        return bool(fn())
    except Exception:
        return None


def _safe_system_info() -> str:
    try:
        if llama_cpp_module is None:
            return ""
        fn = getattr(llama_cpp_module, "llama_print_system_info", None)
        if fn is None:
            return ""
        payload = fn()
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="ignore").strip()
        return str(payload or "").strip()
    except Exception:
        return ""


def _update_runtime_diagnostics(**updates: Any) -> None:
    with _runtime_diagnostics_lock:
        _runtime_diagnostics.update(updates)


def _mark_local_invocation(*, success: bool) -> None:
    with _runtime_diagnostics_lock:
        _runtime_diagnostics["local_invocation_count"] = int(_runtime_diagnostics.get("local_invocation_count", 0)) + 1
        if success:
            _runtime_diagnostics["local_invocation_success_count"] = int(_runtime_diagnostics.get("local_invocation_success_count", 0)) + 1
        else:
            _runtime_diagnostics["local_invocation_error_count"] = int(_runtime_diagnostics.get("local_invocation_error_count", 0)) + 1
        _runtime_diagnostics["last_invocation_at"] = utc_now_iso()


def get_runtime_diagnostics() -> dict[str, Any]:
    with _runtime_diagnostics_lock:
        payload = dict(_runtime_diagnostics)

    payload["provider"] = str(payload.get("provider", "") or "")
    payload["configured_model_path"] = payload.get("model_path", "")
    payload["configured_model_path_exists"] = bool(payload.get("model_path_exists", False))
    payload["gpu_offload_requested"] = bool(payload.get("gpu_offload_requested", False))
    payload["gpu_offload_active"] = payload.get("gpu_offload_confirmed")
    payload["gpu_offload_confirmation_source"] = str(payload.get("gpu_offload_confirmation_source", "") or "")
    payload["local_invocation_count"] = int(payload.get("local_invocation_count", 0))
    payload["local_invocation_success_count"] = int(payload.get("local_invocation_success_count", 0))
    payload["local_invocation_error_count"] = int(payload.get("local_invocation_error_count", 0))
    return payload


def reset_runtime_diagnostics_for_tests() -> None:
    global _model_instance
    global _model_config
    global _watsonx_token_cache
    with _model_lock:
        _model_instance = None
        _model_config = None
    with _watsonx_token_lock:
        _watsonx_token_cache = {"api_key": "", "iam_url": "", "access_token": "", "expires_at": 0.0}
    with _runtime_diagnostics_lock:
        _runtime_diagnostics.clear()
        _runtime_diagnostics.update({
            "llama_cpp_module_available": llama_cpp_module is not None,
            "runtime_initialize_attempted": False,
            "runtime_initialized": False,
            "runtime_initialize_error": "",
            "provider": "",
            "model_path": "",
            "model_path_exists": False,
            "model_alias": "",
            "requested_n_ctx": 0,
            "requested_n_threads": 0,
            "requested_n_batch": 0,
            "requested_n_gpu_layers": 0,
            "gpu_offload_requested": False,
            "gpu_offload_supported": _safe_bool_call(llama_cpp_module, "llama_supports_gpu_offload") if llama_cpp_module is not None else None,
            "gpu_offload_confirmed": None,
            "gpu_offload_confirmation_source": "reset_for_tests",
            "llama_system_info": _safe_system_info(),
            "local_invocation_count": 0,
            "local_invocation_success_count": 0,
            "local_invocation_error_count": 0,
            "last_invocation_at": "",
        })


reset_runtime_diagnostics_for_tests()


# ---------------------------------------------------------
# MODEL LOADER
# ---------------------------------------------------------


def initialize_runtime(config: LLMRuntimeConfig) -> None:
    global _model_instance
    global _model_config
    global _watsonx_token_cache

    model_path = str(config.model_path or "").strip()
    _update_runtime_diagnostics(
        runtime_initialize_attempted=True,
        runtime_initialize_error="",
        provider=str(config.provider or "llama_cpp").strip(),
        model_path=model_path,
        model_path_exists=Path(model_path).exists() if model_path else False,
        model_alias=str(config.model_alias or "").strip(),
        requested_n_ctx=int(config.n_ctx),
        requested_n_threads=int(config.n_threads),
        requested_n_batch=int(config.n_batch),
        requested_n_gpu_layers=int(config.n_gpu_layers),
        gpu_offload_requested=bool(int(config.n_gpu_layers) > 0),
        gpu_offload_supported=_safe_bool_call(llama_cpp_module, "llama_supports_gpu_offload") if llama_cpp_module is not None else None,
        llama_system_info=_safe_system_info(),
        gpu_offload_confirmation_source="initialization_requested",
    )

    with _model_lock:
        if _model_instance is not None:
            _update_runtime_diagnostics(runtime_initialized=True)
            return

        provider = str(config.provider or "llama_cpp").strip() or "llama_cpp"
        if provider == "ibm_watsonx":
            if not str(config.watsonx_url or "").strip():
                message = "IBM watsonx provider requires GRIDSENPAI_WATSONX_URL."
                _update_runtime_diagnostics(runtime_initialized=False, runtime_initialize_error=message)
                raise RuntimeError(message)
            if not str(config.watsonx_api_key or "").strip():
                message = "IBM watsonx provider requires GRIDSENPAI_WATSONX_API_KEY."
                _update_runtime_diagnostics(runtime_initialized=False, runtime_initialize_error=message)
                raise RuntimeError(message)
            if not str(config.watsonx_model_id or "").strip():
                message = "IBM watsonx provider requires GRIDSENPAI_WATSONX_MODEL_ID."
                _update_runtime_diagnostics(runtime_initialized=False, runtime_initialize_error=message)
                raise RuntimeError(message)
            if not (str(config.watsonx_project_id or "").strip() or str(config.watsonx_space_id or "").strip()):
                message = "IBM watsonx provider requires GRIDSENPAI_WATSONX_PROJECT_ID or GRIDSENPAI_WATSONX_SPACE_ID."
                _update_runtime_diagnostics(runtime_initialized=False, runtime_initialize_error=message)
                raise RuntimeError(message)
            _model_instance = {"provider": "ibm_watsonx"}
            _model_config = config
            _update_runtime_diagnostics(
                runtime_initialized=True,
                gpu_offload_confirmed=False,
                gpu_offload_confirmation_source="not_applicable_remote_provider",
            )
            return
        if provider != "llama_cpp":
            message = f"Unsupported LLM provider '{provider}'. Supported providers are 'llama_cpp' and 'ibm_watsonx'."
            _update_runtime_diagnostics(runtime_initialized=False, runtime_initialize_error=message)
            raise RuntimeError(message)

        if LlamaRuntime is None:
            message = "llama_cpp is not installed. Local LLM runtime is unavailable."
            _update_runtime_diagnostics(runtime_initialized=False, runtime_initialize_error=message)
            raise RuntimeError(message)

        try:
            _model_instance = LlamaRuntime(
                model_path=config.model_path,
                n_ctx=config.n_ctx,
                n_threads=config.n_threads,
                n_batch=config.n_batch,
                n_gpu_layers=config.n_gpu_layers,
                verbose=config.verbose,
            )
        except Exception as exc:
            _update_runtime_diagnostics(runtime_initialized=False, runtime_initialize_error=str(exc))
            raise

        _model_config = config
        requested_gpu_layers = int(config.n_gpu_layers)
        gpu_supported = _safe_bool_call(llama_cpp_module, "llama_supports_gpu_offload")
        if requested_gpu_layers <= 0:
            gpu_offload_confirmed = False
            confirmation_source = "n_gpu_layers_not_requested"
        elif gpu_supported is False:
            gpu_offload_confirmed = False
            confirmation_source = "llama_supports_gpu_offload_false"
        elif gpu_supported is True:
            # llama-cpp-python does not expose an exact per-layer offload counter
            # in a stable API.  Successful construction with n_gpu_layers > 0 and
            # a GPU-capable backend is the strongest deterministic confirmation
            # available without parsing native stderr.
            gpu_offload_confirmed = True
            confirmation_source = "runtime_initialized_with_gpu_capable_backend_and_n_gpu_layers_requested"
        else:
            gpu_offload_confirmed = None
            confirmation_source = "provider_did_not_report_gpu_support"
        _update_runtime_diagnostics(
            runtime_initialized=True,
            gpu_offload_supported=gpu_supported,
            gpu_offload_confirmed=gpu_offload_confirmed,
            gpu_offload_confirmation_source=confirmation_source,
        )


def get_runtime_config() -> LLMRuntimeConfig:
    if _model_config is None:
        raise RuntimeError("LLM runtime has not been initialized.")
    return _model_config


def get_model() -> Any:
    if _model_instance is None:
        raise RuntimeError("LLM runtime has not been initialized.")
    return _model_instance


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _hash_payload(value: Any) -> str:
    serialized = json.dumps(_json_safe(value), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _safe_initialize_audit_logger(context: Any) -> Any | None:
    if context is None:
        return None

    try:
        return initialize_audit_logger(context)
    except Exception:
        return None


def _build_request_audit_metadata(
    *,
    request: LLMTaskRequest,
    message_payload: list[dict[str, str]],
    json_mode: bool,
    temperature: float,
    top_p: float,
    top_k: int,
    repeat_penalty: float,
    max_tokens: int,
    stop: list[str],
) -> dict[str, Any]:
    request_dict = request.to_dict()

    return {
        "task_name": request.task_name,
        "prompt_template_id": request.prompt_template_id,
        "json_mode": json_mode,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "repeat_penalty": repeat_penalty,
        "max_tokens": max_tokens,
        "stop": list(stop),
        "request_metadata": dict(request.metadata),
        "request_hash": _hash_payload(request_dict),
        "message_payload_hash": _hash_payload(message_payload),
        "message_count": len(message_payload),
        "response_schema_hash": _hash_payload(request.response_schema),
    }



def _build_watsonx_messages(message_payload: list[dict[str, str]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in message_payload:
        role = str(message.get("role", "user") or "user").strip().lower() or "user"
        content = str(message.get("content", "") or "")
        if role == "user":
            normalized.append({"role": role, "content": [{"type": "text", "text": content}]})
        else:
            normalized.append({"role": role, "content": content})
    return normalized


def _get_watsonx_bearer_token(config: LLMRuntimeConfig) -> str:
    api_key = str(config.watsonx_api_key or "").strip()
    iam_url = str(config.watsonx_iam_url or "https://iam.cloud.ibm.com/identity/token").strip()
    now = time.time()
    with _watsonx_token_lock:
        if (
            api_key
            and str(_watsonx_token_cache.get("api_key", "") or "") == api_key
            and str(_watsonx_token_cache.get("iam_url", "") or "") == iam_url
            and str(_watsonx_token_cache.get("access_token", "") or "")
            and now < float(_watsonx_token_cache.get("expires_at", 0.0) or 0.0) - 60.0
        ):
            return str(_watsonx_token_cache.get("access_token", "") or "")

    payload = urllib_parse.urlencode({
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": api_key,
    }).encode("utf-8")
    req = urllib_request.Request(
        iam_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"IBM watsonx IAM token request failed with HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"IBM watsonx IAM token request failed: {exc}") from exc

    payload_json = json.loads(body)
    access_token = str(payload_json.get("access_token", "") or "").strip()
    if not access_token:
        raise RuntimeError("IBM watsonx IAM token response did not include access_token.")
    expires_in = int(payload_json.get("expires_in", 3600) or 3600)
    with _watsonx_token_lock:
        _watsonx_token_cache.update({
            "api_key": api_key,
            "iam_url": iam_url,
            "access_token": access_token,
            "expires_at": time.time() + max(expires_in, 60),
        })
    return access_token


def _invoke_watsonx_chat_completion(*, config: LLMRuntimeConfig, message_payload: list[dict[str, str]], max_tokens: int, temperature: float, top_p: float) -> dict[str, Any]:
    token = _get_watsonx_bearer_token(config)
    endpoint = f"{str(config.watsonx_url).rstrip('/')}/ml/v1/text/chat?version={urllib_parse.quote(str(config.watsonx_api_version or '2024-10-08'), safe='')}"
    payload: dict[str, Any] = {
        "model_id": str(config.watsonx_model_id or "").strip(),
        "messages": _build_watsonx_messages(message_payload),
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "top_p": float(top_p),
        "time_limit": int(config.watsonx_time_limit_ms),
    }
    project_id = str(config.watsonx_project_id or "").strip()
    space_id = str(config.watsonx_space_id or "").strip()
    if project_id:
        payload["project_id"] = project_id
    elif space_id:
        payload["space_id"] = space_id
    else:
        raise RuntimeError("IBM watsonx runtime requires a project_id or space_id.")

    req = urllib_request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=max(30, int(config.watsonx_time_limit_ms / 1000) + 15)) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"IBM watsonx chat request failed with HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"IBM watsonx chat request failed: {exc}") from exc
    return json.loads(body)


# ---------------------------------------------------------
# MAIN INFERENCE ENTRYPOINT
# ---------------------------------------------------------


def run_llm_task(
    *,
    run_id: str,
    request: LLMTaskRequest,
    context: Any | None = None,
) -> LLMRuntimeResult:
    config = get_runtime_config()
    model = get_model() if str(config.provider or "llama_cpp").strip() == "llama_cpp" else None

    start_time = utc_now_iso()
    start_ms = monotonic_ms()

    invocation_id = build_invocation_id()

    json_mode = request.json_mode
    if json_mode is None:
        json_mode = config.json_mode_default

    system_prompt, user_prompt = apply_response_schema_hint(
        system_prompt=request.system_prompt,
        user_prompt=request.user_prompt,
        response_schema=request.response_schema,
        json_mode=json_mode,
    )

    messages = coerce_messages(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        messages=request.messages,
    )

    message_payload = messages_to_chat_payload(messages)

    temperature = request.temperature if request.temperature is not None else config.temperature
    top_p = request.top_p if request.top_p is not None else config.top_p
    top_k = request.top_k if request.top_k is not None else config.top_k
    repeat_penalty = (
        request.repeat_penalty if request.repeat_penalty is not None else config.repeat_penalty
    )
    max_tokens = request.max_tokens if request.max_tokens is not None else config.max_tokens
    stop = request.stop if request.stop else config.stop

    audit_logger = _safe_initialize_audit_logger(context)
    request_audit_metadata = _build_request_audit_metadata(
        request=request,
        message_payload=message_payload,
        json_mode=json_mode,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repeat_penalty=repeat_penalty,
        max_tokens=max_tokens,
        stop=stop,
    )

    if audit_logger is not None:
        audit_logger.log_event(
            event_type="llm_invocation_start",
            stage_name=str(request.metadata.get("stage_name", "")).strip() or None,
            substage_name=str(request.metadata.get("task_name", request.task_name)).strip() or None,
            status="STARTED",
            message=f"Starting LLM task '{request.task_name}'.",
            metadata={
                "invocation_id": invocation_id,
                "model_alias": config.model_alias,
                **request_audit_metadata,
            },
        )

    try:
        provider = str(config.provider or "llama_cpp").strip() or "llama_cpp"
        if provider == "ibm_watsonx":
            response = _invoke_watsonx_chat_completion(
                config=config,
                message_payload=message_payload,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
        else:
            response = model.create_chat_completion(
                messages=message_payload,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repeat_penalty,
                max_tokens=max_tokens,
                stop=stop,
                seed=config.seed,
            )

        raw_text, finish_reason = extract_text_from_completion_response(response)

        parsed_json = None
        parse_error = ""

        if json_mode:
            parsed_json, parse_error = try_parse_json(raw_text)

        success = True

    except Exception as exc:
        raw_text = ""
        parsed_json = None
        parse_error = str(exc)
        finish_reason = ""
        success = False

    end_time = utc_now_iso()
    duration = elapsed_ms(start_ms)

    input_tokens = estimate_message_token_count(messages)
    output_tokens = estimate_token_count(raw_text)

    invocation = LLMInvocationRecord(
        invocation_id=invocation_id,
        run_id=run_id,
        task_name=request.task_name,
        prompt_template_id=request.prompt_template_id,
        model_alias=config.model_alias,
        provider=config.provider,
        model_path=config.model_path,
        started_at=start_time,
        completed_at=end_time,
        duration_ms=duration,
        success=success,
        json_mode=json_mode,
        input_token_estimate=input_tokens,
        output_token_estimate=output_tokens,
        metadata=request.metadata,
    )

    status = "success" if success else "error"

    result = LLMRuntimeResult(
        run_id=run_id,
        status=status,
        invocation=invocation,
        raw_text=raw_text,
        parsed_json=parsed_json,
        parse_error=parse_error,
        finish_reason=finish_reason,
    )

    _mark_local_invocation(success=success)

    if audit_logger is not None:
        completion_event_type = "llm_invocation_complete" if success else "llm_invocation_failure"
        completion_status = "SUCCESS" if success else "FAILED"
        audit_logger.log_event(
            event_type=completion_event_type,
            stage_name=str(request.metadata.get("stage_name", "")).strip() or None,
            substage_name=str(request.metadata.get("task_name", request.task_name)).strip() or None,
            status=completion_status,
            message=f"Completed LLM task '{request.task_name}'.",
            metadata={
                "invocation_id": invocation_id,
                "model_alias": config.model_alias,
                "duration_ms": duration,
                "input_token_estimate": input_tokens,
                "output_token_estimate": output_tokens,
                "finish_reason": finish_reason,
                "success": success,
                "parse_error": parse_error,
                **request_audit_metadata,
            },
        )

    return result