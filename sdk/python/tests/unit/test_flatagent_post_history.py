from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from flatagents import FlatAgent


def _fake_response(content: str = "ok") -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=None,
    )


def _agent_config(post_history: str = "Remember {{ input.name }}.") -> dict:
    return {
        "spec": "flatagent",
        "spec_version": "4.0.1",
        "data": {
            "name": "post-history-test",
            "model": {"provider": "openai", "name": "gpt-test"},
            "system": "You are helpful.",
            "user": "Hello {{ input.name }}",
            "post_history_instructions": post_history,
        },
    }


def _bundle_agent_config() -> dict:
    return {
        "spec": "flatagent",
        "spec_version": "4.0.1",
        "data": {
            "prompt": {
                "system": "You are helpful.",
                "user": "Hello {{ input.name }}",
                "post_history_instructions": "Bundle reminder for {{ input.name }}.",
            },
            "profile": {
                "spec": "flatprofile",
                "spec_version": "4.0.1",
                "data": {
                    "model_profiles": {
                        "default": {"provider": "openai", "name": "gpt-test"},
                    },
                    "default": "default",
                },
            },
        },
    }


def _make_agent(config: dict) -> FlatAgent:
    with patch.object(FlatAgent, "_init_backend", lambda self: None):
        return FlatAgent(config_dict=config, backend="litellm")


@pytest.mark.asyncio
async def test_post_history_appends_to_final_user_message_ephemerally() -> None:
    agent = _make_agent(_agent_config("Final reminder for {{ input.name }}."))
    captured = {}

    async def _fake_call_llm(params):
        captured["messages"] = params["messages"]
        return _fake_response()

    agent._call_llm = _fake_call_llm  # type: ignore[method-assign]

    result = await agent.call(name="Alice")

    assert result.rendered_user_prompt == "Hello Alice"
    assert captured["messages"] == [
        {"role": "system", "content": "You are helpful."},
        {
            "role": "user",
            "content": "Hello Alice\n\nSystem:\n\nFinal reminder for Alice.",
        },
    ]


@pytest.mark.asyncio
async def test_bundle_prompt_post_history_appends_to_final_user_message() -> None:
    agent = _make_agent(_bundle_agent_config())
    captured = {}

    async def _fake_call_llm(params):
        captured["messages"] = params["messages"]
        return _fake_response()

    agent._call_llm = _fake_call_llm  # type: ignore[method-assign]

    result = await agent.call(name="Bob")

    assert result.rendered_user_prompt == "Hello Bob"
    assert captured["messages"][-1] == {
        "role": "user",
        "content": "Hello Bob\n\nSystem:\n\nBundle reminder for Bob.",
    }


@pytest.mark.asyncio
async def test_post_history_does_not_mutate_continuation_chain_when_last_is_tool() -> None:
    agent = _make_agent(_agent_config("Use the tool result, but stay in character."))
    chain = [
        {"role": "user", "content": "Initial request"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "tool output"},
    ]
    original_chain = [dict(message) for message in chain]
    captured = {}

    async def _fake_call_llm(params):
        captured["messages"] = params["messages"]
        return _fake_response()

    agent._call_llm = _fake_call_llm  # type: ignore[method-assign]

    result = await agent.call(messages=chain)

    assert result.rendered_user_prompt is None
    assert chain == original_chain
    assert captured["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "tool output\n\nSystem:\n\nUse the tool result, but stay in character.",
    }
    assert captured["messages"][-1] is not chain[-1]


@pytest.mark.asyncio
async def test_post_history_synthesizes_user_message_when_final_message_is_not_user_or_tool() -> None:
    agent = _make_agent(_agent_config("Final constraints."))
    chain = [{"role": "assistant", "content": "prior answer"}]
    captured = {}

    async def _fake_call_llm(params):
        captured["messages"] = params["messages"]
        return _fake_response()

    agent._call_llm = _fake_call_llm  # type: ignore[method-assign]

    await agent.call(messages=chain)

    assert chain == [{"role": "assistant", "content": "prior answer"}]
    assert captured["messages"] == [
        {"role": "system", "content": "You are helpful."},
        {"role": "assistant", "content": "prior answer"},
        {"role": "user", "content": "System:\n\nFinal constraints."},
    ]


@pytest.mark.asyncio
async def test_empty_post_history_is_noop_and_reuses_message_list() -> None:
    agent = _make_agent(_agent_config("   \n"))
    captured = {}

    async def _fake_call_llm(params):
        captured["messages"] = params["messages"]
        return _fake_response()

    agent._call_llm = _fake_call_llm  # type: ignore[method-assign]

    await agent.call(name="Alice")

    assert captured["messages"] == [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello Alice"},
    ]


@pytest.mark.asyncio
async def test_post_history_appends_to_multimodal_final_user_message_without_mutating_original() -> None:
    agent = _make_agent(_agent_config("Vision reminder."))
    content = [{"type": "text", "text": "Describe image"}]
    chain = [{"role": "user", "content": content}]
    captured = {}

    async def _fake_call_llm(params):
        captured["messages"] = params["messages"]
        return _fake_response()

    agent._call_llm = _fake_call_llm  # type: ignore[method-assign]

    await agent.call(messages=chain)

    assert chain[0]["content"] == [{"type": "text", "text": "Describe image"}]
    assert captured["messages"][-1]["content"] == [
        {"type": "text", "text": "Describe image"},
        {"type": "text", "text": "\n\nSystem:\n\nVision reminder."},
    ]
    assert captured["messages"][-1]["content"] is not content
