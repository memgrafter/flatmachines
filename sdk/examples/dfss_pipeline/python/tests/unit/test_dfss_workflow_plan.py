from __future__ import annotations

from _dfss_test_helpers import load_dfss_module



def _workflow_plan_module():
    return load_dfss_module("workflow_plan.py", "dfss_workflow_plan")



def test_build_plan_contains_all_designed_nodes():
    mod = _workflow_plan_module()
    plan = mod.build_workflow_plan(roots=2, max_depth=3, seed=7)

    nodes = plan["nodes"]
    expected = {
        "root-000/0",
        "root-000/0.0",
        "root-000/0.0.0",
        "root-000/0.0.1",
        "root-000/0.1",
        "root-000/0.1.0",
        "root-001/0",
        "root-001/0.0",
        "root-001/0.0.0",
        "root-001/0.0.0.0",
    }
    assert expected.issubset(set(nodes.keys()))



def test_random_plan_is_deterministic_with_seed():
    mod = _workflow_plan_module()
    a = mod.build_workflow_plan(roots=6, max_depth=3, seed=123)
    b = mod.build_workflow_plan(roots=6, max_depth=3, seed=123)

    a_signature = sorted((k, v["resource_class"], v["depth"]) for k, v in a["nodes"].items())
    b_signature = sorted((k, v["resource_class"], v["depth"]) for k, v in b["nodes"].items())
    assert a_signature == b_signature



def test_plan_precomputes_expensive_descendant_metadata():
    mod = _workflow_plan_module()
    plan = mod.build_workflow_plan(roots=2, max_depth=3, seed=7)
    nodes = plan["nodes"]

    # root-001 chain should be marked as gating expensive descendant
    assert nodes["root-001/0"]["has_expensive_descendant"] is True
    assert nodes["root-001/0.0"]["has_expensive_descendant"] is True
    assert nodes["root-001/0.0.0"]["has_expensive_descendant"] is True



def test_initial_ready_set_contains_only_zero_dependency_nodes():
    mod = _workflow_plan_module()
    plan = mod.build_workflow_plan(roots=4, max_depth=3, seed=7)
    ready_ids = set(mod.initial_ready_task_ids(plan))

    for task_id, node in plan["nodes"].items():
        if node["depth"] == 0:
            assert task_id in ready_ids
        else:
            assert task_id not in ready_ids
