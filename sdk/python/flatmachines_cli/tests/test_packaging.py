"""Tests for package integrity — imports, metadata, structure."""

import importlib
import sys
import pytest
from pathlib import Path


class TestPackageStructure:
    """Verify package structure is correct for distribution."""

    def test_package_is_importable(self):
        import flatmachines_cli
        assert hasattr(flatmachines_cli, "__version__")

    def test_all_submodules_importable(self):
        submodules = [
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
        for mod_name in submodules:
            mod = importlib.import_module(mod_name)
            assert mod is not None, f"Failed to import {mod_name}"

    def test_no_circular_imports(self):
        """Verify modules can be imported independently."""
        # Clear cached imports
        to_remove = [k for k in sys.modules if k.startswith("flatmachines_cli")]
        for k in to_remove:
            del sys.modules[k]

        # Import each module independently
        importlib.import_module("flatmachines_cli.bus")
        importlib.import_module("flatmachines_cli.events")

        # Re-import the full package
        importlib.import_module("flatmachines_cli")

    def test_py_typed_exists(self):
        pkg_dir = Path(__file__).parent.parent / "flatmachines_cli"
        assert (pkg_dir / "py.typed").exists()

    def test_init_exists(self):
        pkg_dir = Path(__file__).parent.parent / "flatmachines_cli"
        assert (pkg_dir / "__init__.py").exists()


class TestPackageMetadata:
    def test_version_format(self):
        from flatmachines_cli import __version__
        parts = __version__.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_pyproject_exists(self):
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        assert pyproject.exists()

    def test_pyproject_has_required_fields(self):
        import tomllib
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        assert "project" in data
        proj = data["project"]
        assert "name" in proj
        assert "version" in proj
        assert "description" in proj
        assert "dependencies" in proj
        assert "requires-python" in proj

    def test_pyproject_scripts_entry_point(self):
        import tomllib
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        scripts = data.get("project", {}).get("scripts", {})
        assert "flatmachines" in scripts
        assert "flatmachines_cli.main:main" in scripts["flatmachines"]

    def test_pyproject_classifiers(self):
        import tomllib
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        classifiers = data["project"]["classifiers"]
        assert any("Beta" in c for c in classifiers)
        assert any("Python :: 3" in c for c in classifiers)
        assert any("Apache" in c for c in classifiers)


class TestExportsCompleteness:
    """Verify all exported names are real, importable objects."""

    def test_all_exports_are_accessible(self):
        import flatmachines_cli
        for name in flatmachines_cli.__all__:
            obj = getattr(flatmachines_cli, name)
            assert obj is not None, f"Export {name} is None"

    def test_all_exports_are_documented(self):
        """Every exported name should have either a docstring or be a constant."""
        import flatmachines_cli
        undocumented = []
        for name in flatmachines_cli.__all__:
            if name.startswith("__"):
                continue
            obj = getattr(flatmachines_cli, name)
            # Constants (str, int, etc.) don't need docstrings
            if isinstance(obj, (str, int, float, frozenset)):
                continue
            # Callables and classes should have docstrings
            if callable(obj) and not getattr(obj, "__doc__", None):
                undocumented.append(name)
        assert undocumented == [], \
            f"Undocumented exports: {undocumented}"


class TestDependencyImports:
    """Verify that required dependencies are available."""

    def test_yaml_available(self):
        import yaml
        assert yaml is not None

    def test_flatmachines_available(self):
        import flatmachines
        assert hasattr(flatmachines, "FlatMachine")

    def test_flatagents_available(self):
        import flatagents
        assert flatagents is not None
