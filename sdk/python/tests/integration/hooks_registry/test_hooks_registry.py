"""
Integration tests for the HooksRegistry.

Tests the full lifecycle: registry creation, hook registration,
resolution from machine config, execution through the machine,
and propagation to child machines.

No LLM calls — all tests use action-only machines.
"""

import asyncio
import pytest
from typing import Any, Dict, Optional

from flatmachines import (
    FlatMachine,
    MachineHooks,
    CompositeHooks,
    LoggingHooks,
    HooksRegistry,
)


# ---------------------------------------------------------------------------
# Test hook implementations
# ---------------------------------------------------------------------------

class CounterHooks(MachineHooks):
    """Increments a counter via the 'increment' action."""

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "increment":
            context["count"] = context.get("count", 0) + 1
        return context


class CounterWithStepHooks(MachineHooks):
    """Increments by a configurable step size."""

    def __init__(self, step: int = 1):
        self.step = step

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "increment":
            context["count"] = context.get("count", 0) + self.step
        return context


class AppendHooks(MachineHooks):
    """Appends a character via the 'append' action."""

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "append":
            context["result"] = context.get("result", "") + context.get("char", "x")
        return context


class LifecycleTracker(MachineHooks):
    """Tracks all lifecycle events for verification."""

    def __init__(self):
        self.events = []

    def on_machine_start(self, context):
        self.events.append("machine_start")
        return context

    def on_machine_end(self, context, final_output):
        self.events.append("machine_end")
        return final_output

    def on_state_enter(self, state_name, context):
        self.events.append(f"enter:{state_name}")
        return context

    def on_state_exit(self, state_name, context, output):
        self.events.append(f"exit:{state_name}")
        return output

    def on_action(self, action_name, context):
        self.events.append(f"action:{action_name}")
        if action_name == "increment":
            context["count"] = context.get("count", 0) + 1
        return context


# ---------------------------------------------------------------------------
# Machine configs (no agents, no LLM calls)
# ---------------------------------------------------------------------------

COUNTER_MACHINE = {
    "spec": "flatmachine",
    "spec_version": "1.2.0",
    "data": {
        "name": "counter",
        "hooks": "counter",
        "context": {"count": 0},
        "states": {
            "start": {
                "type": "initial",
                "transitions": [{"to": "count_up"}],
            },
            "count_up": {
                "action": "increment",
                "transitions": [
                    {"condition": "context.count >= 3", "to": "done"},
                    {"to": "count_up"},
                ],
            },
            "done": {
                "type": "final",
                "output": {"total": "{{ context.count }}"},
            },
        },
    },
}

COUNTER_WITH_ARGS_MACHINE = {
    "spec": "flatmachine",
    "spec_version": "1.2.0",
    "data": {
        "name": "counter-with-args",
        "hooks": {"name": "counter-step", "args": {"step": 5}},
        "context": {"count": 0},
        "states": {
            "start": {
                "type": "initial",
                "transitions": [{"to": "count_up"}],
            },
            "count_up": {
                "action": "increment",
                "transitions": [
                    {"condition": "context.count >= 10", "to": "done"},
                    {"to": "count_up"},
                ],
            },
            "done": {
                "type": "final",
                "output": {"total": "{{ context.count }}"},
            },
        },
    },
}

COMPOSITE_HOOKS_MACHINE = {
    "spec": "flatmachine",
    "spec_version": "1.2.0",
    "data": {
        "name": "composite",
        "hooks": ["lifecycle", "counter"],
        "context": {"count": 0},
        "states": {
            "start": {
                "type": "initial",
                "transitions": [{"to": "count_up"}],
            },
            "count_up": {
                "action": "increment",
                "transitions": [
                    {"condition": "context.count >= 2", "to": "done"},
                    {"to": "count_up"},
                ],
            },
            "done": {
                "type": "final",
                "output": {"total": "{{ context.count }}"},
            },
        },
    },
}

NO_HOOKS_MACHINE = {
    "spec": "flatmachine",
    "spec_version": "1.2.0",
    "data": {
        "name": "no-hooks",
        "context": {"value": "hello"},
        "states": {
            "start": {
                "type": "initial",
                "transitions": [{"to": "done"}],
            },
            "done": {
                "type": "final",
                "output": {"result": "{{ context.value }}"},
            },
        },
    },
}

PARENT_CHILD_MACHINE = {
    "spec": "flatmachine",
    "spec_version": "1.2.0",
    "data": {
        "name": "parent",
        "hooks": "append",
        "context": {"result": "", "char": "P"},
        "machines": {
            "child": {
                "spec": "flatmachine",
                "spec_version": "1.2.0",
                "data": {
                    "name": "child",
                    "hooks": "append",
                    "context": {
                        "result": "{{ input.prefix }}",
                        "char": "C",
                    },
                    "states": {
                        "start": {
                            "type": "initial",
                            "transitions": [{"to": "do_append"}],
                        },
                        "do_append": {
                            "action": "append",
                            "transitions": [{"to": "done"}],
                        },
                        "done": {
                            "type": "final",
                            "output": {"child_result": "{{ context.result }}"},
                        },
                    },
                },
            },
        },
        "states": {
            "start": {
                "type": "initial",
                "transitions": [{"to": "parent_append"}],
            },
            "parent_append": {
                "action": "append",
                "transitions": [{"to": "call_child"}],
            },
            "call_child": {
                "machine": "child",
                "input": {"prefix": "{{ context.result }}"},
                "output_to_context": {
                    "child_result": "{{ output.child_result }}",
                },
                "transitions": [{"to": "done"}],
            },
            "done": {
                "type": "final",
                "output": {
                    "parent_result": "{{ context.result }}",
                    "child_result": "{{ context.child_result }}",
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHooksRegistryUnit:
    """Unit-level tests for HooksRegistry itself."""

    def test_register_and_has(self):
        registry = HooksRegistry()
        assert not registry.has("counter")
        registry.register("counter", CounterHooks)
        assert registry.has("counter")

    def test_resolve_string(self):
        registry = HooksRegistry()
        registry.register("counter", CounterHooks)
        hooks = registry.resolve("counter")
        assert isinstance(hooks, CounterHooks)

    def test_resolve_dict_with_args(self):
        registry = HooksRegistry()
        registry.register("counter-step", CounterWithStepHooks)
        hooks = registry.resolve({"name": "counter-step", "args": {"step": 10}})
        assert isinstance(hooks, CounterWithStepHooks)
        assert hooks.step == 10

    def test_resolve_list_creates_composite(self):
        registry = HooksRegistry()
        registry.register("counter", CounterHooks)
        registry.register("lifecycle", LifecycleTracker)
        hooks = registry.resolve(["lifecycle", "counter"])
        assert isinstance(hooks, CompositeHooks)

    def test_resolve_unknown_name_raises(self):
        registry = HooksRegistry()
        with pytest.raises(KeyError, match="No hooks registered for name 'missing'"):
            registry.resolve("missing")

    def test_resolve_unknown_in_list_raises(self):
        registry = HooksRegistry()
        registry.register("counter", CounterHooks)
        with pytest.raises(KeyError, match="No hooks registered for name 'missing'"):
            registry.resolve(["counter", "missing"])

    def test_factory_function(self):
        """Register a factory function instead of a class."""
        def make_hooks(step=1):
            return CounterWithStepHooks(step=step)

        registry = HooksRegistry()
        registry.register("factory", make_hooks)
        hooks = registry.resolve({"name": "factory", "args": {"step": 7}})
        assert isinstance(hooks, CounterWithStepHooks)
        assert hooks.step == 7

    def test_overwrite_registration(self):
        registry = HooksRegistry()
        registry.register("x", CounterHooks)
        registry.register("x", AppendHooks)
        hooks = registry.resolve("x")
        assert isinstance(hooks, AppendHooks)


class TestHooksRegistryMachineIntegration:
    """Integration tests: registry + FlatMachine execution."""

    @pytest.mark.asyncio
    async def test_string_hooks_ref(self):
        """hooks: "counter" in config resolves from registry."""
        machine = FlatMachine(config_dict=COUNTER_MACHINE)
        machine.hooks_registry.register("counter", CounterHooks)
        result = await machine.execute()
        assert result["total"] == 3

    @pytest.mark.asyncio
    async def test_hooks_ref_with_args(self):
        """hooks: {name: "counter-step", args: {step: 5}} passes args to constructor."""
        machine = FlatMachine(config_dict=COUNTER_WITH_ARGS_MACHINE)
        machine.hooks_registry.register("counter-step", CounterWithStepHooks)
        result = await machine.execute()
        assert result["total"] == 10

    @pytest.mark.asyncio
    async def test_composite_hooks_ref(self):
        """hooks: ["lifecycle", "counter"] creates CompositeHooks."""
        tracker = LifecycleTracker()
        registry = HooksRegistry()
        registry.register("lifecycle", lambda: tracker)
        registry.register("counter", CounterHooks)

        machine = FlatMachine(config_dict=COMPOSITE_HOOKS_MACHINE, hooks_registry=registry)
        result = await machine.execute()
        assert result["total"] == 2
        assert "machine_start" in tracker.events
        assert "machine_end" in tracker.events
        assert "action:increment" in tracker.events

    @pytest.mark.asyncio
    async def test_no_hooks_in_config(self):
        """Machine with no hooks: field works fine."""
        machine = FlatMachine(config_dict=NO_HOOKS_MACHINE)
        result = await machine.execute()
        assert result["result"] == "hello"

    @pytest.mark.asyncio
    async def test_explicit_hooks_bypasses_registry(self):
        """hooks= constructor arg takes priority over config."""
        step_hooks = CounterWithStepHooks(step=100)
        machine = FlatMachine(config_dict=COUNTER_MACHINE, hooks=step_hooks)
        # "counter" is NOT registered, but hooks= bypasses registry
        result = await machine.execute()
        assert result["total"] == 100

    @pytest.mark.asyncio
    async def test_unregistered_hooks_raises(self):
        """Config references unregistered hooks name → clear error at startup."""
        with pytest.raises(KeyError, match="No hooks registered for name 'counter'"):
            machine = FlatMachine(config_dict=COUNTER_MACHINE)
            # No registration → should fail

    @pytest.mark.asyncio
    async def test_registry_passed_to_constructor(self):
        """Registry can be pre-populated and passed to FlatMachine."""
        registry = HooksRegistry()
        registry.register("counter", CounterHooks)
        machine = FlatMachine(config_dict=COUNTER_MACHINE, hooks_registry=registry)
        result = await machine.execute()
        assert result["total"] == 3

    @pytest.mark.asyncio
    async def test_registry_shared_across_machines(self):
        """Same registry used by multiple machines."""
        registry = HooksRegistry()
        registry.register("counter", CounterHooks)

        m1 = FlatMachine(config_dict=COUNTER_MACHINE, hooks_registry=registry)
        m2 = FlatMachine(config_dict=COUNTER_MACHINE, hooks_registry=registry)

        r1 = await m1.execute()
        r2 = await m2.execute()
        assert r1["total"] == 3
        assert r2["total"] == 3


class TestHooksRegistryChildPropagation:
    """Tests that the registry propagates to child machines."""

    @pytest.mark.asyncio
    async def test_child_machine_inherits_registry(self):
        """Parent's registry is available to inline child machines."""
        registry = HooksRegistry()
        registry.register("append", AppendHooks)

        machine = FlatMachine(config_dict=PARENT_CHILD_MACHINE, hooks_registry=registry)
        result = await machine.execute()

        # Parent appends "P", child gets "P" as prefix and appends "C"
        assert result["parent_result"] == "P"
        assert result["child_result"] == "PC"


class TestHooksRegistryProperty:
    """Tests the hooks_registry property on FlatMachine."""

    def test_property_returns_registry(self):
        machine = FlatMachine(config_dict=NO_HOOKS_MACHINE)
        assert isinstance(machine.hooks_registry, HooksRegistry)

    def test_register_after_construction(self):
        """Can register hooks after FlatMachine is constructed (if config has no hooks:)."""
        machine = FlatMachine(config_dict=NO_HOOKS_MACHINE)
        machine.hooks_registry.register("counter", CounterHooks)
        assert machine.hooks_registry.has("counter")

    @pytest.mark.asyncio
    async def test_register_before_execute_for_hooks_in_config(self):
        """
        When config has hooks: "counter", hooks are resolved at construction time,
        so registration must happen before FlatMachine() is called.
        """
        registry = HooksRegistry()
        registry.register("counter", CounterHooks)
        machine = FlatMachine(config_dict=COUNTER_MACHINE, hooks_registry=registry)
        result = await machine.execute()
        assert result["total"] == 3
