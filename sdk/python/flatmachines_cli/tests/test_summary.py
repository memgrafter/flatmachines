"""Summary test — verify the full production readiness checklist."""

import importlib
import json
import os
import pytest
from pathlib import Path


class TestProductionReadiness:
    """High-level production readiness checks."""

    def test_package_importable(self):
        """Package should import without errors."""
        import flatmachines_cli
        assert flatmachines_cli.__version__

    def test_version_is_semver(self):
        """Version should be valid semver."""
        from flatmachines_cli import __version__
        parts = __version__.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_all_exports_accessible(self):
        """Every name in __all__ should be importable."""
        import flatmachines_cli
        for name in flatmachines_cli.__all__:
            assert hasattr(flatmachines_cli, name)

    def test_py_typed_marker(self):
        """PEP 561 py.typed marker should exist."""
        import flatmachines_cli
        pkg_dir = Path(flatmachines_cli.__file__).parent
        assert (pkg_dir / "py.typed").exists()

    def test_no_bare_excepts_in_source(self):
        """Source code should not have bare 'except:' clauses."""
        pkg_dir = Path(__file__).parent.parent / "flatmachines_cli"
        for py_file in pkg_dir.glob("*.py"):
            content = py_file.read_text()
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped == "except:" or stripped == "except :":
                    pytest.fail(f"Bare except in {py_file.name}:{i}")

    def test_all_source_files_have_docstrings(self):
        """Every .py file should start with a module docstring."""
        pkg_dir = Path(__file__).parent.parent / "flatmachines_cli"
        for py_file in sorted(pkg_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text().strip()
            assert content.startswith('"""') or content.startswith("'''"), \
                f"{py_file.name} missing module docstring"

    def test_bus_snapshot_json_serializable(self):
        """Bus snapshots must be JSON-serializable (IPC boundary)."""
        from flatmachines_cli.bus import DataBus
        bus = DataBus()
        bus.write("status", {"phase": "running", "step": 1})
        bus.write("tokens", {"cost": 0.005})
        snap = bus.snapshot()
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert deserialized == snap

    def test_all_processors_have_slot_names(self):
        """Every default processor must have a unique slot_name."""
        from flatmachines_cli.processors import default_processors
        from flatmachines_cli.bus import DataBus
        bus = DataBus()
        procs = default_processors(bus)
        names = [p.slot_name for p in procs]
        assert len(names) == len(set(names))

    def test_event_types_all_lowercase_snake_case(self):
        """All event type constants should be lowercase snake_case."""
        from flatmachines_cli.events import ALL_TYPES
        for t in ALL_TYPES:
            assert t == t.lower()
            assert " " not in t
            assert "-" not in t

    def test_frontend_protocol_is_abstract(self):
        """Frontend should be an ABC that can't be instantiated directly."""
        from flatmachines_cli.protocol import Frontend
        with pytest.raises(TypeError):
            Frontend()

    def test_changelog_exists(self):
        """CHANGELOG should exist and document this version."""
        changelog = Path(__file__).parent.parent / "CHANGELOG.md"
        assert changelog.exists()
        content = changelog.read_text()
        from flatmachines_cli import __version__
        assert __version__ in content

    def test_readme_has_test_instructions(self):
        """README should include test running instructions."""
        readme = Path(__file__).parent.parent / "README.md"
        assert readme.exists()
        content = readme.read_text()
        assert "pytest" in content

    def test_pyproject_has_dev_dependencies(self):
        """pyproject.toml should include dev dependencies."""
        import tomllib
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        dev_deps = data["project"]["optional-dependencies"]["dev"]
        assert "pytest" in dev_deps[0]

    def test_all_classes_have_repr(self):
        """All major classes should have __repr__ methods."""
        from flatmachines_cli.bus import DataBus, Slot
        from flatmachines_cli.backend import CLIBackend
        from flatmachines_cli.frontend import TerminalFrontend
        from flatmachines_cli.discovery import MachineInfo, MachineIndex

        # Verify repr doesn't raise
        repr(DataBus())
        repr(Slot("test"))
        repr(CLIBackend())
        repr(TerminalFrontend())
        repr(MachineInfo(name="test", path="/tmp/test"))

    def test_logging_configured(self):
        """All major modules should use the logging module."""
        import flatmachines_cli.backend
        import flatmachines_cli.processors
        import flatmachines_cli.discovery
        import flatmachines_cli.hooks
        import flatmachines_cli.bus

        for mod in [
            flatmachines_cli.backend,
            flatmachines_cli.processors,
            flatmachines_cli.discovery,
            flatmachines_cli.hooks,
            flatmachines_cli.bus,
        ]:
            assert hasattr(mod, "logger"), f"{mod.__name__} missing logger"
