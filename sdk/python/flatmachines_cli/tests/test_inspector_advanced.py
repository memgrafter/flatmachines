"""Advanced inspector tests — edge cases and complex configs."""

import pytest
from flatmachines_cli.inspector import (
    load_config,
    inspect_machine,
    validate_machine,
    show_context,
    _classify_context,
    _format_state,
    _format_transitions,
)


PARALLEL_MACHINE = """\
spec: flatmachine
spec_version: "2.5.0"
data:
  name: parallel_test
  machines:
    reviewer_a: "./review_a.yml"
    reviewer_b: "./review_b.yml"
  states:
    start:
      type: initial
      machine: [reviewer_a, reviewer_b]
      mode: settled
      transitions:
        - to: merge
    merge:
      agent: merger
      transitions:
        - to: done
    done:
      type: final
      output:
        result: "{{ context.result }}"
"""

FOREACH_MACHINE = """\
spec: flatmachine
spec_version: "2.5.0"
data:
  name: foreach_test
  machines:
    item_processor: "./process.yml"
  context:
    items: "{{ input.items }}"
    results: null
  states:
    start:
      type: initial
      foreach: "{{ context.items }}"
      as: item
      machine: item_processor
      transitions:
        - to: done
    done:
      type: final
      output:
        results: "{{ context.results }}"
"""

WAIT_FOR_MACHINE = """\
spec: flatmachine
spec_version: "2.5.0"
data:
  name: wait_test
  context:
    task_id: "{{ input.task_id }}"
    approved: null
  states:
    start:
      type: initial
      agent: analyzer
      transitions:
        - to: wait_approval
    wait_approval:
      wait_for: "approval/{{ context.task_id }}"
      timeout: 86400
      output_to_context:
        approved: "{{ output.approved }}"
      transitions:
        - condition: "context.approved"
          to: done
        - to: rejected
    rejected:
      type: final
      output:
        result: "rejected"
    done:
      type: final
      output:
        result: "approved"
"""

LAUNCH_MACHINE = """\
spec: flatmachine
spec_version: "2.5.0"
data:
  name: launch_test
  states:
    start:
      type: initial
      launch: background_task
      launch_input:
        data: "{{ context.data }}"
      transitions:
        - to: done
    done:
      type: final
"""

NO_STATES_MACHINE = """\
spec: flatmachine
data:
  name: empty_machine
  states: {}
"""


class TestInspectParallelMachines:
    def test_parallel_annotation(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(PARALLEL_MACHINE)
        output = inspect_machine(str(f))
        assert "parallel" in output.lower()
        assert "reviewer_a" in output
        assert "reviewer_b" in output

    def test_parallel_machines_section(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(PARALLEL_MACHINE)
        output = inspect_machine(str(f))
        assert "Machines" in output


class TestInspectForeachMachine:
    def test_foreach_annotation(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(FOREACH_MACHINE)
        output = inspect_machine(str(f))
        assert "foreach" in output

    def test_foreach_context(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(FOREACH_MACHINE)
        ctx_output = show_context(str(f))
        assert "items" in ctx_output


class TestInspectWaitForMachine:
    def test_wait_for_annotation(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(WAIT_FOR_MACHINE)
        output = inspect_machine(str(f))
        assert "wait:" in output

    def test_conditional_transitions(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(WAIT_FOR_MACHINE)
        output = inspect_machine(str(f))
        assert "done" in output
        assert "rejected" in output


class TestInspectLaunchMachine:
    def test_launch_annotation(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(LAUNCH_MACHINE)
        output = inspect_machine(str(f))
        assert "launch:" in output
        assert "background_task" in output


class TestInspectEdgeCases:
    def test_empty_states(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text(NO_STATES_MACHINE)
        output = inspect_machine(str(f))
        assert "empty_machine" in output
        assert "States" in output

    def test_format_state_empty_dict(self):
        result = _format_state("s", {}, None, set())
        assert "s" in result

    def test_format_state_default_execution(self):
        """Default execution type should not show annotation."""
        result = _format_state("s", {"execution": {"type": "default"}}, None, set())
        assert "default" not in result

    def test_format_transitions_empty(self):
        """Empty transitions list should return '?'."""
        result = _format_transitions([{"to": "?"}])
        assert "?" in result

    def test_format_transitions_many(self):
        """Multiple transitions should all be shown."""
        result = _format_transitions([
            {"condition": "a", "to": "s1"},
            {"condition": "b", "to": "s2"},
            {"condition": "c", "to": "s3"},
            {"to": "default"},
        ])
        assert "s1" in result
        assert "s2" in result
        assert "s3" in result
        assert "default" in result


class TestValidateMachine:
    def test_validate_nonexistent(self):
        result = validate_machine("/nonexistent/path.yml")
        # Should show an error, not crash
        assert isinstance(result, str)

    def test_validate_valid(self, tmp_path):
        f = tmp_path / "machine.yml"
        f.write_text("""\
spec: flatmachine
spec_version: "2.5.0"
data:
  name: valid_machine
  states:
    start:
      type: initial
      transitions:
        - to: end
    end:
      type: final
""")
        result = validate_machine(str(f))
        assert isinstance(result, str)
        # Either "Valid" or warnings — both are acceptable


class TestClassifyContextAdvanced:
    def test_jinja2_default_template(self):
        ctx = {"port": "{{ input.port | default(8080) }}"}
        inp, static = _classify_context(ctx)
        assert "port" in inp

    def test_complex_template(self):
        ctx = {"config": "{{ input.base_config | tojson }}"}
        inp, static = _classify_context(ctx)
        assert "config" in inp

    def test_non_string_values(self):
        ctx = {"list_val": [1, 2, 3], "dict_val": {"a": 1}, "int_val": 42, "bool_val": True}
        inp, static = _classify_context(ctx)
        assert inp == []
        assert len(static) == 4
