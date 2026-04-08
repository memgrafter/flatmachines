"""
FlatMachines interactive REPL.

Explore, inspect, validate, and run flatmachine configs interactively.
No LLM in the loop — the REPL itself is pure Python. LLMs are only
invoked when you execute a machine via `run`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .discovery import MachineIndex, MachineInfo

try:
    import readline

    _HISTORY_FILE = os.path.expanduser("~/.flatmachines_history")
    _HISTORY_LENGTH = 1000
except ImportError:
    readline = None  # type: ignore
    _HISTORY_FILE = None
    _HISTORY_LENGTH = 0


# --- ANSI helpers ---

def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m"


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


# --- Execution history ---

@dataclass
class ExecutionRecord:
    name: str
    path: str
    input: Dict[str, Any]
    duration_s: float = 0.0
    success: bool = False
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# --- REPL ---

class FlatMachinesREPL:
    """Interactive REPL for exploring and running flatmachines."""

    def __init__(
        self,
        project_root: Optional[str] = None,
        extra_paths: Optional[List[str]] = None,
        working_dir: Optional[str] = None,
    ):
        self._index = MachineIndex(
            project_root=project_root,
            extra_paths=extra_paths,
        )
        self._working_dir = working_dir or os.getcwd()
        self._history: List[ExecutionRecord] = []
        self._last_bus_snapshot: Optional[Dict[str, Any]] = None
        self._interrupt_count = 0

        # Command dispatch table
        self._last_backend: Optional[Any] = None
        self._last_hooks: Optional[Any] = None
        self._commands = {
            "list": self._cmd_list,
            "ls": self._cmd_list,
            "inspect": self._cmd_inspect,
            "info": self._cmd_inspect,
            "validate": self._cmd_validate,
            "context": self._cmd_context,
            "run": self._cmd_run,
            "history": self._cmd_history,
            "bus": self._cmd_bus,
            "stats": self._cmd_stats,
            "save": self._cmd_save,
            "improve": self._cmd_improve,
            "experiment": self._cmd_experiment,
            "help": self._cmd_help,
            "?": self._cmd_help,
        }

    def _load_history(self) -> None:
        """Load command history from disk."""
        if readline is not None and _HISTORY_FILE:
            try:
                readline.read_history_file(_HISTORY_FILE)
                readline.set_history_length(_HISTORY_LENGTH)
            except (FileNotFoundError, OSError):
                pass
        # Set up tab completion
        if readline is not None:
            readline.set_completer(self._completer)
            readline.parse_and_bind("tab: complete")
            readline.set_completer_delims(" ")

    def _completer(self, text: str, state: int) -> Optional[str]:
        """Tab-completion for REPL commands and machine names.

        First word: complete command names.
        Second word (after inspect/validate/context/run): complete machine names.
        """
        try:
            buffer = readline.get_line_buffer() if readline else ""
            parts = buffer.split()

            if not parts or (len(parts) == 1 and not buffer.endswith(" ")):
                # Complete command names
                prefix = text.lower()
                all_cmds = list(self._commands.keys()) + ["quit", "exit"]
                matches = [c for c in all_cmds if c.startswith(prefix)]
            else:
                # Complete machine names for commands that take them
                cmd = parts[0].lower()
                if cmd in ("inspect", "info", "validate", "context", "run"):
                    prefix = text.lower()
                    machines = self._index.list_all()
                    matches = [m.name for m in machines if m.name.lower().startswith(prefix)]
                else:
                    matches = []

            if state < len(matches):
                return matches[state]
            return None
        except Exception:
            return None

    def _save_history(self) -> None:
        """Save command history to disk."""
        if readline is not None and _HISTORY_FILE:
            try:
                readline.set_history_length(_HISTORY_LENGTH)
                readline.write_history_file(_HISTORY_FILE)
            except OSError:
                pass

    async def start(self) -> None:
        """Run the REPL loop."""
        self._load_history()
        self._print_banner()

        while True:
            try:
                raw = input("fm> ").strip()
                self._interrupt_count = 0
            except KeyboardInterrupt:
                self._interrupt_count += 1
                if self._interrupt_count >= 2:
                    print()
                    self._save_history()
                    break
                print(f"\n{_dim('(ctrl-c again to quit)')}")
                continue
            except EOFError:
                print()
                self._save_history()
                break

            if not raw:
                continue

            # Parse command and args
            try:
                parts = shlex.split(raw)
            except ValueError:
                parts = raw.split()

            cmd = parts[0].lower()
            args = parts[1:]

            if cmd in ("quit", "exit", "q"):
                self._save_history()
                break

            handler = self._commands.get(cmd)
            if handler is None:
                # Try prefix match
                matches = [k for k in self._commands if k.startswith(cmd)]
                if len(matches) == 1:
                    handler = self._commands[matches[0]]
                else:
                    print(f"  Unknown command: {cmd}. Type 'help' for commands.")
                    continue

            try:
                result = handler(args)
                if asyncio.iscoroutine(result):
                    await result
            except KeyboardInterrupt:
                print(f"\n{_dim('Interrupted.')}")
            except Exception as e:
                print(f"  {_red(f'Error: {e}')}")

            print()

    def _print_banner(self) -> None:
        """Print REPL welcome banner."""
        try:
            from flatmachines_cli import __version__
            version = __version__
        except Exception:
            version = "?"

        n = self._index.count
        machines_text = f"{n} example{'s' if n != 1 else ''}" if n else "no examples"
        print(f"\n  {_bold('flatmachines')} {_dim(f'v{version}')} — {machines_text} found")
        print(f"  {_dim('type help for commands, list to see machines')}")
        print()

    # --- Commands ---

    def _cmd_help(self, args: List[str]) -> None:
        """Show available commands."""
        print(f"""
  {_bold('Commands')}

    {_cyan('list')}                       Show discovered machines
    {_cyan('inspect')} <name|path>        Show machine structure (states, transitions, agents)
    {_cyan('validate')} <name|path>       Run schema validation
    {_cyan('context')} <name|path>        Show context template and required inputs
    {_cyan('run')} <name|path> [json]     Execute a machine (prompts for input if needed)
    {_cyan('history')}                    Show recent executions
    {_cyan('bus')}                        Dump last DataBus snapshot
    {_cyan('stats')}                      Show processor/hook performance stats
    {_cyan('save')} [path]                Save last bus snapshot to JSON file
    {_cyan('improve')}                    Run self-improvement (or: improve status, improve validate)
    {_cyan('experiment')} [cmd] [path]    Experiment tracking (load, summary)
    {_cyan('help')}                       This message
    {_cyan('quit')}                       Exit""")

    def _cmd_list(self, args: List[str]) -> None:
        """List discovered machines."""
        machines = self._index.list_all()
        if not machines:
            print("  No machines found.")
            return

        # Calculate column widths
        name_w = max(len(m.name) for m in machines)
        name_w = max(name_w, 4)

        print(f"  {'Name':<{name_w}}  {'States':>6}  Description")
        print(f"  {'─' * name_w}  {'─' * 6}  {'─' * 40}")

        for m in machines:
            desc = m.description if m.description else _dim("—")
            features = []
            if m.has_machines:
                features.append("machines")
            if m.has_agents:
                features.append("agents")
            feat_str = f" {_dim('[' + ', '.join(features) + ']')}" if features else ""

            print(f"  {_cyan(m.name):<{name_w + 9}}  {m.state_count:>6}  {desc}{feat_str}")

    def _cmd_inspect(self, args: List[str]) -> None:
        """Inspect a machine config."""
        if not args:
            print("  Usage: inspect <name|path>")
            return

        info = self._resolve(args[0])
        if not info:
            return

        from .inspector import inspect_machine
        print(inspect_machine(info.path))

    def _cmd_validate(self, args: List[str]) -> None:
        """Validate a machine config."""
        if not args:
            print("  Usage: validate <name|path>")
            return

        info = self._resolve(args[0])
        if not info:
            return

        from .inspector import validate_machine
        print(f"\n  Validating {_bold(info.name)} ...")
        print(validate_machine(info.path))

    def _cmd_context(self, args: List[str]) -> None:
        """Show context template."""
        if not args:
            print("  Usage: context <name|path>")
            return

        info = self._resolve(args[0])
        if not info:
            return

        from .inspector import show_context
        print(show_context(info.path))

    async def _cmd_run(self, args: List[str]) -> None:
        """Execute a machine."""
        if not args:
            print("  Usage: run <name|path> [json_input]")
            return

        info = self._resolve(args[0])
        if not info:
            return

        # Parse or prompt for input
        input_data = self._get_input(info, args[1:])
        if input_data is None:
            return  # user cancelled

        print(f"\n  Running {_bold(info.name)} ...")
        print(f"  {_dim(f'input: {json.dumps(input_data)}')}")
        print()

        record = ExecutionRecord(
            name=info.name,
            path=info.path,
            input=input_data,
        )

        t0 = time.monotonic()
        try:
            result = await self._execute_machine(info.path, input_data)
            record.duration_s = time.monotonic() - t0
            record.success = True
            record.output = result
        except KeyboardInterrupt:
            record.duration_s = time.monotonic() - t0
            record.error = "Interrupted"
            print(f"\n  {_yellow('Interrupted')}")
        except Exception as e:
            record.duration_s = time.monotonic() - t0
            record.error = str(e)
            print(f"\n  {_red(f'Error: {e}')}")

        self._history.append(record)

        if record.success:
            print(f"\n  {_green('✓')} Completed in {record.duration_s:.1f}s")
            if record.output:
                out_str = json.dumps(record.output, indent=2, default=str)
                print(f"  {_dim(out_str)}")

    def _cmd_history(self, args: List[str]) -> None:
        """Show execution history."""
        if not self._history:
            print("  No executions yet.")
            return

        for i, rec in enumerate(self._history, 1):
            status = _green("✓") if rec.success else _red("✗")
            duration = f"{rec.duration_s:.1f}s"
            error_msg = f" — {rec.error}" if rec.error else ""
            print(f"  {i}. {status} {_bold(rec.name)} ({duration}){_dim(error_msg)}")

    def _cmd_bus(self, args: List[str]) -> None:
        """Dump last DataBus snapshot."""
        if self._last_bus_snapshot is None:
            print("  No bus data yet. Run a machine first.")
            return

        print(json.dumps(self._last_bus_snapshot, indent=2, default=str))

    def _cmd_stats(self, args: List[str]) -> None:
        """Show performance stats from last execution."""
        if self._last_backend is None:
            print("  No execution data yet. Run a machine first.")
            return

        # Backend health check
        print(f"\n  {_bold('Backend Health')}")
        health = self._last_backend.health_check()
        print(f"    Processors: {health['processor_count']}")
        print(f"    Bus slots:  {health['bus_slots']}")

        # Processor stats
        if health['processors']:
            print(f"\n  {_bold('Processor Stats')}")
            print(f"    {'Name':<12} {'Processed':>10} {'Dropped':>8} {'QueueHWM':>9}")
            print(f"    {'─' * 12} {'─' * 10} {'─' * 8} {'���' * 9}")
            for p in health['processors']:
                print(f"    {p['name']:<12} {p['events_processed']:>10} {p['events_dropped']:>8} {p['queue_hwm']:>9}")

        # Hook timing stats
        if self._last_hooks and hasattr(self._last_hooks, 'timing_stats'):
            timing = self._last_hooks.timing_stats
            if timing:
                print(f"\n  {_bold('Hook Timings')}")
                print(f"    {'Hook':<20} {'Calls':>6} {'Total(ms)':>10} {'Avg(ms)':>8}")
                print(f"    {'─' * 20} {'─' * 6} {'─' * 10} {'─' * 8}")
                for name, st in sorted(timing.items()):
                    print(f"    {name:<20} {st['calls']:>6} {st['total_ms']:>10.3f} {st['avg_ms']:>8.3f}")

    async def _cmd_improve(self, args: List[str]) -> None:
        """Run self-improvement or show status."""
        from .improve import validate_self_improve_config

        if not args:
            # Default: run the improvement loop
            args = ["run"]

        subcmd = args[0]

        if subcmd == "run":
            # Run the self-improvement loop — same as `flatmachines improve . --git --run`
            target = args[1] if len(args) >= 2 else self._working_dir
            target = os.path.abspath(target)
            generations = 0
            parent_selection = "model"

            # Parse simple flags
            i = 1
            while i < len(args):
                if args[i] in ("-g", "--generations") and i + 1 < len(args):
                    generations = int(args[i + 1])
                    i += 2
                elif args[i] in ("--parent-selection",) and i + 1 < len(args):
                    parent_selection = args[i + 1]
                    i += 2
                else:
                    i += 1

            from .main import run_once
            from pathlib import Path

            config = str(Path(__file__).parent.parent / "config" / "self_improve.yml")

            has_program = os.path.isfile(os.path.join(target, "program.md"))
            print(f"\n  {_bold('Self-Improvement')}")
            print(f"  Target:      {target}")
            print(f"  program.md:  {'found' if has_program else 'not found (agent will explore)'}")
            print(f"  Generations: {'unlimited' if generations == 0 else generations}")
            if generations == 0 or generations > 1:
                print(f"  Parent sel:  {parent_selection}")
            print()

            result = await run_once(
                config_file=config,
                task="",
                working_dir=target,
                human_review=False,
                auto_approve=True,
                max_generations=generations,
                parent_selection=parent_selection,
                git_enabled=True,
            )

            if result:
                print()
                print(f"  {_bold('Result:')}")
                for k, v in result.items():
                    print(f"    {k}: {v}")

        elif subcmd == "status":
            result = validate_self_improve_config()
            if result["valid"]:
                info = result["info"]
                print(f"\n  {_green('✓')} Self-improvement config: {_bold(info.get('name', '?'))}")
                print(f"    States:   {info.get('state_count', '?')}")
                print(f"    Agents:   {info.get('agent_count', '?')}")
                print(f"    Profiles: {'yes' if info.get('has_profiles') else 'no'}")
                if result["warnings"]:
                    print()
                    for w in result["warnings"]:
                        print(f"    ⚠ {w}")
            else:
                print(f"\n  {_red('✗')} Config invalid:")
                for err in result["errors"]:
                    print(f"    {_red(err)}")

        elif subcmd == "validate":
            config_path = args[1] if len(args) >= 2 else None
            result = validate_self_improve_config(config_path)
            if result["valid"]:
                print(f"  {_green('✓')} Valid")
                for k, v in result["info"].items():
                    if k not in ("errors", "warnings"):
                        print(f"    {k}: {v}")
            else:
                print(f"  {_red('✗')} Invalid:")
                for err in result["errors"]:
                    print(f"    {_red(err)}")
            if result["warnings"]:
                for w in result["warnings"]:
                    print(f"    ⚠ {w}")

        else:
            print(f"  Unknown subcommand: {subcmd}")
            print(f"  Try: improve | improve run [dir] | improve status | improve validate")

    def _cmd_experiment(self, args: List[str]) -> None:
        """Show experiment tracking status."""
        from .experiment import ExperimentTracker
        if not args:
            print(f"\n  {_bold('Experiment Tracking')}")
            print(f"  {_dim('Load an experiment log:')}")
            print(f"    experiment load <path.jsonl>")
            print(f"  {_dim('Show summary:')}")
            print(f"    experiment summary <path.jsonl>")
            return

        subcmd = args[0]
        if subcmd in ("load", "summary") and len(args) >= 2:
            path = args[1]
            try:
                tracker = ExperimentTracker.from_file(path)
                summary = tracker.summary()
                print(f"\n  {_bold(summary['name'])}")
                print(f"    Metric: {summary['metric_name']} ({summary['direction']})")
                print(f"    Experiments: {summary['total_experiments']}")
                print(f"    Kept: {_green(str(summary['kept']))}")
                print(f"    Discarded: {summary['discarded']}")
                print(f"    Crashed: {_red(str(summary['crashed']))}")
                best = summary['best_metric']
                if best is not None:
                    print(f"    Best: {_bold(str(best))}")
            except FileNotFoundError:
                print(f"  {_red(f'File not found: {path}')}")
            except Exception as e:
                print(f"  {_red(f'Error: {e}')}")
        else:
            print(f"  Usage: experiment [load|summary] <path.jsonl>")

    def _cmd_save(self, args: List[str]) -> None:
        """Save last bus snapshot to a JSON file."""
        if self._last_bus_snapshot is None:
            print("  No bus data yet. Run a machine first.")
            return

        path = args[0] if args else "bus_snapshot.json"
        try:
            import json as _json
            from pathlib import Path
            Path(path).write_text(
                _json.dumps(self._last_bus_snapshot, indent=2, default=str)
            )
            print(f"  {_green('✓')} Saved to {_bold(path)}")
        except Exception as e:
            print(f"  {_red(f'Error saving: {e}')}")

    # --- Helpers ---

    def _resolve(self, name_or_path: str) -> Optional[MachineInfo]:
        """Resolve a machine name/path, printing errors on failure."""
        info = self._index.resolve(name_or_path)
        if info:
            return info

        # Check for ambiguous prefix
        matches = self._index.prefix_matches(name_or_path)
        if len(matches) > 1:
            names = ", ".join(m.name for m in matches)
            print(f"  Ambiguous: {names}")
        else:
            print(f"  Not found: {name_or_path}")
            print(f"  {_dim('Use list to see available machines, or pass a file path')}")
        return None

    def _get_input(
        self,
        info: MachineInfo,
        extra_args: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Get machine input — from args JSON or interactive prompts.

        Returns None if user cancels.
        """
        # If JSON provided as arg, use it
        if extra_args:
            json_str = " ".join(extra_args)
            try:
                data = json.loads(json_str)
                if isinstance(data, dict):
                    return data
                print(f"  {_red('Input must be a JSON object')}")
                return None
            except json.JSONDecodeError as e:
                print(f"  {_red(f'Invalid JSON: {e}')}")
                return None

        # Load config to find required input keys
        from .inspector import load_config, _classify_context
        config = load_config(info.path)
        context = config.get("data", {}).get("context", {})
        input_keys, _ = _classify_context(context)

        if not input_keys:
            return {}

        # Prompt for each required key
        print(f"  {_dim('Enter values (empty to skip, ctrl-c to cancel):')}")
        result = {}
        try:
            for key in input_keys:
                default_hint = ""
                val = context.get(key)
                if isinstance(val, str) and "default(" in val:
                    # Extract default from Jinja template
                    import re
                    m = re.search(r"default\(([^)]+)\)", val)
                    if m:
                        default_hint = f" [{m.group(1).strip()}]"

                raw = input(f"    {_bold(key)}{_dim(default_hint)}: ").strip()
                if raw:
                    # Try to parse as JSON value (numbers, bools, etc.)
                    try:
                        result[key] = json.loads(raw)
                    except json.JSONDecodeError:
                        result[key] = raw
        except (KeyboardInterrupt, EOFError):
            print()
            return None

        return result

    async def _execute_machine(
        self,
        config_path: str,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a machine through the CLI backend pipeline."""
        import logging
        import warnings

        # Suppress noisy warnings during execution
        warnings.filterwarnings("ignore", message=".*validation.*")
        warnings.filterwarnings("ignore", message=".*Flatmachine.*")
        warnings.filterwarnings("ignore", message=".*Flatagent.*")

        from flatmachines import FlatMachine
        from .backend import CLIBackend
        from .bus import DataBus
        from .frontend import TerminalFrontend
        from .hooks import CLIHooks
        from .main import _try_find_tool_provider

        bus = DataBus()
        frontend = TerminalFrontend(auto_approve=False)
        backend = CLIBackend(bus=bus, frontend=frontend)
        backend.set_frontend(frontend)

        tool_provider_factory = _try_find_tool_provider(self._working_dir)
        hooks = CLIHooks(backend, tool_provider_factory=tool_provider_factory)

        machine = FlatMachine(
            config_file=config_path,
            hooks=hooks,
        )

        result = await backend.run_machine(machine, input=input_data)

        # Capture bus snapshot and references for debug/stats
        self._last_bus_snapshot = bus.snapshot()
        self._last_backend = backend
        self._last_hooks = hooks

        return result


async def interactive_repl(
    project_root: Optional[str] = None,
    extra_paths: Optional[List[str]] = None,
    working_dir: Optional[str] = None,
) -> None:
    """Entry point for the interactive REPL."""
    repl = FlatMachinesREPL(
        project_root=project_root,
        extra_paths=extra_paths,
        working_dir=working_dir,
    )
    await repl.start()
