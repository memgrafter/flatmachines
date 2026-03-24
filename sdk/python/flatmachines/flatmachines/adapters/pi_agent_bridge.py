"""pi-mono adapter using a Node.js runner (cross-runtime bridge)."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional

from ..agents import AgentAdapter, AgentAdapterContext, AgentExecutor, AgentRef, AgentResult


class PiAgentBridgeExecutor(AgentExecutor):
    def __init__(
        self,
        ref: str,
        config: Optional[Dict[str, Any]],
        runner_path: str,
        node_path: str,
        cwd: str,
        env: Dict[str, str],
        timeout: Optional[float],
    ):
        self._ref = ref
        self._config = config or {}
        self._runner_path = runner_path
        self._node_path = node_path
        self._cwd = cwd
        self._env = env
        self._timeout = timeout

    @property
    def metadata(self) -> Dict[str, Any]:
        return {}

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        request = {
            "ref": self._ref,
            "config": self._config,
            "input": input_data,
            "context": context or {},
        }
        payload = json.dumps(request)

        proc = await asyncio.create_subprocess_exec(
            self._node_path,
            self._runner_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=self._env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(payload.encode()), timeout=self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError("pi-agent runner timed out")

        if proc.returncode != 0:
            raise RuntimeError(
                f"pi-agent runner failed ({proc.returncode}): {stderr.decode().strip()}"
            )

        if not stdout:
            return AgentResult()

        try:
            result = json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON from pi-agent runner: {stdout.decode()}") from exc

        return AgentResult(
            output=result.get("output"),
            content=result.get("content"),
            raw=result.get("raw"),
            usage=result.get("usage"),
            cost=result.get("cost"),
            metadata=result.get("metadata"),
        )


class PiAgentBridgeAdapter(AgentAdapter):
    type_name = "pi-agent"

    def create_executor(
        self,
        *,
        agent_name: str,
        agent_ref: AgentRef,
        context: AgentAdapterContext,
    ) -> AgentExecutor:
        if not agent_ref.ref:
            raise ValueError(f"pi-agent reference missing ref for agent '{agent_name}'")

        settings = context.settings.get("agent_runners", {}).get("pi_agent", {})
        config = agent_ref.config or {}

        runner_path = config.get("runner") or settings.get("runner")
        if not runner_path:
            runner_path = os.path.join(os.path.dirname(__file__), "pi_agent_runner.mjs")
        elif not os.path.isabs(runner_path):
            runner_path = os.path.join(context.config_dir, runner_path)

        node_path = config.get("node") or settings.get("node") or "node"
        timeout = config.get("timeout") or settings.get("timeout")
        cwd = config.get("cwd") or settings.get("cwd") or context.config_dir

        env = dict(os.environ)
        env.update(settings.get("env", {}) if isinstance(settings.get("env"), dict) else {})
        env.update(config.get("env", {}) if isinstance(config.get("env"), dict) else {})

        return PiAgentBridgeExecutor(
            ref=agent_ref.ref,
            config=config.get("agent_config") or config.get("config") or {},
            runner_path=runner_path,
            node_path=node_path,
            cwd=cwd,
            env=env,
            timeout=timeout,
        )
