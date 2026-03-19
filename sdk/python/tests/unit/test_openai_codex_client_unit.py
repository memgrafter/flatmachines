from __future__ import annotations

import json
from pathlib import Path

from flatagents.providers.openai_codex_client import CodexClient
from _codex_test_helpers import token_for_account, write_auth_file


def _client(tmp_path: Path) -> CodexClient:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=token_for_account("acc_123"))
    return CodexClient(
        {
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api",
            "codex_auth_file": str(auth_file),
            "auth": {"type": "oauth", "provider": "openai-codex", "auth_file": str(auth_file)},
        }
    )


def test_build_request_body_includes_session_tools_reasoning(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = client._build_request_body(  # noqa: SLF001
        {
            "model": "openai-codex/gpt-5.4",
            "messages": [
                {"role": "system", "content": "Sys"},
                {"role": "user", "content": "Hi"},
            ],
            "tools": [{"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}],
            "reasoning": {"effort": "low", "summary": "auto"},
            "temperature": 0.1,
        },
        session_id="sess-42",
    )
    assert body["model"] == "gpt-5.4"
    assert body["prompt_cache_key"] == "sess-42"
    assert body["instructions"] == "Sys"
    assert body["reasoning"]["effort"] == "low"
    assert body["tools"]


def test_parse_sse_to_result_handles_text_and_usage(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = "\n\n".join(
        [
            f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': 'Hello'})}",
            f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': ' there'})}",
            f"data: {json.dumps({'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5, 'input_tokens_details': {'cached_tokens': 1}}}})}",
            "data: [DONE]",
        ]
    ) + "\n\n"

    result = client._parse_sse_to_result(payload)  # noqa: SLF001
    assert result.content == "Hello there"
    assert result.finish_reason == "stop"
    assert result.usage.input_tokens == 3
    assert result.usage.cached_tokens == 1


def test_parse_error_response_maps_usage_limit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    message = client._parse_error_response(  # noqa: SLF001
        429,
        json.dumps({"error": {"code": "usage_limit_reached", "message": "quota hit", "plan_type": "PLUS"}}),
    )
    assert "usage limit" in message.lower()


def test_parse_sse_normalizes_long_function_call_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    long_call_id = "call_" + ("x" * 80)
    payload = "\n\n".join(
        [
            f"data: {json.dumps({'type': 'response.function_call_arguments.delta', 'call_id': long_call_id, 'delta': '{\"k\":\"v\"}'})}",
            f"data: {json.dumps({'type': 'response.output_item.done', 'item': {'type': 'function_call', 'call_id': long_call_id, 'id': 'fc_item', 'name': 'read', 'arguments': '{\"path\":\"a\"}'}})}",
            f"data: {json.dumps({'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}})}",
            "data: [DONE]",
        ]
    ) + "\n\n"

    result = client._parse_sse_to_result(payload)  # noqa: SLF001
    assert result.tool_calls
    assert len(result.tool_calls[0].id) <= 64
