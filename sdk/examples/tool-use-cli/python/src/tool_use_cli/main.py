"""
Tool Use CLI — a coding agent with read, write, bash, and edit tools.

Default: interactive REPL. Use -p for single-shot mode.

Usage:
    python -m tool_use_cli.main                              # REPL
    python -m tool_use_cli.main -p "list Python files"       # single-shot
    python -m tool_use_cli.main --standalone "summarize README.md"
"""

import argparse
import asyncio
import os
import sys
import warnings
from pathlib import Path

# Suppress validation warnings until schemas are regenerated
warnings.filterwarnings("ignore", category=UserWarning, message=".*validation.*")

from flatmachines import FlatMachine, setup_logging, get_logger
from flatagents import FlatAgent
from flatagents.tool_loop import ToolLoopAgent, Guardrails, StopReason

from .hooks import CLIToolHooks
from .tools import CLIToolProvider

_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
setup_logging(level=_log_level)
logger = get_logger(__name__)


def _config_path(name: str) -> str:
    return str(Path(__file__).parent.parent.parent.parent / "config" / name)


async def run_machine(task: str, working_dir: str):
    """Run a single task via FlatMachine with tool loop + human review."""
    hooks = CLIToolHooks(working_dir=working_dir)
    machine = FlatMachine(
        config_file=_config_path("machine.yml"),
        hooks=hooks,
    )

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
    """Run a single task via ToolLoopAgent (no machine)."""
    agent = FlatAgent(config_file=_config_path("agent.yml"))
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


async def repl(working_dir: str):
    """Interactive REPL — enter tasks, agent executes with human review loop."""
    print(f"Tool Use CLI — working dir: {working_dir}")
    print(f"Type a task, or 'quit' to exit.")
    print()

    while True:
        try:
            task = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not task:
            continue
        if task.lower() in ("quit", "exit", "q"):
            break

        try:
            await run_machine(task, working_dir)
        except Exception as e:
            print(f"Error: {e}")

        print()


def main():
    parser = argparse.ArgumentParser(
        description="CLI coding agent with read, write, bash, edit tools"
    )
    parser.add_argument(
        "-p", "--print",
        metavar="TASK",
        dest="task",
        help="Run a single task and exit (useful for pipes)",
    )
    parser.add_argument(
        "--working-dir", "-w",
        default=os.getcwd(),
        help="Working directory for file operations (default: cwd)",
    )
    parser.add_argument(
        "--standalone", "-s",
        metavar="TASK",
        nargs="?",
        const=True,
        help="Use standalone ToolLoopAgent (no machine, no human review)",
    )
    args = parser.parse_args()

    working_dir = os.path.abspath(args.working_dir)

    if args.standalone:
        # --standalone "task" or --standalone with -p "task"
        task = args.standalone if isinstance(args.standalone, str) and args.standalone is not True else args.task
        if not task:
            parser.error("--standalone requires a task (--standalone 'task' or -p 'task' --standalone)")
        asyncio.run(run_standalone(task, working_dir))
    elif args.task:
        # -p "task" — single shot
        asyncio.run(run_machine(args.task, working_dir))
    else:
        # Default: REPL
        asyncio.run(repl(working_dir))


if __name__ == "__main__":
    main()
