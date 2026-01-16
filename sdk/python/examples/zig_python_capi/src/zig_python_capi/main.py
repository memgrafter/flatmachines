"""
Main entry point for Zig + Python C-API demo.

This demo showcases:
1. Zig code using @cImport to integrate with Python.h
2. Direct Python C-API usage for zero-overhead function calls
3. FlatMachine orchestrating LLM agents + Zig compute
4. Performance comparison between Python and Zig implementations
"""

import asyncio
import importlib.util
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from flatagents import FlatMachine, MachineHooks


class ZigPrimeHooks(MachineHooks):
    """Custom hooks for executing Zig-powered prime computations."""

    def __init__(self):
        """Initialize hooks and load Zig extension module."""
        super().__init__()
        self.zigprimes = None
        self.load_zig_module()

    def load_zig_module(self):
        """Dynamically load the Zig-compiled Python extension."""
        # Try to import zigprimes from current directory or parent
        try:
            import zigprimes

            self.zigprimes = zigprimes
            print("✓ Loaded Zig extension module: zigprimes")
        except ImportError:
            # Try loading from the package directory
            module_dir = Path(__file__).parent
            zig_module_path = None

            # Search for the .so/.pyd file
            for pattern in ["zigprimes*.so", "zigprimes*.pyd", "zigprimes*.dylib"]:
                matches = list(module_dir.glob(pattern))
                if matches:
                    zig_module_path = matches[0]
                    break

            if zig_module_path is None:
                raise RuntimeError(
                    "Zig extension module not found. Please run: cd zig_src && make && make install"
                )

            # Load the module dynamically
            spec = importlib.util.spec_from_file_location("zigprimes", zig_module_path)
            if spec and spec.loader:
                zigprimes = importlib.util.module_from_spec(spec)
                sys.modules["zigprimes"] = zigprimes
                spec.loader.exec_module(zigprimes)
                self.zigprimes = zigprimes
                print(f"✓ Loaded Zig extension from: {zig_module_path}")
            else:
                raise RuntimeError(f"Failed to load module from {zig_module_path}")

    def on_machine_start(self, context: dict) -> dict:
        """Called when machine starts."""
        print("\n" + "=" * 70)
        print("🚀 ZIG + PYTHON C-API DEMO")
        print("=" * 70)
        print(f"\nConfiguration:")
        print(f"  - Tasks per iteration: {context.get('num_tasks', 3)}")
        print(f"  - Focus area: {context.get('focus_area', 'general')}")
        print(f"  - Max iterations: {context.get('max_iterations', 2)}")
        print(f"\n{'=' * 70}\n")
        return context

    def on_action(self, action_name: str, context: dict) -> dict:
        """Handle custom actions."""
        if action_name == "execute_zig_tasks":
            return self.execute_zig_tasks(context)
        elif action_name == "increment_iteration":
            return self.increment_iteration(context)
        return context

    def execute_zig_tasks(self, context: dict) -> dict:
        """Execute tasks using Zig C-API functions."""
        tasks = context.get("tasks", [])
        results = []
        total_time = 0.0

        print(f"\n⚡ Executing {len(tasks)} tasks with Zig...")
        print("-" * 70)

        for i, task in enumerate(tasks, 1):
            task_type = task.get("task_type")
            description = task.get("description")
            params = task.get("params", {})

            print(f"\n[Task {i}/{len(tasks)}] {description}")
            print(f"  Type: {task_type}")
            print(f"  Params: {params}")

            start_time = time.time()
            result = None

            try:
                if task_type == "is_prime":
                    n = int(params.get("n", 0))
                    result = self.zigprimes.is_prime(n)
                    print(f"  ✓ Result: {n} is {'PRIME' if result else 'NOT PRIME'}")

                elif task_type == "count_primes":
                    start = int(params.get("start", 0))
                    end = int(params.get("end", 0))
                    result = self.zigprimes.count_primes(start, end)
                    print(f"  ✓ Result: {result} primes in range [{start}, {end}]")

                elif task_type == "nth_prime":
                    n = int(params.get("n", 0))
                    result = self.zigprimes.nth_prime(n)
                    print(f"  ✓ Result: The {n}th prime is {result}")

                else:
                    print(f"  ✗ Unknown task type: {task_type}")
                    result = None

            except Exception as e:
                print(f"  ✗ Error: {e}")
                result = None

            execution_time = time.time() - start_time
            total_time += execution_time

            print(f"  Time: {execution_time:.6f}s")

            results.append(
                {
                    "task_type": task_type,
                    "description": description,
                    "params": params,
                    "result": result,
                    "execution_time": execution_time,
                }
            )

        print(f"\n{'─' * 70}")
        print(f"Total Zig execution time: {total_time:.6f}s")
        print(f"{'─' * 70}\n")

        # Store results in context
        context["task_results"] = results
        context["total_execution_time"] = total_time

        # Accumulate all results
        all_results = context.get("all_results", [])
        all_results.extend(results)
        context["all_results"] = all_results

        return context

    def increment_iteration(self, context: dict) -> dict:
        """Increment iteration counter."""
        iteration = context.get("iteration", 0)
        context["iteration"] = iteration + 1
        print(f"\n📊 Completed iteration {iteration + 1}")
        return context

    def on_state_enter(self, state: str, context: dict) -> dict:
        """Called when entering a state."""
        state_icons = {
            "generate_tasks": "🎯",
            "execute_tasks": "⚡",
            "analyze_results": "🔍",
            "done": "✅",
        }
        icon = state_icons.get(state, "▶️")
        print(f"\n{icon} State: {state}")
        return context

    def on_machine_end(self, context: dict, result: dict) -> dict:
        """Called when machine completes."""
        print("\n" + "=" * 70)
        print("🎉 DEMO COMPLETE")
        print("=" * 70)
        print(f"\nTotal iterations: {result.get('total_iterations', 0)}")
        print(f"\nFinal insights:")
        print(result.get("final_insights", "No insights available"))
        print("\n" + "=" * 70)
        return result


async def run(
    num_tasks: int = 3,
    focus_area: str = "large primes and ranges",
    max_iterations: int = 2,
) -> Dict[str, Any]:
    """
    Run the Zig + Python C-API demo.

    Args:
        num_tasks: Number of tasks to generate per iteration
        focus_area: Focus area for task generation
        max_iterations: Maximum number of iterations to run

    Returns:
        Final machine result with insights and statistics
    """
    config_path = Path(__file__).parent.parent.parent / "config" / "machine.yml"

    if not config_path.exists():
        raise FileNotFoundError(f"Machine config not found: {config_path}")

    # Create machine with custom hooks
    machine = FlatMachine(config_file=str(config_path), hooks=ZigPrimeHooks())

    # Execute machine
    result = await machine.execute(
        input={
            "num_tasks": num_tasks,
            "focus_area": focus_area,
            "max_iterations": max_iterations,
        }
    )

    return result


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Zig + Python C-API Demo with FlatAgents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  zig-capi-demo                           # Run with defaults
  zig-capi-demo --tasks 5                 # Generate 5 tasks per iteration
  zig-capi-demo --focus "small primes"    # Focus on small primes
  zig-capi-demo --iterations 3            # Run 3 iterations
        """,
    )

    parser.add_argument(
        "--tasks",
        type=int,
        default=3,
        help="Number of tasks to generate per iteration (default: 3)",
    )

    parser.add_argument(
        "--focus",
        type=str,
        default="large primes and ranges",
        help="Focus area for task generation (default: 'large primes and ranges')",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=2,
        help="Maximum number of iterations (default: 2)",
    )

    args = parser.parse_args()

    try:
        result = asyncio.run(run(args.tasks, args.focus, args.iterations))
        return 0
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
