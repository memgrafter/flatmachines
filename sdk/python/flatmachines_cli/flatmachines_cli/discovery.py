"""
Machine config discovery — find and index flatmachine configs.

Scans known directories for machine.yml files, parses lightweight
metadata without full FlatMachine initialization.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class MachineInfo:
    """Lightweight metadata about a discovered machine config."""
    name: str
    path: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    spec_version: str = ""
    has_agents: bool = False
    has_machines: bool = False
    state_count: int = 0

    @property
    def short_path(self) -> str:
        """Path relative to cwd or home for display."""
        try:
            return str(Path(self.path).relative_to(Path.cwd()))
        except ValueError:
            try:
                return "~/" + str(Path(self.path).relative_to(Path.home()))
            except ValueError:
                return self.path


def _parse_machine_header(path: str) -> Optional[MachineInfo]:
    """Parse just the metadata from a machine config file.

    Fast — only reads YAML, no FlatMachine init, no agent resolution.
    Returns None if the file isn't a valid flatmachine config.
    """
    try:
        with open(path) as f:
            config = yaml.safe_load(f)

        if not isinstance(config, dict):
            return None
        if config.get("spec") != "flatmachine":
            return None

        data = config.get("data", {})
        metadata = config.get("metadata", {})
        states = data.get("states", {})

        return MachineInfo(
            name=data.get("name", Path(path).parent.name),
            path=str(Path(path).resolve()),
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            spec_version=config.get("spec_version", ""),
            has_agents=bool(data.get("agents")),
            has_machines=bool(data.get("machines")),
            state_count=len(states),
        )
    except (OSError, yaml.YAMLError) as e:
        logger.debug("Failed to parse machine header %s: %s", path, e)
        return None
    except Exception as e:
        logger.warning("Unexpected error parsing machine header %s: %s", path, e)
        return None


def discover_examples(project_root: str) -> List[MachineInfo]:
    """Find all machine configs in sdk/examples/."""
    examples_dir = Path(project_root) / "sdk" / "examples"
    results = []

    if not examples_dir.is_dir():
        return results

    for config_dir in sorted(examples_dir.iterdir()):
        machine_yml = config_dir / "config" / "machine.yml"
        if machine_yml.is_file():
            info = _parse_machine_header(str(machine_yml))
            if info:
                results.append(info)

    return results


def discover_paths(paths: List[str]) -> List[MachineInfo]:
    """Parse machine info from explicit file paths."""
    results = []
    for p in paths:
        resolved = Path(p).resolve()
        if resolved.is_file():
            info = _parse_machine_header(str(resolved))
            if info:
                results.append(info)
        elif resolved.is_dir():
            # Try config/machine.yml convention
            candidate = resolved / "config" / "machine.yml"
            if candidate.is_file():
                info = _parse_machine_header(str(candidate))
                if info:
                    results.append(info)
            # Also try machine.yml directly in dir
            candidate = resolved / "machine.yml"
            if candidate.is_file():
                info = _parse_machine_header(str(candidate))
                if info:
                    results.append(info)
    return results


def find_project_root(start: str = ".") -> Optional[str]:
    """Walk up from start to find .git root."""
    d = Path(start).resolve()
    while d != d.parent:
        if (d / ".git").exists():
            return str(d)
        d = d.parent
    return None


class MachineIndex:
    """Index of discovered machines with name-based lookup."""

    def __init__(self, project_root: Optional[str] = None, extra_paths: Optional[List[str]] = None):
        self._machines: Dict[str, MachineInfo] = {}
        self._project_root = project_root or find_project_root()

        if self._project_root:
            for info in discover_examples(self._project_root):
                self._machines[info.name] = info

        if extra_paths:
            for info in discover_paths(extra_paths):
                self._machines[info.name] = info

    @property
    def count(self) -> int:
        return len(self._machines)

    def list_all(self) -> List[MachineInfo]:
        """All discovered machines, sorted by name."""
        return sorted(self._machines.values(), key=lambda m: m.name)

    def resolve(self, name_or_path: str) -> Optional[MachineInfo]:
        """Resolve a name or path to a MachineInfo.

        Tries in order:
        1. Exact name match from index
        2. Prefix match (unique)
        3. File path
        """
        # Exact name
        if name_or_path in self._machines:
            return self._machines[name_or_path]

        # Prefix match
        matches = [m for n, m in self._machines.items() if n.startswith(name_or_path)]
        if len(matches) == 1:
            return matches[0]

        # Path
        p = Path(name_or_path)
        if p.is_file():
            info = _parse_machine_header(str(p.resolve()))
            if info:
                self._machines[info.name] = info
                return info

        # Directory with config/machine.yml
        if p.is_dir():
            for candidate in [p / "config" / "machine.yml", p / "machine.yml"]:
                if candidate.is_file():
                    info = _parse_machine_header(str(candidate.resolve()))
                    if info:
                        self._machines[info.name] = info
                        return info

        return None

    def prefix_matches(self, prefix: str) -> List[MachineInfo]:
        """Return all machines whose name starts with prefix."""
        return [m for n, m in self._machines.items() if n.startswith(prefix)]
