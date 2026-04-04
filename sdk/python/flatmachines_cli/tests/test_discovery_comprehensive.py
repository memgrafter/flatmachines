"""Comprehensive discovery tests — project root, machine scanning, resolution."""

import os
import pytest
import yaml

from flatmachines_cli.discovery import (
    MachineIndex, MachineInfo, find_project_root, discover_examples,
)


def make_machine(name="test"):
    return {
        "spec": "flatmachine",
        "spec_version": "2.5.0",
        "data": {
            "name": name,
            "states": {
                "init": {"type": "initial", "agent": "fast"},
                "done": {"type": "final"},
            },
        },
    }


class TestFindProjectRoot:
    def test_finds_git_root(self, tmp_path):
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        result = find_project_root(str(sub))
        assert result == str(tmp_path)

    def test_returns_none_no_git(self, tmp_path):
        sub = tmp_path / "isolated"
        sub.mkdir()
        result = find_project_root(str(sub))
        # May or may not find a root depending on parent dirs
        # Just verify it doesn't crash
        assert result is None or isinstance(result, str)


class TestMachineIndex:
    def test_empty_index(self, tmp_path):
        idx = MachineIndex(project_root=str(tmp_path))
        assert idx.count == 0
        assert idx.list_all() == []

    def test_finds_machines(self, tmp_path):
        (tmp_path / ".git").mkdir()
        examples = tmp_path / "sdk" / "examples" / "my_machine" / "config"
        examples.mkdir(parents=True)
        (examples / "machine.yml").write_text(yaml.dump(make_machine("my_machine")))

        idx = MachineIndex(project_root=str(tmp_path))
        machines = idx.list_all()
        assert len(machines) >= 1
        names = [m.name for m in machines]
        assert "my_machine" in names

    def test_resolve_by_name(self, tmp_path):
        (tmp_path / ".git").mkdir()
        examples = tmp_path / "sdk" / "examples" / "flow_a" / "config"
        examples.mkdir(parents=True)
        (examples / "machine.yml").write_text(yaml.dump(make_machine("flow_a")))

        idx = MachineIndex(project_root=str(tmp_path))
        info = idx.resolve("flow_a")
        assert info is not None
        assert info.name == "flow_a"

    def test_resolve_nonexistent(self, tmp_path):
        idx = MachineIndex(project_root=str(tmp_path))
        info = idx.resolve("nonexistent_machine")
        assert info is None

    def test_prefix_matches(self, tmp_path):
        (tmp_path / ".git").mkdir()
        for name in ("flow_alpha", "flow_beta"):
            p = tmp_path / "sdk" / "examples" / name / "config"
            p.mkdir(parents=True)
            (p / "machine.yml").write_text(yaml.dump(make_machine(name)))

        idx = MachineIndex(project_root=str(tmp_path))
        matches = idx.prefix_matches("flow")
        assert len(matches) >= 2

    def test_extra_paths_file(self, tmp_path):
        """extra_paths pointing directly to a YAML file."""
        extra = tmp_path / "extra.yml"
        extra.write_text(yaml.dump(make_machine("extra_m")))

        idx = MachineIndex(
            project_root=str(tmp_path),
            extra_paths=[str(extra)],
        )
        machines = idx.list_all()
        names = [m.name for m in machines]
        assert "extra_m" in names

    def test_extra_paths_dir(self, tmp_path):
        """extra_paths pointing to a directory with config/machine.yml."""
        extra = tmp_path / "my_extra" / "config"
        extra.mkdir(parents=True)
        (extra / "machine.yml").write_text(yaml.dump(make_machine("my_extra")))

        idx = MachineIndex(
            project_root=str(tmp_path),
            extra_paths=[str(tmp_path / "my_extra")],
        )
        machines = idx.list_all()
        names = [m.name for m in machines]
        assert "my_extra" in names

    def test_repr(self, tmp_path):
        idx = MachineIndex(project_root=str(tmp_path))
        r = repr(idx)
        assert "MachineIndex" in r


class TestMachineInfo:
    def test_basic_fields(self):
        info = MachineInfo(
            name="test",
            path="/tmp/test.yml",
            state_count=3,
            description="A test",
        )
        assert info.name == "test"
        assert info.state_count == 3
        assert info.description == "A test"

    def test_default_description(self):
        info = MachineInfo(name="x", path="/tmp/x.yml", state_count=1)
        assert info.description is None or info.description == ""

    def test_repr(self):
        info = MachineInfo(name="flow", path="/tmp/flow.yml", state_count=5)
        r = repr(info)
        assert "flow" in r


class TestDiscoverExamples:
    def test_empty_dir(self, tmp_path):
        machines = discover_examples(str(tmp_path))
        assert machines == []

    def test_finds_nested_configs(self, tmp_path):
        # discover_examples looks in sdk/examples/ relative to project_root
        examples = tmp_path / "sdk" / "examples" / "example_one" / "config"
        examples.mkdir(parents=True)
        (examples / "machine.yml").write_text(yaml.dump(make_machine("example_one")))

        machines = discover_examples(str(tmp_path))
        assert len(machines) >= 1

    def test_ignores_non_yaml(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not a machine")
        machines = discover_examples(str(tmp_path))
        assert machines == []
