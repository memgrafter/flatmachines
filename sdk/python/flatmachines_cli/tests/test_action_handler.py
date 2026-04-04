"""Tests for ActionHandler routing."""

import pytest
from flatmachines_cli.protocol import ActionHandler


class TestActionHandlerRouting:
    def test_no_handler_returns_context(self):
        ah = ActionHandler()
        result = ah.handle("unknown", {"x": 1})
        assert result == {"x": 1}

    def test_registered_handler(self):
        ah = ActionHandler()
        ah.register("greet", lambda name, ctx: {**ctx, "greeting": "hi"})
        result = ah.handle("greet", {"name": "world"})
        assert result["greeting"] == "hi"

    def test_default_handler(self):
        ah = ActionHandler()
        ah.set_default(lambda name, ctx: {**ctx, "default": True})
        result = ah.handle("anything", {})
        assert result["default"] is True

    def test_specific_over_default(self):
        ah = ActionHandler()
        ah.set_default(lambda name, ctx: {**ctx, "handler": "default"})
        ah.register("specific", lambda name, ctx: {**ctx, "handler": "specific"})
        assert ah.handle("specific", {})["handler"] == "specific"
        assert ah.handle("other", {})["handler"] == "default"

    def test_overwrite_handler(self):
        ah = ActionHandler()
        ah.register("x", lambda name, ctx: {**ctx, "v": 1})
        ah.register("x", lambda name, ctx: {**ctx, "v": 2})
        assert ah.handle("x", {})["v"] == 2

    def test_multiple_actions(self):
        ah = ActionHandler()
        ah.register("a", lambda name, ctx: {**ctx, "action": "a"})
        ah.register("b", lambda name, ctx: {**ctx, "action": "b"})
        assert ah.handle("a", {})["action"] == "a"
        assert ah.handle("b", {})["action"] == "b"

    def test_handler_receives_action_name(self):
        ah = ActionHandler()
        received = []
        ah.register("test", lambda name, ctx: (received.append(name), ctx)[1])
        ah.handle("test", {})
        assert received == ["test"]

    def test_handler_receives_context(self):
        ah = ActionHandler()
        received = []
        ah.register("test", lambda name, ctx: (received.append(ctx), ctx)[1])
        ah.handle("test", {"key": "val"})
        assert received == [{"key": "val"}]

    def test_empty_context(self):
        ah = ActionHandler()
        result = ah.handle("any", {})
        assert result == {}

    def test_none_context(self):
        ah = ActionHandler()
        ah.register("test", lambda name, ctx: ctx)
        result = ah.handle("test", None)
        assert result is None

    def test_default_replaces(self):
        ah = ActionHandler()
        ah.set_default(lambda name, ctx: {**ctx, "v": 1})
        ah.set_default(lambda name, ctx: {**ctx, "v": 2})
        assert ah.handle("x", {})["v"] == 2

    def test_action_name_case_sensitive(self):
        ah = ActionHandler()
        ah.register("Test", lambda name, ctx: {**ctx, "upper": True})
        assert ah.handle("Test", {})["upper"] is True
        assert ah.handle("test", {}) == {}  # Not found
