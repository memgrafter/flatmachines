"""
Agent Machine API — entry point.

Demonstrates an agent that can introspect and control its own FlatMachine
runtime via tool calls. The agent can launch child machines, inspect their
state, read/write context, and send signals.

Usage:
    # Interactive REPL
    python -m agent_machine_api.main

    # Single task
    python -m agent_machine_api.main -p "Launch the echo machine with message 'hello world'"

    # Debug mode (verbose checkpointing)
    python -m agent_machine_api.main -p "Invoke writer_critic for topic 'AI safety', then inspect the result"

Environment:
    LOG_LEVEL=DEBUG for verbose logging (default: WARNING)
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from flatmachines import FlatMachine, HooksRegistry

from .hooks import MachineAPIHooks


def _setup_logging():
    level = os.environ.get("LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        format="%(name)s %(levelname)s %(message)s",
    )


def _config_dir() -> str:
    return str(Path(__file__).resolve().parents[3] / "config")


async def run_task(task: str):
    """Run a single task through the orchestrator machine."""
    config_dir = _config_dir()
    machine_config = os.path.join(config_dir, "machine.yml")

    # Create hooks and registry
    hooks = MachineAPIHooks()
    registry = HooksRegistry()
    registry.register("machine-api", lambda: hooks)

    # Create machine
    machine = FlatMachine(
        config_file=machine_config,
        hooks_registry=registry,
    )

    # Inject machine reference into hooks so the tool provider can access it
    hooks.set_machine(machine)

    print(f"Task: {task}")
    print("---")

    result = await machine.execute(input={"task": task})

    print()
    print("---")
    print(f"Result: {result}")
    print(f"Cost: ${machine.total_cost:.4f} | API calls: {machine.total_api_calls}")

    return result


async def repl():
    """Interactive REPL — type tasks, see the agent work."""
    print("Agent Machine API — Interactive Mode")
    print("Type a task, or Ctrl+D to exit.")
    print()

    while True:
        try:
            task = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not task:
            continue

        await run_task(task)
        print()


def main():
    parser = argparse.ArgumentParser(description="Agent Machine API example")
    parser.add_argument("-p", "--prompt", help="Single task to run")
    args = parser.parse_args()

    _setup_logging()

    if args.prompt:
        asyncio.run(run_task(args.prompt))
    else:
        asyncio.run(repl())


if __name__ == "__main__":
    main()
