from __future__ import annotations

import pytest

from flatagents import FlatAgent


def _agent_config(model_backend: str = "claude_code") -> dict:
    return {
        "spec": "flatagent",
        "spec_version": "2.2.2",
        "data": {
            "name": "claude-code-backend-test",
            "model": {
                "provider": "anthropic",
                "name": "claude-sonnet-4-20250514",
                "backend": model_backend,
            },
            "system": "You are concise.",
            "user": "{{ input.prompt }}",
        },
    }


def test_flatagent_accepts_backend_claude_code_from_model_config() -> None:
    agent = FlatAgent(config_dict=_agent_config("claude_code"))
    assert agent._backend == "claude_code"


@pytest.mark.asyncio
async def test_call_llm_routes_to_claude_code_client() -> None:
    class _FakeClaudeCodeClient:
        async def call(self, params):
            return {"ok": True, "model": params["model"]}

    agent = object.__new__(FlatAgent)
    agent._backend = "claude_code"
    agent._claude_code_client = _FakeClaudeCodeClient()

    result = await FlatAgent._call_llm(
        agent, {"model": "anthropic/claude-sonnet-4-20250514", "messages": []}
    )
    assert result["ok"] is True
    assert result["model"] == "anthropic/claude-sonnet-4-20250514"


def test_flatagent_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unknown backend"):
        FlatAgent(config_dict=_agent_config("nonexistent_backend"))
