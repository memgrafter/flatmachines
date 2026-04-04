"""Advanced ActionHandler tests — registration, routing, edge cases."""

import pytest
from flatmachines_cli.protocol import ActionHandler


class TestActionHandlerOverwrite:
    def test_register_overwrites_existing(self):
        ah = ActionHandler()
        ah.register("test", lambda n, c: {"handler": 1})
        ah.register("test", lambda n, c: {"handler": 2})
        result = ah.handle("test", {})
        assert result["handler"] == 2

    def test_set_default_overwrites(self):
        ah = ActionHandler()
        ah.set_default(lambda n, c: {"d": 1})
        ah.set_default(lambda n, c: {"d": 2})
        result = ah.handle("any", {})
        assert result["d"] == 2


class TestActionHandlerContextMutation:
    def test_handler_can_mutate_context(self):
        ah = ActionHandler()
        def mutator(name, ctx):
            ctx["mutated"] = True
            ctx["count"] = ctx.get("count", 0) + 1
            return ctx
        ah.register("mutate", mutator)

        ctx = {"original": True}
        result = ah.handle("mutate", ctx)
        assert result["mutated"] is True
        assert result["original"] is True
        assert result["count"] == 1

    def test_handler_can_replace_context(self):
        ah = ActionHandler()
        def replacer(name, ctx):
            return {"replaced": True}
        ah.register("replace", replacer)

        result = ah.handle("replace", {"original": True})
        assert result == {"replaced": True}

    def test_handler_receives_action_name(self):
        ah = ActionHandler()
        received = {}
        def tracker(name, ctx):
            received["name"] = name
            return ctx
        ah.set_default(tracker)

        ah.handle("my_special_action", {})
        assert received["name"] == "my_special_action"


class TestActionHandlerChaining:
    def test_no_chaining(self):
        """Only one handler should run per action."""
        ah = ActionHandler()
        call_count = [0]

        def handler(name, ctx):
            call_count[0] += 1
            return ctx

        ah.register("test", handler)
        ah.set_default(handler)

        ah.handle("test", {})
        assert call_count[0] == 1  # specific, not default

    def test_fallback_chain(self):
        """Default runs only when no specific handler matches."""
        ah = ActionHandler()
        specific_called = [False]
        default_called = [False]

        ah.register("specific", lambda n, c: (specific_called.__setitem__(0, True), c)[1])
        ah.set_default(lambda n, c: (default_called.__setitem__(0, True), c)[1])

        ah.handle("specific", {})
        assert specific_called[0] is True
        assert default_called[0] is False

        ah.handle("other", {})
        assert default_called[0] is True


class TestActionHandlerEmpty:
    def test_empty_handler_passthrough(self):
        ah = ActionHandler()
        ctx = {"data": "unchanged"}
        result = ah.handle("any_action", ctx)
        assert result is ctx
        assert result["data"] == "unchanged"

    def test_empty_handler_preserves_complex_context(self):
        ah = ActionHandler()
        ctx = {
            "list": [1, 2, 3],
            "nested": {"a": {"b": True}},
            "none": None,
        }
        result = ah.handle("x", ctx)
        assert result["list"] == [1, 2, 3]
        assert result["nested"]["a"]["b"] is True
        assert result["none"] is None
