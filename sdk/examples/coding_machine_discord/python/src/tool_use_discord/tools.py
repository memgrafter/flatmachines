"""
CLI tool implementations: read, bash, write, edit.

Same tools as pi-mono defaults. All paths are resolved relative to the
configured working directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flatagents.tools import ToolProvider, ToolResult

MAX_LINES = 2000
MAX_BYTES = 50 * 1024  # 50KB


# ---------------------------------------------------------------------------
# Truncation helpers
# ---------------------------------------------------------------------------

def _truncate_head(content: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES):
    """Keep first N lines/bytes. For file reads."""
    lines = content.split("\n")
    total_lines = len(lines)
    total_bytes = len(content.encode("utf-8"))

    if total_lines <= max_lines and total_bytes <= max_bytes:
        return content, False, total_lines

    output = []
    byte_count = 0
    for i, line in enumerate(lines):
        if i >= max_lines:
            break
        line_bytes = len(line.encode("utf-8")) + (1 if i > 0 else 0)
        if byte_count + line_bytes > max_bytes:
            break
        output.append(line)
        byte_count += line_bytes

    return "\n".join(output), True, total_lines


def _truncate_tail(content: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES):
    """Keep last N lines/bytes. For bash output."""
    lines = content.split("\n")
    total_lines = len(lines)
    total_bytes = len(content.encode("utf-8"))

    if total_lines <= max_lines and total_bytes <= max_bytes:
        return content, False, total_lines

    output = []
    byte_count = 0
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        line_bytes = len(line.encode("utf-8")) + (1 if output else 0)
        if byte_count + line_bytes > max_bytes:
            break
        if len(output) >= max_lines:
            break
        output.insert(0, line)
        byte_count += line_bytes

    return "\n".join(output), True, total_lines


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def tool_read(working_dir: str, _id: str, args: Dict[str, Any]) -> ToolResult:
    """Read file contents with optional offset/limit."""
    path = args.get("path", "")
    offset = args.get("offset")
    limit = args.get("limit")

    try:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(working_dir) / p

        if not p.exists():
            return ToolResult(content=f"File not found: {path}", is_error=True)
        if not p.is_file():
            return ToolResult(content=f"Not a file: {path}", is_error=True)

        text = p.read_text(errors="replace")
        all_lines = text.split("\n")
        total_lines = len(all_lines)

        start = 0
        if offset is not None:
            start = max(0, int(offset) - 1)
            if start >= total_lines:
                return ToolResult(
                    content=f"Offset {offset} beyond end of file ({total_lines} lines)",
                    is_error=True,
                )

        selected = all_lines[start:]
        if limit is not None:
            selected = selected[: int(limit)]

        content = "\n".join(selected)
        truncated, was_truncated, _ = _truncate_head(content)

        if was_truncated:
            shown = len(truncated.split("\n"))
            end_line = start + shown
            truncated += (
                f"\n\n[Showing lines {start + 1}-{end_line} of {total_lines}. "
                f"Use offset={end_line + 1} to continue]"
            )
        elif limit is not None:
            shown = len(selected)
            end_line = start + shown
            remaining = total_lines - end_line
            if remaining > 0:
                truncated += (
                    f"\n\n[{remaining} more lines in file. "
                    f"Use offset={end_line + 1} to continue]"
                )

        return ToolResult(content=truncated)
    except Exception as e:
        return ToolResult(content=f"Error reading {path}: {e}", is_error=True)


async def tool_bash(working_dir: str, _id: str, args: Dict[str, Any]) -> ToolResult:
    """Execute a bash command, return stdout+stderr."""
    command = args.get("command", "")
    timeout = args.get("timeout", 30)

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
        )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += "\n"
            output += result.stderr
        if not output:
            output = "(no output)"

        truncated, was_truncated, total_lines = _truncate_tail(output)

        if was_truncated:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", prefix="cli-bash-", suffix=".log", delete=False
            )
            tmp.write(output)
            tmp.close()
            output_lines = len(truncated.split("\n"))
            start_line = total_lines - output_lines + 1
            truncated += (
                f"\n\n[Showing lines {start_line}-{total_lines} of {total_lines}. "
                f"Full output: {tmp.name}]"
            )
            output = truncated
        else:
            output = truncated

        if result.returncode != 0:
            return ToolResult(
                content=f"{output}\n\nCommand exited with code {result.returncode}",
                is_error=True,
            )
        return ToolResult(content=output)
    except subprocess.TimeoutExpired:
        return ToolResult(content=f"Command timed out after {timeout}s", is_error=True)
    except Exception as e:
        return ToolResult(content=f"Error executing command: {e}", is_error=True)


async def tool_write(working_dir: str, _id: str, args: Dict[str, Any]) -> ToolResult:
    """Write content to a file. Creates parent dirs."""
    path = args.get("path", "")
    content = args.get("content", "")

    try:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(working_dir) / p

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return ToolResult(content=f"Successfully wrote {len(content)} bytes to {p}")
    except Exception as e:
        return ToolResult(content=f"Error writing {path}: {e}", is_error=True)


async def tool_edit(working_dir: str, _id: str, args: Dict[str, Any]) -> ToolResult:
    """Edit a file by replacing exact text."""
    path = args.get("path", "")
    old_text = args.get("oldText", "")
    new_text = args.get("newText", "")

    try:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(working_dir) / p

        if not p.exists():
            return ToolResult(content=f"File not found: {path}", is_error=True)
        if not p.is_file():
            return ToolResult(content=f"Not a file: {path}", is_error=True)

        content = p.read_text(errors="replace")

        if old_text not in content:
            return ToolResult(
                content=f"oldText not found in {path}. Make sure it matches exactly (including whitespace).",
                is_error=True,
            )

        count = content.count(old_text)
        if count > 1:
            return ToolResult(
                content=f"oldText matches {count} locations in {path}. Make it more specific.",
                is_error=True,
            )

        new_content = content.replace(old_text, new_text, 1)
        p.write_text(new_content)
        return ToolResult(content=f"Successfully edited {path}")
    except Exception as e:
        return ToolResult(content=f"Error editing {path}: {e}", is_error=True)


async def tool_timestamp_utc(_working_dir: str, _id: str, args: Dict[str, Any]) -> ToolResult:
    """Return current UTC timestamp while validating the requested timezone."""
    timezone_name = str(args.get("timezone", "")).strip()
    if not timezone_name:
        return ToolResult(content="Missing required parameter: timezone", is_error=True)

    try:
        requested_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ToolResult(content=f"Invalid timezone: {timezone_name}", is_error=True)

    now_utc = datetime.now(timezone.utc)
    payload = {
        "timezone": timezone_name,
        "timestamp_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "unix_utc": int(now_utc.timestamp()),
        "timestamp_in_timezone": now_utc.astimezone(requested_tz).isoformat(),
    }
    return ToolResult(content=json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# ToolProvider that binds tools to a working directory
# ---------------------------------------------------------------------------

class CLIToolProvider:
    """ToolProvider with read, bash, write, edit bound to a working directory."""

    def __init__(self, working_dir: str = ".", bash_mode: str = "full"):
        self.working_dir = os.path.abspath(working_dir)
        self.bash_mode = bash_mode

    def get_tool_definitions(self) -> list:
        # Definitions come from the agent YAML, not here
        return []

    def set_bash_mode(self, bash_mode: str) -> None:
        self.bash_mode = bash_mode

    def _is_safe_date_command(self, command: str) -> bool:
        cmd = command.strip()
        if not cmd:
            return False
        if "date" not in cmd:
            return False
        allowed_prefixes = (
            "date",
            "/bin/date",
            "/usr/bin/date",
            "command date",
            "env date",
            "builtin date",
        )
        return any(cmd == prefix or cmd.startswith(prefix + " ") for prefix in allowed_prefixes)

    async def execute_tool(self, name: str, tool_call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        if name == "read":
            return await tool_read(self.working_dir, tool_call_id, arguments)
        elif name == "bash":
            if self.bash_mode == "date-only":
                command = str(arguments.get("command", ""))
                if not self._is_safe_date_command(command):
                    return ToolResult(
                        content="bash is restricted in this state: only safe `date` invocations are allowed.",
                        is_error=True,
                    )
            return await tool_bash(self.working_dir, tool_call_id, arguments)
        elif name == "write":
            return await tool_write(self.working_dir, tool_call_id, arguments)
        elif name == "edit":
            return await tool_edit(self.working_dir, tool_call_id, arguments)
        else:
            return ToolResult(content=f"Unknown tool: {name}", is_error=True)


class EveryoneTimestampToolProvider(ToolProvider):
    """Restricted provider for everyone mode: timestamp_utc only."""

    def get_tool_definitions(self) -> list:
        # Definitions come from the agent YAML, not here
        return []

    async def execute_tool(self, name: str, tool_call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        if name != "timestamp_utc":
            return ToolResult(content=f"Unknown tool: {name}", is_error=True)
        return await tool_timestamp_utc(".", tool_call_id, arguments)
