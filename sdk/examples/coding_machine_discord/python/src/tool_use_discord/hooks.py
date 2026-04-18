"""
CLI Tool Use Hooks.

Provides the tool provider, file tracking, per-call display, human review,
and append-only JSONL chat history persistence.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flatmachines import MachineHooks

from .paths import default_history_dir
from .tools import CLIToolProvider


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


class CLIToolHooks(MachineHooks):
    """Hooks for CLI tool-use workflow with per-call display and human review."""

    def __init__(
        self,
        working_dir: str = ".",
        auto_approve: bool = False,
        history_enabled: bool = True,
        history_dir: Optional[str] = None,
    ):
        self._provider = CLIToolProvider(working_dir)
        self._auto_approve = auto_approve
        self._history_enabled = bool(history_enabled)

        resolved_history_dir = history_dir or default_history_dir()
        self._history_dir = Path(resolved_history_dir).expanduser().resolve()

    def get_tool_provider(self, state_name: str):
        return self._provider

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        context["_history_last_state"] = state_name
        return self._sync_history_from_chain(state_name, context)

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        state_name = str(context.get("_history_last_state") or "unknown")
        context = self._sync_history_from_chain(state_name, context)

        if action_name == "human_review":
            context = self._human_review(context)
            context = self._sync_history_from_chain(state_name, context)
        return context

    def on_tool_calls(self, state_name: str, tool_calls: List[Dict[str, Any]], context: Dict[str, Any]) -> Dict[str, Any]:
        """Print agent thinking/content and token usage before tool execution."""
        # Show agent thinking/content if present
        content = context.get("_tool_loop_content")
        if content and content.strip():
            print()
            print(_dim(content.strip()))

        # Show token/cost metrics
        usage = context.get("_tool_loop_usage") or {}
        parts = []
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is not None or output_tokens is not None:
            parts.append(f"tokens: {input_tokens or 0}→{output_tokens or 0}")
        cost = context.get("_tool_loop_cost")
        if cost:
            parts.append(f"${cost:.4f}")
        if parts:
            print(_dim(" | ".join(parts)))

        return self._sync_history_from_chain(state_name, context)

    def on_tool_result(self, state_name: str, tool_result: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Print tool call result and track modified files."""
        name = tool_result.get("name", "")
        args = tool_result.get("arguments", {})
        is_error = tool_result.get("is_error", False)

        # Print tool call summary
        if name == "bash":
            label = f"bash: {args.get('command', '')}"
        elif name == "read":
            label = f"read: {args.get('path', '')}"
            offset = args.get("offset")
            limit = args.get("limit")
            if offset or limit:
                extras = []
                if offset:
                    extras.append(f"offset={offset}")
                if limit:
                    extras.append(f"limit={limit}")
                label += f" ({', '.join(extras)})"
        elif name == "write":
            n = len(args.get("content", ""))
            label = f"write: {args.get('path', '')} ({n} bytes)"
        elif name == "edit":
            label = f"edit: {args.get('path', '')}"
        else:
            label = f"{name}: {args}"

        status = "✗" if is_error else "✓"
        print(f"  {status} {_bold(label)}")

        # Track files modified
        if not is_error and name in ("write", "edit"):
            path = args.get("path", "")
            if path:
                modified = context.setdefault("files_modified", [])
                if path not in modified:
                    modified.append(path)

        return self._sync_history_from_chain(state_name, context)

    def _history_role(self, state_name: str, context: Dict[str, Any]) -> str:
        value = context.get("_tool_loop_chain_agent") or state_name or "assistant"
        return self._sanitize_filename_token(str(value), default="assistant")

    def _history_channel(self, context: Dict[str, Any]) -> str:
        value = context.get("conversation_key") or context.get("channel_id") or "default"
        return self._sanitize_filename_token(str(value), default="default")

    @staticmethod
    def _sanitize_filename_token(value: str, *, default: str) -> str:
        token = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip())
        token = token.strip("-._")
        return token or default

    def _history_payload_from_chain_message(self, message: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(message, dict):
            return None

        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", ""))

        if role == "user":
            return {
                "role": "user",
                "type": "message",
                "content": content,
            }

        if role == "assistant":
            payload: Dict[str, Any] = {
                "role": "assistant",
                "type": "message",
                "content": content,
            }

            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                normalized_tool_calls: list[dict[str, Any]] = []
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    function = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                    normalized_tool_calls.append(
                        {
                            "name": str(function.get("name") or tc.get("name") or ""),
                            "arguments": function.get("arguments")
                            if function.get("arguments") is not None
                            else tc.get("arguments", {}),
                        }
                    )

                if normalized_tool_calls:
                    payload["type"] = "tool_call"
                    payload["tool_calls"] = normalized_tool_calls

            return payload

        # FlatMachines stores tool results as role=tool chain entries.
        if role == "tool":
            return {
                "role": "assistant",
                "type": "tool_response",
                "content": content,
                "tool_call_id": str(message.get("tool_call_id", "")),
            }

        return None

    def _sync_history_from_chain(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self._history_enabled:
            return context

        chain = context.get("_tool_loop_chain")
        if not isinstance(chain, list) or not chain:
            return context

        role = self._history_role(state_name, context)
        channel = self._history_channel(context)
        identity = f"{role}|{channel}"

        cursors = context.setdefault("_history_chain_cursors", {})
        cursor_raw = cursors.get(identity, 0)
        try:
            cursor = int(cursor_raw)
        except (TypeError, ValueError):
            cursor = 0

        if cursor < 0 or cursor > len(chain):
            cursor = 0

        new_messages = chain[cursor:]
        if not new_messages:
            return context

        now_unix = int(time.time())
        entries: list[dict[str, Any]] = []
        for message in new_messages:
            payload = self._history_payload_from_chain_message(message)
            if not payload:
                continue
            payload["ts"] = now_unix
            entries.append(payload)

        cursors[identity] = len(chain)
        if not entries:
            return context

        file_ts_map = context.setdefault("_history_file_ts", {})
        file_ts_raw = file_ts_map.get(identity)
        try:
            file_ts = int(file_ts_raw)
        except (TypeError, ValueError):
            file_ts = now_unix
            file_ts_map[identity] = file_ts

        history_file = self._history_dir / f"{file_ts}_{role}_{channel}.jsonl"

        try:
            self._history_dir.mkdir(parents=True, exist_ok=True)
            with history_file.open("a", encoding="utf-8") as handle:
                for entry in entries:
                    handle.write(json.dumps(entry, ensure_ascii=False))
                    handle.write("\n")
            context["_history_last_file"] = str(history_file)
        except Exception as exc:
            print(f"[history] warning: failed to append {history_file}: {exc}", flush=True)

        return context

    def _human_review(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Show agent output, ask for follow-up or accept."""
        result = context.get("result", "")
        if result:
            print()
            print(result)

        files = context.get("files_modified", [])
        if files:
            print()
            print(_dim(f"Files modified: {', '.join(files)}"))

        # Non-interactive mode: auto-approve after showing output
        if self._auto_approve:
            context["human_approved"] = True
            return context

        print()
        try:
            response = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            response = ""

        if response:
            # Append feedback directly to the message chain so the LLM
            # sees it as a continuation — prefix cache stays intact
            chain = context.get("_tool_loop_chain", [])
            chain.append({"role": "user", "content": response})
            context["_tool_loop_chain"] = chain
            context["human_approved"] = False
        else:
            context["human_approved"] = True

        return context
