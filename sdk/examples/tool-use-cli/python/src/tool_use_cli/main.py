"""
Tool Use CLI — a coding agent with read, write, bash, and edit tools.

Runs a FlatMachine with a tool loop, or standalone with ToolLoopAgent.

Usage:
    python -m tool_use_cli.main "list all Python files in src/"
    python -m tool_use_cli.main --standalone "read README.md and summarize it"
    python -m tool_use_cli.main --working-dir /tmp/project "create a hello world script"
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from flatmachines import FlatMachine, setup_logging, get_logger
from flatagents import FlatAgent
from flatagents.tool_loop import ToolLoopAgent, Guardrails, StopReason

from .hooks import CLIToolHooks
from .tools import CLIToolProvider

setup_logging(level="INFO")
logger = get_logger(__name__)


async def run_machine(task: str, working_dir: str):
    """Run via FlatMachine with tool loop (hooks, checkpoints, transitions)."""
    config_path = Path(__file__).parent.parent.parent.parent / "config" / "machine.yml"

    hooks = CLIToolHooks(working_dir=working_dir)
    machine = FlatMachine(
        config_file=str(config_path),
        hooks=hooks,
    )

    print(f"Machine: {machine.machine_name}")
    print(f"Working dir: {working_dir}")
    print(f"Task: {task}")
    print("-" * 60)

    result = await machine.execute(input={
        "task": task,
        "working_dir": working_dir,
    })

    print("=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"Stop reason: {result.get('stop_reason', 'unknown')}")
    print(f"Tool calls:  {result.get('tool_calls', 0)}")
    print(f"LLM turns:   {result.get('turns', 0)}")
    print(f"Cost:        ${float(result.get('cost', 0)):.4f}")
    print(f"API calls:   {machine.total_api_calls}")
    print()

    content = result.get("result", "")
    if content:
        print(content)

    return result


async def run_standalone(task: str, working_dir: str):
    """Run via ToolLoopAgent (no machine, no hooks)."""
    config_path = Path(__file__).parent.parent.parent.parent / "config" / "agent.yml"

    agent = FlatAgent(config_file=str(config_path))
    provider = CLIToolProvider(working_dir=working_dir)

    loop = ToolLoopAgent(
        agent=agent,
        tool_provider=provider,
        guardrails=Guardrails(
            max_turns=30,
            max_tool_calls=100,
            max_cost=2.00,
            tool_timeout=60.0,
            total_timeout=600.0,
        ),
    )

    print(f"Standalone ToolLoopAgent")
    print(f"Working dir: {working_dir}")
    print(f"Task: {task}")
    print("-" * 60)

    result = await loop.run(task=task)

    print("=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"Stop reason: {result.stop_reason.value}")
    print(f"Tool calls:  {result.tool_calls_count}")
    print(f"LLM turns:   {result.turns}")
    print(f"API calls:   {result.usage.api_calls}")
    print(f"Cost:        ${result.usage.total_cost:.4f}")
    print()

    if result.error:
        print(f"Error: {result.error}")

    if result.content:
        print(result.content)

    return result


def main():
    parser = argparse.ArgumentParser(description="CLI coding agent with tool use")
    parser.add_argument("task", help="Task for the agent to perform")
    parser.add_argument(
        "--working-dir", "-w",
        default=os.getcwd(),
        help="Working directory for file operations (default: cwd)",
    )
    parser.add_argument(
        "--standalone", "-s",
        action="store_true",
        help="Use standalone ToolLoopAgent instead of FlatMachine",
    )
    args = parser.parse_args()

    working_dir = os.path.abspath(args.working_dir)

    if args.standalone:
        asyncio.run(run_standalone(args.task, working_dir))
    else:
        asyncio.run(run_machine(args.task, working_dir))


if __name__ == "__main__":
    main()
