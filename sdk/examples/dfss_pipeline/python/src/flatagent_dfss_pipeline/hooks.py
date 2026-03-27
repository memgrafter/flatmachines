from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from flatmachines import MachineHooks


# parent_task_id -> child specs
# child spec: (resource_class, has_expensive_descendant, distance_to_nearest_slow_descendant)
DESIGNED_TREE: Dict[str, List[Tuple[str, bool, int]]] = {
    # root-000: produces two simultaneous slow tasks at depth 2.
    "root-000/0": [
        ("fast", True, 1),
        ("fast", False, 10_000),
    ],
    "root-000/0.0": [
        ("slow", False, 0),
        ("slow", False, 0),
    ],
    "root-000/0.1": [
        ("fast", False, 10_000),
    ],
    # root-001: slow task at depth 3 behind fast predecessors.
    "root-001/0": [
        ("fast", True, 2),
    ],
    "root-001/0.0": [
        ("fast", True, 1),
    ],
    "root-001/0.0.0": [
        ("slow", False, 0),
    ],
}


class TaskHooks(MachineHooks):
    """Task execution hooks for the DFSS example."""

    def __init__(self, max_depth: int = 3, fail_rate: float = 0.15, seed: int = 7):
        self.max_depth = int(max_depth)
        self.fail_rate = float(fail_rate)
        self._rng = random.Random(seed)

    def _designed_children(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        task_id = str(context["task_id"])
        root_id = str(context["root_id"])
        depth = int(context.get("depth", 0))

        specs = DESIGNED_TREE.get(task_id, [])
        children: List[Dict[str, Any]] = []
        for idx, (resource_class, has_expensive_descendant, distance) in enumerate(specs):
            children.append(
                {
                    "task_id": f"{task_id}.{idx}",
                    "root_id": root_id,
                    "depth": depth + 1,
                    "resource_class": resource_class,
                    "has_expensive_descendant": bool(has_expensive_descendant),
                    "distance_to_nearest_slow_descendant": int(distance),
                }
            )
        return children

    def _random_children(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        task_id = str(context["task_id"])
        root_id = str(context["root_id"])
        depth = int(context.get("depth", 0))

        if depth >= self.max_depth:
            return []

        n_children = self._rng.randint(0, 2)
        children: List[Dict[str, Any]] = []
        for idx in range(n_children):
            resource_class = self._rng.choice(["fast", "slow"])
            hint = resource_class == "fast" and (self._rng.random() < 0.25)
            if resource_class == "slow":
                distance = 0
            elif hint:
                distance = self._rng.randint(1, max(1, self.max_depth - depth))
            else:
                distance = 10_000

            children.append(
                {
                    "task_id": f"{task_id}.{idx}",
                    "root_id": root_id,
                    "depth": depth + 1,
                    "resource_class": resource_class,
                    "has_expensive_descendant": bool(hint),
                    "distance_to_nearest_slow_descendant": int(distance),
                }
            )

        return children

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name != "run_task":
            return context

        if self._rng.random() < self.fail_rate:
            raise RuntimeError(f"transient failure in {context.get('task_id', 'unknown')}")

        task_id = str(context.get("task_id", "unknown"))
        root_id = str(context.get("root_id", ""))

        if root_id in {"root-000", "root-001"}:
            children = self._designed_children(context)
        else:
            children = self._random_children(context)

        context["children"] = children
        context["result"] = f"ok:{task_id}"
        return context
