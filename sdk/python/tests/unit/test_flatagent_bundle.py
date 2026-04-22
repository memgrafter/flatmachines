from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from flatagents import FlatAgent
from flatagents.adapters.compat import AgentResult


@pytest.mark.asyncio
async def test_flatagent_bundle_inline_llm_profile():
    config = {
        "spec": "flatagent",
        "spec_version": "4.0.0",
        "data": {
            "prompt": {
                "system": "You are helpful.",
                "user": "Hello {{ input.name }}",
                "output": {
                    "greeting": {"type": "str"},
                },
            },
            "profile": {
                "type": "llm",
                "model": {
                    "provider": "openai",
                    "name": "gpt-test",
                },
            },
        },
    }

    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
    )
    message = SimpleNamespace(content='{"greeting": "Hello Alice"}', tool_calls=None)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=usage,
    )

    with patch.object(FlatAgent, "_init_backend", lambda self: None):
        agent = FlatAgent(config_dict=config, backend="litellm")

    async def _fake_call_llm(params):
        return response

    agent._call_llm = _fake_call_llm  # type: ignore[method-assign]

    result = await agent.call(name="Alice")

    assert agent._runtime_type == "llm"
    assert result.error is None
    assert result.output == {"greeting": "Hello Alice"}
    assert result.rendered_user_prompt == "Hello Alice"


@pytest.mark.asyncio
async def test_flatagent_bundle_prompt_and_profile_refs(tmp_path: Path):
    prompt_path = tmp_path / "prompt.yml"
    profile_path = tmp_path / "profile.yml"
    agent_path = tmp_path / "agent.yml"

    prompt_path.write_text(
        "spec: prompt\n"
        "spec_version: '4.0.0'\n"
        "data:\n"
        "  system: Be careful.\n"
        "  user: '{{ input.task }}'\n"
    )
    profile_path.write_text(
        "spec: flatprofile\n"
        "spec_version: '4.0.0'\n"
        "data:\n"
        "  type: claude-code\n"
        "  model: opus\n"
        "  permission_mode: bypassPermissions\n"
    )
    agent_path.write_text(
        "spec: flatagent\n"
        "spec_version: '4.0.0'\n"
        "data:\n"
        "  prompt: ./prompt.yml\n"
        "  profile: ./profile.yml\n"
    )

    captured = {}

    class FakeExecutor:
        async def execute(self, input_data, context=None, session_id=None):
            captured["input_data"] = dict(input_data)
            captured["context"] = context
            captured["session_id"] = session_id
            return AgentResult(
                output={"result": "done", "session_id": "sess-1"},
                content="done",
                metadata={"session_id": "sess-1"},
            )

    with patch.object(FlatAgent, "_init_runtime_executor", lambda self: FakeExecutor()):
        agent = FlatAgent(config_file=str(agent_path))

    result = await agent.call(task="Ship it", resume_session="sess-0")

    assert agent._runtime_type == "claude-code"
    assert result.output == {"result": "done", "session_id": "sess-1"}
    assert captured["input_data"]["task"] == "Ship it"
    assert captured["input_data"]["resume_session"] == "sess-0"
    assert captured["input_data"]["_append_system_prompt"] == "Be careful."
