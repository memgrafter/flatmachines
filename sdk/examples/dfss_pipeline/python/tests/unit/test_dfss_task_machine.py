from __future__ import annotations

from _dfss_test_helpers import load_dfss_module



def _task_machine_module():
    return load_dfss_module("task_machine.py", "dfss_task_machine")



def test_task_config_has_required_states():
    mod = _task_machine_module()
    cfg = mod.task_config()

    states = cfg["data"]["states"]
    assert set(["start", "execute_task", "done", "error_exit"]).issubset(states.keys())
    assert states["start"]["type"] == "initial"
    assert states["done"]["type"] == "final"
    assert states["error_exit"]["type"] == "final"



def test_execute_task_has_on_error_to_error_exit():
    mod = _task_machine_module()
    cfg = mod.task_config()

    execute_state = cfg["data"]["states"]["execute_task"]
    assert execute_state["action"] == "run_task"
    assert execute_state["on_error"] == "error_exit"



def test_final_output_contains_typed_children_list():
    mod = _task_machine_module()
    cfg = mod.task_config()

    out = cfg["data"]["states"]["done"]["output"]
    assert "task_id" in out
    assert "root_id" in out
    assert "result" in out
    assert "children" in out



def test_error_exit_outputs_error_field():
    mod = _task_machine_module()
    cfg = mod.task_config()

    out = cfg["data"]["states"]["error_exit"]["output"]
    assert "error" in out
