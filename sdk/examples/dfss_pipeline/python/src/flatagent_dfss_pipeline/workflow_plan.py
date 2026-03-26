from __future__ import annotations

import random
from typing import Any, Dict, List


Node = Dict[str, Any]
Plan = Dict[str, Any]


def _add_node(
    nodes: Dict[str, Node],
    task_id: str,
    root_id: str,
    depth: int,
    resource_class: str,
    parent_id: str | None,
) -> None:
    if task_id in nodes:
        return
    nodes[task_id] = {
        "task_id": task_id,
        "root_id": root_id,
        "depth": int(depth),
        "resource_class": resource_class,
        "parent_id": parent_id,
        "children": [],
        "has_expensive_descendant": False,
        "distance_to_nearest_slow_descendant": 10_000,
    }
    if parent_id and parent_id in nodes:
        nodes[parent_id]["children"].append(task_id)


def _add_designed_roots(nodes: Dict[str, Node]) -> None:
    # root-000
    _add_node(nodes, "root-000/0", "root-000", 0, "fast", None)
    _add_node(nodes, "root-000/0.0", "root-000", 1, "fast", "root-000/0")
    _add_node(nodes, "root-000/0.0.0", "root-000", 2, "slow", "root-000/0.0")
    _add_node(nodes, "root-000/0.0.1", "root-000", 2, "slow", "root-000/0.0")
    _add_node(nodes, "root-000/0.1", "root-000", 1, "fast", "root-000/0")
    _add_node(nodes, "root-000/0.1.0", "root-000", 2, "fast", "root-000/0.1")

    # root-001
    _add_node(nodes, "root-001/0", "root-001", 0, "fast", None)
    _add_node(nodes, "root-001/0.0", "root-001", 1, "fast", "root-001/0")
    _add_node(nodes, "root-001/0.0.0", "root-001", 2, "fast", "root-001/0.0")
    _add_node(nodes, "root-001/0.0.0.0", "root-001", 3, "slow", "root-001/0.0.0")


def _build_random_tree(nodes: Dict[str, Node], root_id: str, max_depth: int, rng: random.Random) -> None:
    root_task = f"{root_id}/0"
    _add_node(nodes, root_task, root_id, 0, rng.choice(["fast", "slow"]), None)

    def walk(task_id: str, depth: int) -> None:
        if depth >= max_depth:
            return

        # Keep random roots non-trivial for demos/tests.
        if depth == 0:
            n_children = rng.choice([1, 2])
        elif depth < max_depth - 1:
            n_children = rng.choices([0, 1, 2], weights=[0.25, 0.45, 0.30], k=1)[0]
        else:
            n_children = rng.choices([0, 1], weights=[0.7, 0.3], k=1)[0]

        for i in range(n_children):
            child_id = f"{task_id}.{i}"
            resource_class = rng.choice(["fast", "slow"])
            _add_node(nodes, child_id, root_id, depth + 1, resource_class, task_id)
            walk(child_id, depth + 1)

    walk(root_task, 0)


def _annotate_metadata(nodes: Dict[str, Node]) -> None:
    by_depth_desc = sorted(nodes.values(), key=lambda n: n["depth"], reverse=True)

    for node in by_depth_desc:
        children: List[str] = node["children"]
        if not children:
            if node["resource_class"] == "slow":
                node["distance_to_nearest_slow_descendant"] = 0
            continue

        child_nodes = [nodes[cid] for cid in children]

        # Distance includes self (0 when self is slow).
        best = 0 if node["resource_class"] == "slow" else 10_000
        for c in child_nodes:
            d = int(c.get("distance_to_nearest_slow_descendant", 10_000))
            if d < 10_000:
                best = min(best, d + 1)
        node["distance_to_nearest_slow_descendant"] = best

        # Descendant-only expensive hint (exclude self).
        node["has_expensive_descendant"] = any(
            (c["resource_class"] == "slow") or bool(c.get("has_expensive_descendant"))
            for c in child_nodes
        )


def build_workflow_plan(roots: int = 8, max_depth: int = 3, seed: int = 7) -> Plan:
    rng = random.Random(seed)
    nodes: Dict[str, Node] = {}

    # Deterministic designed roots first.
    if roots >= 1:
        _add_designed_roots(nodes)

    # Additional random roots.
    for i in range(2, max(roots, 2)):
        root_id = f"root-{i:03d}"
        _build_random_tree(nodes, root_id, max_depth=max_depth, rng=rng)

    _annotate_metadata(nodes)

    root_ids = sorted({n["root_id"] for n in nodes.values()})
    return {
        "roots": root_ids,
        "nodes": nodes,
    }


def initial_ready_task_ids(plan: Plan) -> List[str]:
    nodes: Dict[str, Node] = plan["nodes"]
    ready = [task_id for task_id, node in nodes.items() if int(node["depth"]) == 0]
    return sorted(ready)
