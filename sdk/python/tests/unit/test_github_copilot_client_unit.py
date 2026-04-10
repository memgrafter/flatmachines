from __future__ import annotations

import json
from pathlib import Path

from flatagents.providers.github_copilot_client import CopilotClient
from _github_copilot_test_helpers import token_for_proxy_host, write_auth_file


def _client(tmp_path: Path) -> CopilotClient:
    auth_file = tmp_path / "auth.json"
    write_auth_file(auth_file, access_token=token_for_proxy_host())
    return CopilotClient(
        {
            "provider": "github-copilot",
            "base_url": "https://api.individual.githubcopilot.com",
            "copilot_auth_file": str(auth_file),
            "auth": {"type": "oauth", "provider": "github-copilot", "auth_file": str(auth_file)},
        }
    )


def test_build_request_body_includes_model_messages_tools(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = client._build_request_body(  # noqa: SLF001
        {
            "model": "github-copilot/gpt-4o",
            "messages": [{"role": "system", "content": "Sys"}, {"role": "user", "content": "Hi"}],
            "tools": [{"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}],
            "temperature": 0.1,
            "stream": True,
        }
    )
    assert body["model"] == "gpt-4o"
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "system"
    assert body["tools"]


def test_build_dynamic_headers_sets_initiator_and_vision(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = client._build_dynamic_headers(  # noqa: SLF001
        [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://x/y.png"}}]},
            {"role": "assistant", "content": "Working"},
        ]
    )
    assert headers["X-Initiator"] == "agent"
    assert headers["Openai-Intent"] == "conversation-edits"
    assert headers["Copilot-Vision-Request"] == "true"


def test_parse_response_to_result_handles_text_usage_and_tool_calls(tmp_path: Path) -> None:
    client = _client(tmp_path)
    result = client._parse_response_to_result(  # noqa: SLF001
        {
            "choices": [
                {
                    "message": {
                        "content": "Hello there",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "read", "arguments": json.dumps({"path": "x"})},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
    )

    assert result.content == "Hello there"
    assert result.finish_reason == "tool_calls"
    assert result.usage.input_tokens == 3
    assert result.tool_calls[0].name == "read"


def test_parse_error_response_maps_auth_and_rate_limit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    auth_message = client._parse_error_response(  # noqa: SLF001
        401,
        json.dumps({"error": {"message": "expired"}}),
    )
    rate_message = client._parse_error_response(  # noqa: SLF001
        429,
        json.dumps({"error": {"message": "busy"}}),
    )
    assert "authentication" in auth_message.lower()
    assert "rate limited" in rate_message.lower()
