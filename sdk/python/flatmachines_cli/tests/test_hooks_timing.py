"""Tests for hook timing instrumentation."""

import pytest
from unittest.mock import MagicMock

from flatmachines_cli.hooks import CLIHooks
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.bus import DataBus


@pytest.fixture
def hooks():
    bus = DataBus()
    backend = CLIBackend(bus=bus, processors=[])
    return CLIHooks(backend)


class TestTimingStats:
    def test_initial_empty(self, hooks):
        assert hooks.timing_stats == {}

    def test_records_machine_start(self, hooks):
        hooks.on_machine_start({"machine": {}})
        stats = hooks.timing_stats
        assert "on_machine_start" in stats
        assert stats["on_machine_start"]["calls"] == 1
        assert stats["on_machine_start"]["total_ms"] >= 0

    def test_records_state_enter(self, hooks):
        hooks.on_state_enter("s1", {"machine": {}})
        hooks.on_state_enter("s2", {"machine": {}})
        stats = hooks.timing_stats
        assert stats["on_state_enter"]["calls"] == 2

    def test_records_all_hooks(self, hooks):
        hooks.on_machine_start({"machine": {}})
        hooks.on_state_enter("s1", {"machine": {}})
        hooks.on_state_exit("s1", {}, None)
        hooks.on_transition("s1", "s2", {})
        hooks.on_tool_calls("s1", [], {})
        hooks.on_tool_result("s1", {}, {})
        hooks.on_error("s1", ValueError("test"), {})
        hooks.on_action("test_action", {})
        hooks.on_machine_end({}, {})

        stats = hooks.timing_stats
        expected_hooks = {
            "on_machine_start", "on_state_enter", "on_state_exit",
            "on_transition", "on_tool_calls", "on_tool_result",
            "on_error", "on_action", "on_machine_end",
        }
        assert set(stats.keys()) == expected_hooks

    def test_avg_ms_computed(self, hooks):
        for _ in range(10):
            hooks.on_state_enter("s", {"machine": {}})
        stats = hooks.timing_stats["on_state_enter"]
        assert stats["calls"] == 10
        assert stats["avg_ms"] > 0
        assert stats["avg_ms"] <= stats["total_ms"]

    def test_timing_counts_independent(self, hooks):
        hooks.on_machine_start({"machine": {}})
        hooks.on_state_enter("s", {"machine": {}})
        assert hooks._hook_counts["on_machine_start"] == 1
        assert hooks._hook_counts["on_state_enter"] == 1
