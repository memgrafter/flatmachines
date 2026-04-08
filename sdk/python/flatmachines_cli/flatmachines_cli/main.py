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


# Debug by default for development
_log_level = os.environ.get("LOG_LEVEL", "DEBUG").upper()
logging.getLogger().setLevel(_log_level)
for _name in ("flatagents", "flatmachines", "flatmachines_cli"):
    logging.getLogger(_name).setLevel(_log_level)
# Keep LiteLLM quiet
logging.getLogger("LiteLLM").setLevel("WARNING")


def _resolve_config(config_path: str) -> str:
    """Resolve config path (absolute or relative to cwd)."""
    p = Path(config_path)
    if p.is_absolute():
        return str(p)
    return str(Path.cwd() / p)


def _make_self_improve_handler():
    """Create a lazy-init action handler for self-improve actions.

    On first call, creates SelfImprover from the machine context.
    Subsequent calls reuse the same instance.
    """
    from .improve import SelfImprover, ConvergedSelfImproveHooks

    state = {"hooks": None}

    def handler(action_name, context):
        if state["hooks"] is None:
            # Auto-enable isolation when max_generations > 1
            max_gen = context.get("max_generations", 1)
            if isinstance(max_gen, str):
                try:
                    max_gen = int(max_gen)
                except (ValueError, TypeError):
                    max_gen = 1
            enable_isolation = max_gen > 1

            improver = SelfImprover(
                target_dir=context.get("working_dir", "."),
                working_dir=context.get("working_dir", os.getcwd()),
                git_enabled=context.get("git_enabled", False),
                enable_isolation=enable_isolation,
            )
            state["hooks"] = ConvergedSelfImproveHooks(improver)

        return state["hooks"].on_action(action_name, context)

    return handler


# All self-improve actions (simple + converged)
_SELF_IMPROVE_ACTIONS = {
    # Original simple actions
    "evaluate_improvement", "archive_result", "revert_changes",
    # Converged outer loop
    "prepare_parent_selection_context", "apply_parent_selection",
    "select_parent_from_archive", "create_isolated_worktree",
    "extract_diff_and_archive", "cleanup_isolated_worktree",
    "write_archive_summary",
    # Converged inner loop
    "run_checks", "evaluate_with_staging",
    "commit_inner_improvement", "revert_inner_changes",
}


def _register_self_improve_actions(backend, config_file: str) -> None:
    """Register self-improve actions if the machine config uses them."""
    import yaml

    try:
        with open(config_file) as f:
            config = yaml.safe_load(f)
    except Exception:
        return

    states = config.get("data", {}).get("states", {})
    used = {s.get("action") for s in states.values()} & _SELF_IMPROVE_ACTIONS

    if not used:
        return

    handler = _make_self_improve_handler()
    for action_name in used:
        backend.register_action(action_name, handler)


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
    **extra_input,
) -> Dict[str, Any]:
    """
    Run a single task through a flatmachine with the CLI pipeline.

    This is the core execution function. It wires up:
    backend (bus + processors) ← hooks ← flatmachine → hooks → backend → frontend

    Extra keyword args are passed as machine input fields.
    """
    bus = DataBus()
    frontend = TerminalFrontend(auto_approve=auto_approve or not human_review)
    backend = CLIBackend(bus=bus, frontend=frontend)
    backend.set_frontend(frontend)

    tool_provider_factory = _try_find_tool_provider(working_dir)
    hooks = CLIHooks(backend, tool_provider_factory=tool_provider_factory)

    resolved_config = _resolve_config(config_file)
    _register_self_improve_actions(backend, resolved_config)

    machine_input = {"task": task, "working_dir": working_dir, **extra_input}

    machine = FlatMachine(
        config_file=resolved_config,
        hooks=hooks,
    )

    result = await backend.run_machine(
        machine,
        input=machine_input,
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


class _JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production use."""

    def format(self, record: logging.LogRecord) -> str:
        import json as _json
        import time as _time

        log_entry = {
            "timestamp": _time.strftime(
                "%Y-%m-%dT%H:%M:%S", _time.gmtime(record.created)
            ) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }
        return _json.dumps(log_entry, default=str)


def _configure_json_logging(log_level: Optional[str] = None) -> None:
    """Set up structured JSON logging on all relevant loggers."""
    level = getattr(logging, log_level) if log_level else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    for name in ("flatagents", "flatmachines", "flatmachines_cli", "LiteLLM"):
        logging.getLogger(name).setLevel(level)


def _run_async(coro):
    """Run an async coroutine with graceful signal handling.

    Catches KeyboardInterrupt and exits cleanly instead of printing
    a traceback. Returns the coroutine result.
    """
    try:
        return asyncio.run(coro)
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
        "--log-format",
        default="text",
        choices=["text", "json"],
        help="Log output format: text (default) or json (structured)",
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
        nargs="?",
        default=None,
        help="Machine name or path to YAML config (default: built-in self_improve.yml)",
    )
    validate_parser.add_argument(
        "--self-improve", "-s",
        action="store_true",
        default=False,
        help="Use self-improvement validator (checks agents, profiles, transitions)",
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

    # --- improve command ---
    improve_parser = subparsers.add_parser(
        "improve",
        help="Run self-improvement loop on a target directory",
    )
    improve_parser.add_argument(
        "target_dir",
        nargs="?",
        default=".",
        help="Directory containing the code to improve (default: cwd)",
    )
    improve_parser.add_argument(
        "--config", "-c",
        default=None,
        help="Machine config for the improvement loop (default: built-in self_improve.yml)",
    )
    improve_parser.add_argument(
        "--run", "-r",
        action="store_true",
        default=False,
        help="Run the self-improvement loop with LLM agent",
    )
    improve_parser.add_argument(
        "--git",
        action="store_true",
        default=False,
        help="Enable git integration (auto-commit on keep, auto-revert on discard)",
    )
    improve_parser.add_argument(
        "--generations", "-g",
        type=int,
        default=0,
        help="Number of generations (0 = unlimited, 1 = single pass, >1 = tree search with worktree isolation)",
    )
    improve_parser.add_argument(
        "--parent-selection",
        default="model",
        choices=["model", "best", "score_child_prop", "random"],
        help="Parent selection strategy for multi-generation search (default: model)",
    )
    improve_parser.add_argument(
        "--init",
        action="store_true",
        default=False,
        help="Initialize self-improvement configs in target directory",
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
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Validate config and show what would run without executing",
    )

    args = parser.parse_args()
    working_dir = os.path.abspath(args.working_dir)

    # Apply logging configuration
    if args.log_format == "json":
        _configure_json_logging(args.log_level)
    elif args.log_level:
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

    if args.command in ("inspect", "context"):
        from .inspector import inspect_machine, show_context

        resolved = _resolve_machine_path(args.config, working_dir)
        if not resolved:
            print(f"Machine not found: {args.config}")
            sys.exit(1)

        handlers = {
            "inspect": inspect_machine,
            "context": show_context,
        }
        print(handlers[args.command](resolved))
        return

    if args.command == "validate":
        # Self-improvement validator or standard validator
        if args.self_improve or args.config is None:
            from .improve import validate_self_improve_config

            config_path = None
            if args.config:
                resolved = _resolve_machine_path(args.config, working_dir)
                if resolved:
                    config_path = resolved
                else:
                    config_path = args.config  # Let validator handle the error

            result = validate_self_improve_config(config_path)

            # Pretty-print results
            if result["valid"]:
                info = result["info"]
                print(f"  ✓ Valid self-improvement config: {info.get('name', '?')}")
                print(f"    States: {info.get('state_count', '?')}")
                print(f"    Agents: {info.get('agent_count', '?')}")
                print(f"    Profiles: {'yes' if info.get('has_profiles') else 'no'}")
            else:
                print(f"  ✗ Invalid config")
                for err in result["errors"]:
                    print(f"    ✗ {err}")
                sys.exit(1)

            if result["warnings"]:
                print()
                for warn in result["warnings"]:
                    print(f"    ⚠ {warn}")

            sys.exit(0)
        else:
            from .inspector import validate_machine

            resolved = _resolve_machine_path(args.config, working_dir)
            if not resolved:
                print(f"Machine not found: {args.config}")
                sys.exit(1)
            print(validate_machine(resolved))
            return

    if args.command == "improve" and getattr(args, 'init', False):
        from .improve import scaffold_self_improve

        target = os.path.abspath(args.target_dir)
        created = scaffold_self_improve(target)
        if created:
            print("Self-improvement configs initialized:")
            for f in created:
                print(f"  ✓ {f}")
            print()
            print("Next steps:")
            print(f"  1. Edit profiles.yml to set your LLM provider")
            print(f"  2. Edit program.md to describe optimization goals")
            print(f"  3. Run: flatmachines improve {args.target_dir} --run")
        else:
            print("  All configs already exist — nothing to create.")
        return

    if args.command == "improve":
        target = os.path.abspath(args.target_dir)

        # Show configuration
        has_program = os.path.isfile(os.path.join(target, "program.md"))
        print(f"Self-improvement loop")
        print(f"  Target:    {target}")
        print(f"  program.md: {'found' if has_program else 'not found (agent will explore)'}")
        print(f"  Generations: {'unlimited' if args.generations == 0 else args.generations}")
        if args.generations > 1:
            print(f"  Parent sel: {args.parent_selection}")
            print(f"  Isolation:  worktree (auto-enabled)")
        print(f"  Git:       {'enabled' if args.git else 'disabled'}")
        print()

        if args.run:
            # Resolve machine config
            config = args.config
            if not config or not os.path.isfile(config):
                config = str(
                    Path(__file__).parent.parent / "config" / "self_improve.yml"
                )

            print(f"  Config:    {config}")
            print()
            print("Running self-improvement via FlatMachine...")
            print()

            result = _run_async(run_once(
                config_file=config,
                task="",
                working_dir=target,
                human_review=False,
                auto_approve=True,
                max_generations=args.generations,
                parent_selection=args.parent_selection,
                git_enabled=args.git,
            ))

            if result:
                print()
                print("Result:")
                for k, v in result.items():
                    print(f"  {k}: {v}")

            sys.exit(0)
        else:
            print("Use --run to start the self-improvement loop.")
        return

    if args.command == "run":
        # Validate config file exists
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        if not config_path.is_file():
            run_parser.error(f"Config file not found: {args.config}")

        if getattr(args, 'dry_run', False):
            from .inspector import inspect_machine, validate_machine, show_context
            config_str = str(config_path)
            print("=== Dry Run ===")
            print(f"Config: {config_str}")
            print()
            print("--- Validation ---")
            print(validate_machine(config_str))
            print()
            print("--- Structure ---")
            print(inspect_machine(config_str))
            print()
            print("--- Context ---")
            print(show_context(config_str))
            return

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
