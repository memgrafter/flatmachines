"""Tests for public API contract stability.

These tests verify that the public API surface remains stable across
versions. If any test fails, it means the API has changed — which
should be a conscious decision reflected in the changelog.
"""

import inspect
import pytest
import flatmachines_cli


class TestModuleExports:
    def test_all_exports_importable(self):
        """Every name in __all__ should be importable."""
        for name in flatmachines_cli.__all__:
            obj = getattr(flatmachines_cli, name)
            assert obj is not None, f"{name} exported but is None"

    def test_version_is_string(self):
        assert isinstance(flatmachines_cli.__version__, str)
        parts = flatmachines_cli.__version__.split(".")
        assert len(parts) == 3, "Version should be semver (X.Y.Z)"

    def test_event_types_are_strings(self):
        for name in ("MACHINE_START", "MACHINE_END", "STATE_ENTER",
                      "STATE_EXIT", "TRANSITION", "TOOL_CALLS",
                      "TOOL_RESULT", "ACTION", "ERROR"):
            val = getattr(flatmachines_cli, name)
            assert isinstance(val, str), f"{name} should be a string"


class TestClassInterfaces:
    def test_databus_has_required_methods(self):
        bus = flatmachines_cli.DataBus
        for method in ("write", "read", "read_data", "snapshot",
                       "versions", "slot_names", "reset",
                       "to_json", "from_json", "save", "load"):
            assert hasattr(bus, method), f"DataBus missing {method}"

    def test_slot_has_required_methods(self):
        slot = flatmachines_cli.Slot
        for method in ("write", "read", "read_data", "read_if_changed", "wait"):
            assert hasattr(slot, method), f"Slot missing {method}"

    def test_backend_has_required_methods(self):
        backend = flatmachines_cli.CLIBackend
        for method in ("start", "stop", "emit", "handle_action",
                       "run_machine", "set_frontend", "add_processor",
                       "health_check"):
            assert hasattr(backend, method), f"CLIBackend missing {method}"

    def test_processor_has_required_methods(self):
        proc = flatmachines_cli.Processor
        for method in ("process", "start", "stop", "enqueue", "accepts", "reset"):
            assert hasattr(proc, method), f"Processor missing {method}"
        assert hasattr(proc, "stats"), "Processor missing stats property"

    def test_frontend_is_abstract(self):
        assert inspect.isabstract(flatmachines_cli.Frontend)

    def test_action_handler_has_required_methods(self):
        ah = flatmachines_cli.ActionHandler
        for method in ("register", "set_default", "handle"):
            assert hasattr(ah, method), f"ActionHandler missing {method}"


class TestProcessorSubclasses:
    """Verify all processor subclasses have correct slot names."""

    def test_status_processor_slot(self):
        assert flatmachines_cli.StatusProcessor.slot_name == "status"

    def test_token_processor_slot(self):
        assert flatmachines_cli.TokenProcessor.slot_name == "tokens"

    def test_tool_processor_slot(self):
        assert flatmachines_cli.ToolProcessor.slot_name == "tools"

    def test_content_processor_slot(self):
        assert flatmachines_cli.ContentProcessor.slot_name == "content"

    def test_error_processor_slot(self):
        assert flatmachines_cli.ErrorProcessor.slot_name == "error"


class TestDiscoveryAPI:
    def test_machine_index_instantiation(self):
        idx = flatmachines_cli.MachineIndex()
        assert idx is not None

    def test_machine_info_fields(self):
        """MachineInfo should have name, path, state_count, description."""
        from flatmachines_cli.discovery import MachineInfo
        info = MachineInfo(
            name="test",
            path="/tmp/test.yml",
            state_count=3,
            description="A test machine",
        )
        assert info.name == "test"
        assert info.path == "/tmp/test.yml"
        assert info.state_count == 3
        assert info.description == "A test machine"


class TestInspectorAPI:
    def test_inspect_machine_is_callable(self):
        assert callable(flatmachines_cli.inspect_machine)

    def test_validate_machine_is_callable(self):
        assert callable(flatmachines_cli.validate_machine)

    def test_show_context_is_callable(self):
        assert callable(flatmachines_cli.show_context)
