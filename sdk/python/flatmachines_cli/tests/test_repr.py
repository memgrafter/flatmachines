"""Tests for __repr__ methods across all classes."""

import pytest
from flatmachines_cli.bus import DataBus, Slot
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.processors import (
    StatusProcessor, TokenProcessor, ToolProcessor,
    ContentProcessor, ErrorProcessor,
)
from flatmachines_cli.frontend import TerminalFrontend
from flatmachines_cli.discovery import MachineInfo, MachineIndex


class TestSlotRepr:
    def test_empty(self):
        s = Slot("test_slot")
        r = repr(s)
        assert "test_slot" in r
        assert "version=0" in r
        assert "has_value=False" in r

    def test_with_value(self):
        s = Slot("filled")
        s.write(42)
        r = repr(s)
        assert "version=1" in r
        assert "has_value=True" in r


class TestDataBusRepr:
    def test_empty(self):
        bus = DataBus()
        r = repr(bus)
        assert "DataBus" in r

    def test_with_data(self):
        bus = DataBus()
        bus.write("status", {"phase": "running"})
        bus.write("tokens", {"count": 100})
        r = repr(bus)
        assert "status" in r
        assert "tokens" in r


class TestCLIBackendRepr:
    def test_stopped(self):
        backend = CLIBackend()
        r = repr(backend)
        assert "stopped" in r
        assert "procs=5" in r
        assert "frontend=None" in r

    def test_with_frontend(self):
        frontend = TerminalFrontend()
        backend = CLIBackend(frontend=frontend)
        r = repr(backend)
        assert "TerminalFrontend" in r


class TestProcessorRepr:
    def test_status(self):
        bus = DataBus()
        p = StatusProcessor(bus)
        r = repr(p)
        assert "StatusProcessor" in r
        assert "status" in r
        assert "stopped" in r

    def test_token(self):
        bus = DataBus()
        p = TokenProcessor(bus)
        assert "TokenProcessor" in repr(p)

    def test_tool(self):
        bus = DataBus()
        p = ToolProcessor(bus)
        assert "ToolProcessor" in repr(p)

    def test_content(self):
        bus = DataBus()
        p = ContentProcessor(bus)
        assert "ContentProcessor" in repr(p)

    def test_error(self):
        bus = DataBus()
        p = ErrorProcessor(bus)
        assert "ErrorProcessor" in repr(p)


class TestFrontendRepr:
    def test_default(self):
        f = TerminalFrontend()
        r = repr(f)
        assert "TerminalFrontend" in r
        assert "10.0" in r
        assert "False" in r

    def test_custom(self):
        f = TerminalFrontend(fps=60.0, auto_approve=True)
        r = repr(f)
        assert "60.0" in r
        assert "True" in r


class TestMachineInfoRepr:
    def test_basic(self):
        info = MachineInfo(name="test", path="/tmp/test.yml", state_count=5)
        r = repr(info)
        assert "test" in r
        assert "5" in r

    def test_empty(self):
        info = MachineInfo(name="empty", path="/tmp/e.yml")
        r = repr(info)
        assert "empty" in r


class TestMachineIndexRepr:
    def test_empty(self, tmp_path):
        idx = MachineIndex(project_root=str(tmp_path))
        r = repr(idx)
        assert "MachineIndex" in r
        assert "count=0" in r


class TestReprUsefulForDebugging:
    """Verify reprs contain enough info for debugging."""

    def test_slot_repr_changes_on_write(self):
        s = Slot("evolving")
        r1 = repr(s)
        s.write("data")
        r2 = repr(s)
        assert r1 != r2  # repr should change

    def test_bus_repr_grows_with_slots(self):
        bus = DataBus()
        r1 = repr(bus)
        bus.write("new_slot", 1)
        r2 = repr(bus)
        assert len(r2) > len(r1)
