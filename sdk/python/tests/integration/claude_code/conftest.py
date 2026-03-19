"""Conftest for Claude Code live integration tests.

Registers the --live flag and provides the `live` marker.
"""

import shutil
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live integration tests (hits real Claude API, costs money)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        # --live given: only skip if claude binary missing
        if not shutil.which("claude"):
            skip = pytest.mark.skip(reason="claude binary not found on PATH")
            for item in items:
                item.add_marker(skip)
    else:
        # No --live: skip everything
        skip = pytest.mark.skip(reason="live integration tests require --live flag")
        for item in items:
            item.add_marker(skip)
