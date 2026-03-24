"""smolagents adapter for FlatMachines."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
from typing import Any, Dict, Optional, Tuple

from ..agents import AgentAdapter, AgentAdapterContext, AgentExecutor, AgentRef, AgentResult

try:
    from smolagents.agents import MultiStepAgent, RunResult
except ImportError as exc:  # pragma: no cover - optional dependency
    raise ImportError("smolagents is required for SmolagentsAdapter") from exc


class SmolagentsExecutor(AgentExecutor):
    def __init__(self, agent: MultiStepAgent, default_kwargs: Optional[Dict[str, Any]] = None):
        self._agent = agent
        self._default_kwargs = default_kwargs or {}

    @property
    def metadata(self) -> Dict[str, Any]:
        return {}

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        task = input_data.get("task") or input_data.get("prompt")
        if task is None:
            raise ValueError("smolagents adapter requires input.task or input.prompt")

        run_kwargs = dict(self._default_kwargs)
        additional_args = input_data.get("additional_args")
        if additional_args is not None:
            run_kwargs["additional_args"] = additional_args

        if input_data.get("max_steps") is not None:
            run_kwargs["max_steps"] = input_data["max_steps"]

        if input_data.get("return_full_result") is not None:
            run_kwargs["return_full_result"] = input_data["return_full_result"]
        else:
            run_kwargs.setdefault("return_full_result", True)

        result = await asyncio.to_thread(self._agent.run, task, **run_kwargs)

        if isinstance(result, RunResult):
            output = result.output
            usage = result.token_usage.dict() if result.token_usage is not None else None
            content = None
            if output is None:
                content = None
            elif isinstance(output, dict):
                content = output.get("content") if isinstance(output.get("content"), str) else None
            else:
                content = str(output)
                output = {"content": content}

            return AgentResult(
                output=output if isinstance(output, dict) else None,
                content=content,
                raw=result,
                usage=usage,
            )

        if isinstance(result, dict):
            return AgentResult(output=result, raw=result)

        content = None if result is None else str(result)
        return AgentResult(output={"content": content} if content is not None else None, content=content, raw=result)


class SmolagentsAdapter(AgentAdapter):
    type_name = "smolagents"

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        if agent_ref.ref:
            factory = _load_factory(agent_ref.ref, context.config_dir)
            kwargs = agent_ref.config or {}
            agent = factory(**kwargs)
            if not isinstance(agent, MultiStepAgent):
                raise TypeError("smolagents factory did not return MultiStepAgent")
            return SmolagentsExecutor(agent)

        raise ValueError(f"smolagents reference missing ref for agent '{agent_name}'")


def _parse_ref(ref: str) -> Tuple[str, str]:
    if "#" in ref:
        module_ref, factory_name = ref.split("#", 1)
    else:
        module_ref, factory_name = ref, "build_agent"
    return module_ref, factory_name


def _load_factory(ref: str, config_dir: str):
    module_ref, factory_name = _parse_ref(ref)

    if module_ref.endswith(".py") or module_ref.startswith(".") or "/" in module_ref:
        module_path = module_ref
        if not os.path.isabs(module_path):
            module_path = os.path.join(config_dir, module_path)
        spec = importlib.util.spec_from_file_location("smolagents_factory", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load smolagents factory from {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_ref)

    factory = getattr(module, factory_name, None)
    if factory is None:
        raise AttributeError(f"Factory '{factory_name}' not found in {module_ref}")
    return factory
