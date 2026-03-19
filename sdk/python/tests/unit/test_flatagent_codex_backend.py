from __future__ import annotations

import pytest

from flatagents import FlatAgent


def _agent_config(model_backend: str = "codex") -> dict:
    return {
        "spec": "flatagent",
        "spec_version": "2.2.2",
        "data": {
            "name": "codex-core-backend-test",
            "model": {
                "provider": "openai-codex",
                "name": "gpt-5.4",
                "backend": model_backend,
            },
            "system": "You are concise.",
            "user": "{{ input.prompt }}",
        },
    }


def test_flatagent_accepts_backend_codex_from_model_config() -> None:
    agent = FlatAgent(config_dict=_agent_config("codex"))
    assert agent._backend == "codex"


@pytest.mark.asyncio
async def test_call_llm_routes_to_codex_client_when_backend_is_codex() -> None:
    class _FakeCodexClient:
        async def call(self, params):
            return {"ok": True, "model": params["model"]}

    agent = object.__new__(FlatAgent)
    agent._backend = "codex"
    agent._codex_client = _FakeCodexClient()

    result = await FlatAgent._call_llm(agent, {"model": "openai-codex/gpt-5.4", "messages": []})
    assert result["ok"] is True
    assert result["model"] == "openai-codex/gpt-5.4"
