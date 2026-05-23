"""
Unit tests for helloworld machine conditional logic.

Tests:
- Conditional transitions based on output correctness
- Character appending only when output matches expected
- Loop termination when target is reached
"""

import pytest
from flatmachines import FlatMachine


def get_helloworld_config():
    """Return the helloworld machine config for testing."""
    return {
        "spec": "flatmachine",
        "spec_version": "0.8.0",
        "data": {
            "name": "hello-world-loop",
            "context": {
                "target": "{{ input.target }}",
                "current": ""
            },
            "agents": {
                "builder": {
                    "spec": "flatagent",
                    "spec_version": "0.8.0",
                    "data": {
                        "model": {"provider": "test", "name": "test"},
                        "system": "test",
                        "user": "{{ input.current }}",
                    },
                }
            },
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [
                        {"condition": "context.current == context.target", "to": "done"},
                        {"to": "build_char"}
                    ]
                },
                "build_char": {
                    "agent": "builder",
                    "input": {
                        "current": "{{ context.current }}",
                        "target": "{{ context.target }}"
                    },
                    "output_to_context": {
                        "expected_char": "{{ context.target[context.current|length] }}",
                        "last_output": "{{ output.next_char }}"
                    },
                    "transitions": [
                        {"condition": "context.last_output == context.expected_char", "to": "append_char"},
                        {"to": "build_char"}
                    ]
                },
                "append_char": {
                    "output_to_context": {
                        "current": "{{ context.current }}{{ context.last_output }}"
                    },
                    "transitions": [
                        {"condition": "context.current == context.target", "to": "done"},
                        {"to": "build_char"}
                    ]
                },
                "done": {
                    "type": "final",
                    "output": {
                        "result": "{{ context.current }}",
                        "success": True
                    }
                }
            }
        }
    }


class TestHelloworldConditions:
    """Test conditional logic in helloworld machine."""

    def test_expected_char_computed_correctly(self):
        """Test that expected_char is computed from target at current position."""
        machine = FlatMachine(config_dict=get_helloworld_config())

        # Simulate context where current="HE" and target="HELLO"
        result = machine._render_template(
            "{{ context.target[context.current|length] }}",
            {"context": {"target": "HELLO", "current": "HE"}}
        )
        assert result == "L"

    def test_expected_char_at_start(self):
        """Test expected_char when current is empty."""
        machine = FlatMachine(config_dict=get_helloworld_config())

        result = machine._render_template(
            "{{ context.target[context.current|length] }}",
            {"context": {"target": "HELLO", "current": ""}}
        )
        assert result == "H"

    def test_append_char_concatenation(self):
        """Test that append_char correctly concatenates."""
        machine = FlatMachine(config_dict=get_helloworld_config())

        result = machine._render_template(
            "{{ context.current }}{{ context.last_output }}",
            {"context": {"current": "HEL", "last_output": "L"}}
        )
        assert result == "HELL"

    def test_condition_correct_output(self):
        """Test condition evaluates true when output matches expected."""
        machine = FlatMachine(config_dict=get_helloworld_config())

        result = machine._evaluate_condition(
            "context.last_output == context.expected_char",
            {"last_output": "L", "expected_char": "L"}
        )
        assert result is True

    def test_condition_wrong_output(self):
        """Test condition evaluates false when output doesn't match."""
        machine = FlatMachine(config_dict=get_helloworld_config())

        result = machine._evaluate_condition(
            "context.last_output == context.expected_char",
            {"last_output": "X", "expected_char": "L"}
        )
        assert result is False

    def test_condition_target_reached(self):
        """Test condition for target completion."""
        machine = FlatMachine(config_dict=get_helloworld_config())

        result = machine._evaluate_condition(
            "context.current == context.target",
            {"current": "HELLO", "target": "HELLO"}
        )
        assert result is True

    def test_condition_target_not_reached(self):
        """Test condition when target not yet complete."""
        machine = FlatMachine(config_dict=get_helloworld_config())

        result = machine._evaluate_condition(
            "context.current == context.target",
            {"current": "HELL", "target": "HELLO"}
        )
        assert result is False


class TestHelloworldAppendAction:
    """Test append_char action hook behavior."""

    def test_append_char_action(self):
        """Test that append_char action concatenates correctly."""
        from flatmachines import LoggingHooks

        class TestHooks(LoggingHooks):
            def on_action(self, action_name, context):
                if action_name == "append_char":
                    context["current"] = context["current"] + context["last_output"]
                return context

        hooks = TestHooks()
        context = {"current": "HE", "last_output": "L"}
        result = hooks.on_action("append_char", context)
        assert result["current"] == "HEL"

    def test_append_char_from_empty(self):
        """Test appending first character."""
        from flatmachines import LoggingHooks

        class TestHooks(LoggingHooks):
            def on_action(self, action_name, context):
                if action_name == "append_char":
                    context["current"] = context["current"] + context["last_output"]
                return context

        hooks = TestHooks()
        context = {"current": "", "last_output": "H"}
        result = hooks.on_action("append_char", context)
        assert result["current"] == "H"
