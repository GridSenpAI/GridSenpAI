from services.llm_runtime_service.models import (
    LLMInvocationRecord,
    LLMMessage,
    LLMRuntimeConfig,
    LLMRuntimeResult,
    LLMTaskRequest,
)
from services.llm_runtime_service.utils import (
    apply_response_schema_hint,
    coerce_messages,
    estimate_message_token_count,
    extract_text_from_completion_response,
    strip_json_fences,
    try_parse_json,
)


def test_llm_runtime_config_to_dict() -> None:
    config = LLMRuntimeConfig(
        model_path="models/test-model.gguf",
        model_alias="test-model",
        n_ctx=4096,
        n_threads=8,
        n_batch=256,
        n_gpu_layers=20,
    )

    payload = config.to_dict()

    assert payload["model_path"] == "models/test-model.gguf"
    assert payload["model_alias"] == "test-model"
    assert payload["n_ctx"] == 4096
    assert payload["n_threads"] == 8
    assert payload["n_batch"] == 256
    assert payload["n_gpu_layers"] == 20


def test_llm_task_request_to_dict() -> None:
    request = LLMTaskRequest(
        task_name="drawing_topology_inference",
        prompt_template_id="phase4.drawing.v1",
        system_prompt="Return valid JSON only.",
        user_prompt="Infer topology.",
        response_schema={"type": "object"},
        messages=[
            LLMMessage(role="system", content="System message"),
            LLMMessage(role="user", content="User message"),
        ],
        json_mode=True,
        metadata={"stage": "extraction"},
    )

    payload = request.to_dict()

    assert payload["task_name"] == "drawing_topology_inference"
    assert payload["prompt_template_id"] == "phase4.drawing.v1"
    assert payload["json_mode"] is True
    assert payload["messages"][0]["role"] == "system"
    assert payload["metadata"]["stage"] == "extraction"


def test_coerce_messages_builds_default_messages() -> None:
    messages = coerce_messages(
        system_prompt="You are a structured extraction worker.",
        user_prompt='Return {"ok": true}.',
        messages=None,
    )

    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"


def test_coerce_messages_preserves_supplied_messages() -> None:
    supplied = [
        LLMMessage(role="system", content="A"),
        LLMMessage(role="user", content="B"),
    ]

    messages = coerce_messages(
        system_prompt="ignored",
        user_prompt="ignored",
        messages=supplied,
    )

    assert messages == supplied


def test_estimate_message_token_count_counts_message_content() -> None:
    messages = [
        LLMMessage(role="system", content="Return valid JSON only"),
        LLMMessage(role="user", content="Infer topology from drawing"),
    ]

    count = estimate_message_token_count(messages)

    assert count > 0


def test_apply_response_schema_hint_in_json_mode() -> None:
    system_prompt, user_prompt = apply_response_schema_hint(
        system_prompt="You are an extraction worker.",
        user_prompt="Return the result.",
        response_schema={"type": "object", "properties": {"topology": {"type": "string"}}},
        json_mode=True,
    )

    assert "Return only valid JSON" in system_prompt
    assert "Required response schema" in user_prompt
    assert '"topology"' in user_prompt


def test_apply_response_schema_hint_without_json_mode() -> None:
    system_prompt, user_prompt = apply_response_schema_hint(
        system_prompt="You are an extraction worker.",
        user_prompt="Return the result.",
        response_schema={"type": "object"},
        json_mode=False,
    )

    assert system_prompt == "You are an extraction worker."
    assert user_prompt == "Return the result."


def test_extract_text_from_chat_completion_dict_response() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": '{"topology": "ring bus"}'
                },
                "finish_reason": "stop",
            }
        ]
    }

    raw_text, finish_reason = extract_text_from_completion_response(response)

    assert raw_text == '{"topology": "ring bus"}'
    assert finish_reason == "stop"


def test_extract_text_from_text_completion_dict_response() -> None:
    response = {
        "choices": [
            {
                "text": '{"ok": true}',
                "finish_reason": "length",
            }
        ]
    }

    raw_text, finish_reason = extract_text_from_completion_response(response)

    assert raw_text == '{"ok": true}'
    assert finish_reason == "length"


def test_strip_json_fences_removes_markdown_wrapping() -> None:
    raw = """```json
{"topology": "radial"}
```"""

    stripped = strip_json_fences(raw)

    assert stripped == '{"topology": "radial"}'


def test_try_parse_json_parses_object() -> None:
    parsed, error = try_parse_json('{"topology": "breaker_and_half"}')

    assert error == ""
    assert parsed == {"topology": "breaker_and_half"}


def test_try_parse_json_parses_list() -> None:
    parsed, error = try_parse_json('[{"field_path": "facility.topology"}]')

    assert error == ""
    assert parsed == [{"field_path": "facility.topology"}]


def test_try_parse_json_returns_error_for_invalid_json() -> None:
    parsed, error = try_parse_json('{"topology": }')

    assert parsed is None
    assert "JSON parse error" in error


def test_llm_invocation_record_to_dict() -> None:
    record = LLMInvocationRecord(
        invocation_id="llm_123",
        run_id="run_001",
        task_name="entity_review",
        prompt_template_id="phase4.entity.v1",
        model_alias="qwen-local",
        provider="llama_cpp",
        model_path="models/qwen.gguf",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:01+00:00",
        duration_ms=1000,
        success=True,
        json_mode=True,
        input_token_estimate=120,
        output_token_estimate=40,
        metadata={"stage": "extraction"},
    )

    payload = record.to_dict()

    assert payload["invocation_id"] == "llm_123"
    assert payload["success"] is True
    assert payload["json_mode"] is True
    assert payload["metadata"]["stage"] == "extraction"


def test_llm_runtime_result_to_dict() -> None:
    invocation = LLMInvocationRecord(
        invocation_id="llm_124",
        run_id="run_002",
        task_name="topology_review",
        prompt_template_id="phase4.topology.v1",
        model_alias="qwen-local",
        provider="llama_cpp",
        model_path="models/qwen.gguf",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:02+00:00",
        duration_ms=2000,
        success=True,
        json_mode=True,
    )

    result = LLMRuntimeResult(
        run_id="run_002",
        status="success",
        invocation=invocation,
        raw_text='{"topology": "ring bus"}',
        parsed_json={"topology": "ring bus"},
        parse_error="",
        finish_reason="stop",
        warnings=[],
        errors=[],
    )

    payload = result.to_dict()

    assert payload["run_id"] == "run_002"
    assert payload["status"] == "success"
    assert payload["parsed_json"] == {"topology": "ring bus"}
    assert payload["finish_reason"] == "stop"

def test_llm_runtime_result_failure_payload() -> None:
    invocation = LLMInvocationRecord(
        invocation_id="llm_fail",
        run_id="run_fail",
        task_name="entity_review",
        prompt_template_id="phase4.entity.v1",
        model_alias="qwen-local",
        provider="llama_cpp",
        model_path="models/qwen.gguf",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:01+00:00",
        duration_ms=1000,
        success=False,
        json_mode=True,
    )

    result = LLMRuntimeResult(
        run_id="run_fail",
        status="error",
        invocation=invocation,
        raw_text="",
        parsed_json=None,
        parse_error="JSON parse error",
        finish_reason="error",
        warnings=[],
        errors=["runtime failure"],
    )

    payload = result.to_dict()

    assert payload["status"] == "error"
    assert payload["invocation"]["success"] is False
    assert payload["parse_error"] == "JSON parse error"

def test_runtime_diagnostics_report_requested_gpu_layers(monkeypatch) -> None:
    import services.llm_runtime_service.service as runtime_service

    runtime_service.reset_runtime_diagnostics_for_tests()

    class FakeModel:
        pass

    def fake_runtime(**kwargs):
        return FakeModel()

    monkeypatch.setattr(runtime_service, "LlamaRuntime", fake_runtime)
    monkeypatch.setattr(runtime_service, "llama_cpp_module", None)

    config = LLMRuntimeConfig(
        model_path="models/test.gguf",
        model_alias="test-local",
        n_ctx=4096,
        n_threads=4,
        n_batch=128,
        n_gpu_layers=40,
    )

    runtime_service.initialize_runtime(config)
    diagnostics = runtime_service.get_runtime_diagnostics()

    assert diagnostics["runtime_initialized"] is True
    assert diagnostics["requested_n_gpu_layers"] == 40
    assert diagnostics["gpu_offload_requested"] is True
    assert diagnostics["model_alias"] == "test-local"


def test_runtime_diagnostics_count_local_invocations(monkeypatch) -> None:
    import services.llm_runtime_service.service as runtime_service

    runtime_service.reset_runtime_diagnostics_for_tests()

    class FakeModel:
        def create_chat_completion(self, **kwargs):
            return {
                "choices": [
                    {
                        "message": {"content": '{"ok": true}'},
                        "finish_reason": "stop",
                    }
                ]
            }

    monkeypatch.setattr(runtime_service, "_model_instance", FakeModel())
    monkeypatch.setattr(runtime_service, "_model_config", LLMRuntimeConfig(model_path="models/test.gguf"))

    result = runtime_service.run_llm_task(
        run_id="run_diag_001",
        request=LLMTaskRequest(
            task_name="diag_task",
            prompt_template_id="diag.v1",
            system_prompt="Return JSON.",
            user_prompt="Return the result.",
            response_schema={"type": "object"},
            json_mode=True,
        ),
    )

    diagnostics = runtime_service.get_runtime_diagnostics()

    assert result.status == "success"
    assert diagnostics["local_invocation_count"] == 1
    assert diagnostics["local_invocation_success_count"] == 1
    assert diagnostics["local_invocation_error_count"] == 0


def test_initialize_runtime_supports_ibm_watsonx() -> None:
    import services.llm_runtime_service.service as runtime_service

    runtime_service.reset_runtime_diagnostics_for_tests()

    config = LLMRuntimeConfig(
        provider="ibm_watsonx",
        model_path="",
        model_alias="granite-watsonx",
        watsonx_url="https://us-south.ml.cloud.ibm.com",
        watsonx_api_key="secret-key",
        watsonx_project_id="project-123",
        watsonx_model_id="ibm/granite-3-3-8b-instruct",
    )

    runtime_service.initialize_runtime(config)
    diagnostics = runtime_service.get_runtime_diagnostics()

    assert diagnostics["runtime_initialized"] is True
    assert diagnostics["provider"] == "ibm_watsonx"


def test_run_llm_task_supports_ibm_watsonx(monkeypatch) -> None:
    import services.llm_runtime_service.service as runtime_service

    runtime_service.reset_runtime_diagnostics_for_tests()
    runtime_service._model_config = LLMRuntimeConfig(
        provider="ibm_watsonx",
        model_path="",
        model_alias="granite-watsonx",
        watsonx_url="https://us-south.ml.cloud.ibm.com",
        watsonx_api_key="secret-key",
        watsonx_project_id="project-123",
        watsonx_model_id="ibm/granite-3-3-8b-instruct",
        max_tokens=300,
    )
    runtime_service._model_instance = {"provider": "ibm_watsonx"}

    monkeypatch.setattr(runtime_service, "_invoke_watsonx_chat_completion", lambda **kwargs: {
        "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]
    })

    result = runtime_service.run_llm_task(
        run_id="run_wx_001",
        request=LLMTaskRequest(
            task_name="granite_task",
            prompt_template_id="granite.v1",
            system_prompt="Return JSON.",
            user_prompt="Return the result.",
            response_schema={"type": "object"},
            json_mode=True,
        ),
    )

    assert result.status == "success"
    assert result.invocation.provider == "ibm_watsonx"
    assert result.parsed_json == {"ok": True}
