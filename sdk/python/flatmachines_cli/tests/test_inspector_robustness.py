"""Robustness tests for inspector module with unusual configs."""

import pytest
import yaml

from flatmachines_cli.inspector import inspect_machine, validate_machine, show_context


class TestInspectMalformedConfigs:
    def test_empty_states(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text(yaml.dump({
            "spec": "flatmachine",
            "spec_version": "2.5.0",
            "data": {"states": {}},
        }))
        result = inspect_machine(str(f))
        assert isinstance(result, str)

    def test_state_no_type(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text(yaml.dump({
            "spec": "flatmachine",
            "spec_version": "2.5.0",
            "data": {"states": {"s1": {"agent": "fast"}}},
        }))
        result = inspect_machine(str(f))
        assert "s1" in result

    def test_deep_transitions(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text(yaml.dump({
            "spec": "flatmachine",
            "spec_version": "2.5.0",
            "data": {
                "states": {
                    "init": {
                        "type": "initial",
                        "agent": "fast",
                        "transitions": [
                            {"condition": "context.score >= 8", "to": "final"},
                            {"condition": "context.retries > 3", "to": "error"},
                            {"to": "init"},  # loop
                        ],
                    },
                    "final": {"type": "final"},
                    "error": {"type": "final"},
                },
            },
        }))
        result = inspect_machine(str(f))
        assert "init" in result
        assert "final" in result

    def test_machine_with_context(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text(yaml.dump({
            "spec": "flatmachine",
            "spec_version": "2.5.0",
            "data": {
                "context": {
                    "task": "{{ input.task }}",
                    "max_retries": "{{ input.max_retries | default(3) }}",
                    "internal_state": "running",
                },
                "states": {
                    "start": {"type": "initial", "agent": "fast"},
                },
            },
        }))
        result = show_context(str(f))
        assert "task" in result

    def test_machine_with_foreach(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text(yaml.dump({
            "spec": "flatmachine",
            "spec_version": "2.5.0",
            "data": {
                "states": {
                    "init": {
                        "type": "initial",
                        "foreach": "{{ context.items }}",
                        "as": "item",
                        "machine": "processor",
                    },
                },
            },
        }))
        result = inspect_machine(str(f))
        assert "foreach" in result or "init" in result


class TestValidateMalformed:
    def test_validate_empty_file(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text("")
        result = validate_machine(str(f))
        assert isinstance(result, str)

    def test_validate_not_yaml(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text("this is not valid yaml: [{{")
        result = validate_machine(str(f))
        assert isinstance(result, str)

    def test_validate_missing_spec(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text(yaml.dump({"data": {"states": {}}}))
        result = validate_machine(str(f))
        assert isinstance(result, str)

    def test_validate_wrong_spec(self, tmp_path):
        f = tmp_path / "m.yml"
        f.write_text(yaml.dump({
            "spec": "flatagent",  # wrong spec type
            "spec_version": "2.5.0",
            "data": {},
        }))
        result = validate_machine(str(f))
        assert isinstance(result, str)
