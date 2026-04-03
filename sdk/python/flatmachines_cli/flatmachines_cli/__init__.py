"""
flatmachines-cli — Branded CLI for flatmachines with async backend/frontend pipeline.

Architecture:
    flatmachines hooks → events → processors → DataBus (slots) → frontend

Backend (permanent):
    - DataBus: UDP-like latest-value data slots
    - Processors: async tasks that aggregate events into UI-ready data
    - CLIHooks: bridge from flatmachines MachineHooks to event pipeline
    - CLIBackend: orchestrates processors, bus, and frontend

Frontend (temporary, will be replaced by Rust):
    - Frontend: abstract protocol for any frontend implementation
    - TerminalFrontend: simple line-based terminal output

The backend/frontend boundary is the DataBus.snapshot() dict — a plain
dict that serializes cleanly to JSON/msgpack for future IPC with Rust.
"""

__version__ = "2.5.0"

from .bus import DataBus, Slot, SlotValue
from .events import (
    MACHINE_START,
    MACHINE_END,
    STATE_ENTER,
    STATE_EXIT,
    TRANSITION,
    TOOL_CALLS,
    TOOL_RESULT,
    ACTION,
    ERROR,
)
from .processors import (
    Processor,
    StatusProcessor,
    TokenProcessor,
    ToolProcessor,
    ContentProcessor,
    ErrorProcessor,
    default_processors,
)
from .hooks import CLIHooks
from .backend import CLIBackend
from .protocol import Frontend, ActionHandler
from .frontend import TerminalFrontend
from .discovery import MachineIndex, MachineInfo, discover_examples
from .inspector import inspect_machine, validate_machine, show_context
from .repl import FlatMachinesREPL, interactive_repl

__all__ = [
    "__version__",
    # Bus
    "DataBus",
    "Slot",
    "SlotValue",
    # Event types
    "MACHINE_START",
    "MACHINE_END",
    "STATE_ENTER",
    "STATE_EXIT",
    "TRANSITION",
    "TOOL_CALLS",
    "TOOL_RESULT",
    "ACTION",
    "ERROR",
    # Processors
    "Processor",
    "StatusProcessor",
    "TokenProcessor",
    "ToolProcessor",
    "ContentProcessor",
    "ErrorProcessor",
    "default_processors",
    # Backend
    "CLIBackend",
    "CLIHooks",
    # Frontend protocol
    "Frontend",
    "ActionHandler",
    # Terminal frontend
    "TerminalFrontend",
    # Discovery & inspection
    "MachineIndex",
    "MachineInfo",
    "discover_examples",
    "inspect_machine",
    "validate_machine",
    "show_context",
    # REPL
    "FlatMachinesREPL",
    "interactive_repl",
]
