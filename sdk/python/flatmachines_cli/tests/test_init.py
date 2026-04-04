"""Tests for package init — public API surface."""

import pytest


class TestPublicAPI:
    def test_version(self):
        from flatmachines_cli import __version__
        assert isinstance(__version__, str)
        assert __version__ == "2.5.0"

    def test_bus_exports(self):
        from flatmachines_cli import DataBus, Slot, SlotValue
        assert DataBus is not None
        assert Slot is not None
        assert SlotValue is not None

    def test_event_exports(self):
        from flatmachines_cli import (
            MACHINE_START, MACHINE_END, STATE_ENTER, STATE_EXIT,
            TRANSITION, TOOL_CALLS, TOOL_RESULT, ACTION, ERROR,
        )
        assert all(isinstance(e, str) for e in [
            MACHINE_START, MACHINE_END, STATE_ENTER, STATE_EXIT,
            TRANSITION, TOOL_CALLS, TOOL_RESULT, ACTION, ERROR,
        ])

    def test_processor_exports(self):
        from flatmachines_cli import (
            Processor, StatusProcessor, TokenProcessor,
            ToolProcessor, ContentProcessor, ErrorProcessor,
            default_processors,
        )
        assert callable(default_processors)

    def test_backend_exports(self):
        from flatmachines_cli import CLIBackend, CLIHooks
        assert CLIBackend is not None
        assert CLIHooks is not None

    def test_frontend_exports(self):
        from flatmachines_cli import Frontend, ActionHandler, TerminalFrontend
        assert Frontend is not None
        assert ActionHandler is not None
        assert TerminalFrontend is not None

    def test_discovery_exports(self):
        from flatmachines_cli import MachineIndex, MachineInfo, discover_examples
        assert MachineIndex is not None
        assert MachineInfo is not None
        assert callable(discover_examples)

    def test_inspector_exports(self):
        from flatmachines_cli import inspect_machine, validate_machine, show_context
        assert callable(inspect_machine)
        assert callable(validate_machine)
        assert callable(show_context)

    def test_repl_exports(self):
        from flatmachines_cli import FlatMachinesREPL, interactive_repl
        assert FlatMachinesREPL is not None
        assert callable(interactive_repl)

    def test_all_list_complete(self):
        import flatmachines_cli
        all_names = flatmachines_cli.__all__
        for name in all_names:
            assert hasattr(flatmachines_cli, name), f"__all__ lists '{name}' but it's not exported"

    def test_no_extra_public_names(self):
        import flatmachines_cli
        public = {n for n in dir(flatmachines_cli) if not n.startswith("_")}
        modules = {"bus", "events", "processors", "hooks", "backend",
                    "protocol", "frontend", "discovery", "inspector", "repl"}
        public -= modules
        all_set = set(flatmachines_cli.__all__)
        missing = public - all_set
        assert missing == set(), f"Public names not in __all__: {missing}"
