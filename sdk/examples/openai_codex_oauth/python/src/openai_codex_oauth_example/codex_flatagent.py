from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict

from flatagents import FlatAgent

from .openai_codex_client import CodexClient
from .openai_codex_types import CodexResult


class CodexFlatAgent(FlatAgent):
    """
    Example-only FlatAgent subclass that adds backend="codex" support
    without modifying FlatAgents core.
    """

    def __init__(self, *args: Any, backend: str | None = None, **kwargs: Any):
        super().__init__(*args, backend=backend or "codex", **kwargs)

    def _init_backend(self) -> None:
        if self._backend == "codex":
            self._codex_client = CodexClient(self._model_config_raw)
            return
        super()._init_backend()

    async def _call_llm(self, params: Dict[str, Any]) -> Any:
        if self._backend != "codex":
            return await super()._call_llm(params)

        result = await self._codex_client.call(params)
        return self._adapt_codex_result(result)

    def _adapt_codex_result(self, result: CodexResult) -> Any:
        prompt_tokens_details = SimpleNamespace(cached_tokens=result.usage.cached_tokens)
        usage = SimpleNamespace(
            prompt_tokens=result.usage.input_tokens,
            completion_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
            prompt_tokens_details=prompt_tokens_details,
        )

        tool_calls = []
        for tool_call in result.tool_calls:
            tool_calls.append(
                SimpleNamespace(
                    id=tool_call.id,
                    function=SimpleNamespace(
                        name=tool_call.name,
                        arguments=self._normalize_tool_arguments(tool_call.arguments_json),
                    ),
                )
            )

        message = SimpleNamespace(
            content=result.content,
            tool_calls=tool_calls or None,
        )
        choice = SimpleNamespace(
            message=message,
            finish_reason=result.finish_reason,
        )

        return SimpleNamespace(
            choices=[choice],
            usage=usage,
            _raw=result.raw_events,
        )

    def _normalize_tool_arguments(self, arguments_json: str) -> str:
        if not arguments_json:
            return "{}"
        try:
            parsed = json.loads(arguments_json)
            return json.dumps(parsed)
        except json.JSONDecodeError:
            return "{}"
