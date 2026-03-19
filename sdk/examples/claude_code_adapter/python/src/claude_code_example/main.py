"""
Claude Code Adapter Example — drive Claude Code CLI via FlatMachine.

Usage:
    python -m claude_code_example.main -p "add a /health endpoint"
    python -m claude_code_example.main -p "add a /health endpoint" --multi-state
    python -m claude_code_example.main -p "add a /health endpoint" --config machine_with_refs.yml
    python -m claude_code_example.main -p "add a /health endpoint" -w /path/to/project
"""

import argparse
import asyncio
import logging
import os
from pathlib import Path

from flatmachines import FlatMachine

from .hooks import ClaudeCodeHooks

_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.getLogger().setLevel(_log_level)
for _name in ("flatagents", "flatmachines"):
    logging.getLogger(_name).setLevel(_log_level)

_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


def _config_path(name: str) -> str:
    return str(_CONFIG_DIR / name)


async def run(
    task: str,
    working_dir: str,
    multi_state: bool = False,
    config_name: str | None = None,
):
    """Run a task via the Claude Code adapter."""
    hooks = ClaudeCodeHooks()

    if config_name:
        config_file = _config_path(config_name)
    elif multi_state:
        config_file = _config_path("machine_multi_state.yml")
    else:
        config_file = _config_path("machine.yml")

    machine = FlatMachine(
        config_file=config_file,
        hooks=hooks,
    )

    # Build input — multi-state and refs machines use "feature", single uses "task"
    uses_feature = multi_state or (config_name and "ref" in config_name)
    input_data = {"working_dir": working_dir}
    if uses_feature:
        input_data["feature"] = task
    else:
        input_data["task"] = task

    result = await machine.execute(input=input_data)

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    content = result.get("result") if isinstance(result, dict) else result
    if content:
        # Strip sentinel from display
        if content and "<<AGENT_EXIT>>" in str(content):
            content = str(content).replace("<<AGENT_EXIT>>", "").strip()
        print(content)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code adapter example — drive Claude Code CLI via FlatMachine"
    )
    parser.add_argument(
        "-p", "--print",
        metavar="TASK",
        dest="task",
        required=True,
        help="Task to execute",
    )
    parser.add_argument(
        "-w", "--working-dir",
        default=os.getcwd(),
        help="Working directory for Claude Code (default: cwd)",
    )
    parser.add_argument(
        "--multi-state",
        action="store_true",
        help="Use plan→implement→test multi-state machine",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        dest="config_name",
        help="Machine config filename from config/ (e.g., machine_with_refs.yml)",
    )
    args = parser.parse_args()

    asyncio.run(run(
        args.task,
        os.path.abspath(args.working_dir),
        args.multi_state,
        args.config_name,
    ))


if __name__ == "__main__":
    main()
