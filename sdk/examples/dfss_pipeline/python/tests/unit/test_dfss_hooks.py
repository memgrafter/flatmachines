from __future__ import annotations

import inspect
import pytest

from _dfss_test_helpers import load_dfss_module



def _hooks_module():
    return load_dfss_module("hooks.py", "dfss_hooks")


async def _call_on_action(hooks, action_name: str, context: dict):
    result = hooks.on_action(action_name, context)
    if inspect.isawaitable(result):
        return await result
    return result


@pytest.mark.asyncio
async def test_designed_root_000_shape():
    mod = _hooks_module()
    hooks = mod.TaskHooks(max_depth=3, fail_rate=0.0, seed=7)

    root = {
        "task_id": "root-000/0",
        "root_id": "root-000",
        "depth": 0,
        "resource_class": "fast",
        "has_expensive_descendant": True,
    }
    out = await _call_on_action(hooks, "run_task", root)
    children = out.get("children", [])

    assert len(children) == 2
    assert children[0]["task_id"] == "root-000/0.0"
    assert children[1]["task_id"] == "root-000/0.1"

    branch = {
        "task_id": "root-000/0.0",
        "root_id": "root-000",
        "depth": 1,
        "resource_class": "fast",
        "has_expensive_descendant": True,
    }
    out2 = await _call_on_action(hooks, "run_task", branch)
    classes = [c["resource_class"] for c in out2.get("children", [])]
    assert classes == ["slow", "slow"]


@pytest.mark.asyncio
async def test_designed_root_001_shape():
    mod = _hooks_module()
    hooks = mod.TaskHooks(max_depth=3, fail_rate=0.0, seed=7)

    root = {
        "task_id": "root-001/0",
        "root_id": "root-001",
        "depth": 0,
        "resource_class": "fast",
        "has_expensive_descendant": True,
    }
    out = await _call_on_action(hooks, "run_task", root)
    child = out["children"][0]
    assert child["task_id"] == "root-001/0.0"
    assert child["resource_class"] == "fast"
    assert child["has_expensive_descendant"] is True


@pytest.mark.asyncio
async def test_designed_leaves_return_no_children():
    mod = _hooks_module()
    hooks = mod.TaskHooks(max_depth=3, fail_rate=0.0, seed=7)

    leaf = {
        "task_id": "root-001/0.0.0.0",
        "root_id": "root-001",
        "depth": 3,
        "resource_class": "slow",
        "has_expensive_descendant": False,
    }
    out = await _call_on_action(hooks, "run_task", leaf)
    assert out.get("children") == []


@pytest.mark.asyncio
async def test_random_mode_respects_max_depth():
    mod = _hooks_module()
    hooks = mod.TaskHooks(max_depth=2, fail_rate=0.0, seed=123)

    at_max = {
        "task_id": "root-999/0.0",
        "root_id": "root-999",
        "depth": 2,
        "resource_class": "fast",
        "has_expensive_descendant": False,
    }
    out = await _call_on_action(hooks, "run_task", at_max)
    assert out.get("children") == []


@pytest.mark.asyncio
async def test_fail_rate_1_raises_transient_error():
    mod = _hooks_module()
    hooks = mod.TaskHooks(max_depth=3, fail_rate=1.0)

    ctx = {
        "task_id": "root-000/0",
        "root_id": "root-000",
        "depth": 0,
        "resource_class": "fast",
        "has_expensive_descendant": False,
    }
    with pytest.raises(RuntimeError):
        await _call_on_action(hooks, "run_task", ctx)
