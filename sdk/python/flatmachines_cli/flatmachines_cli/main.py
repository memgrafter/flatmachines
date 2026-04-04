"""
FlatMachines CLI — entry point.

Branded CLI for running flatmachines with an async backend/frontend pipeline.

Usage:
    flatmachines                               # interactive REPL
    flatmachines run machine.yml -p "task"     # single-shot
    flatmachines run machine.yml               # agent REPL on specific config
    flatmachines run machine.yml --standalone "task"
    flatmachines --version                     # show version
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, Optional

# Suppress validation warnings until schemas are regenerated
warnings.filterwarnings("ignore", message=".*validation.*")
warnings.filterwarnings("ignore", message=".*Flatmachine.*")
warnings.filterwarnings("ignore", message=".*Flatagent.*")

from flatmachines import FlatMachine  # noqa: E402

from .backend import CLIBackend  # noqa: E402
from .bus import DataBus  # noqa: E402
from .frontend import TerminalFrontend  # noqa: E402
from .hooks import CLIHooks  # noqa: E402

try:
    import readline  # noqa: F401 — enables arrow keys, history in input()
except ImportError:
    pass


# Quiet by default
_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.getLogger().setLevel(_log_level)
for _name in ("flatagents", "flatmachines", "flatmachines_cli", "LiteLLM"):
    logging.getLogger(_name).setLevel(_log_level)


def _resolve_config(config_path: str) -> str:
    """Resolve config path (absolute or relative to cwd)."""
    p = Path(config_path)
    if p.is_absolute():
        return str(p)
    return str(Path.cwd() / p)


def _try_find_tool_provider(working_dir: str):
    """
    Try to import and create CLIToolProvider from tool_use_cli.
    Returns a factory callable, or None if not available.

    This is a shim — the tool provider will be configurable later.
    """
    try:
        from tool_use_cli.tools import CLIToolProvider
        provider = CLIToolProvider(working_dir)
        return lambda state_name: provider
    except ImportError:
        pass

    # Try flatagents built-in tool provider as fallback
    try:
        from flatagents import ToolProvider
        return None  # No default tool provider — machine config defines tools
    except ImportError:
        return None


async def run_once(
    config_file: str,
    task: str,
    working_dir: str,
    human_review: bool = True,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """
    Run a single task through a flatmachine with the CLI pipeline.

    This is the core execution function. It wires up:
    backend (bus + processors) ← hooks ← flatmachine → hooks → backend → frontend
    """
    bus = DataBus()
    frontend = TerminalFrontend(auto_approve=auto_approve or not human_review)
    backend = CLIBackend(bus=bus, frontend=frontend)
    backend.set_frontend(frontend)

    tool_provider_factory = _try_find_tool_provider(working_dir)
    hooks = CLIHooks(backend, tool_provider_factory=tool_provider_factory)

    machine = FlatMachine(
        config_file=_resolve_config(config_file),
        hooks=hooks,
    )

    result = await backend.run_machine(
        machine,
        input={"task": task, "working_dir": working_dir},
    )

    return result


async def run_standalone(
    config_file: str,
    task: str,
    working_dir: str,
) -> Dict[str, Any]:
    """Run a single task without interactive review."""
    result = await run_once(
        config_file, task, working_dir,
        human_review=False, auto_approve=True,
    )
    content = result.get("result") if isinstance(result, dict) else result
    if content:
        print()
        print("=" * 60)
        print(content)
        print("=" * 60)
    return result


async def repl(config_file: str, working_dir: str) -> None:
    """Interactive REPL — enter tasks, agent executes with human review."""
    print(f"flatmachines cli — {working_dir}")
    print(f"config: {config_file}")
    print()

    _interrupt_count = 0

    while True:
        try:
            task = input("> ").strip()
            _interrupt_count = 0
        except KeyboardInterrupt:
            _interrupt_count += 1
            if _interrupt_count >= 2:
                print()
                break
            print()
            continue
        except EOFError:
            print()
            break

        if not task:
            continue

        _interrupt_count = 0

        try:
            await run_once(config_file, task, working_dir, human_review=True)
        except KeyboardInterrupt:
            print("\nInterrupted.")
        except Exception as e:
            print(f"Error: {e}")

        print()


def _run_async(coro):
    """Run an async coroutine with graceful signal handling.

    Catches KeyboardInterrupt and exits cleanly instead of printing
    a traceback.
    """
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        # Clean exit on Ctrl-C
        print()
        sys.exit(130)  # 128 + SIGINT(2)


def main():
    from flatmachines_cli import __version__

    parser = argparse.ArgumentParser(
        prog="flatmachines",
        description="FlatMachines CLI — run state machines with async data pipeline",
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--working-dir", "-w",
        default=os.getcwd(),
        help="Working directory for file operations (default: cwd)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set log level (overrides LOG_LEVEL env var)",
    )
    parser.add_argument(
        "--examples-dir",
        default=None,
        help="Additional directory to scan for machine configs",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- list command ---
    list_parser = subparsers.add_parser(
        "list",
        help="List discovered machine configs",
    )

    # --- inspect command ---
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a machine config (states, transitions, agents)",
    )
    inspect_parser.add_argument(
        "config",
        help="Machine name or path to YAML config",
    )

    # --- validate command ---
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a machine config against the schema",
    )
    validate_parser.add_argument(
        "config",
        help="Machine name or path to YAML config",
    )

    # --- context command ---
    context_parser = subparsers.add_parser(
        "context",
        help="Show context template and required inputs",
    )
    context_parser.add_argument(
        "config",
        help="Machine name or path to YAML config",
    )

    # --- run command ---
    run_parser = subparsers.add_parser(
        "run",
        help="Run a flatmachine config",
    )
    run_parser.add_argument(
        "config",
        help="Path to machine YAML config file",
    )
    run_parser.add_argument(
        "-p", "--prompt",
        metavar="TASK",
        dest="task",
        help="Run a single task and exit",
    )
    run_parser.add_argument(
        "--standalone", "-s",
        metavar="TASK",
        nargs="?",
        const=True,
        help="Run without interactive review",
    )

    args = parser.parse_args()
    working_dir = os.path.abspath(args.working_dir)

    # Apply --log-level if specified
    if args.log_level:
        level = getattr(logging, args.log_level)
        logging.getLogger().setLevel(level)
        for _logger_name in ("flatagents", "flatmachines", "flatmachines_cli", "LiteLLM"):
            logging.getLogger(_logger_name).setLevel(level)

    if not args.command:
        # No subcommand → interactive REPL
        from .repl import interactive_repl
        from .discovery import find_project_root

        extra_paths = [args.examples_dir] if args.examples_dir else None
        project_root = find_project_root(working_dir)

        _run_async(interactive_repl(
            project_root=project_root,
            extra_paths=extra_paths,
            working_dir=working_dir,
        ))
        return

    def _resolve_machine_path(name_or_path: str, working_dir: str) -> Optional[str]:
        """Resolve a machine name or path to an absolute config file path.

        Returns the resolved path, or None if not found.
        """
        from .discovery import MachineIndex, find_project_root

        project_root = find_project_root(working_dir)
        index = MachineIndex(project_root=project_root)
        info = index.resolve(name_or_path)
        if info:
            return info.path

        # Try as direct file path
        config_path = Path(name_or_path)
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        if config_path.is_file():
            return str(config_path)

        return None

    if args.command == "list":
        from .discovery import MachineIndex, find_project_root

        extra_paths = [args.examples_dir] if args.examples_dir else None
        project_root = find_project_root(working_dir)
        index = MachineIndex(project_root=project_root, extra_paths=extra_paths)

        machines = index.list_all()
        if not machines:
            print("No machines found.")
            return

        for m in machines:
            desc = f" — {m.description}" if m.description else ""
            print(f"  {m.name} ({m.state_count} states){desc}")
        return

    if args.command in ("inspect", "validate", "context"):
        from .inspector import inspect_machine, validate_machine, show_context

        resolved = _resolve_machine_path(args.config, working_dir)
        if not resolved:
            print(f"Machine not found: {args.config}")
            sys.exit(1)

        handlers = {
            "inspect": inspect_machine,
            "validate": validate_machine,
            "context": show_context,
        }
        print(handlers[args.command](resolved))
        return

    if args.command == "run":
        # Validate config file exists
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        if not config_path.is_file():
            run_parser.error(f"Config file not found: {args.config}")

        if args.standalone:
            # --standalone can be used with or without a value:
            # --standalone "task" → args.standalone = "task"
            # --standalone → args.standalone = True (const), use -p for task
            if isinstance(args.standalone, str) and args.standalone is not True:
                task = args.standalone
            else:
                task = args.task
            if not task:
                run_parser.error("--standalone requires a task (pass it directly or use -p)")
            _run_async(run_standalone(args.config, task, working_dir))
        elif args.task:
            _run_async(run_once(args.config, args.task, working_dir))
        else:
            _run_async(repl(args.config, working_dir))


if __name__ == "__main__":
    main()
