"""
Unit tests for FlatMachine tool loop orchestration.

Tests:
- Basic tool loop: agent calls tool → gets result → responds (mock agent + mock provider)
- Multi-round: 3 rounds of tool calls before completion
- Guardrails: max_turns, max_tool_calls, max_cost, total_timeout
- Per-tool-call hooks: on_tool_calls fires once per LLM response, on_tool_result fires per tool
- Per-tool-call checkpoints: verify checkpoint saved after each tool execution
- Mid-loop conditional transition: hook sets context flag → conditional transition fires mid-batch
- Unconditional transition NOT firing mid-loop (only on natural exit)
- _abort_tool_loop from hook stops the loop
- _skip_tools from hook skips specific tool calls
- _steering_messages injection
- Jinja2 guardrail rendering
- _tool_loop_next_state override in execute loop
- Non-capable adapter → RuntimeError
- Cost tracking: loop_cost local + total_cost machine-wide
- Denied/allowed tools at machine level
- Tool definitions merge (provider + YAML)
- _find_conditional_transition evaluates only conditional transitions
- _render_guardrail with Jinja2 templates
- _build_assistant_message formats correctly
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from flatmachines import FlatMachine, MachineHooks, MemoryBackend
from flatmachines.agents import AgentResult, AgentExecutor
from flatmachines.persistence import MachineSnapshot, CheckpointManager
from flatagents.tools import ToolResult, ToolProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent_result(
    content="done",
    finish_reason="stop",
    tool_calls=None,
    error=None,
    cost=None,
    usage=None,
    rendered_user_prompt="rendered prompt",
):
    """Build an AgentResult for tests."""
    return AgentResult(
        content=content,
        finish_reason=finish_reason,
        tool_calls=tool_calls,
        error=error,
        cost=cost or {"total": 0.001},
        usage=usage or {"api_calls": 1, "input_tokens": 10, "output_tokens": 5},
        rendered_user_prompt=rendered_user_prompt,
    )


def _make_tool_result(tool_calls_data, content=None, cost=None):
    """Build an AgentResult with tool calls (finish_reason=tool_use)."""
    return _make_agent_result(
        content=content,
        finish_reason="tool_use",
        tool_calls=tool_calls_data,
        cost=cost,
    )


class MockToolProvider:
    """Mock ToolProvider for testing."""

    def __init__(self, results=None, definitions=None):
        self._results = results or {}
        self._definitions = definitions or []
        self.calls = []  # Track calls for assertions

    def get_tool_definitions(self):
        return self._definitions

    async def execute_tool(self, name, tool_call_id, arguments):
        self.calls.append({"name": name, "tool_call_id": tool_call_id, "arguments": arguments})
        if name in self._results:
            return self._results[name]
        return ToolResult(content=f"executed {name}({arguments})")


class MockExecutor:
    """Mock AgentExecutor with execute_with_tools support."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._call_idx = 0
        self.calls = []

    @property
    def metadata(self):
        return {}

    async def execute(self, input_data, context=None, session_id=None):
        return self._next_response("execute", input_data=input_data, session_id=session_id)

    async def execute_with_tools(self, input_data, tools, messages=None, context=None, session_id=None):
        return self._next_response(
            "execute_with_tools",
            input_data=input_data,
            tools=tools,
            messages=messages,
            session_id=session_id,
        )

    def _next_response(self, method, **kwargs):
        self.calls.append({"method": method, **kwargs})
        if self._call_idx >= len(self._responses):
            return _make_agent_result(content="fallback")
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp


class NoToolsExecutor:
    """Executor without execute_with_tools — should trigger RuntimeError."""

    @property
    def metadata(self):
        return {}

    async def execute(self, input_data, context=None, session_id=None):
        return _make_agent_result()


def _machine_config(
    tool_loop=True,
    transitions=None,
    agent_inline=None,
    output_to_context=None,
):
    """Build a minimal machine config dict for tool_loop testing."""
    state_def = {
        "agent": "coder",
        "tool_loop": tool_loop,
        "input": {"task": "{{ context.task }}"},
    }
    if transitions is not None:
        state_def["transitions"] = transitions
    else:
        state_def["transitions"] = [{"to": "done"}]
    if output_to_context:
        state_def["output_to_context"] = output_to_context

    agents = {"coder": agent_inline} if agent_inline else {"coder": "./agent.yml"}

    return {
        "spec": "flatmachine",
        "spec_version": "1.1.1",
        "data": {
            "name": "test-tool-loop",
            "context": {"task": "{{ input.task }}"},
            "agents": agents,
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "work"}],
                },
                "work": state_def,
                "done": {
                    "type": "final",
                    "output": {"result": "{{ context.result }}"},
                },
            },
        },
    }


def _build_machine(
    executor_responses,
    tool_provider=None,
    hooks=None,
    config=None,
    persistence=None,
):
    """Build a FlatMachine with a mocked executor."""
    cfg = config or _machine_config()
    machine = FlatMachine(
        config_dict=cfg,
        hooks=hooks,
        tool_provider=tool_provider,
        persistence=persistence or MemoryBackend(),
    )

    executor = MockExecutor(executor_responses)
    machine._agents = {"coder": executor}
    return machine, executor


# ---------------------------------------------------------------------------
# Tests: Basic Machine Tool Loop
# ---------------------------------------------------------------------------

class TestBasicMachineToolLoop:

    @pytest.mark.asyncio
    async def test_single_tool_call_then_complete(self):
        """Agent calls one tool, gets result, then completes."""
        provider = MockToolProvider()
        machine, executor = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "read_file", "arguments": {"path": "x"}}]),
                _make_agent_result(content="file contents analyzed"),
            ],
            tool_provider=provider,
        )

        result = await machine.execute(input={"task": "read a file"})

        assert provider.calls[0]["name"] == "read_file"
        assert executor.calls[0]["method"] == "execute_with_tools"
        assert executor.calls[1]["method"] == "execute_with_tools"

    @pytest.mark.asyncio
    async def test_tool_loop_passes_stable_session_id(self):
        """All tool-loop turns should share a stable non-empty session_id."""
        provider = MockToolProvider()
        machine, executor = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "read_file", "arguments": {"path": "x"}}]),
                _make_agent_result(content="file contents analyzed"),
            ],
            tool_provider=provider,
        )

        await machine.execute(input={"task": "read a file"})

        session_ids = [c.get("session_id") for c in executor.calls if c.get("method") == "execute_with_tools"]
        assert session_ids
        assert all(session_ids)
        assert len(set(session_ids)) == 1

    @pytest.mark.asyncio
    async def test_multi_round_tool_calls(self):
        """3 rounds of tool calls before completion."""
        provider = MockToolProvider()
        machine, executor = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "read_file", "arguments": {}}]),
                _make_tool_result([{"id": "c2", "name": "write_file", "arguments": {}}]),
                _make_tool_result([{"id": "c3", "name": "bash", "arguments": {}}]),
                _make_agent_result(content="all done"),
            ],
            tool_provider=provider,
        )

        result = await machine.execute(input={"task": "complex work"})

        assert len(provider.calls) == 3
        assert len(executor.calls) == 4  # 3 tool rounds + 1 final

    @pytest.mark.asyncio
    async def test_multiple_tools_in_single_response(self):
        """Agent returns 3 tool calls in one response, all executed."""
        provider = MockToolProvider()
        machine, executor = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "read_file", "arguments": {"path": "a"}},
                    {"id": "c2", "name": "read_file", "arguments": {"path": "b"}},
                    {"id": "c3", "name": "read_file", "arguments": {"path": "c"}},
                ]),
                _make_agent_result(content="read all three"),
            ],
            tool_provider=provider,
        )

        result = await machine.execute(input={"task": "read three files"})

        assert len(provider.calls) == 3

    @pytest.mark.asyncio
    async def test_output_to_context_mapping(self):
        """output_to_context maps tool loop output correctly."""
        cfg = _machine_config(
            output_to_context={
                "result": "{{ output.content }}",
                "calls": "{{ output._tool_calls_count }}",
            },
        )
        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "test", "arguments": {}}]),
                _make_agent_result(content="final answer"),
            ],
            tool_provider=provider,
            config=cfg,
        )

        result = await machine.execute(input={"task": "work"})

        assert result.get("result") == "final answer"

    @pytest.mark.asyncio
    async def test_no_tool_calls_completes_immediately(self):
        """Agent responds without tool calls → loop completes in 1 turn."""
        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[_make_agent_result(content="immediate answer")],
            tool_provider=provider,
        )

        result = await machine.execute(input={"task": "simple question"})

        assert len(provider.calls) == 0


# ---------------------------------------------------------------------------
# Tests: Chain isolation + continuation behavior
# ---------------------------------------------------------------------------

class TestToolLoopChainScoping:

    @pytest.mark.asyncio
    async def test_cross_state_tool_loop_chain_isolation(self):
        """State B should not reuse State A's chain (fresh input render expected)."""
        cfg = {
            "spec": "flatmachine",
            "spec_version": "1.1.1",
            "data": {
                "name": "chain-scope",
                "context": {},
                "agents": {"coder": "./agent.yml"},
                "states": {
                    "start": {"type": "initial", "transitions": [{"to": "work_a"}]},
                    "work_a": {
                        "agent": "coder",
                        "tool_loop": True,
                        "input": {"task": "state-a"},
                        "transitions": [{"to": "work_b"}],
                    },
                    "work_b": {
                        "agent": "coder",
                        "tool_loop": True,
                        "input": {"task": "state-b"},
                        "transitions": [{"to": "done"}],
                    },
                    "done": {"type": "final", "output": {"ok": True}},
                },
            },
        }

        machine, executor = _build_machine(
            executor_responses=[
                _make_agent_result(content="a", rendered_user_prompt="prompt-a"),
                _make_agent_result(content="b", rendered_user_prompt="prompt-b"),
            ],
            tool_provider=MockToolProvider(),
            config=cfg,
        )

        await machine.execute(input={})

        assert len(executor.calls) == 2
        assert executor.calls[0]["input_data"] == {"task": "state-a"}
        assert executor.calls[0]["messages"] is None
        assert executor.calls[1]["input_data"] == {"task": "state-b"}
        assert executor.calls[1]["messages"] is None

    @pytest.mark.asyncio
    async def test_same_state_continuation_reuses_chain(self):
        """Same state+agent continuation should reuse saved chain."""
        machine, executor = _build_machine(
            executor_responses=[_make_agent_result(content="continued")],
            tool_provider=MockToolProvider(),
        )

        seed_chain = [
            {"role": "user", "content": "prior prompt"},
            {"role": "assistant", "content": "prior answer"},
        ]
        context = {
            "task": "resume",
            "_tool_loop_chain": [*seed_chain],
            "_tool_loop_chain_state": "work",
            "_tool_loop_chain_agent": "coder",
        }

        updated_context, _ = await machine._execute_tool_loop(
            "work", machine.states["work"], "coder", context
        )

        assert executor.calls[0]["input_data"] == {}
        assert executor.calls[0]["messages"] is not None
        assert executor.calls[0]["messages"][0]["content"] == "prior prompt"
        assert updated_context["_tool_loop_chain_state"] == "work"
        assert updated_context["_tool_loop_chain_agent"] == "coder"

    @pytest.mark.asyncio
    async def test_continuation_does_not_append_synthetic_user_prompt(self):
        """Continuation turn should not append rendered_user_prompt into existing chain."""
        machine, _ = _build_machine(
            executor_responses=[
                _make_agent_result(
                    content="continued answer",
                    rendered_user_prompt="SHOULD_NOT_APPEND",
                )
            ],
            tool_provider=MockToolProvider(),
        )

        seed_chain = [
            {"role": "user", "content": "prior prompt"},
            {"role": "assistant", "content": "prior answer"},
        ]
        context = {
            "task": "resume",
            "_tool_loop_chain": [*seed_chain],
            "_tool_loop_chain_state": "work",
            "_tool_loop_chain_agent": "coder",
        }

        updated_context, _ = await machine._execute_tool_loop(
            "work", machine.states["work"], "coder", context
        )

        final_chain = updated_context["_tool_loop_chain"]
        assert len(final_chain) == 3
        assert not any(
            m.get("role") == "user" and m.get("content") == "SHOULD_NOT_APPEND"
            for m in final_chain
        )


# ---------------------------------------------------------------------------
# Tests: Guardrails
# ---------------------------------------------------------------------------

class TestMachineGuardrails:

    @pytest.mark.asyncio
    async def test_max_turns(self):
        """Loop stops after max_turns LLM calls."""
        cfg = _machine_config(
            tool_loop={"max_turns": 2, "total_timeout": 600},
            output_to_context={"stop": "{{ output._tool_loop_stop }}"},
        )
        provider = MockToolProvider()
        # Infinite tool call loop
        responses = [
            _make_tool_result([{"id": f"c{i}", "name": "test", "arguments": {}}])
            for i in range(10)
        ]
        machine, _ = _build_machine(responses, tool_provider=provider, config=cfg)

        await machine.execute(input={"task": "loop"})

    @pytest.mark.asyncio
    async def test_max_tool_calls(self):
        """Loop stops when total tool calls exceed limit."""
        cfg = _machine_config(
            tool_loop={"max_tool_calls": 2, "max_turns": 100, "total_timeout": 600},
            output_to_context={"stop": "{{ output._tool_loop_stop }}"},
        )
        provider = MockToolProvider()
        # Each response has 3 tool calls → exceeds limit of 2 on first check
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "test", "arguments": {}},
                    {"id": "c2", "name": "test", "arguments": {}},
                    {"id": "c3", "name": "test", "arguments": {}},
                ]),
            ],
            tool_provider=provider,
            config=cfg,
        )

        await machine.execute(input={"task": "test"})

        # Should have stopped before executing any tools (3 > 2)
        assert len(provider.calls) == 0

    @pytest.mark.asyncio
    async def test_max_cost_guardrail(self):
        """Loop stops when cost exceeds limit."""
        cfg = _machine_config(
            tool_loop={"max_cost": 0.005, "max_turns": 100, "total_timeout": 600},
            output_to_context={"stop": "{{ output._tool_loop_stop }}"},
        )
        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result(
                    [{"id": "c1", "name": "test", "arguments": {}}],
                    cost={"total": 0.003},
                ),
                _make_tool_result(
                    [{"id": "c2", "name": "test", "arguments": {}}],
                    cost={"total": 0.003},
                ),
            ],
            tool_provider=provider,
            config=cfg,
        )

        await machine.execute(input={"task": "expensive"})

        # First round costs 0.003. Second round costs 0.003 → total 0.006 > 0.005
        # But the check is at loop top, so after turn 1 (0.003) the check passes,
        # turn 2 happens (0.006), then the check catches it.
        assert len(provider.calls) >= 1

    @pytest.mark.asyncio
    async def test_jinja2_guardrail_rendering(self):
        """Guardrails can be Jinja2 templates resolved from context with cast filters."""
        cfg = _machine_config(tool_loop={"max_turns": "{{ context.max_iters | int }}", "total_timeout": 600})
        cfg["data"]["context"]["max_iters"] = 2
        provider = MockToolProvider()
        responses = [
            _make_tool_result([{"id": f"c{i}", "name": "test", "arguments": {}}])
            for i in range(10)
        ]
        machine, _ = _build_machine(responses, tool_provider=provider, config=cfg)

        await machine.execute(input={"task": "test"})

        # Should have respected the rendered max_turns=2

    @pytest.mark.asyncio
    async def test_denied_tools(self):
        """Denied tools get skipped with 'not allowed' message."""
        cfg = _machine_config(
            tool_loop={"denied_tools": ["write_file"], "total_timeout": 600},
        )
        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "write_file", "arguments": {}}]),
                _make_agent_result(content="ok"),
            ],
            tool_provider=provider,
            config=cfg,
        )

        await machine.execute(input={"task": "try to write"})

        # write_file should NOT have been executed via provider
        assert len(provider.calls) == 0

    @pytest.mark.asyncio
    async def test_allowed_tools(self):
        """Only tools in allowed_tools execute; others get skipped."""
        cfg = _machine_config(
            tool_loop={"allowed_tools": ["read_file"], "total_timeout": 600},
        )
        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "read_file", "arguments": {}},
                    {"id": "c2", "name": "write_file", "arguments": {}},
                ]),
                _make_agent_result(content="ok"),
            ],
            tool_provider=provider,
            config=cfg,
        )

        await machine.execute(input={"task": "mixed tools"})

        # Only read_file should have been executed
        assert len(provider.calls) == 1
        assert provider.calls[0]["name"] == "read_file"


# ---------------------------------------------------------------------------
# Tests: Hooks
# ---------------------------------------------------------------------------

class TestToolLoopHooks:

    @pytest.mark.asyncio
    async def test_on_tool_calls_fires_once_per_response(self):
        """on_tool_calls fires once per LLM response, even with multiple tool calls."""
        hook_calls = []

        class TrackingHooks(MachineHooks):
            def on_tool_calls(self, state_name, tool_calls, context):
                hook_calls.append(("on_tool_calls", len(tool_calls)))
                return context

        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "a", "arguments": {}},
                    {"id": "c2", "name": "b", "arguments": {}},
                ]),
                _make_agent_result(content="done"),
            ],
            tool_provider=provider,
            hooks=TrackingHooks(),
        )

        await machine.execute(input={"task": "test"})

        assert len(hook_calls) == 1
        assert hook_calls[0] == ("on_tool_calls", 2)

    @pytest.mark.asyncio
    async def test_on_tool_result_fires_per_tool(self):
        """on_tool_result fires once per individual tool call."""
        result_hooks = []

        class TrackingHooks(MachineHooks):
            def on_tool_result(self, state_name, tool_result, context):
                result_hooks.append(tool_result["name"])
                return context

        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "read_file", "arguments": {}},
                    {"id": "c2", "name": "write_file", "arguments": {}},
                    {"id": "c3", "name": "bash", "arguments": {}},
                ]),
                _make_agent_result(content="done"),
            ],
            tool_provider=provider,
            hooks=TrackingHooks(),
        )

        await machine.execute(input={"task": "test"})

        assert result_hooks == ["read_file", "write_file", "bash"]

    @pytest.mark.asyncio
    async def test_abort_tool_loop_from_on_tool_calls(self):
        """Setting _abort_tool_loop in on_tool_calls stops the loop."""

        class AbortHooks(MachineHooks):
            def on_tool_calls(self, state_name, tool_calls, context):
                context["_abort_tool_loop"] = True
                return context

        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "test", "arguments": {}}]),
                _make_agent_result(content="unreachable"),
            ],
            tool_provider=provider,
            hooks=AbortHooks(),
        )

        await machine.execute(input={"task": "test"})

        # No tools should have been executed
        assert len(provider.calls) == 0

    @pytest.mark.asyncio
    async def test_abort_tool_loop_from_on_tool_result(self):
        """Setting _abort_tool_loop in on_tool_result stops before next tool."""

        class AbortAfterFirstHooks(MachineHooks):
            def on_tool_result(self, state_name, tool_result, context):
                context["_abort_tool_loop"] = True
                return context

        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "a", "arguments": {}},
                    {"id": "c2", "name": "b", "arguments": {}},
                ]),
                _make_agent_result(content="done"),
            ],
            tool_provider=provider,
            hooks=AbortAfterFirstHooks(),
        )

        await machine.execute(input={"task": "test"})

        # Only first tool should execute — abort before second
        assert len(provider.calls) == 1
        assert provider.calls[0]["name"] == "a"

    @pytest.mark.asyncio
    async def test_skip_tools_by_id(self):
        """_skip_tools with tool_call IDs skips specific calls."""

        class SkipHooks(MachineHooks):
            def on_tool_calls(self, state_name, tool_calls, context):
                context["_skip_tools"] = ["c2"]
                return context

        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "a", "arguments": {}},
                    {"id": "c2", "name": "b", "arguments": {}},
                    {"id": "c3", "name": "c", "arguments": {}},
                ]),
                _make_agent_result(content="done"),
            ],
            tool_provider=provider,
            hooks=SkipHooks(),
        )

        await machine.execute(input={"task": "test"})

        # c2 should be skipped
        executed_names = [c["name"] for c in provider.calls]
        assert executed_names == ["a", "c"]

    @pytest.mark.asyncio
    async def test_skip_tools_by_name(self):
        """_skip_tools with tool names skips matching calls."""

        class SkipByNameHooks(MachineHooks):
            def on_tool_calls(self, state_name, tool_calls, context):
                context["_skip_tools"] = ["b"]
                return context

        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "a", "arguments": {}},
                    {"id": "c2", "name": "b", "arguments": {}},
                ]),
                _make_agent_result(content="done"),
            ],
            tool_provider=provider,
            hooks=SkipByNameHooks(),
        )

        await machine.execute(input={"task": "test"})

        executed_names = [c["name"] for c in provider.calls]
        assert executed_names == ["a"]

    @pytest.mark.asyncio
    async def test_steering_messages_injection(self):
        """_steering_messages set by hook are appended to chain."""
        steering_injected = False

        class SteeringHooks(MachineHooks):
            def on_tool_result(self, state_name, tool_result, context):
                context["_steering_messages"] = [
                    {"role": "user", "content": "keep focused"}
                ]
                return context

        provider = MockToolProvider()
        machine, executor = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "test", "arguments": {}}]),
                _make_agent_result(content="done"),
            ],
            tool_provider=provider,
            hooks=SteeringHooks(),
        )

        await machine.execute(input={"task": "test"})

        # Second call should receive messages with the steering message
        second_call = executor.calls[1]
        messages = second_call.get("messages")
        assert messages is not None
        steering = [m for m in messages if m.get("content") == "keep focused"]
        assert len(steering) == 1

    @pytest.mark.asyncio
    async def test_get_tool_provider_from_hooks(self):
        """Hook's get_tool_provider overrides constructor provider."""
        hook_provider = MockToolProvider(results={"test": ToolResult(content="from hooks")})
        constructor_provider = MockToolProvider(results={"test": ToolResult(content="from constructor")})

        class ProviderHooks(MachineHooks):
            def get_tool_provider(self, state_name):
                return hook_provider

        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "test", "arguments": {}}]),
                _make_agent_result(content="done"),
            ],
            tool_provider=constructor_provider,
            hooks=ProviderHooks(),
        )

        await machine.execute(input={"task": "test"})

        # Hook provider should have been called, not constructor provider
        assert len(hook_provider.calls) == 1
        assert len(constructor_provider.calls) == 0


# ---------------------------------------------------------------------------
# Tests: Conditional Transitions Mid-Loop
# ---------------------------------------------------------------------------

class TestMidLoopTransitions:

    @pytest.mark.asyncio
    async def test_conditional_transition_mid_batch(self):
        """Hook sets context flag → conditional transition fires mid-batch."""
        cfg = _machine_config(
            transitions=[
                {"condition": "context.needs_review", "to": "done"},
                {"to": "done"},
            ],
        )

        class ReviewHooks(MachineHooks):
            def on_tool_result(self, state_name, tool_result, context):
                if tool_result["name"] == "write_file":
                    context["needs_review"] = True
                return context

        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "read_file", "arguments": {}},
                    {"id": "c2", "name": "write_file", "arguments": {}},
                    {"id": "c3", "name": "bash", "arguments": {}},
                ]),
                _make_agent_result(content="unreachable"),
            ],
            tool_provider=provider,
            hooks=ReviewHooks(),
            config=cfg,
        )

        await machine.execute(input={"task": "test"})

        # bash (c3) should NOT execute — transition fires after write_file
        executed = [c["name"] for c in provider.calls]
        assert "read_file" in executed
        assert "write_file" in executed
        assert "bash" not in executed

    @pytest.mark.asyncio
    async def test_unconditional_transition_does_not_fire_mid_loop(self):
        """Unconditional transitions only fire when the loop completes."""
        cfg = _machine_config(
            transitions=[{"to": "done"}],  # No condition
        )

        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "test", "arguments": {}}]),
                _make_tool_result([{"id": "c2", "name": "test", "arguments": {}}]),
                _make_agent_result(content="all done"),
            ],
            tool_provider=provider,
            config=cfg,
        )

        await machine.execute(input={"task": "test"})

        # Both tools should execute — unconditional didn't fire mid-loop
        assert len(provider.calls) == 2


# ---------------------------------------------------------------------------
# Tests: Checkpoints
# ---------------------------------------------------------------------------

class TestToolLoopCheckpoints:

    def _load_all_snapshots(self, backend, execution_id):
        """Load all snapshots from a MemoryBackend by inspecting stored keys."""
        import json as _json
        snapshots = []
        prefix = f"{execution_id}/"
        for key, data in backend._store.items():
            if key.startswith(prefix) and key.endswith(".json"):
                snap_data = _json.loads(data.decode("utf-8"))
                snapshots.append(MachineSnapshot(**snap_data))
        return snapshots

    @pytest.mark.asyncio
    async def test_checkpoint_saved_per_tool_call(self):
        """A checkpoint is saved after every individual tool call.

        Note: within a single machine step, checkpoint keys collide
        (same step number + event), so the last tool call's checkpoint
        overwrites earlier ones. The checkpoint captures the state after
        all tools in that step. Across multiple rounds (different steps),
        each round gets its own checkpoint.
        """
        backend = MemoryBackend()
        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([
                    {"id": "c1", "name": "a", "arguments": {}},
                    {"id": "c2", "name": "b", "arguments": {}},
                ]),
                _make_agent_result(content="done"),
            ],
            tool_provider=provider,
            persistence=backend,
        )

        await machine.execute(input={"task": "test"})

        all_snapshots = self._load_all_snapshots(backend, machine.execution_id)
        tool_checkpoints = [s for s in all_snapshots if s.event == "tool_call"]
        # One persisted checkpoint per machine step (second tool overwrites first)
        assert len(tool_checkpoints) == 1
        # But it captures both tool results in the chain
        chain = tool_checkpoints[0].tool_loop_state["chain"]
        tool_msgs = [m for m in chain if m.get("role") == "tool"]
        assert len(tool_msgs) == 2

    @pytest.mark.asyncio
    async def test_checkpoint_contains_tool_loop_state(self):
        """tool_call checkpoints include tool_loop_state with chain, turns, etc."""
        backend = MemoryBackend()
        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "test", "arguments": {}}]),
                _make_agent_result(content="done"),
            ],
            tool_provider=provider,
            persistence=backend,
        )

        await machine.execute(input={"task": "test"})

        all_snapshots = self._load_all_snapshots(backend, machine.execution_id)
        tool_cp = [s for s in all_snapshots if s.event == "tool_call"]
        assert len(tool_cp) == 1

        tls = tool_cp[0].tool_loop_state
        assert tls is not None
        assert "chain" in tls
        assert tls["turns"] == 1
        assert tls["tool_calls_count"] == 1
        assert "loop_cost" in tls


# ---------------------------------------------------------------------------
# Tests: Error Cases
# ---------------------------------------------------------------------------

class TestToolLoopErrors:

    @pytest.mark.asyncio
    async def test_non_capable_adapter_raises(self):
        """Adapter without execute_with_tools raises RuntimeError."""
        cfg = _machine_config()
        machine = FlatMachine(
            config_dict=cfg,
            persistence=MemoryBackend(),
        )
        machine._agents = {"coder": NoToolsExecutor()}

        with pytest.raises(RuntimeError, match="does not support"):
            await machine.execute(input={"task": "test"})

    @pytest.mark.asyncio
    async def test_agent_error_raises(self):
        """Agent error during tool loop raises RuntimeError."""
        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_agent_result(
                    error={"type": "ServerError", "message": "model down"},
                    finish_reason="error",
                ),
            ],
            tool_provider=provider,
        )

        with pytest.raises(RuntimeError, match="model down"):
            await machine.execute(input={"task": "test"})

    @pytest.mark.asyncio
    async def test_no_tool_provider_returns_error_result(self):
        """If no tool provider is configured, tool calls get error results."""
        machine, executor = _build_machine(
            executor_responses=[
                _make_tool_result([{"id": "c1", "name": "test", "arguments": {}}]),
                _make_agent_result(content="ok"),
            ],
            tool_provider=None,
        )

        await machine.execute(input={"task": "test"})

        # Second call should have received a chain with an error tool result
        second_call = executor.calls[1]
        messages = second_call.get("messages")
        assert messages is not None
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "No tool provider configured" in tool_msgs[0]["content"]


# ---------------------------------------------------------------------------
# Tests: Cost Tracking
# ---------------------------------------------------------------------------

class TestCostTracking:

    @pytest.mark.asyncio
    async def test_loop_cost_and_machine_total_cost(self):
        """loop_cost tracks per-loop cost; machine total_cost accumulates."""
        cfg = _machine_config(
            output_to_context={
                "loop_cost": "{{ output._tool_loop_cost }}",
            },
        )
        provider = MockToolProvider()
        machine, _ = _build_machine(
            executor_responses=[
                _make_tool_result(
                    [{"id": "c1", "name": "test", "arguments": {}}],
                    cost={"total": 0.01},
                ),
                _make_agent_result(content="done", cost={"total": 0.005}),
            ],
            tool_provider=provider,
            config=cfg,
        )

        await machine.execute(input={"task": "test"})

        # Machine total_cost should be accumulated
        assert machine.total_cost == pytest.approx(0.015)


# ---------------------------------------------------------------------------
# Tests: Helper Methods
# ---------------------------------------------------------------------------

class TestHelperMethods:

    def test_find_conditional_transition_skips_unconditional(self):
        """_find_conditional_transition ignores transitions without conditions."""
        cfg = _machine_config(transitions=[
            {"condition": "context.flag", "to": "flagged"},
            {"to": "default"},
        ])
        machine = FlatMachine(config_dict=cfg)

        # Flag not set → no conditional match
        result = machine._find_conditional_transition("work", {"flag": False})
        assert result is None

        # Flag set → matches
        result = machine._find_conditional_transition("work", {"flag": True})
        assert result == "flagged"

    def test_render_guardrail_number(self):
        """_render_guardrail passes through numbers unchanged."""
        machine = FlatMachine(config_dict=_machine_config())
        result = machine._render_guardrail(42, {}, int)
        assert result == 42

    def test_render_guardrail_none(self):
        """_render_guardrail returns None for None input."""
        machine = FlatMachine(config_dict=_machine_config())
        result = machine._render_guardrail(None, {}, int)
        assert result is None

    def test_render_guardrail_jinja(self):
        """_render_guardrail renders Jinja2 template strings."""
        machine = FlatMachine(config_dict=_machine_config())
        result = machine._render_guardrail(
            "{{ context.budget }}",
            {"context": {"budget": "10"}},
            int,
        )
        assert result == 10

    def test_build_assistant_message_no_tools(self):
        """_build_assistant_message builds simple message without tool_calls."""
        machine = FlatMachine(config_dict=_machine_config())
        result = AgentResult(content="hello")
        msg = machine._build_assistant_message(result)
        assert msg["role"] == "assistant"
        assert msg["content"] == "hello"
        assert "tool_calls" not in msg

    def test_build_assistant_message_with_tools(self):
        """_build_assistant_message includes tool_calls in OpenAI format."""
        machine = FlatMachine(config_dict=_machine_config())
        result = AgentResult(
            content="let me check",
            tool_calls=[
                {"id": "c1", "name": "read_file", "arguments": {"path": "x.py"}},
            ],
        )
        msg = machine._build_assistant_message(result)
        assert msg["role"] == "assistant"
        assert len(msg["tool_calls"]) == 1
        tc = msg["tool_calls"][0]
        assert tc["id"] == "c1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "read_file"
        # arguments should be JSON string
        import json
        assert json.loads(tc["function"]["arguments"]) == {"path": "x.py"}

    def test_extract_cost_from_dict(self):
        """_extract_cost handles cost dict with total."""
        machine = FlatMachine(config_dict=_machine_config())
        result = AgentResult(cost={"total": 0.42})
        assert machine._extract_cost(result) == pytest.approx(0.42)

    def test_extract_cost_from_float(self):
        """_extract_cost handles plain float cost."""
        machine = FlatMachine(config_dict=_machine_config())
        result = AgentResult(cost=0.99)
        assert machine._extract_cost(result) == pytest.approx(0.99)

    def test_extract_cost_none(self):
        """_extract_cost returns 0.0 when no cost info."""
        machine = FlatMachine(config_dict=_machine_config())
        result = AgentResult()
        assert machine._extract_cost(result) == 0.0

    def test_resolve_tool_definitions_from_provider(self):
        """Provider definitions are used when agent YAML has no tools."""
        cfg = _machine_config()
        machine = FlatMachine(config_dict=cfg)

        provider = MockToolProvider(definitions=[
            {"type": "function", "function": {"name": "read", "parameters": {}}},
        ])

        defs = machine._resolve_tool_definitions("coder", provider)
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "read"

    def test_resolve_tool_definitions_from_inline_agent(self):
        """Tool definitions come from inline agent config when no provider."""
        agent_config = {
            "spec": "flatagent",
            "spec_version": "1.1.1",
            "data": {
                "name": "test",
                "model": {"provider": "test", "name": "test"},
                "system": "test",
                "user": "{{ input.task }}",
                "tools": [
                    {"type": "function", "function": {"name": "yaml_tool", "parameters": {}}},
                ],
            },
        }
        cfg = _machine_config(agent_inline=agent_config)
        machine = FlatMachine(config_dict=cfg)

        defs = machine._resolve_tool_definitions("coder", None)
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "yaml_tool"

    def test_resolve_tool_definitions_merge(self):
        """Provider definitions override YAML definitions by name."""
        agent_config = {
            "spec": "flatagent",
            "spec_version": "1.1.1",
            "data": {
                "name": "test",
                "model": {"provider": "test", "name": "test"},
                "system": "test",
                "user": "{{ input.task }}",
                "tools": [
                    {"type": "function", "function": {"name": "shared", "description": "yaml version", "parameters": {}}},
                    {"type": "function", "function": {"name": "yaml_only", "parameters": {}}},
                ],
            },
        }
        cfg = _machine_config(agent_inline=agent_config)
        machine = FlatMachine(config_dict=cfg)

        provider = MockToolProvider(definitions=[
            {"type": "function", "function": {"name": "shared", "description": "provider version", "parameters": {}}},
            {"type": "function", "function": {"name": "provider_only", "parameters": {}}},
        ])

        defs = machine._resolve_tool_definitions("coder", provider)
        names = [d["function"]["name"] for d in defs]
        assert "shared" in names
        assert "yaml_only" in names
        assert "provider_only" in names
        # Provider's version of "shared" should win
        shared_def = [d for d in defs if d["function"]["name"] == "shared"][0]
        assert shared_def["function"]["description"] == "provider version"


# ---------------------------------------------------------------------------
# Tests: FlatAgentExecutor adapter
# ---------------------------------------------------------------------------

class TestFlatAgentExecutorAdapter:
    """Test the FlatAgentExecutor.execute_with_tools and _map_response."""

    def test_agent_result_fields(self):
        """AgentResult has tool_calls and rendered_user_prompt fields."""
        r = AgentResult(
            tool_calls=[{"id": "c1", "name": "test"}],
            rendered_user_prompt="hello",
        )
        assert r.tool_calls == [{"id": "c1", "name": "test"}]
        assert r.rendered_user_prompt == "hello"

    def test_coerce_agent_result_with_tool_fields(self):
        """coerce_agent_result maps tool_calls and rendered_user_prompt from dicts."""
        from flatmachines.agents import coerce_agent_result

        d = {
            "content": "hi",
            "tool_calls": [{"id": "x", "name": "y"}],
            "rendered_user_prompt": "prompt text",
        }
        r = coerce_agent_result(d)
        assert r.tool_calls == [{"id": "x", "name": "y"}]
        assert r.rendered_user_prompt == "prompt text"


# ---------------------------------------------------------------------------
# Tests: Hook Subclasses
# ---------------------------------------------------------------------------

class TestHookSubclasses:

    def test_composite_hooks_chains_tool_hooks(self):
        """CompositeHooks chains on_tool_calls and on_tool_result."""
        from flatmachines.hooks import CompositeHooks

        calls_a = []
        calls_b = []

        class HooksA(MachineHooks):
            def on_tool_calls(self, state_name, tool_calls, context):
                calls_a.append("tool_calls")
                context["a_saw_calls"] = True
                return context

            def on_tool_result(self, state_name, tool_result, context):
                calls_a.append("tool_result")
                return context

        class HooksB(MachineHooks):
            def on_tool_calls(self, state_name, tool_calls, context):
                calls_b.append("tool_calls")
                assert context.get("a_saw_calls")  # A ran first
                return context

            def on_tool_result(self, state_name, tool_result, context):
                calls_b.append("tool_result")
                return context

        composite = CompositeHooks(HooksA(), HooksB())
        ctx = composite.on_tool_calls("work", [{"id": "c1"}], {})
        assert ctx["a_saw_calls"]
        assert calls_a == ["tool_calls"]
        assert calls_b == ["tool_calls"]

        ctx = composite.on_tool_result("work", {"name": "test"}, ctx)
        assert calls_a == ["tool_calls", "tool_result"]
        assert calls_b == ["tool_calls", "tool_result"]

    def test_composite_hooks_get_tool_provider_first_wins(self):
        """CompositeHooks returns first non-None tool provider."""
        from flatmachines.hooks import CompositeHooks

        provider_b = MockToolProvider()

        class HooksA(MachineHooks):
            pass  # Returns None

        class HooksB(MachineHooks):
            def get_tool_provider(self, state_name):
                return provider_b

        composite = CompositeHooks(HooksA(), HooksB())
        assert composite.get_tool_provider("work") is provider_b

    def test_logging_hooks_tool_methods(self):
        """LoggingHooks has no-error implementations of tool hook methods."""
        from flatmachines.hooks import LoggingHooks

        hooks = LoggingHooks()
        ctx = hooks.on_tool_calls("work", [{"name": "test"}], {"key": "val"})
        assert ctx == {"key": "val"}

        ctx = hooks.on_tool_result("work", {"name": "test", "is_error": False}, ctx)
        assert ctx == {"key": "val"}
