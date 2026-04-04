"""Tests for CLIBackend."""

import asyncio
import pytest
from flatmachines_cli.backend import CLIBackend
from flatmachines_cli.bus import DataBus
from flatmachines_cli.processors import StatusProcessor, default_processors
from flatmachines_cli.protocol import Frontend
from flatmachines_cli import events


class MockFrontend(Frontend):
    def __init__(self):
        self.started = False
        self.stopped = False
        self.actions_handled = []

    async def start(self, bus):
        self.started = True
        while not self.stopped:
            await asyncio.sleep(0.01)

    async def stop(self):
        self.stopped = True

    def handle_action(self, action_name, context):
        self.actions_handled.append(action_name)
        context["auto_approved"] = True
        return context


class TestCLIBackendInit:
    def test_default_init(self):
        backend = CLIBackend()
        assert backend.bus is not None
        assert len(backend.processors) == 5
        assert backend.action_handler is not None

    def test_custom_bus(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        assert backend.bus is bus

    def test_custom_processors(self):
        bus = DataBus()
        procs = [StatusProcessor(bus)]
        backend = CLIBackend(bus=bus, processors=procs)
        assert len(backend.processors) == 1

    def test_set_frontend(self):
        backend = CLIBackend()
        frontend = MockFrontend()
        backend.set_frontend(frontend)
        ctx = backend.handle_action("test", {"key": "val"})
        assert ctx["auto_approved"] is True
        assert "test" in frontend.actions_handled


class TestCLIBackendLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        bus = DataBus()
        frontend = MockFrontend()
        backend = CLIBackend(bus=bus, frontend=frontend)
        backend.set_frontend(frontend)
        await backend.start()
        await asyncio.sleep(0.05)
        assert frontend.started is True
        await backend.stop()
        assert frontend.stopped is True

    @pytest.mark.asyncio
    async def test_double_start_idempotent(self):
        backend = CLIBackend()
        await backend.start()
        await backend.start()
        await backend.stop()

    @pytest.mark.asyncio
    async def test_double_stop_idempotent(self):
        backend = CLIBackend()
        await backend.start()
        await backend.stop()
        await backend.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        backend = CLIBackend()
        await backend.stop()

    @pytest.mark.asyncio
    async def test_start_resets_bus(self):
        bus = DataBus()
        bus.write("old_data", 42)
        backend = CLIBackend(bus=bus)
        await backend.start()
        assert bus.read_data("old_data") is None
        await backend.stop()


class TestCLIBackendEventDispatch:
    @pytest.mark.asyncio
    async def test_emit_dispatches_to_processors(self):
        bus = DataBus()
        # Use high-Hz processors to avoid throttle delays in tests
        from flatmachines_cli.processors import StatusProcessor
        procs = [StatusProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        await backend.start()
        evt = events.machine_start({"machine": {"machine_name": "test"}})
        backend.emit(evt)
        await asyncio.sleep(0.1)
        data = bus.read_data("status")
        assert data is not None
        assert data["machine_name"] == "test"
        await backend.stop()

    @pytest.mark.asyncio
    async def test_emit_only_to_matching_processors(self):
        bus = DataBus()
        from flatmachines_cli.processors import ToolProcessor
        procs = [ToolProcessor(bus, max_hz=1000)]
        backend = CLIBackend(bus=bus, processors=procs)
        await backend.start()
        evt = events.tool_calls("s", [{"name": "bash"}], {
            "_tool_loop_content": "thinking",
            "_tool_loop_usage": {},
        })
        backend.emit(evt)
        await asyncio.sleep(0.1)
        tool_data = bus.read_data("tools")
        assert tool_data is not None
        await backend.stop()


class TestCLIBackendActionRouting:
    def test_handle_action_no_frontend(self):
        backend = CLIBackend()
        ctx = {"key": "val"}
        result = backend.handle_action("test", ctx)
        assert result is ctx

    def test_handle_action_with_frontend(self):
        backend = CLIBackend()
        frontend = MockFrontend()
        backend.set_frontend(frontend)
        ctx = backend.handle_action("review", {"k": "v"})
        assert ctx["auto_approved"] is True

    def test_register_custom_action(self):
        backend = CLIBackend()
        def custom_handler(action_name, ctx):
            ctx["custom"] = True
            return ctx
        backend.register_action("custom", custom_handler)
        ctx = backend.handle_action("custom", {})
        assert ctx["custom"] is True

    def test_custom_action_overrides_frontend(self):
        backend = CLIBackend()
        frontend = MockFrontend()
        backend.set_frontend(frontend)
        def custom(action_name, ctx):
            ctx["custom"] = True
            return ctx
        backend.register_action("special", custom)
        ctx = backend.handle_action("special", {})
        assert ctx["custom"] is True
        assert "special" not in frontend.actions_handled


class TestCLIBackendAddProcessor:
    def test_add_processor(self):
        bus = DataBus()
        backend = CLIBackend(bus=bus)
        initial_count = len(backend.processors)
        backend.add_processor(StatusProcessor(bus))
        assert len(backend.processors) == initial_count + 1
