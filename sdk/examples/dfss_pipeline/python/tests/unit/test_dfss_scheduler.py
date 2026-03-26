from __future__ import annotations

from _dfss_test_helpers import load_dfss_module



def _scheduler_module():
    return load_dfss_module("scheduler.py", "dfss_scheduler")



def test_score_prefers_active_root():
    mod = _scheduler_module()
    root = mod.RootState(root_id="root-000", admitted=True, pending=4)
    item = {
        "task_id": "root-000/0",
        "root_id": "root-000",
        "depth": 0,
        "resource_class": "fast",
        "has_expensive_descendant": False,
    }

    assert mod.score(item, root, is_active=True) > mod.score(item, root, is_active=False)



def test_score_prefers_depth():
    mod = _scheduler_module()
    root = mod.RootState(root_id="root-000", admitted=True, pending=4)

    shallow = {
        "task_id": "root-000/0",
        "root_id": "root-000",
        "depth": 0,
        "resource_class": "fast",
        "has_expensive_descendant": False,
    }
    deep = dict(shallow)
    deep["task_id"] = "root-000/0.0.1"
    deep["depth"] = 3

    assert mod.score(deep, root, is_active=True) > mod.score(shallow, root, is_active=True)



def test_score_boosts_slow_resource():
    mod = _scheduler_module()
    root = mod.RootState(root_id="root-000", admitted=True, pending=4)

    fast = {
        "task_id": "root-000/0.1",
        "root_id": "root-000",
        "depth": 2,
        "resource_class": "fast",
        "has_expensive_descendant": False,
    }
    slow = dict(fast)
    slow["task_id"] = "root-000/0.0.0"
    slow["resource_class"] = "slow"

    assert mod.score(slow, root, is_active=True) > mod.score(fast, root, is_active=True)



def test_score_boosts_expensive_predecessor_hint():
    mod = _scheduler_module()
    root = mod.RootState(root_id="root-001", admitted=True, pending=4)

    cheap = {
        "task_id": "root-001/0",
        "root_id": "root-001",
        "depth": 0,
        "resource_class": "fast",
        "has_expensive_descendant": False,
    }
    drill = dict(cheap)
    drill["task_id"] = "root-001/0.0"
    drill["has_expensive_descendant"] = True

    assert mod.score(drill, root, is_active=True) > mod.score(cheap, root, is_active=True)



def test_pick_next_prefers_active_candidates():
    mod = _scheduler_module()

    roots = {
        "root-a": mod.RootState(root_id="root-a", admitted=True, pending=1),
        "root-b": mod.RootState(root_id="root-b", admitted=False, pending=1),
    }
    resources = {
        "fast": mod.ResourcePool(name="fast", capacity=4, in_flight=0, gate_open=True),
        "slow": mod.ResourcePool(name="slow", capacity=2, in_flight=0, gate_open=True),
    }
    candidates = [
        {"work_id": "1", "task_id": "root-b/0", "root_id": "root-b", "depth": 3, "resource_class": "fast", "has_expensive_descendant": False},
        {"work_id": "2", "task_id": "root-a/0", "root_id": "root-a", "depth": 0, "resource_class": "fast", "has_expensive_descendant": False},
    ]

    best = mod.pick_next(candidates, roots, resources, max_active_roots=3)
    assert best is not None
    assert best["root_id"] == "root-a"



def test_pick_next_admits_new_root_when_no_active_runnable():
    mod = _scheduler_module()

    roots = {
        "root-a": mod.RootState(root_id="root-a", admitted=True, pending=1),
        "root-b": mod.RootState(root_id="root-b", admitted=False, pending=1),
    }
    resources = {
        "fast": mod.ResourcePool(name="fast", capacity=4, in_flight=4, gate_open=True),  # saturated
        "slow": mod.ResourcePool(name="slow", capacity=2, in_flight=0, gate_open=True),
    }
    candidates = [
        {"work_id": "1", "task_id": "root-a/0", "root_id": "root-a", "depth": 1, "resource_class": "fast", "has_expensive_descendant": False},
        {"work_id": "2", "task_id": "root-b/0", "root_id": "root-b", "depth": 1, "resource_class": "slow", "has_expensive_descendant": False},
    ]

    best = mod.pick_next(candidates, roots, resources, max_active_roots=3)
    assert best is not None
    assert best["root_id"] == "root-b"



def test_pick_next_respects_gate_closed():
    mod = _scheduler_module()

    roots = {
        "root-000": mod.RootState(root_id="root-000", admitted=True, pending=2),
    }
    resources = {
        "fast": mod.ResourcePool(name="fast", capacity=1, in_flight=0, gate_open=True),
        "slow": mod.ResourcePool(name="slow", capacity=2, in_flight=0, gate_open=False),
    }
    candidates = [
        {"work_id": "1", "task_id": "root-000/0.0.0", "root_id": "root-000", "depth": 2, "resource_class": "slow", "has_expensive_descendant": False},
        {"work_id": "2", "task_id": "root-000/0.1.0", "root_id": "root-000", "depth": 2, "resource_class": "fast", "has_expensive_descendant": False},
    ]

    best = mod.pick_next(candidates, roots, resources, max_active_roots=3)
    assert best is not None
    assert best["resource_class"] == "fast"



def test_refresh_expensive_flag_clears_when_last_slow_removed():
    mod = _scheduler_module()

    root = mod.RootState(root_id="root-000", admitted=True, pending=2)
    candidates = [
        {"work_id": "1", "task_id": "root-000/0.0.0", "root_id": "root-000", "depth": 2, "resource_class": "slow", "has_expensive_descendant": False},
        {"work_id": "2", "task_id": "root-000/0.1.0", "root_id": "root-000", "depth": 2, "resource_class": "fast", "has_expensive_descendant": False},
    ]

    mod.refresh_expensive_pending_flag(root, candidates)
    assert root.has_pending_expensive is True

    candidates = [c for c in candidates if c["resource_class"] != "slow"]
    mod.refresh_expensive_pending_flag(root, candidates)
    assert root.has_pending_expensive is False
