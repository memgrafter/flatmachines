"""
Unit tests for context.machine — immutable runtime metadata.

Tests:
- context.machine is present with correct fields
- context.machine is immutable (MappingProxyType)
- context.machine updates per step (step, current_state, cost)
- context.machine is usable in transition conditions
- context.machine is usable in Jinja2 templates
- context.machine survives checkpoint serialization
- context.machine is rebuilt from live state on resume
- context.machine user overwrite is discarded at next step
"""

from types import MappingProxyType

import pytest

from flatmachines import (
    FlatMachine,
    MemoryBackend,
    CheckpointManager,
    MachineHooks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_config(states=None):
    """Minimal machine config with no agents."""
    if states is None:
        states = {
            "start": {
                "type": "initial",
                "transitions": [{"to": "middle"}],
            },
            "middle": {
                "transitions": [{"to": "done"}],
            },
            "done": {
                "type": "final",
                "output": {
                    "result": "ok",
                },
            },
        }
    return {
        "spec": "flatmachine",
        "spec_version": "2.0.0",
        "data": {
            "name": "test-machine",
            "context": {
                "task": "{{ input.task }}",
            },
            "agents": {},
            "states": states,
        },
    }


class CaptureHooks(MachineHooks):
    """Hooks that capture context.machine at each state entry."""

    def __init__(self):
        self.state_entries = {}

    def on_state_enter(self, state_name, context):
        machine_meta = context.get("machine")
        if machine_meta is not None:
            # Copy to plain dict so it survives after the proxy is replaced
            self.state_entries[state_name] = dict(machine_meta)
        return context


class OverwriteHooks(MachineHooks):
    """Hooks that try to overwrite context.machine."""

    def __init__(self):
        self.saw_overwrite = False

    def on_state_enter(self, state_name, context):
        if state_name == "middle":
            # Try to replace the whole key
            context["machine"] = {"execution_id": "tampered"}
            self.saw_overwrite = True
        return context


# ---------------------------------------------------------------------------
# Presence and fields
# ---------------------------------------------------------------------------

class TestContextMachinePresent:

    @pytest.mark.asyncio
    async def test_context_machine_present_at_state_enter(self):
        hooks = CaptureHooks()
        machine = FlatMachine(config_dict=_simple_config(), hooks=hooks)
        await machine.execute(input={"task": "test"})

        # Should have captured at start, middle, done
        assert "start" in hooks.state_entries
        assert "middle" in hooks.state_entries

    @pytest.mark.asyncio
    async def test_context_machine_has_all_fields(self):
        hooks = CaptureHooks()
        machine = FlatMachine(config_dict=_simple_config(), hooks=hooks)
        await machine.execute(input={"task": "test"})

        meta = hooks.state_entries["start"]
        expected_keys = {
            "execution_id",
            "machine_name",
            "parent_execution_id",
            "spec_version",
            "step",
            "current_state",
            "total_api_calls",
            "total_cost",
        }
        assert set(meta.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_context_machine_values_correct(self):
        hooks = CaptureHooks()
        machine = FlatMachine(config_dict=_simple_config(), hooks=hooks)
        await machine.execute(input={"task": "test"})

        meta = hooks.state_entries["start"]
        assert meta["execution_id"] == machine.execution_id
        assert meta["machine_name"] == "test-machine"
        assert meta["parent_execution_id"] is None
        assert meta["current_state"] == "start"
        assert meta["total_api_calls"] == 0
        assert meta["total_cost"] == 0.0


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------

class TestContextMachineImmutable:

    @pytest.mark.asyncio
    async def test_mapping_proxy_type(self):
        """context.machine should be a MappingProxyType."""
        captured = {}

        class TypeCheckHooks(MachineHooks):
            def on_state_enter(self, state_name, context):
                if state_name == "start":
                    captured["type"] = type(context.get("machine"))
                    captured["value"] = context.get("machine")
                return context

        machine = FlatMachine(config_dict=_simple_config(), hooks=TypeCheckHooks())
        await machine.execute(input={"task": "test"})

        assert captured["type"] is MappingProxyType

    @pytest.mark.asyncio
    async def test_write_raises_type_error(self):
        """Writing to context.machine should raise TypeError."""
        error_raised = {}

        class MutateHooks(MachineHooks):
            def on_state_enter(self, state_name, context):
                if state_name == "start":
                    try:
                        context["machine"]["execution_id"] = "tampered"
                        error_raised["raised"] = False
                    except TypeError:
                        error_raised["raised"] = True
                return context

        machine = FlatMachine(config_dict=_simple_config(), hooks=MutateHooks())
        await machine.execute(input={"task": "test"})

        assert error_raised["raised"] is True


# ---------------------------------------------------------------------------
# Overwrite discarded
# ---------------------------------------------------------------------------

class TestContextMachineOverwrite:

    @pytest.mark.asyncio
    async def test_overwrite_discarded_at_next_step(self):
        """If user overwrites context.machine, it's rebuilt at the next step."""
        hooks = OverwriteHooks()
        capture = CaptureHooks()

        # Use OverwriteHooks to tamper, then check at done
        class CombinedHooks(MachineHooks):
            def on_state_enter(self, state_name, context):
                context = hooks.on_state_enter(state_name, context)
                context = capture.on_state_enter(state_name, context)
                return context

        machine = FlatMachine(config_dict=_simple_config(), hooks=CombinedHooks())
        await machine.execute(input={"task": "test"})

        assert hooks.saw_overwrite is True
        # At "done", context.machine should be rebuilt, not the tampered value
        done_meta = capture.state_entries["done"]
        assert done_meta["execution_id"] == machine.execution_id
        assert done_meta["current_state"] == "done"


# ---------------------------------------------------------------------------
# Updates per step
# ---------------------------------------------------------------------------

class TestContextMachineUpdates:

    @pytest.mark.asyncio
    async def test_step_increments(self):
        hooks = CaptureHooks()
        machine = FlatMachine(config_dict=_simple_config(), hooks=hooks)
        await machine.execute(input={"task": "test"})

        assert hooks.state_entries["start"]["step"] == 1
        assert hooks.state_entries["middle"]["step"] == 2
        assert hooks.state_entries["done"]["step"] == 3

    @pytest.mark.asyncio
    async def test_current_state_updates(self):
        hooks = CaptureHooks()
        machine = FlatMachine(config_dict=_simple_config(), hooks=hooks)
        await machine.execute(input={"task": "test"})

        assert hooks.state_entries["start"]["current_state"] == "start"
        assert hooks.state_entries["middle"]["current_state"] == "middle"
        assert hooks.state_entries["done"]["current_state"] == "done"


# ---------------------------------------------------------------------------
# Transition conditions
# ---------------------------------------------------------------------------

class TestContextMachineInConditions:

    @pytest.mark.asyncio
    async def test_condition_on_step(self):
        """Transition condition can reference context.machine.step."""
        states = {
            "start": {
                "type": "initial",
                "transitions": [{"to": "loop"}],
            },
            "loop": {
                "transitions": [
                    {"condition": "context.machine.step >= 3", "to": "done"},
                    {"to": "loop"},
                ],
            },
            "done": {
                "type": "final",
                "output": {"result": "ok"},
            },
        }
        machine = FlatMachine(config_dict=_simple_config(states))
        result = await machine.execute(input={"task": "test"})
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_condition_on_execution_id(self):
        """Transition condition can reference context.machine.execution_id."""

        class CaptureIdHook(MachineHooks):
            def on_state_enter(self, state_name, context):
                if state_name == "start":
                    # Read from the immutable proxy into user context
                    context["my_id"] = context["machine"]["execution_id"]
                return context

        states = {
            "start": {
                "type": "initial",
                "transitions": [{"to": "check"}],
            },
            "check": {
                "transitions": [
                    {
                        "condition": "context.machine.execution_id == context.my_id",
                        "to": "done",
                    },
                    {"to": "fail"},
                ],
            },
            "done": {
                "type": "final",
                "output": {"matched": True},
            },
            "fail": {
                "type": "final",
                "output": {"matched": False},
            },
        }
        machine = FlatMachine(config_dict=_simple_config(states), hooks=CaptureIdHook())
        result = await machine.execute(input={"task": "test"})
        assert result == {"matched": True}

    @pytest.mark.asyncio
    async def test_condition_on_machine_name(self):
        """Transition condition can reference context.machine.machine_name."""
        states = {
            "start": {
                "type": "initial",
                "transitions": [
                    {
                        "condition": "context.machine.machine_name == 'test-machine'",
                        "to": "done",
                    },
                    {"to": "fail"},
                ],
            },
            "done": {
                "type": "final",
                "output": {"matched": True},
            },
            "fail": {
                "type": "final",
                "output": {"matched": False},
            },
        }
        machine = FlatMachine(config_dict=_simple_config(states))
        result = await machine.execute(input={"task": "test"})
        assert result == {"matched": True}


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TestContextMachineInTemplates:

    @pytest.mark.asyncio
    async def test_template_renders_execution_id(self):
        """Jinja2 templates can access context.machine fields in final output."""
        states = {
            "start": {
                "type": "initial",
                "transitions": [{"to": "done"}],
            },
            "done": {
                "type": "final",
                "output": {
                    "id": "{{ context.machine.execution_id }}",
                    "name": "{{ context.machine.machine_name }}",
                },
            },
        }
        machine = FlatMachine(config_dict=_simple_config(states))
        result = await machine.execute(input={"task": "test"})
        assert result["id"] == machine.execution_id
        assert result["name"] == "test-machine"


# ---------------------------------------------------------------------------
# Serialization (checkpoint round-trip)
# ---------------------------------------------------------------------------

class TestContextMachineSerialization:

    @pytest.mark.asyncio
    async def test_checkpoint_serializes_with_proxy(self):
        """Checkpointing works even though context.machine is a MappingProxyType."""
        persistence = MemoryBackend()
        machine = FlatMachine(
            config_dict=_simple_config(),
            persistence=persistence,
        )
        await machine.execute(input={"task": "test"})

        # Load the latest checkpoint — should have serialized successfully
        mgr = CheckpointManager(persistence, machine.execution_id)
        snapshot = await mgr.load_latest()
        assert snapshot is not None
        # context.machine should be a plain dict in the snapshot (not proxy)
        assert isinstance(snapshot.context.get("machine"), dict)
        assert snapshot.context["machine"]["machine_name"] == "test-machine"


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

class TestContextMachineResume:

    @pytest.mark.asyncio
    async def test_rebuilt_on_resume(self):
        """On resume, context.machine reflects the live machine, not stale snapshot."""
        persistence = MemoryBackend()

        # Run a machine that waits
        from flatmachines.signals import MemorySignalBackend

        signal_backend = MemorySignalBackend()

        wait_config = {
            "spec": "flatmachine",
            "spec_version": "2.0.0",
            "data": {
                "name": "resume-test",
                "context": {},
                "agents": {},
                "states": {
                    "start": {
                        "type": "initial",
                        "transitions": [{"to": "wait_state"}],
                    },
                    "wait_state": {
                        "wait_for": "test/signal",
                        "output_to_context": {
                            "signal_value": "{{ output.value }}",
                        },
                        "transitions": [{"to": "done"}],
                    },
                    "done": {
                        "type": "final",
                        "output": {
                            "exec_id": "{{ context.machine.execution_id }}",
                        },
                    },
                },
            },
        }

        machine1 = FlatMachine(
            config_dict=wait_config,
            persistence=persistence,
            signal_backend=signal_backend,
        )
        exec_id = machine1.execution_id
        result1 = await machine1.execute(input={})
        assert result1.get("_waiting") is True

        # Provide signal and resume
        await signal_backend.send("test/signal", {"value": "hello"})

        machine2 = FlatMachine(
            config_dict=wait_config,
            persistence=persistence,
            signal_backend=signal_backend,
        )
        result2 = await machine2.execute(resume_from=exec_id)

        # The resumed machine should have context.machine.execution_id = exec_id
        assert result2["exec_id"] == exec_id
