"""
CLI tool implementations: read, bash, write, edit.

Same tools as pi-mono defaults. All paths are resolved relative to the
configured working directory.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
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


def _sanitize_history_token(value: str, *, default: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip())
    token = token.strip("-._")
    return token or default


def _parse_history_ts(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)

    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)

    try:
        normalized = raw.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp())
    except ValueError:
        return None


def _history_snippet(content: str, query: str, *, max_chars: int = 240) -> str:
    text = str(content or "").strip().replace("\n", " ")
    if not text:
        return ""

    if len(text) <= max_chars:
        return text

    query_lower = query.lower()
    text_lower = text.lower()
    index = text_lower.find(query_lower)
    if index < 0:
        return text[: max_chars - 1] + "…"

    start = max(0, index - max_chars // 3)
    end = min(len(text), start + max_chars)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


async def tool_history_grep(
    history_dir: str,
    conversation_key: Optional[str],
    _id: str,
    args: Dict[str, Any],
) -> ToolResult:
    """Search persisted JSONL chat history by substring within the current conversation."""
    query = str(args.get("query", "")).strip()
    if not query:
        return ToolResult(content="Missing required parameter: query", is_error=True)

    try:
        limit = int(args.get("limit", 10) or 10)
    except (TypeError, ValueError):
        return ToolResult(content="Invalid limit: expected integer", is_error=True)

    limit = max(1, min(limit, 50))

    ts_from = _parse_history_ts(args.get("ts_from"))
    ts_to = _parse_history_ts(args.get("ts_to"))
    if args.get("ts_from") not in (None, "") and ts_from is None:
        return ToolResult(content="Invalid ts_from: use unix seconds or ISO-8601", is_error=True)
    if args.get("ts_to") not in (None, "") and ts_to is None:
        return ToolResult(content="Invalid ts_to: use unix seconds or ISO-8601", is_error=True)

    root = Path(history_dir).expanduser().resolve()
    if not root.exists():
        payload = {
            "query": query,
            "conversation_key": conversation_key or "",
            "history_dir": str(root),
            "result_count": 0,
            "results": [],
        }
        return ToolResult(content=json.dumps(payload, ensure_ascii=False))

    channel_token = _sanitize_history_token(conversation_key or "", default="default")
    query_lower = query.lower()
    results: list[dict[str, Any]] = []

    candidate_files = sorted(root.glob(f"*_{channel_token}.jsonl"), reverse=True)
    for path in candidate_files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = entry.get("ts")
            try:
                ts_int = int(ts)
            except (TypeError, ValueError):
                continue

            if ts_from is not None and ts_int < ts_from:
                continue
            if ts_to is not None and ts_int > ts_to:
                continue

            content = str(entry.get("content", "") or "")
            tool_names = [
                str(tool.get("name") or "")
                for tool in entry.get("tool_calls", [])
                if isinstance(tool, dict)
            ]
            haystack = "\n".join(part for part in [content, " ".join(tool_names)] if part).lower()
            if query_lower not in haystack:
                continue

            results.append(
                {
                    "ts": ts_int,
                    "timestamp_utc": datetime.fromtimestamp(ts_int, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "role": str(entry.get("role", "")),
                    "type": str(entry.get("type", "message")),
                    "file": path.name,
                    "tool_names": tool_names,
                    "snippet": _history_snippet(content or " ".join(tool_names), query),
                }
            )

    results.sort(key=lambda item: (item.get("ts", 0), item.get("file", "")), reverse=True)
    payload = {
        "query": query,
        "conversation_key": conversation_key or "",
        "history_dir": str(root),
        "result_count": min(len(results), limit),
        "results": results[:limit],
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
    """Restricted provider for everyone mode: timestamp_utc + conversation-scoped history search."""

    def __init__(self, history_dir: Optional[str] = None):
        resolved_history_dir = history_dir or os.environ.get(
            "TOOL_USE_DISCORD_HISTORY_DIR",
            "~/.agents/flatmachines/history",
        )
        self._history_dir = str(Path(resolved_history_dir).expanduser().resolve())
        self._conversation_key = ""

    def set_runtime_scope(self, *, conversation_key: Optional[str]) -> None:
        self._conversation_key = str(conversation_key or "").strip()

    def get_tool_definitions(self) -> list:
        # Definitions come from the agent YAML, not here
        return []

    async def execute_tool(self, name: str, tool_call_id: str, arguments: Dict[str, Any]) -> ToolResult:
        if name == "timestamp_utc":
            return await tool_timestamp_utc(".", tool_call_id, arguments)
        if name == "history_grep":
            return await tool_history_grep(
                self._history_dir,
                self._conversation_key,
                tool_call_id,
                arguments,
            )
        return ToolResult(content=f"Unknown tool: {name}", is_error=True)
