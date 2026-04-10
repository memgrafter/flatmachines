from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .github_copilot_auth import (
    COPILOT_STATIC_HEADERS,
    DEFAULT_BASE_URL,
    DEFAULT_PROVIDER,
    CopilotAuthError,
    CopilotAuthStore,
    get_github_copilot_base_url,
    is_expired,
    load_copilot_credential,
    refresh_copilot_credential,
    resolve_auth_file,
)
from .github_copilot_types import CopilotResult, CopilotToolCall, CopilotUsage

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class CopilotClientError(RuntimeError):
    pass


class CopilotHTTPError(CopilotClientError):
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
        super().__init__(message or f"Copilot request failed with status {status_code}")


@dataclass
class CopilotClientConfig:
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 120.0
    max_retries: int = 3
    refresh_enabled: bool = True
    provider: str = DEFAULT_PROVIDER
    auth_file: str = ""


class CopilotClient:
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

        refresh_value = _first_not_none(oauth_cfg.get("refresh"), model_config.get("copilot_refresh"), True)

        self.config = CopilotClientConfig(
            base_url=str(_first_not_none(model_config.get("base_url"), DEFAULT_BASE_URL)),
            timeout_seconds=float(
                _first_not_none(oauth_cfg.get("timeout_seconds"), model_config.get("copilot_timeout_seconds"), 120)
            ),
            max_retries=int(_first_not_none(oauth_cfg.get("max_retries"), model_config.get("copilot_max_retries"), 3)),
            refresh_enabled=bool(refresh_value),
            provider=provider,
            auth_file=resolve_auth_file(model_config=model_config, config_dir=config_dir),
        )

        self._model_config = model_config
        self._auth_store = CopilotAuthStore(self.config.auth_file)
        self._transport = transport

    async def call(self, params: Dict[str, Any]) -> CopilotResult:
        credential = load_copilot_credential(self._auth_store, self.config.provider)

        if self.config.refresh_enabled and is_expired(credential.expires):
            try:
                credential = await refresh_copilot_credential(
                    self._auth_store,
                    self.config.provider,
                    timeout_seconds=min(self.config.timeout_seconds, 30.0),
                )
            except Exception:
                latest = load_copilot_credential(self._auth_store, self.config.provider)
                if not is_expired(latest.expires, skew_ms=0):
                    credential = latest
                else:
                    raise

        request_base_url = str(params.get("base_url") or credential.base_url or self.config.base_url)
        body = self._build_request_body(params)
        headers = self._build_headers(access_token=credential.access, messages=body.get("messages") or [], params=params)
        request_url = self._resolve_completions_url(request_base_url)

        try:
            payload, response_headers, status_code, retries_used = await self._post_with_retries(
                body=body,
                headers=headers,
                base_url=request_base_url,
            )
            result = self._parse_response_to_result(payload)
            result.response_headers = response_headers
            result.response_status_code = status_code
            result.request_meta = {
                "method": "POST",
                "url": request_url,
                "headers": self._redact_request_headers(headers),
                "retries_used": retries_used,
            }
            return result
        except CopilotHTTPError as first_error:
            should_refresh = (
                self.config.refresh_enabled
                and first_error.status_code in (401, 403)
                and bool(credential.refresh)
            )
            if not should_refresh:
                raise

            refreshed = await refresh_copilot_credential(
                self._auth_store,
                self.config.provider,
                timeout_seconds=min(self.config.timeout_seconds, 30.0),
            )

            retry_base_url = request_base_url
            if "base_url" not in params:
                retry_base_url = refreshed.base_url or request_base_url

            retry_headers = self._build_headers(
                access_token=refreshed.access,
                messages=body.get("messages") or [],
                params=params,
            )
            payload, response_headers, status_code, retries_used = await self._post_with_retries(
                body=body,
                headers=retry_headers,
                base_url=retry_base_url,
            )
            result = self._parse_response_to_result(payload)
            result.response_headers = response_headers
            result.response_status_code = status_code
            result.request_meta = {
                "method": "POST",
                "url": self._resolve_completions_url(retry_base_url),
                "headers": self._redact_request_headers(retry_headers),
                "retries_used": retries_used,
            }
            return result

    def _build_request_body(self, params: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self._normalize_model_name(str(params.get("model") or "")),
            "messages": params.get("messages") or [],
            "stream": bool(params.get("stream", False)),
        }

        passthrough_fields = [
            "temperature",
            "max_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "seed",
            "stop",
            "n",
            "response_format",
            "tool_choice",
            "parallel_tool_calls",
            "service_tier",
        ]
        for field in passthrough_fields:
            if field in params and params[field] is not None:
                body[field] = params[field]

        if params.get("tools"):
            body["tools"] = params["tools"]

        return body

    def _build_headers(
        self,
        *,
        access_token: str,
        messages: List[Dict[str, Any]],
        params: Dict[str, Any],
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {access_token}",
            "accept": "application/json",
            "content-type": "application/json",
            **COPILOT_STATIC_HEADERS,
            **self._build_dynamic_headers(messages),
        }

        config_headers = self._model_config.get("headers")
        if isinstance(config_headers, dict):
            headers.update({str(k): str(v) for k, v in config_headers.items()})

        param_headers = params.get("headers")
        if isinstance(param_headers, dict):
            headers.update({str(k): str(v) for k, v in param_headers.items()})

        return headers

    def _build_dynamic_headers(self, messages: List[Dict[str, Any]]) -> Dict[str, str]:
        last_role = None
        if messages:
            last = messages[-1]
            if isinstance(last, dict):
                role = last.get("role")
                if isinstance(role, str):
                    last_role = role

        headers: Dict[str, str] = {
            "X-Initiator": "agent" if last_role and last_role != "user" else "user",
            "Openai-Intent": "conversation-edits",
        }

        if self._has_image_input(messages):
            headers["Copilot-Vision-Request"] = "true"

        return headers

    def _has_image_input(self, messages: List[Dict[str, Any]]) -> bool:
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue

            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "")
                if item_type in {"image", "input_image", "image_url"}:
                    return True
                if "image_url" in item:
                    return True
        return False

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
    ) -> Tuple[Dict[str, Any], Dict[str, str], int, int]:
        base_delay_seconds = 1.0
        url = self._resolve_completions_url(base_url)

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds, transport=self._transport) as client:
            for attempt in range(self.config.max_retries + 1):
                try:
                    response = await client.post(url, headers=headers, json=body)
                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= self.config.max_retries:
                        raise CopilotClientError(f"Network error while calling Copilot: {exc}") from exc
                    await asyncio.sleep(base_delay_seconds * (2**attempt))
                    continue

                text = response.text
                normalized_headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
                if response.status_code < 400:
                    try:
                        payload = response.json()
                    except Exception as exc:
                        raise CopilotClientError("Copilot response was not valid JSON") from exc

                    if not isinstance(payload, dict):
                        raise CopilotClientError("Copilot response JSON must be an object")
                    return payload, normalized_headers, response.status_code, attempt

                if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.config.max_retries:
                    await asyncio.sleep(base_delay_seconds * (2**attempt))
                    continue

                parsed = self._parse_error_response(response.status_code, text)
                raise CopilotHTTPError(response.status_code, text, parsed, headers=normalized_headers)

        raise CopilotClientError("Copilot request failed after retries")

    def _parse_response_to_result(self, payload: Dict[str, Any]) -> CopilotResult:
        result = CopilotResult(raw_response=payload)

        choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
        first_choice = choices[0] if choices else {}
        if not isinstance(first_choice, dict):
            first_choice = {}

        message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
        result.content = self._coerce_content_text(message.get("content"))

        if isinstance(message.get("tool_calls"), list):
            for tool_call in message["tool_calls"]:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                name = str(function.get("name") or "unknown_tool")
                raw_arguments = function.get("arguments")
                if isinstance(raw_arguments, str):
                    arguments_json = raw_arguments
                else:
                    arguments_json = json.dumps(raw_arguments or {})
                result.tool_calls.append(
                    CopilotToolCall(
                        id=str(tool_call.get("id") or "call"),
                        name=name,
                        arguments_json=arguments_json,
                    )
                )

        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
        result.usage = CopilotUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

        finish_reason = first_choice.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason:
            result.finish_reason = finish_reason
        elif result.tool_calls:
            result.finish_reason = "tool_calls"
        else:
            result.finish_reason = "stop"

        return result

    def _coerce_content_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(parts)
        return str(content)

    def _normalize_model_name(self, model: str) -> str:
        if "/" in model:
            return model.split("/", 1)[1]
        return model

    def _resolve_completions_url(self, base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"

    def _parse_error_response(self, status_code: int, text: str) -> str:
        message = text or f"Copilot request failed ({status_code})"
        friendly: Optional[str] = None

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict):
            err = parsed.get("error") if isinstance(parsed.get("error"), dict) else parsed
            err_message = err.get("message") if isinstance(err, dict) else None
            if isinstance(err_message, str) and err_message:
                message = err_message

            if status_code == 429:
                friendly = "Rate limited by Copilot. Please retry shortly."
            elif status_code in (401, 403):
                friendly = "Copilot authentication failed. Run Copilot login again."

        return friendly or message
