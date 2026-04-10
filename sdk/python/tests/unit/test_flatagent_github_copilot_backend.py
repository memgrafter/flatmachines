from __future__ import annotations

import pytest

from flatagents import FlatAgent


def _agent_config(model_backend: str = "copilot") -> dict:
    return {
        "spec": "flatagent",
        "spec_version": "2.2.2",
        "data": {
            "name": "copilot-core-backend-test",
            "model": {
                "provider": "github-copilot",
                "name": "gpt-4o",
                "backend": model_backend,
            },
            "system": "You are concise.",
            "user": "{{ input.prompt }}",
        },
    }


def test_flatagent_accepts_backend_copilot_from_model_config() -> None:
    agent = FlatAgent(config_dict=_agent_config("copilot"))
    assert agent._backend == "copilot"


@pytest.mark.asyncio
async def test_call_llm_routes_to_copilot_client_when_backend_is_copilot() -> None:
    class _FakeCopilotClient:
        async def call(self, params):
            return {"ok": True, "model": params["model"]}

    agent = object.__new__(FlatAgent)
    agent._backend = "copilot"
    agent._copilot_client = _FakeCopilotClient()

    result = await FlatAgent._call_llm(agent, {"model": "github-copilot/gpt-4o", "messages": []})
    assert result["ok"] is True
    assert result["model"] == "github-copilot/gpt-4o"
