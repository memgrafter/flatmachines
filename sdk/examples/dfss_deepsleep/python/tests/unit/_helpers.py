from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

from flatmachines import HooksRegistry


def example_dir() -> Path:
    """Root of the dfss_deepsleep example."""
    return Path(__file__).resolve().parents[3]


def config_dir() -> Path:
    return example_dir() / "config"


def python_dir() -> Path:
    return example_dir() / "python"


def load_config(filename: str) -> dict:
    """Load a YAML config from the config/ directory."""
    path = config_dir() / filename
    if not path.exists():
        raise AssertionError(f"Expected config file missing: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def load_module(filename: str, module_name: str):
    """Load a Python module from the package source directory."""
    path = python_dir() / "src" / "flatagent_dfss_deepsleep" / filename
    if not path.exists():
        raise AssertionError(f"Expected file missing: {path}")

    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load module spec: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def make_hooks_registry(hooks_instance) -> HooksRegistry:
    """Create a HooksRegistry with the 'deepsleep' name registered.

    This mirrors what the runner (scheduler_main.py) does — the YAML configs
    reference hooks: "deepsleep" and each language SDK resolves that name
    via its own registry.
    """
    registry = HooksRegistry()
    registry.register("deepsleep", lambda: hooks_instance)
    return registry
