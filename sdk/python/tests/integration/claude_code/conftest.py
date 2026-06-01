"""Conftest for Claude Code live integration tests.

Registers the --live flag and provides the `live` marker.
"""

import shutil
from pathlib import Path

import pytest


_CLAUDE_CODE_TEST_DIR = Path(__file__).parent


def pytest_addoption(parser):
    try:
        parser.addoption(
            "--live",
            action="store_true",
            default=False,
            help="Run live integration tests (hits real Claude API, costs money)",
        )
    except ValueError as exc:
        if "--live" not in str(exc):
            raise


def _is_claude_code_test(item) -> bool:
    return _CLAUDE_CODE_TEST_DIR in Path(str(item.fspath)).parents


def pytest_collection_modifyitems(config, items):
    claude_code_items = [item for item in items if _is_claude_code_test(item)]
    if config.getoption("--live"):
        # --live given: only skip if claude binary missing
        if not shutil.which("claude"):
            skip = pytest.mark.skip(reason="claude binary not found on PATH")
            for item in claude_code_items:
                item.add_marker(skip)
    else:
        # No --live: skip Claude Code live tests only.
        skip = pytest.mark.skip(reason="live integration tests require --live flag")
        for item in claude_code_items:
            item.add_marker(skip)
