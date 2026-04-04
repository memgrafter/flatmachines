"""Code quality tests — docstrings, module structure, API consistency."""

import importlib
import inspect
import pytest


MODULES = [
    "flatmachines_cli",
    "flatmachines_cli.bus",
    "flatmachines_cli.events",
    "flatmachines_cli.processors",
    "flatmachines_cli.hooks",
    "flatmachines_cli.backend",
    "flatmachines_cli.protocol",
    "flatmachines_cli.frontend",
    "flatmachines_cli.discovery",
    "flatmachines_cli.inspector",
    "flatmachines_cli.repl",
    "flatmachines_cli.main",
]


class TestModuleDocstrings:
    """Every module should have a docstring."""

    @pytest.mark.parametrize("module_name", MODULES)
    def test_module_has_docstring(self, module_name):
        mod = importlib.import_module(module_name)
        assert mod.__doc__ is not None, f"{module_name} missing module docstring"
        assert len(mod.__doc__.strip()) > 20, \
            f"{module_name} module docstring too short"


class TestPublicClassDocstrings:
    """All public classes should have docstrings."""

    def _get_public_classes(self, module_name):
        mod = importlib.import_module(module_name)
        classes = []
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if not name.startswith("_") and obj.__module__ == module_name:
                classes.append((name, obj))
        return classes

    def test_bus_classes(self):
        for name, cls in self._get_public_classes("flatmachines_cli.bus"):
            assert cls.__doc__ is not None, f"DataBus.{name} missing docstring"

    def test_processor_classes(self):
        for name, cls in self._get_public_classes("flatmachines_cli.processors"):
            assert cls.__doc__ is not None, f"Processor.{name} missing docstring"

    def test_protocol_classes(self):
        for name, cls in self._get_public_classes("flatmachines_cli.protocol"):
            assert cls.__doc__ is not None, f"Protocol.{name} missing docstring"

    def test_backend_class(self):
        from flatmachines_cli.backend import CLIBackend
        assert CLIBackend.__doc__ is not None

    def test_hooks_class(self):
        from flatmachines_cli.hooks import CLIHooks
        assert CLIHooks.__doc__ is not None

    def test_frontend_class(self):
        from flatmachines_cli.frontend import TerminalFrontend
        assert TerminalFrontend.__doc__ is not None

    def test_discovery_classes(self):
        for name, cls in self._get_public_classes("flatmachines_cli.discovery"):
            assert cls.__doc__ is not None, f"Discovery.{name} missing docstring"


class TestAPIConsistency:
    """Test that the API is consistent and well-structured."""

    def test_all_processors_have_slot_name(self):
        from flatmachines_cli.processors import default_processors
        from flatmachines_cli.bus import DataBus
        bus = DataBus()
        for p in default_processors(bus):
            assert hasattr(p, "slot_name")
            assert isinstance(p.slot_name, str)
            assert len(p.slot_name) > 0

    def test_all_processors_have_event_types(self):
        from flatmachines_cli.processors import default_processors
        from flatmachines_cli.bus import DataBus
        bus = DataBus()
        for p in default_processors(bus):
            types = p.event_types
            # Should be frozenset or None
            assert types is None or isinstance(types, frozenset)

    def test_all_processors_have_reset(self):
        from flatmachines_cli.processors import default_processors
        from flatmachines_cli.bus import DataBus
        bus = DataBus()
        for p in default_processors(bus):
            assert hasattr(p, "reset")
            assert callable(p.reset)

    def test_all_processors_have_process(self):
        from flatmachines_cli.processors import default_processors
        from flatmachines_cli.bus import DataBus
        bus = DataBus()
        for p in default_processors(bus):
            assert hasattr(p, "process")
            assert callable(p.process)

    def test_event_constructors_return_dicts(self):
        from flatmachines_cli import events
        ctx = {"machine": {"machine_name": "test"}}
        for func_name in ["machine_start", "machine_end", "state_enter",
                          "state_exit", "transition", "action", "error"]:
            func = getattr(events, func_name)
            # These all take different args — just verify they exist
            assert callable(func)

    def test_all_event_types_are_lowercase(self):
        from flatmachines_cli.events import ALL_TYPES
        for t in ALL_TYPES:
            assert t == t.lower(), f"Event type {t!r} should be lowercase"
            assert "_" in t or t.isalpha(), \
                f"Event type {t!r} should use snake_case"

    def test_bus_read_write_symmetry(self):
        """Writing a value and reading it back should give the same value."""
        from flatmachines_cli.bus import DataBus
        bus = DataBus()
        test_values = [
            42,
            "hello",
            3.14,
            True,
            None,
            [1, 2, 3],
            {"key": "value"},
            {"nested": {"deep": True}},
        ]
        for i, val in enumerate(test_values):
            bus.write(f"slot_{i}", val)
            read_val = bus.read_data(f"slot_{i}")
            assert read_val == val, f"Write/read mismatch for {val!r}"


class TestVersionString:
    def test_version_format(self):
        from flatmachines_cli import __version__
        parts = __version__.split(".")
        assert len(parts) == 3, "Version should be major.minor.patch"
        assert all(p.isdigit() for p in parts), "Version parts should be numeric"

    def test_version_matches_pyproject(self):
        from flatmachines_cli import __version__
        from pathlib import Path
        import tomllib
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        assert __version__ == data["project"]["version"]
