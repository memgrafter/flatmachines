"""
Interpreter Machine — interpret a statement and add to INTERPRETATIONS.md.

Usage:
    python -m interpreter_machine.main "I would like to simplify the flatmachines interface."
    python -m interpreter_machine.main "What if state machines are the wrong abstraction?" -w /path/to/project
"""

import asyncio
import logging
import os
import signal
import sys
import termios
from pathlib import Path

from flatmachines import FlatMachine

from .hooks import InterpreterHooks

_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.getLogger().setLevel(_log_level)
for _name in ("flatagents", "flatmachines"):
    logging.getLogger(_name).setLevel(_log_level)

_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


# Module-level reference so the signal handler can cancel the subprocess.
_machine: FlatMachine | None = None


async def run(statement: str, working_dir: str):
    """Interpret a statement and update INTERPRETATIONS.md."""
    global _machine
    hooks = InterpreterHooks()

    machine = FlatMachine(
        config_file=str(_CONFIG_DIR / "machine.yml"),
        hooks=hooks,
    )
    _machine = machine

    result = await machine.execute(
        input={"statement": statement, "working_dir": working_dir}
    )

    print()
    print("=" * 60)
    print("INTERPRETATION COMPLETE")
    print("=" * 60)
    content = result.get("result") if isinstance(result, dict) else result
    if content:
        clean = str(content).replace("<<AGENT_EXIT>>", "").strip()
        print(clean)

    interp_path = os.path.join(working_dir, "INTERPRETATIONS.md")
    if os.path.exists(interp_path):
        print(f"\n📄 Updated: {interp_path}")
    else:
        print(f"\n⚠️  INTERPRETATIONS.md was not created at {interp_path}")

    return result


def main():
    # Simple arg parsing: first positional arg is the statement, -w for working dir
    args = sys.argv[1:]
    working_dir = os.getcwd()
    statement_parts = []

    i = 0
    while i < len(args):
        if args[i] in ("-w", "--working-dir") and i + 1 < len(args):
            working_dir = os.path.abspath(args[i + 1])
            i += 2
        elif args[i] in ("-h", "--help"):
            print(__doc__.strip())
            sys.exit(0)
        else:
            statement_parts.append(args[i])
            i += 1

    if not statement_parts:
        print("Usage: ./run.sh <statement> [-w <working-dir>]")
        print('Example: ./run.sh "I would like to simplify the flatmachines interface."')
        sys.exit(1)

    statement = " ".join(statement_parts)

    # Save terminal state so we can restore it no matter what the subprocess does.
    try:
        saved_termios = termios.tcgetattr(sys.stdin)
    except termios.error:
        saved_termios = None

    loop = asyncio.new_event_loop()
    main_task = loop.create_task(run(statement, working_dir))

    def _cancel(sig, frame):
        print("\n\nCancelling...")
        # Cancel any running adapter subprocess (claude-code, etc.)
        if _machine is not None:
            for executor in getattr(_machine, "_agents", {}).values():
                if hasattr(executor, "cancel"):
                    asyncio.ensure_future(executor.cancel(), loop=loop)
        main_task.cancel()

    signal.signal(signal.SIGINT, _cancel)

    try:
        loop.run_until_complete(main_task)
    except asyncio.CancelledError:
        print("Cancelled.")
        sys.exit(130)
    finally:
        loop.close()
        # Restore terminal state.
        if saved_termios is not None:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved_termios)
            except termios.error:
                pass


if __name__ == "__main__":
    main()
