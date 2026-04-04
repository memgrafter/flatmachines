"""Tests for Frontend protocol and ActionHandler."""

import pytest
from flatmachines_cli.protocol import Frontend, ActionHandler
from flatmachines_cli.bus import DataBus


class TestActionHandler:
    def test_no_handler_returns_context(self):
        ah = ActionHandler()
        ctx = {"key": "val"}
        result = ah.handle("unknown_action", ctx)
        assert result is ctx

    def test_register_specific_handler(self):
        ah = ActionHandler()
        called = {}
        def handler(action_name, ctx):
            called["name"] = action_name
            ctx["handled"] = True
            return ctx
        ah.register("my_action", handler)
        ctx = {"key": "val"}
        result = ah.handle("my_action", ctx)
        assert result["handled"] is True
        assert called["name"] == "my_action"

    def test_default_handler(self):
        ah = ActionHandler()
        called = {}
        def default(action_name, ctx):
            called["name"] = action_name
            return ctx
        ah.set_default(default)
        ah.handle("any_action", {})
        assert called["name"] == "any_action"

    def test_specific_overrides_default(self):
        ah = ActionHandler()
        def default(action_name, ctx):
            ctx["handler"] = "default"
            return ctx
        def specific(action_name, ctx):
            ctx["handler"] = "specific"
            return ctx
        ah.set_default(default)
        ah.register("special", specific)
        r1 = ah.handle("special", {})
        assert r1["handler"] == "specific"
        r2 = ah.handle("other", {})
        assert r2["handler"] == "default"

    def test_multiple_handlers(self):
        ah = ActionHandler()
        ah.register("a", lambda n, c: {"action": "a"})
        ah.register("b", lambda n, c: {"action": "b"})
        assert ah.handle("a", {})["action"] == "a"
        assert ah.handle("b", {})["action"] == "b"


class TestFrontendABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Frontend()

    def test_can_implement(self):
        class MockFrontend(Frontend):
            async def start(self, bus):
                pass
            async def stop(self):
                pass
            def handle_action(self, action_name, context):
                return context
        f = MockFrontend()
        assert f.handle_action("test", {"k": "v"}) == {"k": "v"}

    def test_on_bus_update_default_noop(self):
        class MockFrontend(Frontend):
            async def start(self, bus):
                pass
            async def stop(self):
                pass
            def handle_action(self, action_name, context):
                return context
        f = MockFrontend()
        f.on_bus_update("slot", "data")  # should not raise
