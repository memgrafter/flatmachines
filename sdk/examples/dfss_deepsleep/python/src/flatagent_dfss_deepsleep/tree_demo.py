"""
DFSS Deep Sleep demo — run the task machine on sample tasks.

This demo runs the task runner machine on a set of seed tasks,
showing how tasks produce children and the tree fans out up to max_depth.
No LLM calls — all work is done in hooks.
"""
import asyncio
import logging
from pathlib import Path

from flatmachines import FlatMachine, MemoryBackend, HooksRegistry

from flatagent_dfss_deepsleep.hooks import DeepSleepHooks

# Suppress internal flatmachines logging so demo output is clean
logging.getLogger("flatmachines").setLevel(logging.WARNING)


async def run():
    """Run the task machine on sample seed tasks and display the tree."""
    print("--- DFSS Deep Sleep Demo ---")
    print()

    config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'task_machine.yml'
    hooks = DeepSleepHooks(max_depth=3, fail_rate=0.0, seed=5)
    registry = HooksRegistry()
    registry.register("deepsleep", lambda: hooks)

    seed_tasks = [
        {
            "task_id": "root-0/0",
            "root_id": "root-0",
            "depth": 0,
            "resource_class": "fast",
            "has_expensive_descendant": True,
            "distance_to_nearest_slow_descendant": 2,
        },
        {
            "task_id": "root-1/0",
            "root_id": "root-1",
            "depth": 0,
            "resource_class": "slow",
            "has_expensive_descendant": False,
            "distance_to_nearest_slow_descendant": 0,
        },
    ]

    all_results = []
    pending = list(seed_tasks)
    generation = 0

    while pending:
        generation += 1
        print(f"Generation {generation}: processing {len(pending)} task(s)")

        results = []
        for task in pending:
            machine = FlatMachine(
                config_file=str(config_path),
                hooks_registry=registry,
                persistence=MemoryBackend(),
            )
            result = await machine.execute(input=task)
            results.append(result)

        # Collect children for next generation
        next_pending = []
        for result in results:
            task_id = result.get("task_id", "?")
            res = result.get("result", "?")
            children = result.get("children", [])
            error = result.get("error")

            if error:
                print(f"  ✗ {task_id}: error — {error}")
            else:
                print(f"  ✓ {task_id}: {res} → {len(children)} child(ren)")

            all_results.append(result)
            next_pending.extend(children)

        pending = next_pending

    print()
    print("--- Demo Complete ---")
    print(f"Total tasks executed: {len(all_results)}")
    successes = sum(1 for r in all_results if not r.get("error"))
    failures = sum(1 for r in all_results if r.get("error"))
    print(f"Successes: {successes}, Failures: {failures}")

    # Print the tree
    print()
    print("--- Task Tree ---")
    for r in all_results:
        depth = r.get("task_id", "").count(".")
        indent = "  " * depth
        tid = r.get("task_id", "?")
        children_count = len(r.get("children", []))
        status = "✗" if r.get("error") else "✓"
        print(f"{indent}{status} {tid} ({children_count} children)")


def main():
    """Synchronous entry point for the script defined in pyproject.toml."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
