"""Advanced discovery tests — ambiguous matches, edge cases, concurrent discovery."""

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


MACHINE_TEMPLATE = """\
spec: flatmachine
spec_version: "2.5.0"
metadata:
  description: "{desc}"
  tags: [{tags}]
data:
  name: {name}
  {agents_section}
  {machines_section}
  states:
    start:
      type: initial
      transitions:
        - to: end
    end:
      type: final
"""

def make_machine_yaml(name, desc="", tags="", has_agents=False, has_machines=False):
    agents = 'agents:\n    a: "./a.yml"' if has_agents else ""
    machines = 'machines:\n    m: "./m.yml"' if has_machines else ""
    return MACHINE_TEMPLATE.format(
        name=name, desc=desc, tags=tags,
        agents_section=agents, machines_section=machines,
    )


class TestMachineInfoProperties:
    def test_short_path_cwd_relative(self):
        cwd = os.getcwd()
        info = MachineInfo(name="test", path=os.path.join(cwd, "config", "machine.yml"))
        assert not info.short_path.startswith("/")
        assert "config" in info.short_path

    def test_short_path_home_relative(self):
        home = str(Path.home())
        info = MachineInfo(name="test", path=os.path.join(home, "projects", "machine.yml"))
        sp = info.short_path
        # Should start with ~/ or be relative
        assert "projects" in sp

    def test_short_path_truly_foreign(self):
        info = MachineInfo(name="test", path="/opt/system/machine.yml")
        sp = info.short_path
        assert sp is not None  # should not crash

    def test_repr_format(self):
        info = MachineInfo(name="my_machine", path="/tmp/m.yml", state_count=5)
        r = repr(info)
        assert "my_machine" in r
        assert "5" in r


class TestMachineIndexResolution:
    def test_ambiguous_prefix(self, tmp_path):
        """Ambiguous prefix should return None."""
        for name in ["analysis_v1", "analysis_v2"]:
            config_dir = tmp_path / "sdk" / "examples" / name / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "machine.yml").write_text(make_machine_yaml(name))

        idx = MachineIndex(project_root=str(tmp_path))
        result = idx.resolve("analysis")
        assert result is None  # ambiguous

    def test_unique_prefix_resolves(self, tmp_path):
        for name in ["alpha", "beta"]:
            config_dir = tmp_path / "sdk" / "examples" / name / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "machine.yml").write_text(make_machine_yaml(name))

        idx = MachineIndex(project_root=str(tmp_path))
        result = idx.resolve("alp")
        assert result is not None
        assert result.name == "alpha"

    def test_resolve_caches_file_lookups(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(make_machine_yaml("dynamic"))

        idx = MachineIndex(project_root=str(tmp_path))
        info1 = idx.resolve(str(f))
        assert info1 is not None

        # Second resolve should use cached entry
        info2 = idx.resolve("dynamic")
        assert info2 is not None
        assert info2.name == "dynamic"

    def test_resolve_directory_machine_yml(self, tmp_path):
        """Resolve directory with machine.yml directly."""
        (tmp_path / "machine.yml").write_text(make_machine_yaml("direct"))
        idx = MachineIndex(project_root=str(tmp_path))
        info = idx.resolve(str(tmp_path))
        assert info is not None
        assert info.name == "direct"


class TestDiscoverExamples:
    def test_empty_examples_dir(self, tmp_path):
        (tmp_path / "sdk" / "examples").mkdir(parents=True)
        results = discover_examples(str(tmp_path))
        assert results == []

    def test_multiple_examples(self, tmp_path):
        for name in ["ex1", "ex2", "ex3"]:
            config_dir = tmp_path / "sdk" / "examples" / name / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "machine.yml").write_text(make_machine_yaml(name))

        results = discover_examples(str(tmp_path))
        assert len(results) == 3
        names = {r.name for r in results}
        assert names == {"ex1", "ex2", "ex3"}

    def test_non_machine_files_ignored(self, tmp_path):
        config_dir = tmp_path / "sdk" / "examples" / "notmachine" / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "machine.yml").write_text("spec: flatagent\ndata: {}")

        results = discover_examples(str(tmp_path))
        assert len(results) == 0

    def test_sorted_output(self, tmp_path):
        for name in ["zebra", "alpha", "middle"]:
            config_dir = tmp_path / "sdk" / "examples" / name / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "machine.yml").write_text(make_machine_yaml(name))

        results = discover_examples(str(tmp_path))
        names = [r.name for r in results]
        assert names == sorted(names)


class TestParseMachineHeaderAdvanced:
    def test_with_agents(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(make_machine_yaml("with_agents", has_agents=True))
        info = _parse_machine_header(str(f))
        assert info is not None
        assert info.has_agents is True

    def test_with_machines(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(make_machine_yaml("with_machines", has_machines=True))
        info = _parse_machine_header(str(f))
        assert info is not None
        assert info.has_machines is True

    def test_with_tags(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(make_machine_yaml("tagged", tags='"tag1", "tag2"'))
        info = _parse_machine_header(str(f))
        assert info is not None
        assert "tag1" in info.tags

    def test_with_description(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(make_machine_yaml("described", desc="A great machine"))
        info = _parse_machine_header(str(f))
        assert info is not None
        assert info.description == "A great machine"

    def test_symlink_target(self, tmp_path):
        """Symlinked machine files should resolve to real path."""
        real = tmp_path / "real" / "machine.yml"
        real.parent.mkdir()
        real.write_text(make_machine_yaml("symlinked"))

        link = tmp_path / "link.yml"
        link.symlink_to(real)

        info = _parse_machine_header(str(link))
        assert info is not None
        assert info.name == "symlinked"
        assert str(real.resolve()) == info.path


class TestFindProjectRoot:
    def test_nested_git(self, tmp_path):
        """Find nearest .git, not parent .git."""
        outer = tmp_path / "outer"
        (outer / ".git").mkdir(parents=True)
        inner = outer / "inner"
        (inner / ".git").mkdir(parents=True)
        sub = inner / "deep" / "dir"
        sub.mkdir(parents=True)

        root = find_project_root(str(sub))
        assert root == str(inner)

    def test_root_at_start(self, tmp_path):
        (tmp_path / ".git").mkdir()
        root = find_project_root(str(tmp_path))
        assert root == str(tmp_path)
