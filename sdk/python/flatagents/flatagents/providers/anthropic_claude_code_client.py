"""
Anthropic Claude Code OAuth client.

Calls the standard Anthropic Messages API using OAuth Bearer authentication
with Claude Code identity headers. This allows users with Claude Pro/Max
subscriptions to use their subscription quota through FlatAgents.

Key differences from the Codex backend:
  - Uses the standard Anthropic Messages API (not a proprietary SSE endpoint).
  - Bearer auth via ``Authorization: Bearer <oauth_token>`` (not API key).
  - Requires Claude Code identity headers and system prompt prefix.
  - Tool names are mapped to/from Claude Code canonical casing.
  - SSE streaming is parsed from the Anthropic event format.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .anthropic_claude_code_auth import (
    CLIENT_ID,
    DEFAULT_PROVIDER,
    TOKEN_URL,
    ClaudeCodeAuthError,
    PiAuthStore,
    is_expired,
    load_claude_code_credential,
    refresh_claude_code_credential,
    resolve_auth_file,
)
from .anthropic_claude_code_types import (
    ClaudeCodeResult,
    ClaudeCodeToolCall,
    ClaudeCodeUsage,
)

DEFAULT_BASE_URL = "https://api.anthropic.com"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Keep in sync with pi-mono packages/ai/src/providers/anthropic.ts
CLAUDE_CODE_VERSION = "2.1.62"

# Required system prompt prefix for OAuth tokens.
CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."

# Claude Code canonical tool names (case-sensitive).
# Source: pi-mono packages/ai/src/providers/anthropic.ts
CLAUDE_CODE_TOOLS = [
    "Read", "Write", "Edit", "Bash", "Grep", "Glob",
    "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "KillShell", "NotebookEdit", "Skill", "Task",
    "TaskOutput", "TodoWrite", "WebFetch", "WebSearch",
]

# Case-insensitive lookup: lowercase → canonical
_CC_TOOL_LOOKUP: Dict[str, str] = {t.lower(): t for t in CLAUDE_CODE_TOOLS}


def _to_claude_code_name(name: str) -> str:
    """Convert a tool name to Claude Code canonical casing if it matches."""
    return _CC_TOOL_LOOKUP.get(name.lower(), name)


def _from_claude_code_name(name: str, original_tools: Optional[List[Dict[str, Any]]] = None) -> str:
    """Convert a Claude Code tool name back to the caller's original casing.

    Matches case-insensitively against the original tool list.  Falls back
    to the name as-is if no match is found.
    """
    if original_tools:
        lower_name = name.lower()
        for tool in original_tools:
            fn = tool.get("function") if isinstance(tool, dict) else None
            if isinstance(fn, dict):
                original_name = fn.get("name", "")
            elif isinstance(tool, dict):
                original_name = tool.get("name", "")
            else:
                continue
            if isinstance(original_name, str) and original_name.lower() == lower_name:
                return original_name
    return name


class ClaudeCodeClientError(RuntimeError):
    """Raised for non-auth errors in the Claude Code client."""
    pass


class ClaudeCodeHTTPError(ClaudeCodeClientError):
    def __init__(
        self,
        status_code: int,
        body: str,
        message: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        super().__init__(message or f"Claude Code request failed with status {status_code}")


@dataclass
class ClaudeCodeClientConfig:
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 120.0
    max_retries: int = 3
    refresh_enabled: bool = True
    provider: str = DEFAULT_PROVIDER
    auth_file: str = ""
    token_url: str = TOKEN_URL
    client_id: str = CLIENT_ID


class ClaudeCodeClient:
    """Client for the Anthropic Messages API using Claude Code OAuth.

    Reads OAuth credentials from the shared ``auth.json``, refreshes
    tokens automatically, injects the required Claude Code identity
    headers/system prompt, and translates tool names.
    """

    def __init__(
        self,
        model_config: Dict[str, Any],
        *,
        config_dir: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        oauth_cfg = (
            model_config.get("oauth")
            if isinstance(model_config.get("oauth"), dict)
            else {}
        )

        def _first(*values: Any) -> Any:
            for v in values:
                if v is not None:
                    return v
            return None

        provider = str(
            _first(
                oauth_cfg.get("provider"),
                model_config.get("provider"),
                DEFAULT_PROVIDER,
            )
        )

        refresh_value = _first(oauth_cfg.get("refresh"), True)

        self.config = ClaudeCodeClientConfig(
            base_url=str(_first(model_config.get("base_url"), DEFAULT_BASE_URL)),
            timeout_seconds=float(_first(oauth_cfg.get("timeout_seconds"), 120)),
            max_retries=int(_first(oauth_cfg.get("max_retries"), 3)),
            refresh_enabled=bool(refresh_value),
            provider=provider,
            auth_file=resolve_auth_file(model_config=model_config, config_dir=config_dir),
            token_url=str(_first(oauth_cfg.get("token_url"), TOKEN_URL)),
            client_id=str(_first(oauth_cfg.get("client_id"), CLIENT_ID)),
        )

        self._model_config = model_config
        self._auth_store = PiAuthStore(self.config.auth_file)
        self._transport = transport

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def call(self, params: Dict[str, Any]) -> ClaudeCodeResult:
        """Execute a single Anthropic Messages API call with OAuth auth.

        Handles pre-request token refresh, builds the request with Claude
        Code identity, and retries on transient/auth errors.
        """
        credential = load_claude_code_credential(self._auth_store, self.config.provider)

        # Pre-request refresh if expired.
        if self.config.refresh_enabled and is_expired(credential.expires, skew_ms=0):
            try:
                credential = await refresh_claude_code_credential(
                    self._auth_store,
                    self.config.provider,
                    timeout_seconds=min(self.config.timeout_seconds, 30.0),
                    token_url=self.config.token_url,
                    client_id=self.config.client_id,
                )
            except Exception:
                # Cross-process: maybe another process refreshed.
                latest = load_claude_code_credential(self._auth_store, self.config.provider)
                if not is_expired(latest.expires, skew_ms=0):
                    credential = latest
                else:
                    raise

        original_tools = params.get("tools")
        body = self._build_request_body(params)
        headers = self._build_headers(access_token=credential.access, params=params)
        request_url = self._resolve_url(
            str(params.get("base_url") or self.config.base_url)
        )

        try:
            payload, resp_headers, status_code, retries_used = await self._post_with_retries(
                body=body,
                headers=headers,
                url=request_url,
            )
            result = self._parse_sse_to_result(payload, original_tools=original_tools)
            result.response_headers = resp_headers
            result.response_status_code = status_code
            result.request_meta = {
                "method": "POST",
                "url": request_url,
                "headers": self._redact_headers(headers),
                "retries_used": retries_used,
            }
            return result
        except ClaudeCodeHTTPError as first_error:
            should_refresh = (
                self.config.refresh_enabled
                and first_error.status_code in (401, 403)
                and bool(credential.refresh)
            )
            if not should_refresh:
                raise

            refreshed = await refresh_claude_code_credential(
                self._auth_store,
                self.config.provider,
                timeout_seconds=min(self.config.timeout_seconds, 30.0),
                token_url=self.config.token_url,
                client_id=self.config.client_id,
            )
            retry_headers = self._build_headers(
                access_token=refreshed.access, params=params,
            )
            payload, resp_headers, status_code, retries_used = await self._post_with_retries(
                body=body,
                headers=retry_headers,
                url=request_url,
            )
            result = self._parse_sse_to_result(payload, original_tools=original_tools)
            result.response_headers = resp_headers
            result.response_status_code = status_code
            result.request_meta = {
                "method": "POST",
                "url": request_url,
                "headers": self._redact_headers(retry_headers),
                "retries_used": retries_used,
            }
            return result

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _build_request_body(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Build the Anthropic Messages API request body.

        Injects the Claude Code identity as the first system block,
        appends the caller's system prompt, and converts tools to
        Anthropic format with Claude Code canonical names.
        """
        messages = params.get("messages") or []
        system_parts, api_messages = self._convert_messages(messages)

        # Build system blocks: identity first, then user system prompt.
        system_blocks = [{"type": "text", "text": CLAUDE_CODE_IDENTITY}]
        if system_parts:
            system_blocks.append({"type": "text", "text": "\n\n".join(system_parts)})

        model_name = self._normalize_model_name(str(params.get("model") or ""))

        body: Dict[str, Any] = {
            "model": model_name,
            "messages": api_messages,
            "system": system_blocks,
            "max_tokens": params.get("max_tokens") or 16384,
            "stream": True,
        }

        if "temperature" in params:
            body["temperature"] = params["temperature"]

        if params.get("tools"):
            body["tools"] = self._convert_tools(params["tools"])

        if params.get("tool_choice"):
            tc = params["tool_choice"]
            if isinstance(tc, str):
                body["tool_choice"] = {"type": tc}
            else:
                body["tool_choice"] = tc

        return body

    def _build_headers(
        self,
        *,
        access_token: str,
        params: Dict[str, Any],
    ) -> Dict[str, str]:
        """Build request headers with Claude Code identity."""
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {access_token}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14",
            "anthropic-dangerous-direct-browser-access": "true",
            "user-agent": f"claude-cli/{CLAUDE_CODE_VERSION}",
            "x-app": "cli",
            "accept": "text/event-stream",
            "content-type": "application/json",
        }

        # Config-level header overrides.
        config_headers = self._model_config.get("headers")
        if isinstance(config_headers, dict):
            headers.update({str(k): str(v) for k, v in config_headers.items()})

        # Per-call header overrides.
        param_headers = params.get("headers")
        if isinstance(param_headers, dict):
            headers.update({str(k): str(v) for k, v in param_headers.items()})

        return headers

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    def _convert_messages(
        self, messages: List[Dict[str, Any]]
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """Convert OpenAI-style messages to Anthropic Messages API format.

        Returns (system_parts, api_messages).

        System messages are extracted and concatenated.  User, assistant,
        and tool messages are converted to the Anthropic schema.
        """
        system_parts: List[str] = []
        api_messages: List[Dict[str, Any]] = []

        for message in messages:
            role = message.get("role")
            content = message.get("content")

            if role == "system":
                text = self._coerce_text(content)
                if text:
                    system_parts.append(text)
                continue

            if role == "user":
                text = self._coerce_text(content)
                if text:
                    api_messages.append({"role": "user", "content": text})
                continue

            if role == "assistant":
                blocks: List[Dict[str, Any]] = []
                text = self._coerce_text(content)
                if text:
                    blocks.append({"type": "text", "text": text})

                # Convert tool_calls to tool_use blocks.
                if isinstance(message.get("tool_calls"), list):
                    for tc in message["tool_calls"]:
                        fn = tc.get("function") if isinstance(tc, dict) else None
                        if not isinstance(fn, dict):
                            continue
                        args_str = fn.get("arguments") or "{}"
                        try:
                            args_parsed = json.loads(args_str) if isinstance(args_str, str) else args_str
                        except json.JSONDecodeError:
                            args_parsed = {}
                        blocks.append({
                            "type": "tool_use",
                            "id": str(tc.get("id") or "call"),
                            "name": _to_claude_code_name(str(fn.get("name") or "")),
                            "input": args_parsed,
                        })

                if blocks:
                    api_messages.append({"role": "assistant", "content": blocks})
                continue

            if role == "tool":
                tool_call_id = str(message.get("tool_call_id") or "call")
                result_text = self._coerce_text(content)
                is_error = bool(message.get("is_error"))
                api_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": result_text,
                        "is_error": is_error,
                    }],
                })

        return system_parts, api_messages

    def _convert_tools(self, tools: Any) -> List[Dict[str, Any]]:
        """Convert OpenAI-format tools to Anthropic format with CC names."""
        if not isinstance(tools, list):
            return []

        converted: List[Dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue

            # OpenAI format: {"type": "function", "function": {...}}
            fn = tool.get("function") if isinstance(tool.get("function"), dict) else None
            if fn:
                name = str(fn.get("name") or "")
                params = fn.get("parameters") or {"type": "object", "properties": {}}
            else:
                # Already Anthropic format or simple format.
                name = str(tool.get("name") or "")
                params = tool.get("input_schema") or tool.get("parameters") or {
                    "type": "object", "properties": {}
                }

            converted.append({
                "name": _to_claude_code_name(name),
                "description": str(fn.get("description") or tool.get("description") or ""),
                "input_schema": {
                    "type": "object",
                    "properties": params.get("properties", {}),
                    "required": params.get("required", []),
                },
            })

        return converted

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    async def _post_with_retries(
        self,
        *,
        body: Dict[str, Any],
        headers: Dict[str, str],
        url: str,
    ) -> Tuple[str, Dict[str, str], int, int]:
        """POST with exponential backoff on retryable status codes."""
        base_delay = 1.0

        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds, transport=self._transport
        ) as client:
            for attempt in range(self.config.max_retries + 1):
                try:
                    response = await client.post(url, headers=headers, json=body)
                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= self.config.max_retries:
                        raise ClaudeCodeClientError(
                            f"Network error calling Anthropic API: {exc}"
                        ) from exc
                    await asyncio.sleep(base_delay * (2 ** attempt))
                    continue

                text = response.text
                norm_headers = {
                    str(k).lower(): str(v) for k, v in response.headers.items()
                }

                if response.status_code < 400:
                    return text, norm_headers, response.status_code, attempt

                if (
                    response.status_code in RETRYABLE_STATUS_CODES
                    and attempt < self.config.max_retries
                ):
                    await asyncio.sleep(base_delay * (2 ** attempt))
                    continue

                parsed = self._parse_error_response(response.status_code, text)
                raise ClaudeCodeHTTPError(
                    response.status_code, text, parsed, headers=norm_headers
                )

        raise ClaudeCodeClientError("Anthropic request failed after retries")

    # ------------------------------------------------------------------
    # SSE parsing (Anthropic streaming format)
    # ------------------------------------------------------------------

    def _parse_sse_to_result(
        self,
        payload: str,
        *,
        original_tools: Optional[Any] = None,
    ) -> ClaudeCodeResult:
        """Parse Anthropic SSE streaming events into a ClaudeCodeResult.

        Handles content_block_start/delta/stop, message_start, message_delta,
        and error events in the Anthropic streaming format.
        """
        events = self._parse_sse_events(payload)
        result = ClaudeCodeResult(raw_events=events)

        text_parts: List[str] = []
        # Track in-flight tool calls by content block index.
        tool_blocks: Dict[int, Dict[str, Any]] = {}

        for event in events:
            event_type = event.get("type")

            if event_type == "error":
                err = event.get("error") if isinstance(event.get("error"), dict) else {}
                raise ClaudeCodeClientError(
                    err.get("message") or err.get("type") or "Anthropic error event"
                )

            if event_type == "message_start":
                msg = event.get("message") if isinstance(event.get("message"), dict) else {}
                usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
                result.usage.input_tokens = int(usage.get("input_tokens") or 0)
                result.usage.output_tokens = int(usage.get("output_tokens") or 0)
                result.usage.cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
                result.usage.cache_write_tokens = int(usage.get("cache_creation_input_tokens") or 0)

            elif event_type == "content_block_start":
                block = event.get("content_block") if isinstance(event.get("content_block"), dict) else {}
                index = event.get("index", 0)
                block_type = block.get("type")

                if block_type == "tool_use":
                    tool_blocks[index] = {
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "input_json": "",
                    }

            elif event_type == "content_block_delta":
                delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
                delta_type = delta.get("type")
                index = event.get("index", 0)

                if delta_type == "text_delta":
                    text_parts.append(delta.get("text", ""))
                elif delta_type == "input_json_delta":
                    if index in tool_blocks:
                        tool_blocks[index]["input_json"] += delta.get("partial_json", "")

            elif event_type == "content_block_stop":
                index = event.get("index", 0)
                if index in tool_blocks:
                    tb = tool_blocks.pop(index)
                    # Reverse-map tool name back to the caller's original name.
                    original_name = _from_claude_code_name(
                        tb["name"],
                        original_tools if isinstance(original_tools, list) else None,
                    )
                    result.tool_calls.append(
                        ClaudeCodeToolCall(
                            id=tb["id"],
                            name=original_name,
                            arguments_json=tb["input_json"] or "{}",
                        )
                    )

            elif event_type == "message_delta":
                delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
                usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}

                stop_reason = delta.get("stop_reason")
                if stop_reason:
                    result.stop_reason = stop_reason

                if usage.get("output_tokens") is not None:
                    result.usage.output_tokens = int(usage["output_tokens"])
                if usage.get("input_tokens") is not None:
                    result.usage.input_tokens = int(usage["input_tokens"])
                if usage.get("cache_read_input_tokens") is not None:
                    result.usage.cache_read_tokens = int(usage["cache_read_input_tokens"])
                if usage.get("cache_creation_input_tokens") is not None:
                    result.usage.cache_write_tokens = int(usage["cache_creation_input_tokens"])

        result.content = "".join(text_parts)
        result.usage.total_tokens = (
            result.usage.input_tokens
            + result.usage.output_tokens
            + result.usage.cache_read_tokens
            + result.usage.cache_write_tokens
        )
        result.finish_reason = self._map_finish_reason(result)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _map_finish_reason(self, result: ClaudeCodeResult) -> str:
        """Map Anthropic stop reasons to OpenAI-compatible finish reasons."""
        if result.tool_calls:
            return "tool_calls"
        sr = result.stop_reason
        if sr == "end_turn":
            return "stop"
        if sr == "max_tokens":
            return "length"
        if sr == "tool_use":
            return "tool_calls"
        return "stop"

    def _coerce_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts)
        return str(content)

    def _normalize_model_name(self, model: str) -> str:
        """Strip provider prefix (e.g. ``anthropic/claude-…`` → ``claude-…``)."""
        if "/" in model:
            return model.split("/", 1)[1]
        return model

    def _resolve_url(self, base_url: str) -> str:
        """Resolve the Anthropic Messages API endpoint."""
        normalized = base_url.rstrip("/")
        if normalized.endswith("/v1/messages"):
            return normalized
        if normalized.endswith("/v1"):
            return f"{normalized}/messages"
        return f"{normalized}/v1/messages"

    def _parse_sse_events(self, payload: str) -> List[Dict[str, Any]]:
        """Parse raw SSE text into a list of event dicts."""
        events: List[Dict[str, Any]] = []
        blocks = payload.replace("\r\n", "\n").split("\n\n")

        for block in blocks:
            data_lines = [line for line in block.split("\n") if line.startswith("data:")]
            if not data_lines:
                continue
            data = "\n".join(line[5:].strip() for line in data_lines).strip()
            if not data or data == "[DONE]":
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)

        return events

    def _parse_error_response(self, status_code: int, text: str) -> str:
        """Parse an error response into a human-friendly message."""
        message = text or f"Anthropic request failed ({status_code})"
        friendly: Optional[str] = None

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict):
            err = parsed.get("error") if isinstance(parsed.get("error"), dict) else {}
            err_type = str(err.get("type") or "")
            err_message = err.get("message")

            if err_type == "rate_limit_error" or status_code == 429:
                friendly = "Rate limited by Anthropic. Please retry shortly."
            elif status_code in (401, 403):
                friendly = (
                    "Anthropic authentication failed. "
                    "Run claude-code-login again."
                )
            elif err_type == "overloaded_error":
                friendly = "Anthropic API is overloaded. Please retry shortly."

            if isinstance(err_message, str) and err_message:
                message = err_message

        return friendly or message

    def _redact_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        redacted: Dict[str, str] = {}
        for key, value in headers.items():
            if str(key).lower() == "authorization":
                redacted[str(key)] = "Bearer ***"
            else:
                redacted[str(key)] = str(value)
        return redacted
