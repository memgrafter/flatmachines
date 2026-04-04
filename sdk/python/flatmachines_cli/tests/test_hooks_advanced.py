"""Advanced hooks tests — emission ordering, context flow, tool provider."""

import pytest
from flatmachines_cli.hooks import CLIHooks
from flatmachines_cli import events


class MockBackend:
    def __init__(self):
        self.emitted = []
        self.action_results = {}

    def emit(self, event):
        self.emitted.append(event)

    def handle_action(self, action_name, context):
        if action_name in self.action_results:
            context.update(self.action_results[action_name])
        return context


class TestHooksEmissionOrdering:
    """Test that hooks emit events in the correct order."""

    def test_full_lifecycle_order(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)

        hooks.on_machine_start({"machine": {}})
        hooks.on_state_enter("s1", {"machine": {"step": 1}})
        hooks.on_tool_calls("s1", [{"name": "bash"}], {})
        hooks.on_tool_result("s1", {"name": "bash", "content": "ok"}, {})
        hooks.on_state_exit("s1", {}, {"result": "done"})
        hooks.on_transition("s1", "s2", {})
        hooks.on_state_enter("s2", {"machine": {"step": 2}})
        hooks.on_machine_end({}, {"output": "final"})

        types = [e["type"] for e in backend.emitted]
        assert types == [
            events.MACHINE_START,
            events.STATE_ENTER,
            events.TOOL_CALLS,
            events.TOOL_RESULT,
            events.STATE_EXIT,
            events.TRANSITION,
            events.STATE_ENTER,
            events.MACHINE_END,
        ]

    def test_error_in_lifecycle(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)

        hooks.on_machine_start({"machine": {}})
        hooks.on_state_enter("s1", {"machine": {"step": 1}})
        hooks.on_error("s1", ValueError("boom"), {})

        types = [e["type"] for e in backend.emitted]
        assert types == [events.MACHINE_START, events.STATE_ENTER, events.ERROR]


class TestHooksContextFlow:
    """Test that hooks pass context through correctly."""

    def test_machine_start_returns_context(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        ctx = {"machine": {"machine_name": "test"}, "extra": "data"}
        result = hooks.on_machine_start(ctx)
        assert result is ctx  # same object
        assert result["extra"] == "data"

    def test_machine_end_returns_output(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        output = {"result": "success", "files": ["/tmp/a"]}
        result = hooks.on_machine_end({}, output)
        assert result is output

    def test_state_enter_returns_context(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        ctx = {"key": "value"}
        result = hooks.on_state_enter("s", ctx)
        assert result is ctx

    def test_state_exit_returns_output(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        output = {"data": [1, 2, 3]}
        result = hooks.on_state_exit("s", {}, output)
        assert result is output

    def test_transition_returns_to_state(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        result = hooks.on_transition("from", "to_state", {})
        assert result == "to_state"

    def test_error_returns_none(self):
        """on_error returns None to signal re-raise."""
        backend = MockBackend()
        hooks = CLIHooks(backend)
        result = hooks.on_error("s", RuntimeError("e"), {})
        assert result is None

    def test_action_returns_modified_context(self):
        backend = MockBackend()
        backend.action_results["review"] = {"approved": True}
        hooks = CLIHooks(backend)
        ctx = {"task": "check"}
        result = hooks.on_action("review", ctx)
        assert result["approved"] is True
        assert result["task"] == "check"

    def test_tool_calls_returns_context(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        ctx = {"step": 1}
        result = hooks.on_tool_calls("s", [], ctx)
        assert result is ctx

    def test_tool_result_returns_context(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        ctx = {"step": 2}
        result = hooks.on_tool_result("s", {}, ctx)
        assert result is ctx


class TestToolProviderLifecycle:
    def test_no_factory_no_provider(self):
        backend = MockBackend()
        hooks = CLIHooks(backend)
        assert hooks.get_tool_provider("any") is None

    def test_factory_lazy_creation(self):
        backend = MockBackend()
        created = []

        def factory(state):
            created.append(state)
            return f"provider_for_{state}"

        hooks = CLIHooks(backend, tool_provider_factory=factory)
        assert len(created) == 0

        p = hooks.get_tool_provider("state_1")
        assert p == "provider_for_state_1"
        assert len(created) == 1

    def test_factory_cached_after_first_call(self):
        backend = MockBackend()
        count = [0]

        def factory(state):
            count[0] += 1
            return "singleton"

        hooks = CLIHooks(backend, tool_provider_factory=factory)
        hooks.get_tool_provider("s1")
        hooks.get_tool_provider("s2")
        hooks.get_tool_provider("s3")
        assert count[0] == 1

    def test_factory_exception_propagates(self):
        backend = MockBackend()

        def bad_factory(state):
            raise RuntimeError("factory error")

        hooks = CLIHooks(backend, tool_provider_factory=bad_factory)
        with pytest.raises(RuntimeError, match="factory error"):
            hooks.get_tool_provider("s")
