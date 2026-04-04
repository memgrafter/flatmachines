"""Tests for machine inspector."""

import pytest
from flatmachines_cli.inspector import (
    load_config,
    inspect_machine,
    show_context,
    _classify_context,
    _format_transitions,
    _format_state,
)


FULL_MACHINE_YAML = """\
spec: flatmachine
spec_version: "2.5.0"
metadata:
  description: "A test machine"
  tags: ["test", "example"]
data:
  name: test_machine
  agents:
    analyzer: "./analyzer.yml"
    coder: "./coder.yml"
  machines:
    sub_machine: "./sub.yml"
  context:
    task: "{{ input.task }}"
    working_dir: "{{ input.working_dir }}"
    result: null
    max_retries: 3
  persistence:
    enabled: true
    backend: local
  states:
    start:
      type: initial
      agent: analyzer
      transitions:
        - condition: "context.needs_code"
          to: code
        - to: done
    code:
      agent: coder
      tool_loop:
        max_turns: 10
      execution:
        type: retry
        backoffs: [2, 4, 8]
      on_error: error_handler
      transitions:
        - to: review
    review:
      action: human_review
      transitions:
        - condition: "context.approved"
          to: done
        - to: code
    error_handler:
      agent: analyzer
      transitions:
        - to: done
    done:
      type: final
      output:
        result: "{{ context.result }}"
"""

MINIMAL_MACHINE_YAML = """\
spec: flatmachine
data:
  name: minimal
  states:
    start:
      type: initial
      transitions:
        - to: end
    end:
      type: final
"""


class TestLoadConfig:
    def test_loads_yaml(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(FULL_MACHINE_YAML)
        config = load_config(str(f))
        assert config["spec"] == "flatmachine"
        assert config["data"]["name"] == "test_machine"

    def test_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/file.yml")


class TestClassifyContext:
    def test_input_keys(self):
        ctx = {"task": "{{ input.task }}", "dir": "{{ input.dir }}"}
        inp, static = _classify_context(ctx)
        assert "task" in inp
        assert "dir" in inp
        assert static == []

    def test_static_keys(self):
        ctx = {"max_retries": 3, "result": None}
        inp, static = _classify_context(ctx)
        assert inp == []
        assert "max_retries" in static
        assert "result" in static

    def test_mixed(self):
        ctx = {
            "task": "{{ input.task }}",
            "result": None,
            "config": {"key": "val"},
        }
        inp, static = _classify_context(ctx)
        assert inp == ["task"]
        assert "result" in static
        assert "config" in static

    def test_empty_context(self):
        inp, static = _classify_context({})
        assert inp == []
        assert static == []


class TestFormatTransitions:
    def test_single_unconditional(self):
        result = _format_transitions([{"to": "next"}])
        assert result == "next"

    def test_conditional(self):
        result = _format_transitions([
            {"condition": "context.ready", "to": "go"},
            {"to": "wait"},
        ])
        assert "go" in result
        assert "wait" in result
        assert "context.ready" in result

    def test_long_condition_truncated(self):
        long_cond = "context.very_long_condition_name_that_exceeds_forty_characters"
        result = _format_transitions([
            {"condition": long_cond, "to": "target"},
        ])
        assert "..." in result


class TestFormatState:
    def test_initial_state(self):
        result = _format_state("start", {"type": "initial"}, "start", set())
        assert "●" in result
        assert "start" in result

    def test_final_state(self):
        result = _format_state("end", {"type": "final", "output": {"r": "v"}}, "start", {"end"})
        assert "◼" in result
        assert "outputs:" in result

    def test_agent_annotation(self):
        result = _format_state("s", {"agent": "analyzer"}, None, set())
        assert "agent:analyzer" in result

    def test_machine_annotation(self):
        result = _format_state("s", {"machine": "sub"}, None, set())
        assert "machine:sub" in result

    def test_parallel_machines(self):
        result = _format_state("s", {"machine": ["a", "b"]}, None, set())
        assert "parallel:" in result

    def test_foreach(self):
        result = _format_state("s", {"foreach": "context.items"}, None, set())
        assert "foreach:" in result

    def test_tool_loop(self):
        result = _format_state("s", {"tool_loop": {"max_turns": 10}}, None, set())
        assert "tool_loop" in result

    def test_retry_execution(self):
        result = _format_state("s", {"execution": {"type": "retry"}}, None, set())
        assert "retry" in result

    def test_wait_for(self):
        result = _format_state("s", {"wait_for": "signal/123"}, None, set())
        assert "wait:" in result

    def test_launch(self):
        result = _format_state("s", {"launch": "bg_task"}, None, set())
        assert "launch:" in result

    def test_action(self):
        result = _format_state("s", {"action": "human_review"}, None, set())
        assert "action:" in result


class TestInspectMachine:
    def test_full_inspection(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(FULL_MACHINE_YAML)
        output = inspect_machine(str(f))
        assert "test_machine" in output
        assert "A test machine" in output
        assert "States" in output
        assert "Agents" in output
        assert "analyzer" in output
        assert "coder" in output
        assert "Machines" in output
        assert "Context" in output
        assert "persistence" in output

    def test_minimal_inspection(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        output = inspect_machine(str(f))
        assert "minimal" in output
        assert "States" in output


class TestShowContext:
    def test_show_context(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(FULL_MACHINE_YAML)
        output = show_context(str(f))
        assert "Context Template" in output
        assert "task" in output
        assert "working_dir" in output

    def test_no_context(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(MINIMAL_MACHINE_YAML)
        output = show_context(str(f))
        assert "Context Template" in output
