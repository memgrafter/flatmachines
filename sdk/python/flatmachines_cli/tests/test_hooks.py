"""Tests for CLIHooks."""

import asyncio
import pytest
from flatmachines_cli.hooks import CLIHooks
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import StatusProcessor
from flatmachines_cli import events


class MockBackend:
    def __init__(self):
        self.emitted_events = []
        self.action_results = {}

    def emit(self, event):
        self.emitted_events.append(event)

    def handle_action(self, action_name, context):
        if action_name in self.action_results:
            context.update(self.action_results[action_name])
        return context


class TestCLIHooksEmission:
    def test_on_machine_start(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        ctx = {"machine": {"machine_name": "test"}}
        result = hooks.on_machine_start(ctx)
        assert result is ctx
        assert len(backend.emitted_events) == 1
        assert backend.emitted_events[0]["type"] == events.MACHINE_START

    def test_on_machine_end(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        output = hooks.on_machine_end({}, {"result": "ok"})
        assert output == {"result": "ok"}
        assert backend.emitted_events[0]["type"] == events.MACHINE_END

    def test_on_state_enter(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        ctx = {"machine": {"step": 1}}
        result = hooks.on_state_enter("my_state", ctx)
        assert result is ctx
        assert backend.emitted_events[0]["type"] == events.STATE_ENTER

    def test_on_state_exit(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        output = hooks.on_state_exit("s", {}, {"data": 1})
        assert output == {"data": 1}
        assert backend.emitted_events[0]["type"] == events.STATE_EXIT

    def test_on_state_exit_none_output(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        output = hooks.on_state_exit("s", {}, None)
        assert output is None

    def test_on_transition(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        result = hooks.on_transition("from", "to", {})
        assert result == "to"
        assert backend.emitted_events[0]["type"] == events.TRANSITION

    def test_on_error(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        result = hooks.on_error("s1", ValueError("bad"), {})
        assert result is None
        assert backend.emitted_events[0]["type"] == events.ERROR

    def test_on_action(self):
        backend = MockBackend()
        backend.action_results["human_review"] = {"approved": True}
        hooks = CLIHooks(backend)
        ctx = hooks.on_action("human_review", {"task": "review"})
        assert ctx["approved"] is True
        assert backend.emitted_events[0]["type"] == events.ACTION

    def test_on_tool_calls(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        calls = [{"name": "bash", "arguments": {"command": "ls"}}]
        ctx = hooks.on_tool_calls("s1", calls, {"key": "val"})
        assert ctx == {"key": "val"}
        assert backend.emitted_events[0]["type"] == events.TOOL_CALLS

    def test_on_tool_result(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        result = {"name": "bash", "content": "output"}
        ctx = hooks.on_tool_result("s1", result, {"key": "val"})
        assert ctx == {"key": "val"}
        assert backend.emitted_events[0]["type"] == events.TOOL_RESULT


class TestCLIHooksToolProvider:
    def test_no_factory_returns_none(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        assert hooks.get_tool_provider("s1") is None

    def test_factory_called_lazily(self):
        backend = MockBackend()
        factory_calls = []
        def factory(state_name):
            factory_calls.append(state_name)
            return "mock_provider"
        hooks = CLIHooks(backend, tool_provider_factory=factory)
        assert len(factory_calls) == 0
        provider = hooks.get_tool_provider("s1")
        assert provider == "mock_provider"
        assert len(factory_calls) == 1

    def test_factory_called_once(self):
        backend = MockBackend()
        call_count = [0]
        def factory(state_name):
            call_count[0] += 1
            return "provider"
        hooks = CLIHooks(backend, tool_provider_factory=factory)
        hooks.get_tool_provider("s1")
        hooks.get_tool_provider("s2")
        assert call_count[0] == 1


class TestCLIHooksWithRealBackend:
    @pytest.mark.asyncio
    async def test_hooks_to_bus(self):
        bus = DataBus()
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        hooks = CLIHooks(backend)

        await backend.start()

        hooks.on_machine_start({"machine": {"machine_name": "integration"}})
        hooks.on_state_enter("analyze", {"machine": {"step": 1}})
        await asyncio.sleep(0.15)

        status = bus.read_data("status")
        assert status is not None
        assert status["machine_name"] == "integration"
        assert status["state"] == "analyze"

        await backend.stop()
