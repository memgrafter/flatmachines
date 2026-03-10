from __future__ import annotations

import asyncio
import json
import platform
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .openai_codex_auth import (
    CodexAuthError,
    DEFAULT_PROVIDER,
    OPENAI_CODEX_CLIENT_ID,
    TOKEN_URL,
    PiAuthStore,
    is_expired,
    load_codex_credential,
    refresh_codex_credential,
    resolve_auth_file,
)
from .openai_codex_types import CodexResult, CodexToolCall, CodexUsage

DEFAULT_BASE_URL = "https://chatgpt.com/backend-api"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class CodexClientError(RuntimeError):
    pass


class CodexHTTPError(CodexClientError):
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
        super().__init__(message or f"Codex request failed with status {status_code}")


@dataclass
class CodexClientConfig:
    base_url: str = DEFAULT_BASE_URL
    originator: str = "pi"
    timeout_seconds: float = 120.0
    max_retries: int = 3
    refresh_enabled: bool = True
    provider: str = DEFAULT_PROVIDER
    auth_file: str = ""
    token_url: str = TOKEN_URL
    client_id: str = OPENAI_CODEX_CLIENT_ID


class CodexClient:
    def __init__(
        self,
        model_config: Dict[str, Any],
        *,
        config_dir: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        oauth_cfg = model_config.get("oauth") if isinstance(model_config.get("oauth"), dict) else {}
        auth_cfg = model_config.get("auth") if isinstance(model_config.get("auth"), dict) else {}

        def _first_not_none(*values: Any) -> Any:
            for value in values:
                if value is not None:
                    return value
            return None

        provider = str(
            _first_not_none(
                oauth_cfg.get("provider"),
                auth_cfg.get("provider"),
                model_config.get("provider"),
                DEFAULT_PROVIDER,
            )
        )

        refresh_value = _first_not_none(oauth_cfg.get("refresh"), model_config.get("codex_refresh"), True)

        self.config = CodexClientConfig(
            base_url=str(_first_not_none(model_config.get("base_url"), DEFAULT_BASE_URL)),
            originator=str(_first_not_none(oauth_cfg.get("originator"), model_config.get("codex_originator"), "pi")),
            timeout_seconds=float(_first_not_none(oauth_cfg.get("timeout_seconds"), model_config.get("codex_timeout_seconds"), 120)),
            max_retries=int(_first_not_none(oauth_cfg.get("max_retries"), model_config.get("codex_max_retries"), 3)),
            refresh_enabled=bool(refresh_value),
            provider=provider,
            auth_file=resolve_auth_file(model_config=model_config, config_dir=config_dir),
            token_url=str(_first_not_none(oauth_cfg.get("token_url"), model_config.get("codex_token_url"), TOKEN_URL)),
            client_id=str(_first_not_none(oauth_cfg.get("client_id"), model_config.get("codex_client_id"), OPENAI_CODEX_CLIENT_ID)),
        )

        self._model_config = model_config
        self._auth_store = PiAuthStore(self.config.auth_file)
        self._transport = transport

    async def call(self, params: Dict[str, Any]) -> CodexResult:
        credential = load_codex_credential(self._auth_store, self.config.provider)

        if self.config.refresh_enabled and is_expired(credential.expires, skew_ms=0):
            try:
                credential = await refresh_codex_credential(
                    self._auth_store,
                    self.config.provider,
                    timeout_seconds=min(self.config.timeout_seconds, 30.0),
                    token_url=self.config.token_url,
                    client_id=self.config.client_id,
                )
            except Exception:
                latest = load_codex_credential(self._auth_store, self.config.provider)
                if not is_expired(latest.expires, skew_ms=0):
                    credential = latest
                else:
                    raise

        session_id = self._resolve_session_id(params)
        body = self._build_request_body(params, session_id=session_id)

        headers = self._build_headers(
            access_token=credential.access,
            account_id=credential.account_id or "",
            session_id=session_id,
            params=params,
        )

        request_base_url = str(params.get("base_url") or self.config.base_url)
        request_url = self._resolve_codex_url(request_base_url)

        try:
            payload, response_headers, status_code, retries_used = await self._post_with_retries(
                body=body,
                headers=headers,
                base_url=request_base_url,
            )
            result = self._parse_sse_to_result(payload)
            result.response_headers = response_headers
            result.response_status_code = status_code
            result.request_meta = {
                "method": "POST",
                "url": request_url,
                "headers": self._redact_request_headers(headers),
                "retries_used": retries_used,
            }
            return result
        except CodexHTTPError as first_error:
            should_refresh = (
                self.config.refresh_enabled
                and first_error.status_code in (401, 403)
                and bool(credential.refresh)
            )
            if not should_refresh:
                raise

            refreshed = await refresh_codex_credential(
                self._auth_store,
                self.config.provider,
                timeout_seconds=min(self.config.timeout_seconds, 30.0),
                token_url=self.config.token_url,
                client_id=self.config.client_id,
            )
            retry_headers = self._build_headers(
                access_token=refreshed.access,
                account_id=refreshed.account_id or "",
                session_id=session_id,
                params=params,
            )
            payload, response_headers, status_code, retries_used = await self._post_with_retries(
                body=body,
                headers=retry_headers,
                base_url=request_base_url,
            )
            result = self._parse_sse_to_result(payload)
            result.response_headers = response_headers
            result.response_status_code = status_code
            result.request_meta = {
                "method": "POST",
                "url": request_url,
                "headers": self._redact_request_headers(retry_headers),
                "retries_used": retries_used,
            }
            return result

    def _resolve_session_id(self, params: Dict[str, Any]) -> Optional[str]:
        session_id = params.get("session_id") or params.get("sessionId") or self._model_config.get("codex_session_id")
        return str(session_id) if session_id else None

    def _build_request_body(self, params: Dict[str, Any], session_id: Optional[str]) -> Dict[str, Any]:
        messages = params.get("messages") or []
        instructions, input_items = self._convert_messages(messages)

        body: Dict[str, Any] = {
            "model": self._normalize_model_name(str(params.get("model") or "")),
            "store": False,
            "stream": True,
            "instructions": instructions,
            "input": input_items,
            "text": {"verbosity": self._resolve_text_verbosity(params)},
            "include": ["reasoning.encrypted_content"],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }

        if session_id:
            body["prompt_cache_key"] = session_id

        if "temperature" in params:
            body["temperature"] = params["temperature"]

        if params.get("tools"):
            body["tools"] = params["tools"]

        reasoning = self._resolve_reasoning(params)
        if reasoning:
            body["reasoning"] = reasoning

        service_tier = params.get("service_tier") or self._model_config.get("service_tier")
        if service_tier:
            body["service_tier"] = service_tier

        return body

    def _build_headers(
        self,
        *,
        access_token: str,
        account_id: str,
        session_id: Optional[str],
        params: Dict[str, Any],
    ) -> Dict[str, str]:
        if not account_id:
            raise CodexAuthError("Missing chatgpt account id. Re-run codex login.")

        headers: Dict[str, str] = {
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id,
            "OpenAI-Beta": "responses=experimental",
            "originator": self.config.originator,
            "User-Agent": f"flatagents ({platform.system().lower()} {platform.release()}; {platform.machine()})",
            "accept": "text/event-stream",
            "content-type": "application/json",
        }

        if session_id:
            headers["session_id"] = session_id

        config_headers = self._model_config.get("headers")
        if isinstance(config_headers, dict):
            headers.update({str(k): str(v) for k, v in config_headers.items()})

        param_headers = params.get("headers")
        if isinstance(param_headers, dict):
            headers.update({str(k): str(v) for k, v in param_headers.items()})

        return headers

    def _redact_request_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        redacted: Dict[str, str] = {}
        for key, value in headers.items():
            if str(key).lower() == "authorization":
                redacted[str(key)] = "Bearer ***"
            else:
                redacted[str(key)] = str(value)
        return redacted

    async def _post_with_retries(
        self,
        *,
        body: Dict[str, Any],
        headers: Dict[str, str],
        base_url: str,
    ) -> Tuple[str, Dict[str, str], int, int]:
        base_delay_seconds = 1.0
        url = self._resolve_codex_url(base_url)

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds, transport=self._transport) as client:
            for attempt in range(self.config.max_retries + 1):
                try:
                    response = await client.post(url, headers=headers, json=body)
                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= self.config.max_retries:
                        raise CodexClientError(f"Network error while calling Codex: {exc}") from exc
                    await asyncio.sleep(base_delay_seconds * (2**attempt))
                    continue

                text = response.text
                normalized_headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
                if response.status_code < 400:
                    return text, normalized_headers, response.status_code, attempt

                if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.config.max_retries:
                    await asyncio.sleep(base_delay_seconds * (2**attempt))
                    continue

                parsed = self._parse_error_response(response.status_code, text)
                raise CodexHTTPError(response.status_code, text, parsed, headers=normalized_headers)

        raise CodexClientError("Codex request failed after retries")

    def _parse_sse_to_result(self, payload: str) -> CodexResult:
        events = self._parse_sse_events(payload)

        result = CodexResult(raw_events=events)
        text_parts: List[str] = []
        tool_args_by_call: Dict[str, str] = {}

        for event in events:
            event_type = event.get("type")

            if event_type == "error":
                raise CodexClientError(event.get("message") or event.get("code") or "Codex error event received")

            if event_type == "response.failed":
                error_message = (
                    event.get("response", {}).get("error", {}).get("message")
                    if isinstance(event.get("response"), dict)
                    else None
                )
                raise CodexClientError(error_message or "Codex response failed")

            if event_type == "response.output_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str):
                    text_parts.append(delta)

            if event_type == "response.function_call_arguments.delta":
                call_id = event.get("call_id") or event.get("item_id") or "call"
                if isinstance(call_id, str):
                    tool_args_by_call[call_id] = tool_args_by_call.get(call_id, "") + str(event.get("delta", ""))

            if event_type == "response.output_item.done":
                item = event.get("item") if isinstance(event.get("item"), dict) else {}
                item_type = item.get("type")

                if item_type == "message" and not text_parts:
                    for content_item in item.get("content", []):
                        if isinstance(content_item, dict) and content_item.get("type") == "output_text":
                            text_value = content_item.get("text")
                            if isinstance(text_value, str):
                                text_parts.append(text_value)

                if item_type == "function_call":
                    call_id = str(item.get("call_id") or "call")
                    item_id = str(item.get("id") or "fc")
                    arguments_json = item.get("arguments")
                    if not isinstance(arguments_json, str):
                        arguments_json = tool_args_by_call.get(call_id, "{}")
                    if not arguments_json:
                        arguments_json = "{}"
                    result.tool_calls.append(
                        CodexToolCall(
                            id=f"{call_id}|{item_id}",
                            name=str(item.get("name") or "unknown_tool"),
                            arguments_json=arguments_json,
                        )
                    )

            if event_type in ("response.completed", "response.done"):
                response_obj = event.get("response") if isinstance(event.get("response"), dict) else {}
                result.status = str(response_obj.get("status")) if response_obj.get("status") else None
                usage_obj = response_obj.get("usage") if isinstance(response_obj.get("usage"), dict) else {}
                input_tokens = int(usage_obj.get("input_tokens") or 0)
                output_tokens = int(usage_obj.get("output_tokens") or 0)
                total_tokens = int(usage_obj.get("total_tokens") or (input_tokens + output_tokens))
                cached_tokens = int(
                    (usage_obj.get("input_tokens_details") or {}).get("cached_tokens")
                    if isinstance(usage_obj.get("input_tokens_details"), dict)
                    else 0
                )
                result.usage = CodexUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cached_tokens=cached_tokens,
                )

        result.content = "".join(text_parts)
        result.finish_reason = self._map_finish_reason(result)
        return result

    def _map_finish_reason(self, result: CodexResult) -> str:
        if result.tool_calls:
            return "tool_calls"
        if result.status == "incomplete":
            return "length"
        return "stop"

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
        instructions_parts: List[str] = []
        input_items: List[Dict[str, Any]] = []

        for message in messages:
            role = message.get("role")
            content_text = self._coerce_text(message.get("content"))

            if role == "system":
                if content_text:
                    instructions_parts.append(content_text)
                continue

            if role in ("user", "assistant"):
                type_name = "input_text" if role == "user" else "output_text"
                input_items.append(
                    {
                        "role": role,
                        "content": [{"type": type_name, "text": content_text}],
                    }
                )

                if role == "assistant" and isinstance(message.get("tool_calls"), list):
                    for tool_call in message["tool_calls"]:
                        function = tool_call.get("function") if isinstance(tool_call, dict) else None
                        if not isinstance(function, dict):
                            continue
                        call_id = str(tool_call.get("id") or "call")
                        input_items.append(
                            {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": str(function.get("name") or "unknown_tool"),
                                "arguments": str(function.get("arguments") or "{}"),
                            }
                        )
                continue

            if role == "tool":
                call_id = str(message.get("tool_call_id") or "call")
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": content_text,
                    }
                )

        instructions = "\n\n".join([part for part in instructions_parts if part])
        return instructions, input_items

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

    def _resolve_reasoning(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        reasoning_obj = params.get("reasoning") if isinstance(params.get("reasoning"), dict) else {}
        effort = (
            reasoning_obj.get("effort")
            or params.get("reasoning_effort")
            or self._model_config.get("codex_reasoning_effort")
        )
        summary = (
            reasoning_obj.get("summary")
            or params.get("reasoning_summary")
            or self._model_config.get("codex_reasoning_summary")
        )
        if effort is None and summary is None:
            return None

        result: Dict[str, Any] = {}
        if effort is not None:
            result["effort"] = effort
        if summary is not None:
            result["summary"] = summary
        return result

    def _resolve_text_verbosity(self, params: Dict[str, Any]) -> str:
        text_obj = params.get("text") if isinstance(params.get("text"), dict) else {}
        verbosity = text_obj.get("verbosity") or params.get("verbosity") or self._model_config.get("codex_text_verbosity")
        return str(verbosity or "medium")

    def _normalize_model_name(self, model: str) -> str:
        if "/" in model:
            return model.split("/", 1)[1]
        return model

    def _resolve_codex_url(self, base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/codex/responses"):
            return normalized
        if normalized.endswith("/codex"):
            return f"{normalized}/responses"
        return f"{normalized}/codex/responses"

    def _parse_sse_events(self, payload: str) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        blocks = payload.replace("\r\n", "\n").split("\n\n")

        for block in blocks:
            lines = [line for line in block.split("\n") if line.startswith("data:")]
            if not lines:
                continue
            data = "\n".join(line[5:].strip() for line in lines).strip()
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
        message = text or f"Codex request failed ({status_code})"
        friendly: Optional[str] = None

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict):
            err = parsed.get("error") if isinstance(parsed.get("error"), dict) else {}
            code = str(err.get("code") or err.get("type") or "")
            err_message = err.get("message")

            if code and any(token in code for token in ("usage_limit_reached", "usage_not_included", "rate_limit_exceeded")):
                plan = str(err.get("plan_type") or "").lower()
                plan_part = f" ({plan} plan)" if plan else ""
                friendly = f"You have hit your ChatGPT usage limit{plan_part}."
            elif status_code == 429:
                friendly = "Rate limited by Codex. Please retry shortly."
            elif status_code in (401, 403):
                friendly = "Codex authentication failed. Run codex login again."

            if isinstance(err_message, str) and err_message:
                message = err_message

        return friendly or message
