"""Tests for version consistency and metadata."""

import subprocess
import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python < 3.11

PYTHON = "sdk/python/flatmachines_cli/.venv/bin/python"


def _load_pyproject():
    with open("sdk/python/flatmachines_cli/pyproject.toml", "rb") as f:
        return tomllib.load(f)


class TestVersionConsistency:
    def test_package_version_matches_init(self):
        """__version__ in __init__.py should match pyproject.toml."""
        import flatmachines_cli
        pyproject = _load_pyproject()
        project_version = pyproject["project"]["version"]
        assert flatmachines_cli.__version__ == project_version

    def test_cli_version_output(self):
        result = subprocess.run(
            [PYTHON, "-m", "flatmachines_cli.main", "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "flatmachines" in result.stdout
        # Should contain semver
        import re
        assert re.search(r"\d+\.\d+\.\d+", result.stdout)

    def test_version_is_semver(self):
        import flatmachines_cli
        import re
        assert re.match(r"^\d+\.\d+\.\d+", flatmachines_cli.__version__)


class TestPackageMetadata:
    def test_pyproject_has_required_fields(self):
        pyproject = _load_pyproject()
        project = pyproject["project"]
        assert "name" in project
        assert "version" in project
        assert "description" in project

    def test_package_name(self):
        pyproject = _load_pyproject()
        assert pyproject["project"]["name"] == "flatmachines-cli"

    def test_python_requires(self):
        pyproject = _load_pyproject()
        assert "requires-python" in pyproject["project"]
