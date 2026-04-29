from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from services.llm_runtime_service.models import LLMMessage


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def monotonic_ms() -> int:
    return int(time.perf_counter() * 1000)


def elapsed_ms(start_ms: int, end_ms: int | None = None) -> int:
    end_value = end_ms if end_ms is not None else monotonic_ms()
    return max(0, end_value - start_ms)


def build_invocation_id() -> str:
    return f"llm_{uuid.uuid4().hex[:16]}"


def estimate_token_count(text: str) -> int:
    if not isinstance(text, str) or not text.strip():
        return 0
    return max(1, len(text.split()))


def estimate_message_token_count(messages: list[LLMMessage]) -> int:
    total = 0
    for message in messages:
        if not isinstance(message, LLMMessage):
            continue
        total += estimate_token_count(message.role)
        total += estimate_token_count(message.content)
    return total


def ensure_string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def ensure_dict(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a dict, got {type(value).__name__}.")
    return value


def ensure_list(value: Any, name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list, got {type(value).__name__}.")
    return value


def coerce_messages(
    *,
    system_prompt: str,
    user_prompt: str,
    messages: list[LLMMessage] | None = None,
) -> list[LLMMessage]:
    if messages:
        return messages

    normalized_messages: list[LLMMessage] = []

    system_text = ensure_string(system_prompt).strip()
    user_text = ensure_string(user_prompt).strip()

    if system_text:
        normalized_messages.append(
            LLMMessage(
                role="system",
                content=system_text,
            )
        )

    if user_text:
        normalized_messages.append(
            LLMMessage(
                role="user",
                content=user_text,
            )
        )

    return normalized_messages


def messages_to_chat_payload(messages: list[LLMMessage]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, LLMMessage):
            continue
        payload.append(
            {
                "role": ensure_string(message.role).strip(),
                "content": ensure_string(message.content),
            }
        )
    return payload


def extract_text_from_completion_response(response: Any) -> tuple[str, str]:
    if response is None:
        return "", ""

    if isinstance(response, dict):
        choices = response.get("choices", [])
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                finish_reason = ensure_string(choice.get("finish_reason", "")).strip()

                message = choice.get("message")
                if isinstance(message, dict):
                    return ensure_string(message.get("content", "")), finish_reason

                text = choice.get("text")
                if text is not None:
                    return ensure_string(text), finish_reason

        content = response.get("content")
        if content is not None:
            return ensure_string(content), ""

    choices = getattr(response, "choices", None)
    if isinstance(choices, list) and choices:
        choice = choices[0]
        finish_reason = ensure_string(getattr(choice, "finish_reason", "")).strip()

        message = getattr(choice, "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if content is not None:
                return ensure_string(content), finish_reason

        text = getattr(choice, "text", None)
        if text is not None:
            return ensure_string(text), finish_reason

    content = getattr(response, "content", None)
    if content is not None:
        return ensure_string(content), ""

    return ensure_string(response), ""


def strip_json_fences(text: str) -> str:
    raw = ensure_string(text).strip()
    if not raw:
        return ""

    if raw.startswith("```json"):
        raw = raw[len("```json"):].strip()
    elif raw.startswith("```"):
        raw = raw[len("```"):].strip()

    if raw.endswith("```"):
        raw = raw[:-3].strip()

    return raw


def try_parse_json(text: str) -> tuple[dict[str, Any] | list[Any] | None, str]:
    candidate = strip_json_fences(text)
    if not candidate:
        return None, "Empty response cannot be parsed as JSON."

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc}"
    except Exception as exc:
        return None, f"Unexpected JSON parse failure: {exc}"

    if not isinstance(parsed, (dict, list)):
        return None, "Parsed JSON must be an object or list."

    return parsed, ""


def apply_response_schema_hint(
    *,
    system_prompt: str,
    user_prompt: str,
    response_schema: dict[str, Any] | None,
    json_mode: bool,
) -> tuple[str, str]:
    schema = response_schema if isinstance(response_schema, dict) else {}
    if not json_mode:
        return system_prompt, user_prompt

    schema_text = ""
    if schema:
        schema_text = json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True)

    json_instruction = (
        "Return only valid JSON. "
        "Do not include markdown fences, commentary, or explanatory text."
    )

    enhanced_system = ensure_string(system_prompt).strip()
    enhanced_user = ensure_string(user_prompt).strip()

    if enhanced_system:
        enhanced_system = f"{enhanced_system}\n\n{json_instruction}"
    else:
        enhanced_system = json_instruction

    if schema_text:
        enhanced_user = (
            f"{enhanced_user}\n\n"
            f"Required response schema:\n{schema_text}"
        ).strip()

    return enhanced_system, enhanced_user