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
import logging
import os
import warnings
from pathlib import Path

# Suppress validation warnings until schemas are regenerated
warnings.filterwarnings("ignore", message=".*validation.*")
warnings.filterwarnings("ignore", message=".*Flatmachine.*")
warnings.filterwarnings("ignore", message=".*Flatagent.*")

from flatmachines import FlatMachine  # noqa: E402

from .hooks import CLIToolHooks  # noqa: E402

try:
    import readline  # noqa: F401 — enables arrow keys, history in input()
except ImportError:
    pass

# Quiet by default — set LOG_LEVEL=INFO or LOG_LEVEL=DEBUG to see logs
_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.getLogger().setLevel(_log_level)
for _name in ("flatagents", "flatmachines", "LiteLLM"):
    logging.getLogger(_name).setLevel(_log_level)


def _config_path(name: str) -> str:
    return str(Path(__file__).parent.parent.parent.parent / "config" / name)


async def run_machine(task: str, working_dir: str, human_review: bool = True):
    """Run a single task via FlatMachine machine-driven tool loop."""
    hooks = CLIToolHooks(working_dir=working_dir, auto_approve=not human_review)
    machine = FlatMachine(
        config_file=_config_path("machine.yml"),
        hooks=hooks,
    )

    result = await machine.execute(input={
        "task": task,
        "working_dir": working_dir,
    })

    return result


async def run_standalone(task: str, working_dir: str):
    """Run a single task via FlatMachine without interactive review."""
    result = await run_machine(task, working_dir, human_review=False)

    print("=" * 60)
    print("DONE")
    print("=" * 60)
    content = result.get("result") if isinstance(result, dict) else result
    if content:
        print(content)

    return result


async def repl(working_dir: str):
    """Interactive REPL — enter tasks, agent executes with human review loop."""
    print(f"Tool Use CLI — {working_dir}")
    print()

    _interrupt_count = 0

    while True:
        try:
            task = input("> ").strip()
            _interrupt_count = 0
        except KeyboardInterrupt:
            # Single ^C clears input, double ^C exits
            _interrupt_count += 1
            if _interrupt_count >= 2:
                print()
                break
            print()
            continue
        except EOFError:
            # ^D exits
            print()
            break

        if not task:
            continue

        _interrupt_count = 0

        try:
            await run_machine(task, working_dir)
        except KeyboardInterrupt:
            print("\nInterrupted.")
        except Exception as e:
            print(f"Error: {e}")

        print()


def main():
    parser = argparse.ArgumentParser(
        description="CLI coding agent with FlatMachine tool loop (read, write, bash, edit)"
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
        help="Run FlatMachine tool loop without interactive review",
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
