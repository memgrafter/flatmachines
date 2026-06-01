"""Conftest for Codex integration tests.

Adds a --live flag and gates tests marked with @pytest.mark.live.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser):
    try:
        parser.addoption(
            "--live",
            action="store_true",
            default=False,
            help="Run live Codex OAuth integration tests (hits real API, costs money)",
        )
    except ValueError as exc:
        if "--live" not in str(exc):
            raise


def pytest_configure(config):
    config.addinivalue_line("markers", "live: marks tests that hit real Codex API")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return

    skip_live = pytest.mark.skip(reason="live integration tests require --live flag")
    for item in items:
        if item.get_closest_marker("live") is not None:
            item.add_marker(skip_live)
