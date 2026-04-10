"""
Interpreter machine display hooks.

Minimal terminal display for the interpretation process.
"""

from typing import Any, Dict, Optional

from flatmachines import MachineHooks


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m"


class InterpreterHooks(MachineHooks):
    """Display hooks for the interpreter machine."""

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if state_name == "interpret":
            stmt = context.get("statement", "")
            print(f"\n{'─' * 60}")
            print(f"  {_cyan('Interpreting')}: {_bold(stmt)}")
            print(f"{'─' * 60}")
        return context

    def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if state_name != "interpret" or not output:
            return output

        thread_id = context.get("thread_id", "")
        if thread_id:
            print(f"  {_dim(f'thread: {thread_id}')}")

        result = context.get("result", "")
        if isinstance(result, str) and result.strip():
            preview = result.strip().splitlines()[0][:180]
            print(f"  {_dim(preview)}")

        return output
