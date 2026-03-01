"""
Unit tests for type preservation fixes.

Tests:
- P0: Path reference syntax for direct value passing (no Jinja2 coercion)
- P2: Serialization warnings with specific field names
- Markdown stripping for LLM JSON responses
"""

import json
import logging
import pytest
from flatmachines import FlatMachine, CheckpointManager, MemoryBackend
from flatmachines.utils import strip_markdown_json


def get_minimal_config():
    """Return a minimal machine config for testing."""
    return {
        "spec": "flatmachine",
        "spec_version": "0.1.0",
        "data": {
            "name": "test",
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "end"}]
                },
                "end": {
                    "type": "final",
                    "output": {}
                }
            }
        }
    }


class TestPathReferences:
    """P0: Test that path references pass values directly without Jinja2 coercion."""

    def test_path_reference_list(self):
        """Test that output.items returns list directly."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "output.items",
            {"output": {"items": ["a", "b", "c"]}}
        )
        assert result == ["a", "b", "c"]
        assert isinstance(result, list)

    def test_path_reference_dict(self):
        """Test that output.data returns dict directly."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "output.data",
            {"output": {"data": {"key": "value", "num": 42}}}
        )
        assert result == {"key": "value", "num": 42}
        assert isinstance(result, dict)

    def test_path_reference_nested(self):
        """Test nested path like context.user.name."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "context.user.name",
            {"context": {"user": {"name": "Alice"}}}
        )
        assert result == "Alice"

    def test_path_reference_boolean(self):
        """Test that booleans are preserved with path refs."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "output.flag",
            {"output": {"flag": True}}
        )
        assert result is True
        assert isinstance(result, bool)

    def test_path_reference_none(self):
        """Test that None is preserved."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "output.value",
            {"output": {"value": None}}
        )
        assert result is None

    def test_path_reference_with_whitespace(self):
        """Test that whitespace is trimmed."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "  output.items  ",
            {"output": {"items": [1, 2, 3]}}
        )
        assert result == [1, 2, 3]

    def test_context_path_reference(self):
        """Test context.* paths."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "context.chapters",
            {"context": {"chapters": ["ch1", "ch2"]}}
        )
        assert result == ["ch1", "ch2"]

    def test_input_path_reference(self):
        """Test input.* paths."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "input.query",
            {"input": {"query": "test"}}
        )
        assert result == "test"

    def test_missing_path_returns_none(self):
        """Test that missing paths return None."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "output.nonexistent",
            {"output": {"other": "value"}}
        )
        assert result is None


class TestJinja2StillWorks:
    """Ensure Jinja2 templates still work for complex expressions."""

    def test_jinja2_string_interpolation(self):
        """Test string interpolation still works."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "Hello {{ context.name }}!",
            {"context": {"name": "Alice"}}
        )
        assert result == "Hello Alice!"

    def test_jinja2_with_tojson(self):
        """Test that | tojson renders a JSON string (Jinja2 always returns strings)."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "{{ context.chapters | tojson }}",
            {"context": {"chapters": ["a", "b"]}}
        )
        assert result == '["a", "b"]'
        assert isinstance(result, str)
        # Caller can recover the list with json.loads()
        assert json.loads(result) == ["a", "b"]

    def test_jinja2_list_without_tojson(self):
        """Test that lists render as valid JSON strings via _json_finalize.

        The custom finalize hook converts lists/dicts to JSON so the output is
        parseable, but Jinja2 still returns a string — callers must json.loads()
        if they need the native type.  Use bare path refs for type preservation.
        """
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "{{ context.my_list }}",
            {"context": {"my_list": ["a", "b"]}}
        )
        assert isinstance(result, str)
        assert json.loads(result) == ["a", "b"]

    def test_jinja2_dict_without_tojson(self):
        """Test that dicts render as valid JSON strings via _json_finalize."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "{{ context.data }}",
            {"context": {"data": {"key": "value", "num": 42}}}
        )
        assert isinstance(result, str)
        assert json.loads(result) == {"key": "value", "num": 42}

    def test_jinja2_nested_list_without_tojson(self):
        """Test nested lists render as valid JSON strings."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "{{ context.nested }}",
            {"context": {"nested": [["a", "b"], ["c", "d"]]}}
        )
        assert isinstance(result, str)
        assert json.loads(result) == [["a", "b"], ["c", "d"]]

    def test_jinja2_filter_expression(self):
        """Test Jinja2 filters work."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "{{ context.name | upper }}",
            {"context": {"name": "alice"}}
        )
        assert result == "ALICE"

    def test_jinja2_conditional(self):
        """Test Jinja2 conditionals work."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "{% if context.active %}yes{% else %}no{% endif %}",
            {"context": {"active": True}}
        )
        assert result == "yes"

    def test_plain_string_unchanged(self):
        """Test that plain strings pass through."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "hello world",
            {}
        )
        assert result == "hello world"

    def test_non_path_string_unchanged(self):
        """Test that strings that aren't paths pass through."""
        machine = FlatMachine(config_dict=get_minimal_config())
        result = machine._render_template(
            "some.random.text",  # Not output.*/context.*/input.*
            {}
        )
        assert result == "some.random.text"


class _LogCapture(logging.Handler):
    """Lightweight handler that accumulates formatted log output."""
    def __init__(self):
        super().__init__()
        self.output = ""
    def emit(self, record):
        self.output += self.format(record) + "\n"


class TestSerializationWarnings:
    """P2: Test that serialization warnings include field names.

    The flatmachines logger uses propagate=False, so pytest caplog/capsys
    can't see the records.  We attach a handler directly to the persistence
    logger for the duration of each test.
    """

    @pytest.fixture(autouse=True)
    def _capture_persistence_logs(self):
        self._log = _LogCapture()
        logger = logging.getLogger("flatmachines.persistence")
        logger.addHandler(self._log)
        yield
        logger.removeHandler(self._log)

    def test_safe_serialize_warns_with_field_name(self):
        """Test that non-serializable fields are logged with names."""
        import datetime

        backend = MemoryBackend()
        manager = CheckpointManager(backend, "test-id")

        data = {
            "good": "value",
            "timestamp": datetime.datetime.now()
        }

        result = manager._safe_serialize(data)

        # Should have serialized successfully
        parsed = json.loads(result)
        assert parsed["good"] == "value"
        assert "timestamp" in parsed  # Field exists as string

        # Should have logged warning with field name
        assert "timestamp (datetime)" in self._log.output
        assert "good" not in self._log.output  # Only warn about bad fields

    def test_safe_serialize_nested_non_serializable(self):
        """Test that nested non-serializable fields are identified."""
        import datetime

        backend = MemoryBackend()
        manager = CheckpointManager(backend, "test-id")

        data = {
            "wrapper": {
                "nested_time": datetime.datetime.now()
            }
        }

        result = manager._safe_serialize(data)

        parsed = json.loads(result)
        assert "wrapper" in parsed
        assert "nested_time" in parsed["wrapper"]

        # Warning should include path
        assert "wrapper.nested_time (datetime)" in self._log.output

    def test_safe_serialize_list_with_non_serializable(self):
        """Test that non-serializable items in lists are identified."""
        import datetime

        backend = MemoryBackend()
        manager = CheckpointManager(backend, "test-id")

        data = {
            "items": ["good", datetime.datetime.now(), "also_good"]
        }

        result = manager._safe_serialize(data)

        parsed = json.loads(result)
        assert len(parsed["items"]) == 3
        assert parsed["items"][0] == "good"
        assert parsed["items"][2] == "also_good"

        # Warning should include index
        assert "items[1] (datetime)" in self._log.output

    def test_safe_serialize_all_good_no_warning(self):
        """Test that no warning is logged when all fields are serializable."""
        backend = MemoryBackend()
        manager = CheckpointManager(backend, "test-id")

        data = {
            "string": "value",
            "number": 42,
            "list": [1, 2, 3],
            "nested": {"a": "b"}
        }

        result = manager._safe_serialize(data)

        parsed = json.loads(result)
        assert parsed == data

        # No warning should be logged
        assert "not JSON serializable" not in self._log.output

    def test_safe_serialize_multiple_bad_fields(self):
        """Test that multiple non-serializable fields are all reported."""
        import datetime

        backend = MemoryBackend()
        manager = CheckpointManager(backend, "test-id")

        class CustomObj:
            pass

        data = {
            "time1": datetime.datetime.now(),
            "good": "value",
            "custom": CustomObj()
        }

        result = manager._safe_serialize(data)

        # Both bad fields should be mentioned
        assert "time1 (datetime)" in self._log.output
        assert "custom (CustomObj)" in self._log.output


class TestMarkdownStripping:
    """Test that markdown code block fences are stripped from LLM responses."""

    def test_strip_json_fence(self):
        """Test stripping ```json ... ``` blocks."""
        content = '```json\n{"key": "value"}\n```'
        result = strip_markdown_json(content)
        assert result == '{"key": "value"}'
        assert json.loads(result) == {"key": "value"}

    def test_strip_json_fence_uppercase(self):
        """Test stripping ```JSON ... ``` blocks."""
        content = '```JSON\n{"key": "value"}\n```'
        result = strip_markdown_json(content)
        assert result == '{"key": "value"}'

    def test_strip_plain_fence(self):
        """Test stripping ``` ... ``` blocks without language."""
        content = '```\n{"key": "value"}\n```'
        result = strip_markdown_json(content)
        assert result == '{"key": "value"}'

    def test_no_fence_unchanged(self):
        """Test that content without fences passes through."""
        content = '{"key": "value"}'
        result = strip_markdown_json(content)
        assert result == '{"key": "value"}'

    def test_whitespace_handling(self):
        """Test that surrounding whitespace is handled."""
        content = '  ```json\n{"key": "value"}\n```  '
        result = strip_markdown_json(content)
        assert result == '{"key": "value"}'

    def test_empty_content(self):
        """Test empty string handling."""
        assert strip_markdown_json("") == ""
        assert strip_markdown_json(None) is None

    def test_complex_json(self):
        """Test with complex nested JSON."""
        json_content = '{"items": ["a", "b"], "nested": {"x": 1}}'
        content = f'```json\n{json_content}\n```'
        result = strip_markdown_json(content)
        assert json.loads(result) == {"items": ["a", "b"], "nested": {"x": 1}}

    def test_text_before_fence(self):
        """Test extracting JSON when there's explanatory text before the fence."""
        content = '''I will search for other potential hook-related files...
```json
{"action": "rg", "pattern": "hook"}
```'''
        result = strip_markdown_json(content)
        assert result == '{"action": "rg", "pattern": "hook"}'
        assert json.loads(result) == {"action": "rg", "pattern": "hook"}

    def test_text_after_fence(self):
        """Test extracting JSON when there's text after the fence."""
        content = '''```json
{"key": "value"}
```
Let me know if you need anything else.'''
        result = strip_markdown_json(content)
        assert result == '{"key": "value"}'

    def test_raw_json_no_fence(self):
        """Test extracting raw JSON object without fence."""
        content = 'Here is the result: {"status": "ok"}'
        result = strip_markdown_json(content)
        assert json.loads(result) == {"status": "ok"}

    def test_raw_json_array(self):
        """Test extracting raw JSON array without fence."""
        content = 'The items are: [1, 2, 3]'
        result = strip_markdown_json(content)
        assert json.loads(result) == [1, 2, 3]
