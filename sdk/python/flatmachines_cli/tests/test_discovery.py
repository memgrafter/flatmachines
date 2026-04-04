"""Tests for machine discovery and MachineIndex."""

import os
import pytest
from pathlib import Path
from flatmachines_cli.discovery import (
    MachineInfo,
    MachineIndex,
    _parse_machine_header,
    discover_examples,
    discover_paths,
    find_project_root,
)


MINIMAL_MACHINE_YAML = """\
spec: flatmachine
spec_version: "2.5.0"
metadata:
  description: "Test machine"
  tags: ["test"]
data:
  name: test_machine
  agents:
    analyzer: "./analyzer.yml"
  states:
    start:
      type: initial
      agent: analyzer
      transitions:
        - to: end
    end:
      type: final
      output:
        result: "{{ context.result }}"
"""

NOT_A_MACHINE_YAML = """\
spec: flatagent
data:
  name: test_agent
"""

INVALID_YAML = """\
{invalid: yaml: content
"""


class TestMachineInfo:
    def test_short_path_relative_to_cwd(self):
        info = MachineInfo(name="test", path=os.path.join(os.getcwd(), "sub", "machine.yml"))
        assert "sub" in info.short_path
        assert not info.short_path.startswith("/")

    def test_short_path_absolute_fallback(self):
        info = MachineInfo(name="test", path="/some/weird/path/machine.yml")
        assert info.short_path is not None

    def test_defaults(self):
        info = MachineInfo(name="test", path="/tmp/test")
        assert info.description == ""
        assert info.tags == []
        assert info.spec_version == ""
        assert info.has_agents is False
        assert info.has_machines is False
        assert info.state_count == 0


class TestParseMachineHeader:
    def test_valid_machine(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        info = _parse_machine_header(str(f))
        assert info is not None
        assert info.name == "test_machine"
        assert info.description == "Test machine"
        assert "test" in info.tags
        assert info.has_agents is True
        assert info.state_count == 2

    def test_not_a_machine(self, tmp_path):
        f = tmp_path / "agent.yml"
        f.write_text(NOT_A_MACHINE_YAML)
        info = _parse_machine_header(str(f))
        assert info is None

    def test_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yml"
        f.write_text(INVALID_YAML)
        info = _parse_machine_header(str(f))
        assert info is None

    def test_nonexistent_file(self):
        info = _parse_machine_header("/nonexistent/path/machine.yml")
        assert info is None

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.yml"
        f.write_text("")
        info = _parse_machine_header(str(f))
        assert info is None

    def test_plain_string_file(self, tmp_path):
        f = tmp_path / "string.yml"
        f.write_text("just a string")
        info = _parse_machine_header(str(f))
        assert info is None

    def test_missing_data(self, tmp_path):
        f = tmp_path / "nodata.yml"
        f.write_text("spec: flatmachine\nspec_version: '2.5.0'\n")
        info = _parse_machine_header(str(f))
        assert info is not None
        assert info.state_count == 0

    def test_name_fallback_to_dirname(self, tmp_path):
        subdir = tmp_path / "my_machine"
        subdir.mkdir()
        f = subdir / "machine.yml"
        f.write_text("spec: flatmachine\ndata: {}\n")
        info = _parse_machine_header(str(f))
        assert info is not None
        assert info.name == "my_machine"


class TestDiscoverPaths:
    def test_discover_file(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        results = discover_paths([str(f)])
        assert len(results) == 1
        assert results[0].name == "test_machine"

    def test_discover_directory_with_convention(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        f = config_dir / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        results = discover_paths([str(tmp_path)])
        assert len(results) == 1

    def test_discover_directory_direct(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        results = discover_paths([str(tmp_path)])
        assert len(results) == 1

    def test_discover_nonexistent(self):
        results = discover_paths(["/nonexistent/path"])
        assert results == []

    def test_discover_non_machine(self, tmp_path):
        f = tmp_path / "not_machine.yml"
        f.write_text(NOT_A_MACHINE_YAML)
        results = discover_paths([str(f)])
        assert results == []


class TestMachineIndex:
    def test_empty_index(self, tmp_path):
        idx = MachineIndex(project_root=str(tmp_path))
        assert idx.count == 0
        assert idx.list_all() == []

    def test_resolve_exact_name(self, tmp_path):
        config_dir = tmp_path / "sdk" / "examples" / "test_ex" / "config"
        config_dir.mkdir(parents=True)
        f = config_dir / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        idx = MachineIndex(project_root=str(tmp_path))
        info = idx.resolve("test_machine")
        assert info is not None
        assert info.name == "test_machine"

    def test_resolve_prefix(self, tmp_path):
        config_dir = tmp_path / "sdk" / "examples" / "test_ex" / "config"
        config_dir.mkdir(parents=True)
        f = config_dir / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        idx = MachineIndex(project_root=str(tmp_path))
        info = idx.resolve("test_m")
        assert info is not None
        assert info.name == "test_machine"

    def test_resolve_file_path(self, tmp_path):
        f = tmp_path / "my_machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        idx = MachineIndex(project_root=str(tmp_path))
        info = idx.resolve(str(f))
        assert info is not None

    def test_resolve_nonexistent(self, tmp_path):
        idx = MachineIndex(project_root=str(tmp_path))
        assert idx.resolve("nonexistent") is None

    def test_prefix_matches(self, tmp_path):
        for name in ["alpha", "alpha_v2", "beta"]:
            config_dir = tmp_path / "sdk" / "examples" / name / "config"
            config_dir.mkdir(parents=True)
            f = config_dir / "machine.yml"
            f.write_text(MINIMAL_MACHINE_YAML.replace("test_machine", name))
        idx = MachineIndex(project_root=str(tmp_path))
        matches = idx.prefix_matches("alpha")
        assert len(matches) == 2

    def test_extra_paths(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        idx = MachineIndex(project_root=str(tmp_path), extra_paths=[str(f)])
        assert idx.count >= 1

    def test_list_all_sorted(self, tmp_path):
        for name in ["charlie", "alpha", "bravo"]:
            config_dir = tmp_path / "sdk" / "examples" / name / "config"
            config_dir.mkdir(parents=True)
            f = config_dir / "machine.yml"
            f.write_text(MINIMAL_MACHINE_YAML.replace("test_machine", name))
        idx = MachineIndex(project_root=str(tmp_path))
        names = [m.name for m in idx.list_all()]
        assert names == sorted(names)

    def test_resolve_directory_with_config_convention(self, tmp_path):
        config_dir = tmp_path / "my_project" / "config"
        config_dir.mkdir(parents=True)
        f = config_dir / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        idx = MachineIndex(project_root=str(tmp_path))
        info = idx.resolve(str(tmp_path / "my_project"))
        assert info is not None


class TestFindProjectRoot:
    def test_finds_git_root(self, tmp_path):
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        root = find_project_root(str(sub))
        assert root == str(tmp_path)

    def test_cwd_default(self):
        result = find_project_root()
        # Should not crash
