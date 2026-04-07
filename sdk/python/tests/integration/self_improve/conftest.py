"""Conftest for self-improve integration tests.

Adds a --live flag and gates tests marked with @pytest.mark.live.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live self-improve integration tests (hits real API, costs money)",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: marks tests that hit real Codex API")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return

    skip_live = pytest.mark.skip(reason="live integration tests require --live flag")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
